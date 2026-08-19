"""LA PANTALLA Y LA PLATA DECÍAN COSAS DISTINTAS SOBRE EL MISMO DÍA.

El lunes 17 de agosto la sede pagó de la registradora MÁS de lo que entró en
efectivo y cerró con $177.700 en contra. Esa plata no salió del aire: salió de la
venta del domingo, que todavía estaba en el cajón. Por eso el dueño pidió, con
sus palabras: «el lunes sin consignación, al domingo 16 hay que quitarle
$177.700».

EL SISTEMA YA HACÍA ESA CUENTA. `_saldos_consignacion` arrastra el déficit de un
turno contra el saldo de los anteriores (cascada FIFO, más viejo primero) desde
antes de este cambio, y de ahí come TODA la imputación: `recoger`,
`get_pendiente`, `_turno_pendiente_mas_antiguo` y el cuadre de apertura. O sea que
la plata que de verdad se cobra ya estaba bien.

LO QUE NO LA HACÍA ERA LA PANTALLA. `get_resumen_admin` tenía su propia copia de
la fórmula del consignable y no corría la cascada: el lunes aparecía en cero por
casualidad —un negativo que nadie miraba— y el domingo aparecía entero, sin el
descuento. Dos cuentas distintas sobre la misma plata, y la que el dueño miraba
era justamente la que no mandaba.

Lo que fija este archivo, y por qué cada regla importa:

- EL CASO DEL DUEÑO con sus números, de punta a punta: el domingo baja a $222.300
  y dice quién se llevó los $177.700; el lunes queda en cero y dice quién se los
  puso. Y el número del domingo es EXACTAMENTE la plata que quedó en el cajón,
  que es la única prueba que a él le sirve;
- LA INVARIANTE QUE MATA LA DIVERGENCIA: `saldo_pendiente` de la pantalla ==
  `saldo` post-cascada de `_saldos_consignacion` == lo que `recoger()` cobra. Si
  alguien vuelve a calcular el resumen por su cuenta, ese test tiene que gritar;
- EL RANGO NO MUEVE LA PLATA. La cascada corre sobre la historia completa de la
  sede; el filtro decide QUÉ FILAS SE MUESTRAN y jamás a quién se le cobra. Es el
  error más fácil de cometer «optimizando»: con la cascada acotada al filtro, el
  mismo día valdría dos cosas según por dónde se entró a la pantalla;
- LA PROCEDENCIA es parte del número. Un saldo que baja sin poder explicar por qué
  es indistinguible de un bug, y el dueño no le va a creer a una pantalla que no
  sabe contestarle «¿y esa plata dónde está?»;
- `faltante_sin_cubrir` SE EXPONE Y NO SE COLA EN EL SALDO. Es el déficit que no
  encontró saldo viejo del cual cobrarse: plata que falta y que hasta ahora se
  ignoraba en silencio. Que la aritmética la siga ignorando es defendible; que no
  se pueda mirar, no;
- EL ORDEN: la base de la caja fuerte se descuenta PRIMERO y la cascada corre
  DESPUÉS, sobre el esperado ya corregido. Invertirlo haría que un día tape un
  hueco con plata que no era suya —era la base de emergencia de la sede— y el
  faltante desaparecería de la pantalla justo cuando existe;
- POR SEDE: el hueco de Palmetto no se cobra del cajón de Vida. Son dos cajones
  físicos en dos barrios distintos.

UNA TRAMPA DE ESTE ARCHIVO, para el próximo que agregue un test: los cierres se
anclan a las 18:00 COLOMBIA (23:00 UTC del mismo día calendario) porque el filtro
`desde/hasta` de `get_resumen_admin` compara la columna `fecha_cierre`, que es
UTC, contra fechas locales sin convertir. Un cierre a las 21:00 COL cae en el día
UTC siguiente y se escapa de un rango que "obviamente" lo contiene — y el test del
rango dejaría de medir lo que dice medir.
"""
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
from app.database import Base, get_db
from app.models.models import (CajaTurno, Consignacion, EntregaTurno,
                               EstadoConsignacionEnum, MovimientoCaja, RolEnum,
                               Tienda, Usuario)
from app.routers import caja as caja_router
from app.routers import consignaciones as consignaciones_router
from app.services import caja as svc
from app.services import consignaciones as consig_svc


class CascadaBase(unittest.TestCase):
    """sqlite temporal + los servicios y routers REALES (patrón de la suite).

    Los turnos se abren, se cuadran y se cierran con `abrir_caja` /
    `registrar_cuadre_inicial` / `cerrar_caja` DE VERDAD: el esperado a consignar
    de un día sale de `total_efectivo`, de los movimientos y de las columnas que
    escribe el cierre, así que una fixture que las llenara a mano probaría la
    fixture y no el sistema.

    Se montan los dos routers porque el número que se mide acá se teclea en Caja
    (el traslado de la caja fuerte) y se lee en Consignaciones: probar cada mitad
    contra un mock de la otra dejaría pasar justo el desacuerdo que importa.
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
                               tienda_id=self.palmetto.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.db.commit()

        self.hoy = hoy_col()

        app = FastAPI(title="Test cascada de consignaciones")
        app.include_router(caja_router.router, prefix="/api/v1")
        app.include_router(consignaciones_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Tiempo ───────────────────────────────────────────────────────────────

    def dia(self, delta: int) -> date:
        """Día Colombia relativo a hoy: todo se mide contra hoy y no contra una
        fecha fija del calendario, que envejece."""
        return self.hoy + timedelta(days=delta)

    def momento(self, d: date, hora: int) -> datetime:
        """Instante UTC de las `hora`:00 COLOMBIA del día `d`.

        Ojo con el doble sistema: de las 19:00 COL en adelante el instante cae en
        el día calendario SIGUIENTE en UTC. Por eso los cierres de este archivo
        van a las 18:00 — ver la advertencia del encabezado sobre el filtro
        `desde/hasta`.
        """
        return inicio_dia_col_utc(d) + timedelta(hours=hora)

    # ── Turnos (servicios reales, apertura y cierre anclados) ────────────────

    def _anclar_cuadre(self, turno, momento: datetime):
        """Backdatea el CUADRE de apertura, que es cosa distinta de la apertura:
        entre que el turno abre y la barista cuenta el efectivo pasa el conteo de
        inventario, y el delta de la caja fuerte se ancla en el conteo."""
        for e in (self.db.query(EntregaTurno)
                  .filter(EntregaTurno.turno_id == turno.id,
                          EntregaTurno.tipo == "apertura").all()):
            e.fecha_hora = momento
        self.db.commit()

    def abrir_diferido(self, *, momento: datetime, tienda=None):
        """El flujo real de la sede: el turno abre con las baristas y el efectivo
        se cuenta después del conteo de inventario."""
        tienda = tienda or self.palmetto
        turno = svc.abrir_caja(self.db, tienda.id, None, None, self.admin.id,
                               barista_ids=[self.barista.id], tipo_turno="apertura")
        turno.fecha_apertura = momento
        self.db.commit()
        return turno

    def cuadre_inicial(self, turno, *, efectivo_real, momento, incluye=(),
                       justificacion=None):
        """El conteo del efectivo, con la barista marcando QUÉ días pendientes
        siguen físicamente en el cajón (`incluye`).

        Es la rama que usa la sede y la que le conviene a estos tests: el esperado
        se arma desde los saldos pendientes REALES, así que un escenario con dos o
        tres días sin consignar se puede montar sin que el cuadre acuse un
        sobrante fantasma.
        """
        svc.registrar_cuadre_inicial(self.db, turno.id, self.admin.id,
                                     efectivo_real=efectivo_real,
                                     justificacion=justificacion,
                                     saldos_incluidos=[t.id for t in incluye])
        self._anclar_cuadre(turno, momento)
        self.db.refresh(turno)
        return turno

    def vender_efectivo(self, turno, monto):
        """Lo que hace el POS: acumular la venta en efectivo del turno."""
        turno.total_efectivo = (turno.total_efectivo or 0) + monto
        self.db.commit()

    def egreso(self, turno, monto, momento, concepto="Pago proveedor de contado"):
        """El pago EN EFECTIVO que sale de la registradora. Cuando se come la venta
        del día es lo que deja el turno en contra — el hecho que originó todo."""
        self.db.add(MovimientoCaja(caja_turno_id=turno.id, tipo="egreso",
                                   concepto=concepto, valor=monto,
                                   usuario_id=self.admin.id, fecha=momento))
        self.db.commit()

    def cerrar(self, turno, *, contado, momento, justificacion=None):
        """Cierra el turno de verdad y ancla el cierre en `momento`.

        `tiene_conteo_cierre` se marca a mano porque el conteo de inventario es
        otro módulo entero y acá lo que se mide es la plata del cajón."""
        turno.tiene_conteo_cierre = True
        self.db.commit()
        svc.cerrar_caja(self.db, turno.id, contado, justificacion, self.admin.id)
        turno.fecha_cierre = momento
        self.db.commit()
        self.db.refresh(turno)
        return turno

    def jornada(self, d: date, *, en_caja, incluye=(), venta=0.0, pagado=0.0,
                saca_base=0.0, contado=None, justificacion=None, tienda=None):
        """Un día entero de la sede: cuenta, vende, paga de contado y cierra.

        `en_caja` es la plata que hay FÍSICAMENTE en el cajón cuando la barista la
        cuenta e `incluye` son los turnos cuyo saldo pendiente sigue ahí adentro.
        Que el cuadre inicial dé diferencia CERO lo verifica el propio helper y no
        un test: si un escenario se armara con una plata que no coincide con lo
        pendiente, el sistema lo llamaría «sobrante de apertura», lo metería en el
        esperado a consignar (`sobrante_consignable`) y el número que estamos
        midiendo saldría movido por un motivo que no es la cascada.

        Lo mismo con el cierre: sin `justificacion` explícita, el día tiene que
        cuadrar exacto. Un descuadre silencioso entra al consignable por
        `diferencia_cierre` y ensucia la medición.
        """
        turno = self.abrir_diferido(momento=self.momento(d, 7), tienda=tienda)
        self.cuadre_inicial(turno, efectivo_real=en_caja, incluye=incluye,
                            momento=self.momento(d, 8))
        self.assertEqual(turno.diferencia_apertura, 0,
                         f"el cuadre inicial del {d} no da exacto: revisá `en_caja`")

        if saca_base:
            # La base sale DESPUÉS del conteo, así que es un sumando del turno y no
            # viaja adentro de `base_real`.
            self.traslado(saca_base, sentido="saca", momento=self.momento(d, 10),
                          tienda=tienda or self.palmetto)
        if venta:
            self.vender_efectivo(turno, venta)
        if pagado:
            self.egreso(turno, pagado, self.momento(d, 11))

        if contado is None:
            contado = en_caja + saca_base + venta - pagado
        self.cerrar(turno, contado=contado, momento=self.momento(d, 18),
                    justificacion=justificacion)
        if justificacion is None:
            self.assertEqual(turno.diferencia_cierre, 0,
                             f"el cierre del {d} no cuadra: revisá `contado`")
        return turno

    # ── Plata que sale del cajón ─────────────────────────────────────────────

    def consignar(self, turno, monto, momento):
        """La plata de ese día se fue al banco. Va con `caja_turno_id` puesto: es
        el emparejamiento normal, el de ventana de fecha es solo para las filas
        legacy que nacieron sin FK."""
        self.db.add(Consignacion(
            tienda_id=turno.tienda_id, caja_turno_id=turno.id, valor=monto,
            imagen_url=None, usuario_id=self.admin.id, fecha=momento,
            estado=EstadoConsignacionEnum.realizada,
        ))
        self.db.commit()

    def traslado(self, monto, *, sentido="saca", momento, tienda=None):
        """El traslado de la caja fuerte, por HTTP: es la puerta real del dueño."""
        tienda = tienda or self.palmetto
        r = self.client.post("/api/v1/caja/prestamos-caja-fuerte", json={
            "tienda_id": tienda.id, "sentido": sentido, "monto": monto,
            "fecha": momento.isoformat(),
        })
        self.assertEqual(r.status_code, 201, r.text)
        return r

    # ── Lecturas ─────────────────────────────────────────────────────────────

    def resumen(self, tienda=None, desde=None, hasta=None) -> dict:
        """La pantalla del dueño, indexada por turno para poder preguntarle por un
        día puntual."""
        filas = consig_svc.get_resumen_admin(
            self.db, tienda.id if tienda is not None else None,
            desde=desde, hasta=hasta)
        return {f["turno_id"]: f for f in filas}

    def imputacion(self, tienda=None) -> dict:
        """La OTRA cuenta: la que usan `recoger`, `get_pendiente` y el cuadre de
        apertura. Todo este cambio existe para que las dos digan lo mismo."""
        tienda = tienda or self.palmetto
        return {s["turno"].id: s
                for s in consig_svc._saldos_consignacion(self.db, tienda.id)}

    def cruces(self, fila, clave) -> list:
        """`cubrio` / `cubierto_por` reducidos a (turno, monto) para poder
        compararlos de un vistazo. La fecha se chequea aparte, donde importa."""
        return [(c["turno_id"], c["monto"]) for c in fila[clave]]

    def assert_pantalla_e_imputacion_coinciden(self, tienda=None):
        """LA INVARIANTE. Para CADA turno de la sede, lo que la pantalla muestra
        como pendiente es exactamente el saldo post-cascada que la imputación
        cobra. Es la prueba de que dejaron de ser dos cuentas."""
        tienda = tienda or self.palmetto
        filas = self.resumen(tienda)
        saldos = self.imputacion(tienda)
        self.assertEqual(set(filas), set(saldos),
                         "la pantalla y la imputación no ven los mismos turnos")
        for tid, s in saldos.items():
            self.assertEqual(filas[tid]["saldo_pendiente"], round(s["saldo"], 2),
                             f"turno {tid}: la pantalla y la imputación discrepan")


class ElLunesEnContraTest(CascadaBase):
    """EL CASO DEL DUEÑO, con sus números. Si de todo este archivo pasara un solo
    test, tiene que ser el de esta clase.

    Tres días de Palmetto, encadenados como pasó de verdad:

        sábado   vende $300.000 y cierra con eso en el cajón
        domingo  cuenta los $300.000 del sábado, vende $400.000
        lunes    el sábado se va al banco; cuenta los $400.000 del domingo,
                 vende $100.000 y paga $277.700 de contado

    El lunes cierra con $222.300 en el cajón y $177.700 EN CONTRA: pagó de la
    registradora más de lo que entró. Esa plata salió de la venta del domingo, que
    estaba ahí mismo. La cascada lo dice; la pantalla no lo decía.
    """

    def setUp(self):
        super().setUp()
        self.sabado, self.domingo, self.lunes = self.dia(-3), self.dia(-2), self.dia(-1)

        self.sab = self.jornada(self.sabado, en_caja=0, venta=300_000)
        self.dom = self.jornada(self.domingo, en_caja=300_000, incluye=[self.sab],
                                venta=400_000)
        # El lunes a la mañana la plata del sábado se va al banco: el cajón queda
        # con los $400.000 del domingo, que son los que la barista cuenta.
        self.consignar(self.sab, 300_000, self.momento(self.lunes, 7))
        self.lun = self.jornada(self.lunes, en_caja=400_000, incluye=[self.dom],
                                venta=100_000, pagado=277_700)

    def test_el_domingo_muestra_el_descuento_y_dice_quien_se_lo_llevo(self):
        """EL NÚMERO QUE PIDIÓ. El domingo generó $400.000 y hay que bancar
        $222.300, porque $177.700 ya se usaron para pagar el lunes.

        `esperado_consignar` NO cambia —sigue siendo la cuenta cruda del día, lo
        que ese domingo generó— y el descuento viaja aparte. Son dos preguntas
        distintas («¿cuánto hizo ese día?» y «¿cuánto falta mandar al banco?») y
        colapsarlas en un solo campo es lo que dejó la pantalla sin poder explicar
        nada.
        """
        dom = self.resumen(self.palmetto)[self.dom.id]
        self.assertEqual(dom["esperado_consignar"], 400_000)
        self.assertEqual(dom["cubrio_faltante"], 177_700)
        self.assertEqual(dom["saldo_pendiente"], 222_300)
        self.assertEqual(self.cruces(dom, "cubrio"), [(self.lun.id, 177_700)])

    def test_el_lunes_queda_en_cero_y_dice_quien_se_lo_puso(self):
        """El lunes cerró $177.700 en contra y no hay nada que bancar de ese día:
        `saldo_pendiente` en CERO. Pero cero sin explicación es el estado en el que
        estaba antes —el negativo que nadie miraba—, así que el turno tiene que
        poder decir de dónde salió la plata que gastó."""
        lun = self.resumen(self.palmetto)[self.lun.id]
        self.assertEqual(lun["esperado_consignar"], -177_700)
        self.assertEqual(lun["saldo_pendiente"], 0)
        self.assertEqual(self.cruces(lun, "cubierto_por"), [(self.dom.id, 177_700)])
        # Y no quedó nada colgando: la venta del domingo alcanzó para todo.
        self.assertEqual(lun["faltante_sin_cubrir"], 0)

    def test_las_dos_listas_son_espejo(self):
        """Cada peso que sale de un turno entra en otro. Si `cubrio` y
        `cubierto_por` no cerraran entre sí, la pantalla podría mostrar un
        descuento que ningún otro día reclama — plata evaporada con dos renglones
        que se contradicen."""
        filas = self.resumen(self.palmetto)
        self.assertEqual(self.cruces(filas[self.dom.id], "cubrio"),
                         [(self.lun.id, 177_700)])
        self.assertEqual(self.cruces(filas[self.lun.id], "cubierto_por"),
                         [(self.dom.id, 177_700)])
        self.assertEqual(filas[self.dom.id]["cubrio_faltante"],
                         sum(c["monto"] for c in filas[self.lun.id]["cubierto_por"]))

    def test_la_procedencia_viaja_con_la_fecha_del_otro_dia(self):
        """Sin la fecha, la pantalla tiene un `turno_id` y no una explicación: el
        dueño piensa en días, no en ids. Es lo que deja escribir «cubrió el
        faltante del lunes 17» en vez de «cubrió el faltante del turno 42»."""
        dom = self.resumen(self.palmetto)[self.dom.id]
        self.assertEqual(dom["cubrio"][0]["fecha_cierre"], self.lun.fecha_cierre)
        lun = self.resumen(self.palmetto)[self.lun.id]
        self.assertEqual(lun["cubierto_por"][0]["fecha_cierre"], self.dom.fecha_cierre)

    def test_el_saldo_del_domingo_es_la_plata_que_de_verdad_quedo_en_el_cajon(self):
        """LA PRUEBA QUE AL DUEÑO LE SIRVE, y la única que no depende de creerle a
        ninguna fórmula: el lunes cerró contando $222.300 en el cajón, y $222.300
        es lo que el sistema pide bancar. La pantalla vieja pedía $400.000 — plata
        que ya no estaba ahí."""
        dom = self.resumen(self.palmetto)[self.dom.id]
        self.assertEqual(self.lun.efectivo_final_real, 222_300)
        self.assertEqual(dom["saldo_pendiente"], self.lun.efectivo_final_real)

    def test_el_sabado_ya_consignado_no_le_presta_a_nadie(self):
        """La cascada cobra del MÁS VIEJO CON SALDO, y el sábado ya no tiene: se
        bancó entero el lunes a la mañana. Si un turno saldado igual prestara, el
        sistema estaría cobrando dos veces la misma plata — una al banco y otra al
        hueco del lunes."""
        sab = self.resumen(self.palmetto)[self.sab.id]
        self.assertEqual(sab["esperado_consignar"], 300_000)
        self.assertEqual(sab["total_consignado"], 300_000)
        self.assertEqual(sab["saldo_pendiente"], 0)
        self.assertEqual(sab["cubrio_faltante"], 0)
        self.assertEqual(sab["cubrio"], [])

    def test_por_http_el_dueno_ve_exactamente_ese_numero(self):
        """La cadena entera por la puerta que él usa. El router no tiene
        `response_model`, así que los campos salen tal cual los arma el servicio —
        razón de más para fijarlos acá."""
        r = self.client.get("/api/v1/consignaciones/resumen-admin",
                            params={"tienda_id": self.palmetto.id})
        self.assertEqual(r.status_code, 200, r.text)
        filas = {f["turno_id"]: f for f in r.json()}
        self.assertEqual(filas[self.dom.id]["saldo_pendiente"], 222_300)
        self.assertEqual(filas[self.dom.id]["cubrio_faltante"], 177_700)
        self.assertEqual(filas[self.lun.id]["saldo_pendiente"], 0)
        self.assertEqual(filas[self.lun.id]["cubierto_por"][0]["turno_id"], self.dom.id)

    def test_los_campos_viejos_no_cambiaron_de_valor(self):
        """El contrato dice que lo que ya existía sigue igual. La pantalla actual
        y el reporte imprimible leen esos campos, y moverlos «de paso» rompería
        filas que no tienen nada que ver con la cascada."""
        dom = self.resumen(self.palmetto)[self.dom.id]
        self.assertEqual(dom["total_efectivo"], 400_000)
        self.assertEqual(dom["total_egresos"], 0)
        self.assertEqual(dom["diferencia_cierre"], 0)
        self.assertEqual(dom["esperado_consignar"], 400_000)   # crudo, sin cascada
        self.assertEqual(dom["total_consignado"], 0)
        self.assertEqual(dom["diferencia"], -400_000)          # consignado − esperado

    def test_la_pantalla_y_la_imputacion_dicen_lo_mismo(self):
        self.assert_pantalla_e_imputacion_coinciden()


class LaMismaCuentaParaTodosTest(CascadaBase):
    """LA INVARIANTE QUE MATA LA DIVERGENCIA, sobre un escenario mezclado.

    Dos sedes, cinco turnos, algunos con cascada de por medio y otros sin nada
    raro. Para CADA uno: lo que la pantalla muestra como pendiente es el saldo que
    la imputación cobra. Si alguien vuelve a calcular el resumen por su cuenta
    —que es exactamente el bug que se está cerrando— alguna de estas filas se
    tiene que caer.

    En Palmetto el que presta es el DOMINGO: es el día anterior al del hueco y
    tiene saldo. El sábado queda intacto aunque también deba, porque su plata ya
    está separada esperando el viaje al banco.
    """

    def setUp(self):
        super().setUp()
        sabado, domingo, lunes = self.dia(-3), self.dia(-2), self.dia(-1)

        # ── Palmetto: el sábado queda a medio consignar y termina prestando ──
        self.sab = self.jornada(sabado, en_caja=0, venta=300_000,
                                tienda=self.palmetto)
        self.consignar(self.sab, 100_000, self.momento(domingo, 7))
        self.dom = self.jornada(domingo, en_caja=200_000, incluye=[self.sab],
                                venta=400_000, tienda=self.palmetto)
        self.lun = self.jornada(lunes, en_caja=600_000, incluye=[self.sab, self.dom],
                                venta=100_000, pagado=277_700, tienda=self.palmetto)

        # ── Vida: dos días normales, sin un solo cruce ───────────────────────
        self.vida_sab = self.jornada(sabado, en_caja=0, venta=150_000,
                                     tienda=self.vida)
        self.vida_dom = self.jornada(domingo, en_caja=150_000, incluye=[self.vida_sab],
                                     venta=250_000, tienda=self.vida)

    def test_cada_turno_de_cada_sede_repite_el_saldo_de_la_imputacion(self):
        self.assert_pantalla_e_imputacion_coinciden(self.palmetto)
        self.assert_pantalla_e_imputacion_coinciden(self.vida)

    def test_el_escenario_tiene_de_las_dos_clases_de_fila(self):
        """El guardián del test de arriba: una invariante sobre filas todas
        iguales no prueba nada. Acá hay filas CON cascada y filas SIN, y si un
        refactor dejara la cascada sin correr, esta comprobación se cae antes que
        la invariante — que seguiría cerrando, porque las dos cuentas estarían
        igual de mal."""
        filas = self.resumen(self.palmetto)
        self.assertTrue(any(f["cubrio_faltante"] > 0 for f in filas.values()))
        self.assertTrue(any(f["cubierto_por"] for f in filas.values()))
        self.assertTrue(any(f["saldo_pendiente"] > 0 and not f["cubrio"]
                            for f in filas.values()))

    def test_la_cascada_cobra_del_dia_anterior_y_no_del_mas_viejo(self):
        """LA REGLA, con el escenario que el dueño corrigió.

        El sábado todavía tiene $200.000 sin consignar y aun así NO paga: paga el
        domingo. La plata con la que se tapó el hueco del lunes es la que estaba
        en el cajón esa mañana, o sea la venta del día anterior. La del sábado ya
        está separada esperando el banco.

        La versión original cobraba al más viejo y por eso le pegaba al sábado.
        Si el copy de la pantalla dijera «se descuenta del día anterior», ahora
        dice la verdad."""
        filas = self.resumen(self.palmetto)
        self.assertEqual(filas[self.dom.id]["cubrio_faltante"], 177_700)
        self.assertEqual(filas[self.dom.id]["saldo_pendiente"], 222_300)
        self.assertEqual(filas[self.sab.id]["cubrio_faltante"], 0)
        self.assertEqual(filas[self.sab.id]["saldo_pendiente"], 200_000)
        self.assertEqual(self.cruces(filas[self.lun.id], "cubierto_por"),
                         [(self.dom.id, 177_700)])

    def test_lo_que_se_cobra_al_recoger_es_el_numero_de_la_pantalla(self):
        """El cierre del círculo: el dueño mira la fila, aprieta «Recogí $X» y el
        servicio recalcula el valor por su cuenta (jamás confía en el cliente). Si
        la pantalla dijera otra cosa que la imputación, el botón cobraría un número
        distinto del que él vio un segundo antes."""
        antes = self.resumen(self.palmetto)
        r = consig_svc.recoger(self.db, self.palmetto.id,
                               [self.sab.id, self.dom.id], self.admin.id)
        cobrado = {c["turno_id"]: c["valor"] for c in r["recogidas"]}
        self.assertEqual(cobrado[self.sab.id], antes[self.sab.id]["saldo_pendiente"])
        self.assertEqual(cobrado[self.dom.id], antes[self.dom.id]["saldo_pendiente"])
        self.assertEqual(r["total"], 22_300 + 400_000)

        # Y después de cobrar, la pantalla queda en cero para esos días.
        despues = self.resumen(self.palmetto)
        self.assertEqual(despues[self.sab.id]["saldo_pendiente"], 0)
        self.assertEqual(despues[self.dom.id]["saldo_pendiente"], 0)
        self.assert_pantalla_e_imputacion_coinciden()

    def test_el_listado_de_pendientes_y_la_pantalla_suman_igual(self):
        """`get_pendiente` es lo que ve el kiosko cuando la barista marca qué días
        están en la caja. Sale de la misma función, y por eso tiene que dar la
        misma plata que la pantalla del dueño."""
        pendiente = consig_svc.get_pendiente(self.db, self.palmetto.id)
        filas = self.resumen(self.palmetto)
        self.assertEqual(pendiente["total_pendiente"],
                         round(sum(f["saldo_pendiente"] for f in filas.values()), 2))
        for item in pendiente["items"]:
            self.assertEqual(item["pendiente"],
                             filas[item["turno_id"]]["saldo_pendiente"])

    def test_el_hueco_de_palmetto_no_toca_el_cajon_de_vida(self):
        """POR SEDE. Son dos cajones físicos en dos barrios distintos: la plata que
        Vida no mandó al banco no puede pagar lo que Palmetto gastó de más."""
        vida = self.resumen(self.vida)
        self.assertEqual(vida[self.vida_sab.id]["saldo_pendiente"], 150_000)
        self.assertEqual(vida[self.vida_dom.id]["saldo_pendiente"], 250_000)
        for fila in vida.values():
            self.assertEqual(fila["cubrio_faltante"], 0)
            self.assertEqual(fila["cubrio"], [])
            self.assertEqual(fila["cubierto_por"], [])
            self.assertEqual(fila["faltante_sin_cubrir"], 0)

    def test_ningun_cruce_apunta_a_un_turno_de_otra_sede(self):
        """La otra mitad del aislamiento, mirada desde los cruces: alcanzaría con
        que la cascada corriera sobre la lista mezclada de las dos sedes para que
        un turno de Vida apareciera tapando un hueco de Palmetto — y el descuento
        se vería en la sede equivocada."""
        de_la_sede = {t.id: t.tienda_id for t in self.db.query(CajaTurno).all()}
        for fila in self.resumen().values():          # las dos sedes juntas
            for clave in ("cubrio", "cubierto_por"):
                for c in fila[clave]:
                    self.assertEqual(de_la_sede[c["turno_id"]], fila["tienda_id"],
                                     f"{clave} cruzó sedes en el turno {fila['turno_id']}")

    def test_la_pantalla_sin_filtro_de_sede_trae_las_dos_y_no_las_mezcla(self):
        """La vista de la cadena. Cada sede resuelve su propia cascada y el
        resultado es idéntico al de mirarlas por separado."""
        todas = self.resumen()
        for tienda in (self.palmetto, self.vida):
            for tid, fila in self.resumen(tienda).items():
                self.assertEqual(todas[tid]["saldo_pendiente"], fila["saldo_pendiente"])
                self.assertEqual(todas[tid]["cubrio_faltante"], fila["cubrio_faltante"])


class LaSemanaDePalmettoTest(CascadaBase):
    """LA SEMANA REAL QUE HIZO CAMBIAR EL ORDEN, con las cifras de su pantalla.

    El dueño la miró y dijo: «el lunes sin consignación, al domingo 16 hay que
    quitarle $177.700». Y agregó el dato que rompía la versión anterior: el
    sábado NO está consignado.

    Con la cascada cobrando del más viejo, esos $177.700 salían del sábado —que
    tenía saldo de sobra— y el domingo quedaba entero. Al revés de lo que pasó.

    La plata con la que se tapó el hueco del lunes es la que estaba en el cajón
    esa mañana: la venta del domingo. La del sábado ya estaba separada esperando
    el viaje al banco.
    """

    def setUp(self):
        super().setUp()
        sab, dom, lun = self.dia(-3), self.dia(-2), self.dia(-1)
        # Sábado: los $697.900 de su pantalla ya con la base descontada por el
        # traslado, o sea los $197.900 que hay que bancar.
        self.sab = self.jornada(sab, en_caja=0, venta=197_900)
        self.dom = self.jornada(dom, en_caja=197_900, incluye=[self.sab],
                                venta=334_400)
        # Lunes: vendió $215.780 en efectivo y pagó $393.480 de la registradora.
        self.lun = self.jornada(lun, en_caja=532_300, incluye=[self.sab, self.dom],
                                venta=215_780, pagado=393_480)
        self.filas = self.resumen(self.palmetto)

    def test_el_lunes_queda_en_cero(self):
        self.assertEqual(self.filas[self.lun.id]["esperado_consignar"], -177_700)
        self.assertEqual(self.filas[self.lun.id]["saldo_pendiente"], 0)
        self.assertEqual(self.filas[self.lun.id]["faltante_sin_cubrir"], 0)

    def test_al_domingo_se_le_quitan_los_177700(self):
        dom = self.filas[self.dom.id]
        self.assertEqual(dom["esperado_consignar"], 334_400)
        self.assertEqual(dom["cubrio_faltante"], 177_700)
        self.assertEqual(dom["saldo_pendiente"], 156_700)
        self.assertEqual(self.cruces(dom, "cubrio"), [(self.lun.id, 177_700)])

    def test_el_sabado_queda_intacto_aunque_no_este_consignado(self):
        """EL PUNTO DEL CAMBIO. Tiene saldo, es más viejo, y aun así no paga."""
        sab = self.filas[self.sab.id]
        self.assertEqual(sab["total_consignado"], 0)
        self.assertEqual(sab["cubrio_faltante"], 0)
        self.assertEqual(sab["saldo_pendiente"], 197_900)

    def test_la_pantalla_y_la_imputacion_dicen_lo_mismo(self):
        self.assert_pantalla_e_imputacion_coinciden()


class ElRangoNoMueveLaPlataTest(CascadaBase):
    """EL FILTRO DECIDE QUÉ FILAS SE MUESTRAN, JAMÁS A QUIÉN SE LE COBRA.

    `get_resumen_admin` acepta desde/hasta (y sin rango corta en 60 turnos), pero
    la cascada corre sobre la HISTORIA COMPLETA de la sede. Es el punto del
    contrato más fácil de romper «optimizando»: correrla sobre lo filtrado ahorra
    trabajo y parece inocente.

    No lo es. Acá el hueco del lunes es de $500.000 y no alcanza con un solo día:
    se lleva los $400.000 del domingo y $100.000 del sábado. Si la cascada se
    acotara al filtro, mirando «sábado y domingo» —sin el lunes a la vista— no
    habría ningún hueco que cobrar y los dos días volverían a valer lo que
    vendieron. El mismo día valdría dos cosas según por dónde se entró, y ninguna
    de las dos coincidiría con lo que `recoger()` cobra de verdad.
    """

    def setUp(self):
        super().setUp()
        self.sabado, self.domingo, self.lunes = self.dia(-3), self.dia(-2), self.dia(-1)

        self.sab = self.jornada(self.sabado, en_caja=0, venta=300_000)
        self.consignar(self.sab, 100_000, self.momento(self.domingo, 7))
        self.dom = self.jornada(self.domingo, en_caja=200_000, incluye=[self.sab],
                                venta=400_000)
        self.lun = self.jornada(self.lunes, en_caja=600_000, incluye=[self.sab, self.dom],
                                venta=100_000, pagado=600_000)
        # Sin filtro: el domingo pone sus $400.000 y el sábado completa $100.000.
        self.completo = self.resumen(self.palmetto)

    def test_dejar_afuera_a_uno_de_los_que_pago_no_mueve_al_otro(self):
        """El rango arranca el domingo: el sábado —que puso $100.000— no aparece.
        El domingo tiene que seguir en cero, con sus $400.000 puestos. Si volviera
        a valer $400.000, la cascada se estaría cobrando adentro del filtro."""
        filtrado = self.resumen(self.palmetto, desde=self.domingo, hasta=self.lunes)
        self.assertNotIn(self.sab.id, filtrado)
        self.assertEqual(filtrado[self.dom.id]["cubrio_faltante"], 400_000)
        self.assertEqual(filtrado[self.dom.id]["saldo_pendiente"], 0)

    def test_el_cruce_sigue_apuntando_al_turno_que_quedo_fuera_del_rango(self):
        """Y el lunes sigue diciendo que el sábado le tapó el hueco, aunque el
        sábado no esté en pantalla. Es información que la UI necesita para poder
        avisar «(fuera del periodo mostrado)» en vez de inventar una explicación
        con los días que sí tiene a mano."""
        filtrado = self.resumen(self.palmetto, desde=self.domingo, hasta=self.lunes)
        self.assertEqual(self.cruces(filtrado[self.lun.id], "cubierto_por"),
                         [(self.dom.id, 400_000), (self.sab.id, 100_000)])

    def test_dejar_afuera_al_que_debia_no_le_devuelve_la_plata_al_que_presto(self):
        """El espejo, y el caso que más discrimina: el rango termina el domingo y
        el lunes —el del hueco— no aparece. Los dos tienen que seguir con su
        descuento puesto. Si volvieran a $200.000 y $400.000, el dueño vería plata
        que ya se gastó."""
        filtrado = self.resumen(self.palmetto, desde=self.sabado, hasta=self.domingo)
        self.assertNotIn(self.lun.id, filtrado)
        self.assertEqual(filtrado[self.sab.id]["saldo_pendiente"], 100_000)
        self.assertEqual(filtrado[self.dom.id]["saldo_pendiente"], 0)
        self.assertEqual(filtrado[self.sab.id]["cubrio_faltante"], 100_000)
        self.assertEqual(filtrado[self.dom.id]["cubrio_faltante"], 400_000)
        # Y cada uno sigue diciendo a quién se lo tapó, aunque el lunes no esté.
        self.assertEqual(self.cruces(filtrado[self.sab.id], "cubrio"),
                         [(self.lun.id, 100_000)])
        self.assertEqual(self.cruces(filtrado[self.dom.id], "cubrio"),
                         [(self.lun.id, 400_000)])

    def test_un_solo_dia_en_pantalla_vale_lo_mismo_que_en_la_lista_entera(self):
        """El caso extremo, que es además el que el dueño usa: entra a mirar UN
        día. Con la cascada acotada al filtro, un día solo no tendría de quién
        cobrarse y aparecería siempre entero."""
        for turno in (self.sab, self.dom, self.lun):
            dia_ = (turno.fecha_apertura + timedelta(hours=-5)).date()
            solo = self.resumen(self.palmetto, desde=dia_, hasta=dia_)
            self.assertEqual(list(solo), [turno.id],
                             f"el rango de un día trajo más de una fila: {list(solo)}")
            fila = solo[turno.id]
            for campo in ("esperado_consignar", "saldo_pendiente", "cubrio_faltante",
                          "faltante_sin_cubrir", "total_consignado"):
                self.assertEqual(fila[campo], self.completo[turno.id][campo],
                                 f"{campo} del turno {turno.id} cambió con el rango")
            for clave in ("cubrio", "cubierto_por"):
                self.assertEqual(self.cruces(fila, clave),
                                 self.cruces(self.completo[turno.id], clave))


class CascadaEnCadenaTest(CascadaBase):
    """UN HUECO QUE NO ALCANZA A TAPARSE CON UN SOLO DÍA.

    Tres días sin consignar y un cuarto que cierra $120.000 en contra. El día
    ANTERIOR aporta todo lo que tiene y el de más atrás pone SOLO lo que falta —
    no todo lo suyo, que es el error clásico de una cascada mal escrita (vaciar
    los dos deja al dueño con dos días en cero y plata en el cajón que nadie
    reclama).

    El escenario cierra contra el cajón físico: al final quedan $30.000 adentro y
    $30.000 es lo que el sistema pide bancar, repartido en un solo día.
    """

    def setUp(self):
        super().setUp()
        d1, d2, d3 = self.dia(-3), self.dia(-2), self.dia(-1)
        self.uno = self.jornada(d1, en_caja=0, venta=100_000)
        self.dos = self.jornada(d2, en_caja=100_000, incluye=[self.uno], venta=50_000)
        self.tres = self.jornada(d3, en_caja=150_000, incluye=[self.uno, self.dos],
                                 venta=30_000, pagado=150_000)
        self.filas = self.resumen(self.palmetto)

    def test_el_anterior_se_vacia_primero(self):
        """EL DÍA ANTERIOR PRIMERO: es la plata que estaba en el cajón cuando se
        hizo el hueco. El orden no es un detalle de implementación — decide qué
        día del calendario aparece con el descuento."""
        dos = self.filas[self.dos.id]
        self.assertEqual(dos["esperado_consignar"], 50_000)
        self.assertEqual(dos["cubrio_faltante"], 50_000)
        self.assertEqual(dos["saldo_pendiente"], 0)

    def test_el_de_mas_atras_pone_solo_lo_que_falta(self):
        """$70.000 de los $100.000 que tenía. Vaciarlo entero sería cobrar
        $30.000 de más a un día que no los debe."""
        uno = self.filas[self.uno.id]
        self.assertEqual(uno["esperado_consignar"], 100_000)
        self.assertEqual(uno["cubrio_faltante"], 70_000)
        self.assertEqual(uno["saldo_pendiente"], 30_000)

    def test_el_dia_del_hueco_lista_a_sus_dos_acreedores_en_orden(self):
        """La explicación completa, en el orden en que se cobró. Con una sola línea
        —o con las dos sumadas en un total— el dueño no puede reconstruir por qué
        dos días distintos bajaron a la vez."""
        tres = self.filas[self.tres.id]
        self.assertEqual(tres["esperado_consignar"], -120_000)
        self.assertEqual(tres["saldo_pendiente"], 0)
        self.assertEqual(self.cruces(tres, "cubierto_por"),
                         [(self.dos.id, 50_000), (self.uno.id, 70_000)])
        self.assertEqual(tres["faltante_sin_cubrir"], 0)

    def test_lo_que_queda_por_bancar_es_lo_que_quedo_en_el_cajon(self):
        """El cierre físico del escenario: $30.000 contados al cierre del tercer
        día, $30.000 pendientes en total."""
        self.assertEqual(self.tres.efectivo_final_real, 30_000)
        self.assertEqual(round(sum(f["saldo_pendiente"] for f in self.filas.values()), 2),
                         30_000)

    def test_la_pantalla_y_la_imputacion_dicen_lo_mismo(self):
        self.assert_pantalla_e_imputacion_coinciden()


class FaltanteSinCubrirTest(CascadaBase):
    """EL DÉFICIT QUE NO ENCONTRÓ DE DÓNDE COBRARSE, QUE HASTA HOY NO SE VEÍA.

    Cuando un turno cierra en contra y no queda saldo viejo del cual cobrarse, la
    cascada se queda con un remanente. El código lo llamaba «sobrepago histórico;
    se ignora» y lo tiraba: la aritmética quedaba consistente y el dueño nunca se
    enteraba de que había plata faltando.

    LA ARITMÉTICA NO CAMBIA —se sigue ignorando para el saldo— pero ahora se
    expone en `faltante_sin_cubrir`. Que se ignore en la cuenta es defendible;
    que no se pueda mirar, no.

    El caso realista es el de un cajón que arrancó con plata que el sistema no
    conocía (la carga inicial, o un turno viejo sin cuadre): se pagó de contado con
    esa plata y la contabilidad no tiene a qué día cobrárselo.
    """

    def _turno_viejo_con_plata_de_antes(self, d: date, *, base, venta, pagado):
        """Un turno del mundo pre-sistema: abre con plata en el cajón que ninguna
        venta registrada explica.

        Va por el cuadre UNIFICADO a propósito: esa rama deja `sobrante_consignable`
        en NULL, igual que los turnos viejos de verdad, así que la plata de más NO
        entra al esperado a consignar. Es lo que hace que el día pueda pagar más de
        lo que vendió sin que la contabilidad tenga de dónde descontarlo.
        """
        turno = svc.abrir_caja(self.db, self.palmetto.id, base,
                               "Plata en caja de antes del sistema", self.admin.id,
                               barista_ids=[self.barista.id], tipo_turno="apertura")
        turno.fecha_apertura = self.momento(d, 7)
        self.db.commit()
        self._anclar_cuadre(turno, self.momento(d, 7))
        self.vender_efectivo(turno, venta)
        self.egreso(turno, pagado, self.momento(d, 11))
        return self.cerrar(turno, contado=base + venta - pagado,
                           momento=self.momento(d, 18))

    def test_el_faltante_se_expone_y_el_saldo_queda_en_cero(self):
        """El primer turno de la historia cierra $100.000 en contra: no hay ningún
        día anterior al cual cobrárselos. El saldo es CERO —no negativo: no hay
        nada que bancar de ese día— y los $100.000 salen por `faltante_sin_cubrir`,
        que es la plata que falta."""
        turno = self._turno_viejo_con_plata_de_antes(
            self.dia(-2), base=200_000, venta=20_000, pagado=120_000)

        fila = self.resumen(self.palmetto)[turno.id]
        self.assertEqual(fila["esperado_consignar"], -100_000)
        self.assertEqual(fila["saldo_pendiente"], 0)
        self.assertEqual(fila["faltante_sin_cubrir"], 100_000)
        self.assertEqual(fila["cubierto_por"], [])
        self.assert_pantalla_e_imputacion_coinciden()

    def test_el_faltante_no_se_cuela_en_lo_que_hay_que_bancar(self):
        """El día siguiente vende normal y su saldo queda ENTERO. La cascada mira
        hacia atrás y nunca hacia adelante: cobrarle a un día posterior sería
        inventar que la plata de mañana pagó lo de ayer.

        Y el total pendiente de la sede sigue siendo el de ese día solo: el
        faltante se ve, pero no suma ni resta."""
        viejo = self._turno_viejo_con_plata_de_antes(
            self.dia(-3), base=200_000, venta=20_000, pagado=120_000)
        # En el cajón quedaron $100.000 sin dueño contable. La barista los cuenta
        # y el sistema los llama sobrante de apertura: plata que hay que bancar
        # con ESTE turno, que es el mecanismo que ya existía para eso.
        nuevo = self.abrir_diferido(momento=self.momento(self.dia(-2), 7))
        self.cuadre_inicial(nuevo, efectivo_real=100_000,
                            momento=self.momento(self.dia(-2), 8),
                            justificacion="quedó plata del día anterior")
        self.vender_efectivo(nuevo, 250_000)
        self.cerrar(nuevo, contado=350_000, momento=self.momento(self.dia(-2), 18))

        filas = self.resumen(self.palmetto)
        self.assertEqual(filas[viejo.id]["faltante_sin_cubrir"], 100_000)
        self.assertEqual(filas[nuevo.id]["cubrio_faltante"], 0)
        self.assertEqual(filas[nuevo.id]["cubierto_por"], [])
        self.assertEqual(filas[nuevo.id]["saldo_pendiente"], 350_000)  # venta + sobrante
        self.assertEqual(round(sum(f["saldo_pendiente"] for f in filas.values()), 2),
                         350_000)
        self.assert_pantalla_e_imputacion_coinciden()

    def test_el_faltante_es_solo_el_remanente_que_no_alcanzo_a_cobrarse(self):
        """El caso mixto, que es el que de verdad va a aparecer: había $40.000 de
        un día anterior, el hueco es de $100.000. Se cobran los $40.000 y los
        $60.000 restantes quedan expuestos.

        La plata para pagar salió de la caja fuerte —$100.000 prestados al cajón—,
        que es de dónde sale en la vida real cuando la venta no alcanza. Al final
        quedan $40.000 en el cajón contra $100.000 prestados: la sede le debe
        $60.000 a su propia caja fuerte, y eso es exactamente `faltante_sin_cubrir`.
        """
        d1, d2 = self.dia(-2), self.dia(-1)
        uno = self.jornada(d1, en_caja=0, venta=40_000)
        dos = self.jornada(d2, en_caja=40_000, incluye=[uno], saca_base=100_000,
                           venta=10_000, pagado=110_000)

        filas = self.resumen(self.palmetto)
        self.assertEqual(filas[dos.id]["esperado_consignar"], -100_000)
        self.assertEqual(self.cruces(filas[dos.id], "cubierto_por"),
                         [(uno.id, 40_000)])
        self.assertEqual(filas[dos.id]["faltante_sin_cubrir"], 60_000)
        self.assertEqual(filas[dos.id]["saldo_pendiente"], 0)
        self.assertEqual(filas[uno.id]["saldo_pendiente"], 0)
        self.assertEqual(filas[uno.id]["cubrio_faltante"], 40_000)

        # La lectura física del mismo número: en el cajón hay $40.000 y $100.000
        # son de la caja fuerte.
        self.assertEqual(dos.efectivo_final_real, 40_000)
        self.assertEqual(filas[dos.id]["faltante_sin_cubrir"],
                         100_000 - dos.efectivo_final_real)
        self.assert_pantalla_e_imputacion_coinciden()


class ConLaBaseDeLaCajaFuerteTest(CascadaBase):
    """EL ORDEN: PRIMERO SE CORRIGE EL ESPERADO, DESPUÉS SE COBRA EL HUECO.

    El sábado 15 Palmetto sacó los $500.000 de la caja fuerte para completar un
    pago a proveedores, y NADIE lo registró: el turno cerró con $500.000 de
    sobrante congelado y pidiendo bancar $697.900 —la base de emergencia de la
    propia sede— en vez de $197.900. El traslado se cargó después, y
    `_sobrante_explicado_por_la_base` corrige ese turno ya cerrado sin reescribir
    ninguna columna.

    Encima de eso, el domingo cierra $250.000 en contra. Y acá el orden decide la
    plata:

        base primero, cascada después (lo correcto):
            el sábado tiene $197.900 → los da todos → queda en 0
            y el domingo se queda con $52.100 sin cubrir, que se ven
        cascada primero, base después (invertido):
            el sábado tendría $697.900 → daría $250.000 → quedaría en $447.900
            y el faltante desaparecería

    O sea que invirtiéndolo el sistema taparía el hueco con la base de emergencia
    de la sede y encima diría que no falta nada. Este es el test que lo fija.
    """

    def _arco(self, *, con_traslado: bool):
        """El sábado y el domingo de Palmetto. `con_traslado` es el interruptor
        entre el sistema que sabe que la base se movió y el que no: la plata
        física es idéntica en los dos mundos."""
        sabado, domingo = self.dia(-2), self.dia(-1)
        # Sábado: vende $697.900, paga $500.000 de contado y saca la base para
        # poder hacerlo. Como el traslado todavía no está cargado, el cierre ve
        # $500.000 que no espera y exige justificación.
        sab = self.jornada(sabado, en_caja=0, venta=697_900, pagado=500_000,
                           contado=697_900, justificacion="sobró plata, no sé de dónde")
        self.assertEqual(sab.diferencia_cierre, 500_000)

        if con_traslado:
            # Hoy, dos días después, el dueño carga el traslado con SU fecha real.
            self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 11))

        # Domingo: en el cajón están los $697.900 (los $197.900 propios más la base
        # prestada). Vende poco y paga $300.000 de contado: cierra en contra.
        dom = self.jornada(domingo, en_caja=697_900, incluye=[sab],
                           venta=50_000, pagado=300_000)
        return sab, dom

    def test_la_cascada_se_cobra_del_esperado_YA_corregido_por_la_base(self):
        """El sábado entra a la cascada valiendo $197.900 y no $697.900, así que
        alcanza a tapar $197.900 del hueco y no los $250.000 enteros."""
        sab, dom = self._arco(con_traslado=True)
        filas = self.resumen(self.palmetto)

        self.assertEqual(filas[sab.id]["esperado_consignar"], 197_900)
        self.assertEqual(filas[sab.id]["cubrio_faltante"], 197_900)
        self.assertEqual(filas[sab.id]["saldo_pendiente"], 0)

        self.assertEqual(filas[dom.id]["esperado_consignar"], -250_000)
        self.assertEqual(self.cruces(filas[dom.id], "cubierto_por"),
                         [(sab.id, 197_900)])
        self.assertEqual(filas[dom.id]["faltante_sin_cubrir"], 52_100)
        self.assert_pantalla_e_imputacion_coinciden()

    def test_con_el_orden_invertido_el_sabado_quedaria_pidiendo_447900(self):
        """El número que NO tiene que aparecer, escrito para que se vea la
        distancia: con la cascada corriendo antes de la corrección, el sábado
        quedaría en $447.900 y el faltante en cero."""
        sab, dom = self._arco(con_traslado=True)
        filas = self.resumen(self.palmetto)
        self.assertNotEqual(filas[sab.id]["saldo_pendiente"], 447_900)
        self.assertNotEqual(filas[dom.id]["faltante_sin_cubrir"], 0)

    def test_el_faltante_es_lo_que_la_sede_le_debe_a_su_propia_caja_fuerte(self):
        """La lectura física, que es la que le sirve al dueño: quedaron $447.900 en
        el cajón y $500.000 son de la caja fuerte. Faltan $52.100 para poder
        guardarla — y hasta ahora ese agujero no aparecía en ninguna pantalla."""
        sab, dom = self._arco(con_traslado=True)
        filas = self.resumen(self.palmetto)
        self.assertEqual(dom.efectivo_final_real, 447_900)
        self.assertEqual(filas[dom.id]["faltante_sin_cubrir"],
                         500_000 - dom.efectivo_final_real)

    def test_sin_el_traslado_el_hueco_se_paga_con_el_sobrante_fantasma(self):
        """El mundo viejo, con la misma plata física. Sin el traslado registrado el
        sábado vale $697.900 —incluye la base de emergencia— y el hueco del domingo
        se cobra de ahí sin que falte nada. Los dos números están mal y ninguno se
        ve mal: por eso el arreglo tenía que llegar hasta acá."""
        sab, dom = self._arco(con_traslado=False)
        filas = self.resumen(self.palmetto)
        self.assertEqual(filas[sab.id]["esperado_consignar"], 697_900)
        self.assertEqual(filas[sab.id]["saldo_pendiente"], 447_900)
        self.assertEqual(filas[dom.id]["faltante_sin_cubrir"], 0)

    def test_cargar_el_traslado_despues_mueve_las_dos_puntas_a_la_vez(self):
        """El sábado ya estaba cerrado y el domingo también. Cargar el traslado hoy
        corrige el esperado del sábado Y rehace la cascada del domingo en la misma
        lectura: no hay estado congelado en el medio que quede a mitad de camino."""
        sabado, domingo = self.dia(-2), self.dia(-1)
        sab = self.jornada(sabado, en_caja=0, venta=697_900, pagado=500_000,
                           contado=697_900, justificacion="sobró plata, no sé de dónde")
        dom = self.jornada(domingo, en_caja=697_900, incluye=[sab],
                           venta=50_000, pagado=300_000)
        antes = self.resumen(self.palmetto)
        self.assertEqual(antes[sab.id]["saldo_pendiente"], 447_900)

        self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 11))

        despues = self.resumen(self.palmetto)
        self.assertEqual(despues[sab.id]["saldo_pendiente"], 0)
        self.assertEqual(despues[sab.id]["cubrio_faltante"], 197_900)
        self.assertEqual(despues[dom.id]["faltante_sin_cubrir"], 52_100)
        self.assert_pantalla_e_imputacion_coinciden()


class TurnoSaldadoNoPrestaTest(CascadaBase):
    """UN TURNO CON SALDO CERO NO LE PRESTA A NADIE.

    Si un día ya consignado igual prestara, el sistema estaría cobrando dos veces
    la misma plata: una al banco, que ya la recibió, y otra al hueco de un día
    posterior. El saldo bajaría a negativo y la pantalla pediría bancar plata que
    no existe.

    La cascada tiene que SALTEARLO y seguir buscando hacia atrás, sin dejar rastro
    en él: ni `cubrio_faltante`, ni una fila de procedencia que no explique nada.
    """

    def test_el_dia_consignado_entero_se_saltea_y_paga_el_siguiente(self):
        d1, d2, d3 = self.dia(-3), self.dia(-2), self.dia(-1)
        uno = self.jornada(d1, en_caja=0, venta=100_000)
        # Se banca entero a la mañana siguiente: el cajón queda en cero.
        self.consignar(uno, 100_000, self.momento(d2, 7))
        dos = self.jornada(d2, en_caja=0, venta=200_000)
        tres = self.jornada(d3, en_caja=200_000, incluye=[dos],
                            venta=20_000, pagado=70_000)

        filas = self.resumen(self.palmetto)
        self.assertEqual(filas[uno.id]["saldo_pendiente"], 0)
        self.assertEqual(filas[uno.id]["cubrio_faltante"], 0)
        self.assertEqual(filas[uno.id]["cubrio"], [])
        # El hueco se lo comió el único día que todavía tenía plata sin bancar.
        self.assertEqual(filas[dos.id]["cubrio_faltante"], 50_000)
        self.assertEqual(filas[dos.id]["saldo_pendiente"], 150_000)
        self.assertEqual(self.cruces(filas[tres.id], "cubierto_por"),
                         [(dos.id, 50_000)])
        self.assertEqual(filas[tres.id]["saldo_pendiente"], 0)
        # Y el cajón lo confirma: $150.000 contados, $150.000 por bancar.
        self.assertEqual(tres.efectivo_final_real, 150_000)
        self.assert_pantalla_e_imputacion_coinciden()

    def test_el_dia_a_medio_consignar_presta_solo_lo_que_le_queda(self):
        """La versión parcial, que es la más común: se bancó una parte y el resto
        sigue en el cajón. Presta ese resto y ni un peso más — lo demás ya está en
        el banco y no se puede gastar dos veces."""
        d1, d2, d3 = self.dia(-3), self.dia(-2), self.dia(-1)
        # El PARCIAL es el día anterior al del hueco: es el que la cascada toca
        # primero, así que es donde el tope tiene que probarse.
        uno = self.jornada(d1, en_caja=0, venta=100_000)
        dos = self.jornada(d2, en_caja=100_000, incluye=[uno], venta=200_000)
        self.consignar(dos, 160_000, self.momento(d3, 7))
        tres = self.jornada(d3, en_caja=140_000, incluye=[uno, dos],
                            venta=20_000, pagado=70_000)

        filas = self.resumen(self.palmetto)
        self.assertEqual(filas[dos.id]["esperado_consignar"], 200_000)
        self.assertEqual(filas[dos.id]["total_consignado"], 160_000)
        self.assertEqual(filas[dos.id]["cubrio_faltante"], 40_000)   # lo que quedaba
        self.assertEqual(filas[dos.id]["saldo_pendiente"], 0)
        self.assertEqual(filas[uno.id]["cubrio_faltante"], 10_000)   # el resto
        self.assertEqual(filas[uno.id]["saldo_pendiente"], 90_000)
        self.assertEqual(self.cruces(filas[tres.id], "cubierto_por"),
                         [(dos.id, 40_000), (uno.id, 10_000)])
        # El cajón lo confirma: 100.000 + 200.000 − 160.000 + 20.000 − 70.000.
        self.assertEqual(tres.efectivo_final_real, 90_000)
        self.assert_pantalla_e_imputacion_coinciden()


if __name__ == "__main__":
    unittest.main()
