"""La TERCERA BOLSA: el efectivo que el dueño tiene EN LA MANO.

Hasta julio la plata del negocio vivía en dos lugares y los dos estaban en el
sistema: el cajón de cada sede y el banco. La barista vendía en efectivo y ella
misma iba a consignar, así que la plata se CONSERVABA — salía del cajón y entraba
al banco, y el sistema veía las dos puntas del viaje.

Desde agosto el dueño pasa y RECOGE el efectivo. Con esa plata le paga a los
proveedores que aceptan contado —eso NUNCA toca el banco— y consigna el resto. O
sea que hay un tercer lugar donde vive la plata, y el sistema no lo conocía.

EL ERROR MEDIDO, que es la razón de existir de este archivo:

    venden $1.000.000 en efectivo      → el cajón dice $1.000.000
    él recoge el $1.000.000            → NO SE REGISTRA: el cajón sigue diciendo $1.000.000
    paga $400.000 a un proveedor       → tampoco toca el cajón
    consigna $600.000                  → el banco sube $600.000

    el sistema dice $1.000.000. La plata real es $600.000.

Sobra exactamente lo que pagó de contado, y sobra hacia el lado TRANQUILIZADOR:
la pantalla no inventa deudas, inventa CALMA. Es el número que el dueño mira
antes de abrir, así que no puede sobrar.

Lo que fijan estos tests, y por qué cada regla importa:

- el cajón descuenta lo recogido, con un criterio distinto en cada rama: desde la
  APERTURA con turno abierto (la fórmula del cuadre no sabe de la recogida), y
  solo lo POSTERIOR al cierre en la otra (el conteo físico ya refleja lo anterior;
  restarlo dos veces subestima la caja y fabrica quiebres falsos);
- la consignación de la BARISTA baja el cajón y NO la mano; la del DUEÑO baja la
  mano y NO el cajón. Las distingue `caja_turno_id`, y confundirlas resta la misma
  plata dos veces;
- un pago con `movimiento_caja_id` ya salió de la registradora: no vuelve a
  restarse de la mano;
- `efectivo_en_mano` es None —NUNCA 0.0— mientras no haya ninguna recogida. Cero
  dice «pasó y no le queda nada»; None dice «todavía no registró ninguna pasada».
  Confundirlos es exactamente la familia de error que este cambio corrige;
- filtrando por sede la mano NO entra al total, igual que el banco: esa plata es
  de la EMPRESA y sumarla completa contra las salidas de una sola sede deja la
  serie sistemáticamente optimista;
- las validaciones del alta viven en el HANDLER y vuelven como 400 con `detail`
  STRING. En un 422 de pydantic el `detail` es una LISTA y el cliente solo sabe
  renderizar strings: el dueño terminaba viendo «Reintentá» en vez del motivo.
"""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col, inicio_dia_col_utc
from app.services.costos import fijar_desde_recogidas
from app.database import Base, get_db
from app.models.models import (CajaTurno, Consignacion, EntregaTurno,
                               EstadoConsignacionEnum, EstadoTurnoEnum, Pago,
                               RecogidaEfectivo, RolEnum, Tienda, Usuario)
from app.routers import consignaciones as consignaciones_router
from app.routers import costos as costos_router


class RecogidasBase(unittest.TestCase):
    """sqlite temporal + los routers reales (patrón de la suite).

    Se montan los DOS routers en la misma app porque el cambio es una sola cosa
    partida en dos endpoints: la recogida se teclea en `/consignaciones/recogidas`
    y el efecto se lee en `/costos/flujo`. Probar cada mitad contra un mock de la
    otra dejaría pasar justamente el desacuerdo que importa.
    """

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="Sede Vida", activa=True)
        self.palmetto = Tienda(nombre="Palmetto", direccion="Sede Palmetto", activa=True)
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.barista = Usuario(nombre="Catherin", email="barista@test.local",
                               password_hash="h", rol=RolEnum.barista,
                               tienda_id=self.vida.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.db.commit()

        self.hoy = hoy_col()

        app = FastAPI(title="Test recogidas de efectivo")
        app.include_router(costos_router.router, prefix="/api/v1")
        app.include_router(consignaciones_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        self.app = app
        self.client = TestClient(app)
        self.set_current_user(self.admin)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def set_current_user(self, user):
        """`require_admin` cuelga de `get_current_user`, así que sobreescribir
        este solo alcanza y el chequeo de rol sigue siendo el de producción."""
        self.app.dependency_overrides[get_current_user] = lambda: user

    def dia(self, delta: int) -> date:
        """Día Colombia relativo a hoy: todo lo que se mide acá se mide contra
        hoy, no contra una fecha fija del calendario."""
        return self.hoy + timedelta(days=delta)

    def mediodia(self, d: date) -> datetime:
        """Instante UTC del mediodía Colombia de `d` — cae sin ambigüedad dentro
        del día de negocio `d`, lejos de las dos fronteras."""
        return inicio_dia_col_utc(d) + timedelta(hours=12)

    def turno(self, *, tienda=None, abierto=False, base=0.0, efectivo_ventas=0.0,
              apertura=None, cierre=None, contado=None) -> CajaTurno:
        t = CajaTurno(
            tienda_id=(tienda or self.vida).id,
            usuario_apertura_id=self.admin.id,
            base_real=base,
            total_efectivo=efectivo_ventas,
            estado=EstadoTurnoEnum.abierto if abierto else EstadoTurnoEnum.cerrado,
            efectivo_final_real=contado,
        )
        if apertura is not None:
            t.fecha_apertura = apertura
        if cierre is not None:
            t.fecha_cierre = cierre
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)
        return t

    def recogida(self, monto, *, tienda=None, fecha=None, creado_en=None,
                 nota=None) -> RecogidaEfectivo:
        """La pasada del dueño, escrita directo en la DB.

        `creado_en` se pasa a mano en los tests de borde: es el campo con el que
        `_efectivo_en_registradora` decide si la recogida ya está adentro del
        conteo físico del cierre, y ahí un microsegundo cambia el número.
        """
        r = RecogidaEfectivo(
            tienda_id=(tienda or self.vida).id,
            fecha=fecha or self.hoy,
            monto=monto,
            usuario_id=self.admin.id,
            nota=nota,
        )
        if creado_en is not None:
            r.creado_en = creado_en
        self.db.add(r)
        # El ancla del régimen la deja puesta `registrar_recogida`, y este helper
        # escribe directo en la DB para poder falsear `creado_en`. Si no la
        # fijáramos acá, los tests medirían un mundo donde nadie usó el alta real
        # —y `desde_recogidas` devolvería None— que es justo el estado en que el
        # bucket entero es None.
        fijar_desde_recogidas(self.db, r.fecha)
        self.db.commit()
        self.db.refresh(r)
        return r

    def ids_de_recogidas(self) -> list:
        return [x.id for x in self.db.query(RecogidaEfectivo).order_by(
            RecogidaEfectivo.fecha.asc(), RecogidaEfectivo.id.asc()).all()]

    def primera_recogida_id(self, *, excepto=None) -> int:
        ids = self.ids_de_recogidas()
        if excepto is not None:
            ids = [i for i in ids if i != excepto.id]
        return ids[0]

    def borrar_recogida(self, rid: int):
        r = self.client.delete(f"/api/v1/consignaciones/recogidas/{rid}")
        self.assertEqual(r.status_code, 200, r.text)
        return r

    def pago_efectivo(self, monto, *, fecha=None, movimiento_caja_id=None,
                      anulado=False, metodo="efectivo") -> Pago:
        """Un pago a proveedor. Sin obligación ni factura detrás a propósito: la
        fórmula del efectivo en mano solo mira monto, método, fecha, anulación y
        `movimiento_caja_id`, y colgarle un padre solo agregaría ruido."""
        p = Pago(
            tienda_id=self.vida.id,
            monto=monto,
            fecha_pago=fecha or self.hoy,
            metodo=metodo,
            movimiento_caja_id=movimiento_caja_id,
            usuario_id=self.admin.id,
            anulado=anulado,
        )
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)
        return p

    def consignacion(self, valor, *, tienda=None, turno=None, fecha=None,
                     estado=EstadoConsignacionEnum.realizada) -> Consignacion:
        """`turno=None` es LA CONSIGNACIÓN DEL DUEÑO: la hizo desde su mano, no
        desde el cajón. Con `turno` es la de la barista, que sí sacó plata de la
        registradora. Ese NULL es toda la diferencia entre las dos bolsas."""
        c = Consignacion(
            tienda_id=(tienda or self.vida).id,
            caja_turno_id=turno.id if turno is not None else None,
            valor=valor,
            usuario_id=self.admin.id,
            estado=estado,
            fecha=fecha or self.mediodia(self.hoy),
        )
        self.db.add(c)
        self.db.commit()
        self.db.refresh(c)
        return c

    def declarar_banco(self, saldo, fecha=None):
        body = {"saldo": saldo}
        if fecha is not None:
            body["fecha"] = str(fecha)
        r = self.client.post("/api/v1/costos/saldo-banco", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def caja_hoy(self, **params) -> dict:
        r = self.client.get("/api/v1/costos/flujo", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["caja_hoy"]


class EscenarioDeAgostoTest(RecogidasBase):
    """El escenario del enunciado, con los números de verdad. Si de todo este
    archivo pasara un solo test, tiene que ser el primero de esta clase."""

    def _agosto(self, *, con_recogida: bool) -> dict:
        """Un día de agosto completo. `con_recogida` es el interruptor entre el
        sistema que miente y el que no: TODO lo demás es idéntico."""
        # Vendieron $1.000.000 en efectivo. El turno sigue abierto, que es cuando
        # el dueño mira la pantalla.
        turno = self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=1000000)
        if con_recogida:
            # Él pasó y se llevó el millón. Este es el dato que no existía.
            self.recogida(1000000, tienda=self.vida, fecha=self.hoy)
        # Con esa plata le pagó $400.000 de contado a un proveedor. Esto NUNCA
        # toca el banco ni el cajón: sale de su mano.
        self.pago_efectivo(400000, fecha=self.hoy)
        # Y consignó los $600.000 que le sobraron. `caja_turno_id` NULL: la
        # consignó ÉL desde su mano, no la barista desde el cajón.
        self.consignacion(600000, tienda=self.vida, turno=None)
        # El extracto del banco muestra los $600.000 que acaba de depositar. Se
        # declara porque el sistema registra consignaciones pero jamás un saldo
        # bancario: no hay de dónde derivarlo.
        self.declarar_banco(600000)
        return self.caja_hoy(), turno

    def test_el_total_es_la_plata_que_hay_no_la_que_hubo(self):
        caja, _turno = self._agosto(con_recogida=True)

        # El cajón quedó VACÍO: vendió 1.000.000 y se lo llevaron entero.
        self.assertEqual(caja["efectivo_registradora"], 0)
        # Y la mano también: recogió 1.000.000, pagó 400.000, consignó 600.000.
        self.assertEqual(caja["efectivo_en_mano"], 0)
        self.assertEqual(caja["saldo_banco"], 600000)
        # EL NÚMERO. La plata real del negocio son los $600.000 del banco.
        self.assertEqual(caja["total"], 600000)

    def test_sin_registrar_la_recogida_el_cajon_afirma_plata_que_ya_no_esta(self):
        """El bug medido, tal cual. Este test es el ancla de la regresión: si
        alguien saca la resta de las recogidas, este vuelve a pasar y el de
        arriba se cae."""
        caja, _turno = self._agosto(con_recogida=False)

        # El cajón sigue afirmando el millón entero aunque la plata ya se fue.
        self.assertEqual(caja["efectivo_registradora"], 1000000)
        # Y la tercera bolsa ni siquiera existe, así que nada compensa la mentira:
        # el total suma el millón fantasma MÁS los 600.000 que ya están en el banco.
        self.assertIsNone(caja["efectivo_en_mano"])
        self.assertEqual(caja["total"], 1600000)

    def test_la_plata_se_conserva_al_pasar_por_la_mano(self):
        """Invariante del viaje: lo recogido tiene que estar en algún lado. Cada
        peso que sale del cajón aparece en la mano; cada peso que sale de la mano
        aparece en el banco o en un pago que de verdad se hizo."""
        turno = self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=1000000)
        self.declarar_banco(0)
        antes = self.caja_hoy()["total"]

        # Recoger no crea ni destruye plata: la mueve de bolsa.
        self.recogida(1000000, tienda=self.vida)
        despues = self.caja_hoy()
        self.assertEqual(despues["efectivo_registradora"], 0)
        self.assertEqual(despues["efectivo_en_mano"], 1000000)
        self.assertEqual(despues["total"], antes)

        # Consignar tampoco: baja la mano y sube el banco (el banco lo declara
        # él contra el extracto, que es la única fuente que tiene el sistema).
        self.consignacion(600000, tienda=self.vida, turno=None)
        self.declarar_banco(600000)
        final = self.caja_hoy()
        self.assertEqual(final["efectivo_en_mano"], 400000)
        self.assertEqual(final["saldo_banco"], 600000)
        self.assertEqual(final["total"], antes)
        del turno


class EfectivoEnManoTest(RecogidasBase):
    """La fórmula de la tercera bolsa, término por término."""

    def test_sin_ninguna_recogida_el_bucket_es_none_y_no_es_cero(self):
        """None y 0.0 son cosas DISTINTAS y la diferencia es la que se mira: cero
        se lee «no le queda plata en la mano» y dispara una decisión; None se lee
        «todavía no registró ninguna pasada» y no dispara nada."""
        self.turno(tienda=self.vida, abierto=True, base=50000)
        caja = self.caja_hoy()

        self.assertIsNone(caja["efectivo_en_mano"])
        self.assertIsNone(caja["efectivo_en_mano_desde"])
        self.assertFalse(caja["efectivo_en_mano_incluido"])
        # No es 0.0 disfrazado: un 0.0 sería un float y pasaría los `is None`
        # del frontend como si el bucket existiera.
        self.assertNotIsInstance(caja["efectivo_en_mano"], float)
        # Y no suma nada al total, que sigue siendo cajón + banco.
        self.assertEqual(caja["total"], 50000)

    def test_cero_de_verdad_se_distingue_de_no_hay_dato(self):
        """El caso espejo del anterior: él pasó, gastó todo lo que recogió, y
        ahora sí no le queda nada. El bucket EXISTE y vale 0.0."""
        self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=300000)
        self.recogida(300000, tienda=self.vida)
        self.pago_efectivo(300000)

        caja = self.caja_hoy()
        self.assertEqual(caja["efectivo_en_mano"], 0)
        self.assertIsNotNone(caja["efectivo_en_mano"])
        self.assertTrue(caja["efectivo_en_mano_incluido"])
        self.assertEqual(caja["efectivo_en_mano_desde"], str(self.hoy))

    def test_desde_es_la_fecha_de_la_primera_recogida(self):
        """La primera POR FECHA, no la primera tecleada: él carga la pasada de
        anteayer después de la de ayer, y el arranque de la ventana es el día en
        que empezó a recoger, no el día en que se acordó de escribirlo."""
        self.recogida(100000, fecha=self.dia(-2))
        self.recogida(100000, fecha=self.dia(-5))
        self.recogida(100000, fecha=self.dia(-1))

        self.assertEqual(self.caja_hoy()["efectivo_en_mano_desde"], str(self.dia(-5)))

    def test_pago_en_efectivo_del_dueno_baja_la_mano(self):
        self.recogida(1000000)
        self.pago_efectivo(400000)
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 600000)

    def test_pago_que_no_es_en_efectivo_no_toca_la_mano(self):
        """Una transferencia sale del BANCO, no de su bolsillo. Restarla acá
        haría desaparecer plata que sigue estando en la mano."""
        self.recogida(1000000)
        self.pago_efectivo(400000, metodo="transferencia")
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 1000000)

    def test_pago_con_movimiento_de_caja_no_vuelve_a_restarse_de_la_mano(self):
        """`movimiento_caja_id` seteado significa que ese pago ADOPTÓ un egreso de
        caja: la plata salió de la REGISTRADORA y ya está descontada dentro del
        efectivo del turno. Restarla también de la mano sería contar la misma
        salida dos veces y dejar la mano en rojo sin motivo."""
        self.recogida(1000000)
        self.pago_efectivo(400000, movimiento_caja_id=777)
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 1000000)

    def test_adoptar_un_egreso_de_caja_no_baja_la_mano(self):
        """El mismo filtro que el test de arriba, pero por el camino REAL.

        `adoptar_egreso` convierte un egreso suelto del cajón en obligación +
        pago espejo, y ese pago sale con `metodo="efectivo"` y `fecha_pago` del
        día del egreso: cae de lleno en los otros dos filtros de la fórmula. Lo
        único que lo salva de restarse es `movimiento_caja_id`.

        El comentario del código decía que esa columna «no la escribe nadie» y
        que el filtro era un no-op. Es falso —la escribe `adoptar_egreso`, en el
        mismo archivo— y creerlo invita a borrar el filtro: la mano quedaría
        corta por cada egreso adoptado, o sea el total mostraría MENOS plata de
        la que hay. Este test es el que impide que eso pase en silencio.
        """
        from app.models.models import CostoCategoria, MovimientoCaja
        from app.services import costos as costos_svc

        turno = self.turno(tienda=self.vida, abierto=True, base=0,
                           efectivo_ventas=1000000)
        mov = MovimientoCaja(caja_turno_id=turno.id, tipo="egreso",
                             concepto="Domicilio de emergencia", valor=400000,
                             usuario_id=self.admin.id, fecha=self.mediodia(self.hoy))
        cat = CostoCategoria(clave="servicios", nombre="Servicios", grupo="fijo")
        self.db.add_all([mov, cat])
        self.db.commit()

        # El egreso YA bajó el cajón: 1.000.000 − 400.000.
        self.recogida(600000, tienda=self.vida)
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 0)

        costos_svc.adoptar_egreso(self.db, mov.id, cat.id, self.admin.id)

        caja = self.caja_hoy()
        # Adoptar no mueve un peso: el MovimientoCaja queda intacto y el pago
        # espejo no es una salida nueva.
        self.assertEqual(caja["efectivo_registradora"], 0)
        # Y sobre todo: la mano sigue con los 600.000 que él se llevó. Los
        # 400.000 salieron de la registradora, no de su bolsillo.
        self.assertEqual(caja["efectivo_en_mano"], 600000)

    def test_pago_anulado_no_baja_la_mano(self):
        """Un pago anulado no sacó plata de ningún lado, así que ese efectivo
        SIGUE en su mano. Sin el filtro el bucket queda subestimado — dirección
        prudente, pero igual falso."""
        self.recogida(1000000)
        self.pago_efectivo(400000, anulado=True)
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 1000000)

    def test_consignacion_del_dueno_baja_la_mano(self):
        self.recogida(1000000)
        self.consignacion(600000, turno=None)
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 400000)

    def test_consignacion_pendiente_no_baja_la_mano(self):
        """Pendiente = todavía no llegó al banco. La plata sigue siendo suya
        hasta que la consignación se confirma; mismo criterio que usa el cajón."""
        self.recogida(1000000)
        self.consignacion(600000, turno=None, estado=EstadoConsignacionEnum.pendiente)
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 1000000)

    def test_la_mano_puede_quedar_en_rojo_y_se_muestra_tal_cual(self):
        """Negativo significa que hay una salida cargada sin la pasada que la
        originó: falta registrar una recogida. Taparlo con un piso en cero
        convertiría un dato mal cargado en un cero tranquilizador, que es
        exactamente la familia de error que este módulo viene arrastrando."""
        self.recogida(100000)
        self.consignacion(500000, turno=None)
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], -400000)


class LasDosConsignacionesTest(RecogidasBase):
    """El mismo NULL, dos significados, dos bolsas distintas.

    `Consignacion.caja_turno_id` es lo único que separa «la barista fue al banco
    con la plata del cajón» de «el dueño consignó de su mano». Cruzarlas resta la
    misma plata dos veces, o no la resta de ninguna.
    """

    def test_la_de_la_barista_baja_el_cajon_y_no_la_mano(self):
        turno = self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=1000000)
        self.recogida(200000, tienda=self.vida)     # para que la mano exista
        self.consignacion(300000, tienda=self.vida, turno=turno)

        caja = self.caja_hoy()
        # 1.000.000 vendido − 300.000 que la barista llevó al banco − 200.000 que
        # se llevó el dueño.
        self.assertEqual(caja["efectivo_registradora"], 500000)
        # Su consignación NO sale de la mano del dueño: esa plata nunca la tuvo él.
        self.assertEqual(caja["efectivo_en_mano"], 200000)

    def test_la_del_dueno_baja_la_mano_y_no_el_cajon(self):
        turno = self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=1000000)
        self.recogida(200000, tienda=self.vida)
        self.consignacion(150000, tienda=self.vida, turno=None)

        caja = self.caja_hoy()
        # El cajón solo pierde lo recogido: la consignación de él ya salió de la
        # mano, y descontarla otra vez acá sería restar la misma plata dos veces.
        self.assertEqual(caja["efectivo_registradora"], 800000)
        self.assertEqual(caja["efectivo_en_mano"], 50000)
        del turno

    def test_las_dos_juntas_cada_una_de_su_bolsa(self):
        """El caso realista: la barista consignó de mañana y el dueño pasó de
        tarde. Los dos números tienen que moverse UNA vez cada uno."""
        turno = self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=1000000)
        self.consignacion(300000, tienda=self.vida, turno=turno)   # ella, del cajón
        self.recogida(400000, tienda=self.vida)                    # él pasa
        self.consignacion(250000, tienda=self.vida, turno=None)    # él, de su mano

        caja = self.caja_hoy()
        self.assertEqual(caja["efectivo_registradora"], 300000)   # 1.000k − 300k − 400k
        self.assertEqual(caja["efectivo_en_mano"], 150000)        # 400k − 250k
        # Y la plata no se duplicó ni se evaporó: 300k en el cajón + 150k en la
        # mano + 550k que ya están en el banco = el millón que se vendió.
        self.assertEqual(caja["efectivo_registradora"] + caja["efectivo_en_mano"] + 550000,
                         1000000)


class VentanaDesdeLaPrimeraRecogidaTest(RecogidasBase):
    """Lo anterior a la primera recogida es del MUNDO VIEJO.

    Antes de agosto la barista consignaba y la plata iba directo del cajón al
    banco. Esos pagos y esas consignaciones no salieron de la mano del dueño —esa
    mano no existía— y restarlos la dejaría en rojo desde el primer día.
    """

    def test_pagos_anteriores_a_la_primera_recogida_no_cuentan(self):
        self.recogida(1000000, fecha=self.dia(-5))
        self.pago_efectivo(400000, fecha=self.dia(-6))   # julio: mundo viejo
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 1000000)

    def test_el_pago_del_mismo_dia_de_la_primera_recogida_si_cuenta(self):
        """El borde es INCLUSIVO: él recoge y paga el mismo día, que es
        precisamente el flujo normal."""
        self.recogida(1000000, fecha=self.dia(-5))
        self.pago_efectivo(400000, fecha=self.dia(-5))
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 600000)

    def test_consignaciones_anteriores_a_la_primera_recogida_no_cuentan(self):
        self.recogida(1000000, fecha=self.dia(-5))
        self.consignacion(600000, turno=None, fecha=self.mediodia(self.dia(-6)))
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 1000000)

    def test_la_frontera_de_la_consignacion_es_la_medianoche_COLOMBIA(self):
        """`Consignacion.fecha` es un DateTime UTC y `desde` es un día COLOMBIA.
        Comparar el timestamp contra la fecha pelada movería la frontera cinco
        horas: las consignaciones de la madrugada del primer día se perderían y
        las de la noche anterior se colarían. Las dos direcciones, en un test.
        """
        desde = self.dia(-5)
        self.recogida(1000000, fecha=desde)
        # 01:00 de la mañana COLOMBIA del día `desde` → 06:00 UTC. Es del día
        # `desde`, así que cuenta.
        self.consignacion(100000, turno=None,
                          fecha=inicio_dia_col_utc(desde) + timedelta(hours=1))
        # 23:00 COLOMBIA del día ANTERIOR → 04:00 UTC del mismo día calendario,
        # pero pertenece a la víspera: no cuenta.
        self.consignacion(500000, turno=None,
                          fecha=inicio_dia_col_utc(desde) - timedelta(hours=1))

        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 900000)


class AnclaDelRegimenTest(RecogidasBase):
    """EL ARRANQUE DEL RÉGIMEN NO SE DERIVA DE LAS FILAS, y esta clase es el porqué.

    La primera versión sacaba `desde` de `MIN(RecogidaEfectivo.fecha)`. Dos
    lectores independientes encontraron el mismo agujero: las recogidas se pueden
    BORRAR, así que la ventana se movía sola y con ella la plata.

    Las dos direcciones cuestan, y las dos se prueban acá:
    · borrar la más vieja corría la ventana hacia ADELANTE y los pagos que
      quedaban adentro dejaban de restarse — aparecía plata que no existe;
    · cargar una retroactiva la corría hacia ATRÁS y arrastraba pagos del mundo
      viejo — una recogida de $10.000 mal fechada podía hundir la mano un millón.

    Ahora el ancla vive en `configuracion`, como el saldo del banco: se escribe
    una vez y no se mueve porque alguien toque una fila.
    """

    def test_borrar_la_recogida_mas_vieja_no_hace_aparecer_plata(self):
        """El escenario exacto del hallazgo, con sus números."""
        self.recogida(1000, fecha=self.dia(-10))          # la que va a borrar
        self.pago_efectivo(400000, fecha=self.dia(-9))    # cae DENTRO de la ventana
        r2 = self.recogida(500000, fecha=self.dia(-5))
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 101000)

        # Borra la primera para corregirla: no hay endpoint de edición, así que
        # borrar y volver a cargar es el camino natural.
        primera = self.primera_recogida_id(excepto=r2)
        self.borrar_recogida(primera)

        # Antes daba 500.000: el pago del día -9 se caía de la ventana y
        # aparecían $399.000 de la nada. Ahora el ancla no se movió.
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 100000)

    def test_una_recogida_anterior_al_regimen_se_rechaza(self):
        """El espejo: la retroactiva que arrastra el mundo viejo."""
        self.recogida(1000000, fecha=self.dia(-5))
        self.pago_efectivo(2000000, fecha=self.dia(-90))   # marzo: mundo viejo

        r = self.client.post("/api/v1/consignaciones/recogidas", json={
            "tienda_id": self.vida.id, "fecha": self.dia(-100).isoformat(),
            "monto": 10000,
        })
        self.assertEqual(r.status_code, 400)
        # `detail` STRING, no lista: el cliente solo sabe renderizar strings.
        self.assertIsInstance(r.json()["detail"], str)
        self.assertIn(self.dia(-5).isoformat(), r.json()["detail"])
        # Y la mano quedó intacta: sin el rechazo caía a -$990.000.
        self.assertEqual(self.caja_hoy()["efectivo_en_mano"], 1000000)

    def test_el_ancla_la_fija_la_primera_y_las_siguientes_no_la_mueven(self):
        self.recogida(100000, fecha=self.dia(-5))
        self.assertEqual(self.caja_hoy()["efectivo_en_mano_desde"], self.dia(-5).isoformat())
        self.recogida(100000, fecha=self.dia(-2))
        self.assertEqual(self.caja_hoy()["efectivo_en_mano_desde"], self.dia(-5).isoformat())

    def test_borrar_TODAS_las_recogidas_devuelve_el_bucket_a_None(self):
        """El ancla arregla la VENTANA, no convierte en cero un bolsillo sin medir.

        Escribí este test al revés la primera vez —esperando una mano en rojo— y
        los tests que ya estaban me corrigieron: sin ninguna recogida viva no se
        sabe qué tiene encima, y un número (cualquiera) lo afirmaría. El ancla
        sigue puesta para que la ventana no se mueva, pero el bucket vuelve a
        «no se sabe».
        """
        self.recogida(500000, fecha=self.dia(-5))
        self.pago_efectivo(200000, fecha=self.dia(-4))
        for rid in self.ids_de_recogidas():
            self.borrar_recogida(rid)
        self.assertIsNone(self.caja_hoy()["efectivo_en_mano"])


class CajonTurnoAbiertoTest(RecogidasBase):
    """La rama `turno_abierto`: se descuenta desde la APERTURA.

    La fórmula del cuadre (base + ventas + ingresos − egresos) no sabe nada de la
    recogida, así que hay que restarla entera. Se acota por `creado_en` —un
    instante— y no por `fecha` —un día—: un turno abierto de madrugada y una
    recogida del mismo día calendario pero anterior a la apertura pertenecen a la
    caja de AYER, y comparar días no sabe distinguirlas.
    """

    def test_la_recogida_baja_el_cajon_del_turno_abierto(self):
        self.turno(tienda=self.vida, abierto=True, base=100000, efectivo_ventas=900000)
        self.recogida(600000, tienda=self.vida)
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 400000)

    def test_recogida_exactamente_en_la_apertura_si_se_resta(self):
        """El borde es NO estricto: lo que él se llevó en el instante mismo de la
        apertura pertenece a este turno."""
        apertura = self.mediodia(self.hoy)
        self.turno(tienda=self.vida, abierto=True, base=500000, apertura=apertura)
        self.recogida(200000, tienda=self.vida, creado_en=apertura)
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 300000)

    def test_recogida_anterior_a_la_apertura_no_toca_este_turno(self):
        """Esa plata salió de la caja de AYER; el turno de hoy arrancó con su base
        contada. Restarla acá le sacaría al turno nuevo una plata que nunca tuvo."""
        apertura = self.mediodia(self.hoy)
        self.turno(tienda=self.vida, abierto=True, base=500000, apertura=apertura)
        self.recogida(200000, tienda=self.vida, fecha=self.dia(-1),
                      creado_en=apertura - timedelta(hours=3))
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 500000)

    def test_la_recogida_de_otra_sede_no_baja_este_cajon(self):
        """`RecogidaEfectivo` sí sabe de qué sede salió cada billete, y el cajón
        es por sede: mezclarlas dejaría a una en rojo y a la otra inflada."""
        self.turno(tienda=self.vida, abierto=True, base=500000)
        self.turno(tienda=self.palmetto, abierto=True, base=800000)
        self.recogida(300000, tienda=self.palmetto)

        por_tienda = {d["tienda_nombre"]: d["efectivo"] for d in self.caja_hoy()["por_tienda"]}
        self.assertEqual(por_tienda["Vida"], 500000)
        self.assertEqual(por_tienda["Palmetto"], 500000)


class CajonUltimoCierreTest(RecogidasBase):
    """La rama `ultimo_cierre`: el borde donde es fácil restar dos veces.

    `efectivo_final_real` es un CONTEO FÍSICO. Lo que el dueño se llevó ANTES de
    que la barista contara ya no estaba sobre la mesa cuando ella contó, así que
    restarlo otra vez SUBESTIMA la caja e inventa un punto de quiebre. Lo único
    que el conteo no puede saber es lo que él recogió DESPUÉS de cerrar.
    """

    def _turno_cerrado(self, contado=400000):
        return self.turno(tienda=self.vida, abierto=False, contado=contado,
                          apertura=self.mediodia(self.hoy) - timedelta(hours=6),
                          cierre=self.mediodia(self.hoy))

    def test_recogida_anterior_al_cierre_no_se_resta_otra_vez(self):
        cerrado = self._turno_cerrado(contado=400000)
        self.recogida(600000, tienda=self.vida,
                      creado_en=cerrado.fecha_cierre - timedelta(hours=1))
        # El conteo ya dio 400.000 PORQUE él se había llevado los 600.000. Restar
        # otra vez daría −200.000: un quiebre falso con alerta roja.
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 400000)

    def test_recogida_posterior_al_cierre_si_se_resta(self):
        """Sede cerrada, plata quieta, él pasa a la noche. El conteo no puede
        saberlo, así que es lo único que hay que descontar en esta rama."""
        cerrado = self._turno_cerrado(contado=400000)
        self.recogida(150000, tienda=self.vida,
                      creado_en=cerrado.fecha_cierre + timedelta(hours=2))
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 250000)

    def test_recogida_exactamente_en_el_cierre_no_se_resta(self):
        """El borde es ESTRICTAMENTE mayor. En el empate gana el conteo físico:
        si se contó en ese instante, lo que se llevó ya estaba descontado."""
        cerrado = self._turno_cerrado(contado=400000)
        self.recogida(150000, tienda=self.vida, creado_en=cerrado.fecha_cierre)
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 400000)

    def test_el_origen_del_dato_sigue_siendo_ultimo_cierre(self):
        """La resta no puede cambiar de dónde salió el número: la pantalla usa
        `origen` para explicarle al dueño qué está mirando."""
        cerrado = self._turno_cerrado(contado=400000)
        self.recogida(150000, tienda=self.vida,
                      creado_en=cerrado.fecha_cierre + timedelta(hours=2))
        vida = next(d for d in self.caja_hoy()["por_tienda"] if d["tienda_nombre"] == "Vida")
        self.assertEqual(vida["origen"], "ultimo_cierre")

    def test_la_rama_del_ultimo_cuadre_no_descuenta_recogidas(self):
        """Turno cerrado SIN conteo (efectivo_final_real NULL): el dato cae al
        último EntregaTurno y ahí no hay contra qué acotar la recogida. Queda
        declarado acá porque es el único punto de todo el cambio que sigue del
        lado optimista, y conviene que se vea si alguien lo toca."""
        sin_conteo = self.turno(tienda=self.vida, abierto=False, contado=None,
                                cierre=self.mediodia(self.hoy))
        self.db.add(EntregaTurno(turno_id=sin_conteo.id, tienda_id=self.vida.id,
                                 usuario_id=self.admin.id,
                                 fecha_hora=self.mediodia(self.dia(-1)),
                                 efectivo_esperado=500000, efectivo_real=500000,
                                 ventas_efectivo_siigo=0, ventas_tarjeta_bold=0,
                                 diferencia_efectivo=0, diferencia_tarjeta=0))
        self.db.commit()
        self.recogida(200000, tienda=self.vida)

        vida = next(d for d in self.caja_hoy()["por_tienda"] if d["tienda_nombre"] == "Vida")
        self.assertEqual(vida["origen"], "ultimo_cuadre")
        self.assertEqual(vida["efectivo"], 500000)


class ManoPorSedeTest(RecogidasBase):
    """Con `tienda_id`, la mano NO entra al total — igual que el banco.

    La plata del bolsillo es de la EMPRESA. `RecogidaEfectivo` sabe de qué sede
    salió, pero los pagos y las consignaciones que la consumen no se pueden
    repartir —él le paga al proveedor con la plata junta—, así que una vista por
    sede solo podría sumar el lado de las ENTRADAS. Eso es toda la plata del
    negocio contra una parte de sus salidas: la serie queda sistemáticamente
    optimista, que es el sesgo del que este archivo entero se ocupa.
    """

    def setUp(self):
        super().setUp()
        self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=1000000)
        self.recogida(1000000, tienda=self.vida)
        self.declarar_banco(2000000)

    def test_filtrando_por_sede_la_mano_se_devuelve_pero_no_suma(self):
        caja = self.caja_hoy(tienda_id=self.vida.id)

        # El dato se sigue devolviendo: es real y el dueño tiene que poder verlo.
        self.assertEqual(caja["efectivo_en_mano"], 1000000)
        self.assertEqual(caja["efectivo_en_mano_desde"], str(self.hoy))
        # Pero declarado FUERA del total, y el flag lo dice para que la pantalla
        # no tenga que re-derivar la regla del lado del cliente.
        self.assertFalse(caja["efectivo_en_mano_incluido"])
        self.assertFalse(caja["saldo_banco_incluido"])
        self.assertEqual(caja["total"], 0)   # solo el cajón de Vida, ya vaciado

    def test_sin_filtro_la_mano_entra_al_total(self):
        caja = self.caja_hoy()
        self.assertTrue(caja["efectivo_en_mano_incluido"])
        self.assertEqual(caja["total"], 0 + 1000000 + 2000000)

    def test_el_flag_de_incluido_es_falso_cuando_el_bucket_no_existe(self):
        """`incluido` responde dos preguntas a la vez —¿hay dato? ¿suma?— y las
        dos tienen que dar false para que la pantalla no enumere un sumando que
        no sumó."""
        self.db.query(RecogidaEfectivo).delete()
        self.db.commit()
        caja = self.caja_hoy()
        self.assertIsNone(caja["efectivo_en_mano"])
        self.assertFalse(caja["efectivo_en_mano_incluido"])


class RecogidasApiTest(RecogidasBase):
    """El contrato HTTP del alta. Lo que más importa acá son los 400: cada regla
    violada tiene que llegar a la pantalla como un texto que el dueño pueda leer.
    """

    def crear(self, **campos):
        body = {"tienda_id": self.vida.id, "fecha": str(self.hoy), "monto": 250000}
        body.update(campos)
        return self.client.post("/api/v1/consignaciones/recogidas", json=body)

    def crudo(self, body: dict):
        """`json.dumps` a mano (allow_nan por defecto) porque httpx se niega a
        mandar inf/NaN. Sin esto el caso más peligroso —el valor que revienta al
        serializar— nunca llegaría al servidor. El `json.loads` de Starlette sí
        acepta los literales, igual que un cliente real que los mande."""
        return self.client.post("/api/v1/consignaciones/recogidas",
                                content=json.dumps(body),
                                headers={"content-type": "application/json"})

    def assert_400_legible(self, r, esperado=None):
        """El `detail` tiene que ser un STRING. En un 422 de pydantic es una
        LISTA de errores y el cliente solo sabe renderizar strings: el dueño veía
        «Reintentá» en vez del motivo. Por eso las reglas viven en el handler."""
        self.assertEqual(r.status_code, 400, r.text)
        detalle = r.json()["detail"]
        self.assertIsInstance(detalle, str)
        self.assertNotIsInstance(detalle, list)
        if esperado is not None:
            self.assertEqual(detalle, esperado)

    # ── Alta ─────────────────────────────────────────────────────────────────

    def test_alta_devuelve_201_y_la_fila_creada(self):
        r = self.crear(monto=250000, nota="  pasada de la tarde  ")
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["tienda_id"], self.vida.id)
        self.assertEqual(body["tienda_nombre"], "Vida")
        self.assertEqual(body["monto"], 250000)
        self.assertEqual(body["fecha"], str(self.hoy))
        self.assertEqual(body["usuario_nombre"], "Bryan")
        self.assertEqual(body["nota"], "pasada de la tarde")   # strip()eada

        self.assertEqual(self.db.query(RecogidaEfectivo).count(), 1)

    def test_la_nota_vacia_se_guarda_como_null_no_como_string_vacio(self):
        """Así el frontend puede preguntar `nota ? ... : ...` sin casos
        especiales: una nota de espacios no es una nota."""
        r = self.crear(nota="   ")
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIsNone(r.json()["nota"])

    def test_el_alta_por_http_baja_el_cajon(self):
        """La cadena completa: teclear la recogida en su pantalla tiene que mover
        el número de la otra. Es el desacuerdo que un mock no encontraría."""
        self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=900000)
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 900000)

        self.assertEqual(self.crear(monto=900000).status_code, 201)
        caja = self.caja_hoy()
        self.assertEqual(caja["efectivo_registradora"], 0)
        self.assertEqual(caja["efectivo_en_mano"], 900000)

    # ── Validaciones (todas en el handler, todas 400 con string) ─────────────

    def test_monto_en_cero_es_400(self):
        self.assert_400_legible(self.crear(monto=0),
                                "El monto de la recogida va en positivo.")

    def test_monto_negativo_es_400(self):
        """Una recogida negativa sería «le devolví plata al cajón», que no es
        esta operación. Sin la guarda INFLA el cajón en vez de bajarlo."""
        self.assert_400_legible(self.crear(monto=-50000),
                                "El monto de la recogida va en positivo.")

    def test_monto_infinito_es_400_y_la_respuesta_se_serializa(self):
        r = self.crudo({"tienda_id": self.vida.id, "fecha": str(self.hoy),
                        "monto": float("inf")})
        self.assert_400_legible(r, "El monto de la recogida debe ser un número válido.")

    def test_monto_absurdo_es_400(self):
        """No es una regla inventada: la columna es Numeric(12,2) y un monto más
        grande revienta el INSERT en Postgres con un error que no dice nada."""
        self.assert_400_legible(self.crear(monto=1e9 + 1),
                                "El monto de la recogida es demasiado grande.")

    def test_fecha_futura_es_400(self):
        self.assert_400_legible(
            self.crear(fecha=str(self.dia(1))),
            "No podés registrar una recogida de un día que todavía no llegó.")

    def test_la_pasada_de_hoy_se_acepta_aunque_el_server_corra_en_utc(self):
        """La frontera se mide con `hoy_col()` y no con `date.today()`: entre las
        19:00 y la medianoche de Colombia el servidor UTC ya pasó de día y
        rechazaría la pasada de ESTA tarde."""
        self.assertEqual(self.crear(fecha=str(hoy_col())).status_code, 201)

    def test_la_pasada_de_ayer_se_acepta(self):
        """Él registra tarde: la de ayer, la de anteayer. Nada lo impide."""
        self.assertEqual(self.crear(fecha=str(self.dia(-3))).status_code, 201)

    def test_nota_de_mas_de_300_es_400(self):
        """Sin el tope el INSERT explota en Postgres — ya pasó en este repo con
        otras columnas de texto libre."""
        self.assert_400_legible(self.crear(nota="x" * 301),
                                "La nota de la recogida no puede pasar de 300 caracteres.")
        self.assertEqual(self.crear(nota="x" * 300).status_code, 201)

    def test_sede_inexistente_es_400(self):
        self.assert_400_legible(self.crear(tienda_id=99999), "Esa sede no existe.")

    def test_sede_inactiva_es_400(self):
        """El select del formulario se llena con `/auth/tiendas`, que devuelve
        solo activas: las dos puntas tienen que coincidir o la pantalla ofrece
        una sede que el POST rechaza."""
        cerrada = Tienda(nombre="Sede cerrada", direccion="x", activa=False)
        self.db.add(cerrada)
        self.db.commit()
        self.assert_400_legible(self.crear(tienda_id=cerrada.id), "Esa sede está inactiva.")

    def test_la_forma_mal_tipada_si_es_422_de_pydantic(self):
        """El único caso en que `detail` es una lista: el schema se ocupa de la
        FORMA (qué campos llegan y de qué tipo) y ninguna regla de NEGOCIO cae
        ahí. Este test fija esa frontera."""
        r = self.crear(fecha="ayer")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIsInstance(r.json()["detail"], list)

    def test_la_barista_no_puede_registrar_recogidas(self):
        """La recogida la hace el dueño. Si la pudiera cargar la barista, el
        cajón bajaría sin que él lo supiera."""
        self.set_current_user(self.barista)
        self.assertEqual(self.crear().status_code, 403)
        self.assertEqual(self.client.get("/api/v1/consignaciones/recogidas").status_code, 403)

    # ── Listado ──────────────────────────────────────────────────────────────

    def test_listado_devuelve_items_y_total(self):
        self.crear(monto=100000, fecha=str(self.dia(-1)))
        self.crear(monto=250000, fecha=str(self.hoy))

        body = self.client.get("/api/v1/consignaciones/recogidas").json()
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["total"], 350000)
        # Orden: la más reciente primero, que es la que él acaba de cargar.
        self.assertEqual(body["items"][0]["fecha"], str(self.hoy))

    def test_listado_vacio_devuelve_cero_y_no_null(self):
        """Acá el cero SÍ es cero: «no hubo recogidas en este rango» es un total
        de $0, no un dato ausente. Es el caso opuesto a `efectivo_en_mano`."""
        body = self.client.get("/api/v1/consignaciones/recogidas").json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["total"], 0)
        self.assertIsNotNone(body["total"])

    def test_listado_filtra_por_fecha_y_por_sede(self):
        self.crear(monto=100000, fecha=str(self.dia(-10)))
        self.crear(monto=200000, fecha=str(self.dia(-1)))
        self.crear(monto=300000, fecha=str(self.hoy), tienda_id=self.palmetto.id)

        rango = self.client.get("/api/v1/consignaciones/recogidas",
                                params={"desde": str(self.dia(-2)), "hasta": str(self.hoy)})
        self.assertEqual(rango.json()["total"], 500000)

        sede = self.client.get("/api/v1/consignaciones/recogidas",
                               params={"tienda_id": self.palmetto.id})
        self.assertEqual(sede.json()["total"], 300000)

    def test_listado_filtra_por_el_dia_en_que_recogio_no_por_el_del_teclado(self):
        """Él carga hoy la pasada de la semana pasada. Un reporte que la ubicara
        en el día del teclado no cuadraría contra el cierre de esa sede."""
        self.crear(monto=100000, fecha=str(self.dia(-7)))
        hoy_solo = self.client.get("/api/v1/consignaciones/recogidas",
                                   params={"desde": str(self.hoy)})
        self.assertEqual(hoy_solo.json()["items"], [])

    def test_rango_al_reves_es_400_legible(self):
        r = self.client.get("/api/v1/consignaciones/recogidas",
                            params={"desde": str(self.hoy), "hasta": str(self.dia(-5))})
        self.assert_400_legible(
            r, "El rango de fechas está al revés: 'desde' es posterior a 'hasta'.")

    # ── Borrado ──────────────────────────────────────────────────────────────

    def test_borrar_revierte_la_recogida_y_devuelve_el_cajon(self):
        """Un cero de más tecleado deja el cajón subestimado y la mano inflada.
        Borrar tiene que deshacerlo del todo, no dejar rastro en el número."""
        self.turno(tienda=self.vida, abierto=True, base=0, efectivo_ventas=900000)
        rid = self.crear(monto=900000).json()["id"]
        self.assertEqual(self.caja_hoy()["efectivo_registradora"], 0)

        r = self.client.delete(f"/api/v1/consignaciones/recogidas/{rid}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"ok": True, "id": rid})

        caja = self.caja_hoy()
        self.assertEqual(caja["efectivo_registradora"], 900000)
        # Y con la última recogida borrada el bucket vuelve a NO EXISTIR: None,
        # no 0.0. Si quedara en cero, la pantalla afirmaría que él no tiene plata
        # encima cuando en realidad nadie registró nada.
        self.assertIsNone(caja["efectivo_en_mano"])

    def test_borrar_algo_que_no_existe_es_404(self):
        r = self.client.delete("/api/v1/consignaciones/recogidas/99999")
        self.assertEqual(r.status_code, 404)
        self.assertIsInstance(r.json()["detail"], str)

    def test_la_barista_no_puede_borrar_recogidas(self):
        rid = self.crear().json()["id"]
        self.set_current_user(self.barista)
        self.assertEqual(
            self.client.delete(f"/api/v1/consignaciones/recogidas/{rid}").status_code, 403)


if __name__ == "__main__":
    unittest.main()
