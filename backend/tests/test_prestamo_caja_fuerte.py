"""LA BASE DE LA CAJA FUERTE SALIÓ A TRABAJAR AL CAJÓN.

Cada sede guarda $500.000 fijos en la caja fuerte para emergencias. Cuando los
pagos a proveedores EN EFECTIVO se comen la venta en efectivo del día, la sede
saca esa base al cajón para completar —en cualquier momento del día, no al
abrir— y la vuelve a guardar cuando la venta se normaliza.

EL SISTEMA SABÍA CUÁNTO HABÍA EN LA CAJA FUERTE Y NO SABÍA QUE SE HABÍA MOVIDO.
`CajaTurno.caja_fuerte` guardaba el monto «aparte, no cuenta», y no existía forma
de registrar que esa plata se había pasado al cajón. Entonces el cuadre veía
efectivo de más en la registradora y concluía lo único que sabía concluir:
«sobró, hay que bancarla».

EL ERROR MEDIDO, que es la razón de existir de este archivo — Palmetto, sábado
15 de agosto:

    venden $697.900 en efectivo             → el cajón sube $697.900
    pagan $500.000 de contado a proveedores → el cajón baja $500.000
    sacan los $500.000 de la caja fuerte    → NO SE REGISTRABA: el cajón sube
                                              $500.000 que el cuadre no espera

    conteo del cierre: $697.900
    esperado (sin el término): $197.900  →  «sobran $500.000»
    y ese sobrante entra al esperado a consignar: pedía bancar $697.900.

Lo correcto son $197.900: la plata que sobraba no sobraba, estaba PRESTADA. Y
sobra hacia el lado CARO: le pide al dueño mandar al banco los $500.000 de
emergencia de su propia sede, justo en los meses en que el efectivo no alcanza.

El arreglo es UN TÉRMINO, no un mecanismo nuevo:

    efectivo_esperado = base + ventas + ingresos − egresos + PRESTADO

Lo que fijan estos tests, y por qué cada regla importa:

- con el traslado registrado el cuadre da EXACTO: no hay diferencia, no se fija
  `sobrante_consignable`, y el consignable del sábado da $197.900 sin que la
  fórmula del consignable (services/consignaciones.py) cambie una línea;
- el fantasma NO REAPARECE AL DÍA SIGUIENTE. Es el bug que hundió el diseño
  anterior: el domingo la barista cuenta los $500.000 adentro de la base, así que
  el término se lee distinto —saldo vigente en el cuadre inicial, delta del turno
  en todo cuadre posterior— y confundirlos vuelve a inventar el sobrante con el
  signo dado vuelta;
- el préstamo CRUZA DÍAS: sale el sábado y vuelve el miércoles, y los turnos del
  domingo, lunes y martes tienen que cuadrar igual;
- el saldo es POR SEDE: lo que saca Palmetto no descuadra a Vida;
- el corte es el INSTANTE del traslado, no el día Colombia: un traslado de las
  22:00 con la sede cerrada a las 20:00 no entra en ese turno aunque sea el mismo
  día calendario;
- un saldo NEGATIVO se muestra tal cual. Significa que alguien cargó un
  'devuelve' que nunca salió, y taparlo con un `max(0, ...)` convierte un dato mal
  cargado en un número tranquilizador — exactamente la familia de error que este
  módulo viene matando;
- las validaciones del alta viven en el HANDLER y vuelven como 400 con `detail`
  STRING. En un 422 de pydantic el `detail` es una LISTA y el cliente solo sabe
  renderizar strings: el dueño terminaba viendo «Reintentá» en vez del motivo;
- mover la base es decisión del dueño: la barista no puede cargar ni borrar un
  traslado. Si pudiera, el esperado del cuadre se movería sin que él lo sepa.
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
from app.database import Base, get_db
from app.models.models import (CajaTurno, EntregaTurno, EstadoTurnoEnum,
                               MovimientoCaja, PrestamoCajaFuerte, RolEnum,
                               Tienda, Usuario)
from app.routers import caja as caja_router
from app.routers import consignaciones as consignaciones_router
from app.services import caja as svc
from app.services import consignaciones as consig_svc


class CajaFuerteBase(unittest.TestCase):
    """sqlite temporal + los servicios y routers REALES (patrón de la suite).

    Se montan los dos routers en la misma app porque el cambio es una sola cosa
    partida en dos módulos: el traslado se teclea en `/caja/prestamos-caja-fuerte`
    y el efecto se lee en el cuadre y en `/consignaciones/resumen-admin`. Probar
    cada mitad contra un mock de la otra dejaría pasar justamente el desacuerdo
    que importa — que es todo el bug.

    Los turnos se abren y se cierran con `abrir_caja` / `registrar_cuadre_inicial`
    / `cerrar_caja` DE VERDAD, no con fixtures que escriben `diferencia_cierre` a
    mano: el término vive adentro de esas fórmulas y una fixture lo saltearía.
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

        app = FastAPI(title="Test préstamos de caja fuerte")
        app.include_router(caja_router.router, prefix="/api/v1")
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

    # ── Helpers de tiempo ────────────────────────────────────────────────────

    def set_current_user(self, user):
        """`require_admin` cuelga de `get_current_user`, así que sobreescribir
        este solo alcanza y el chequeo de rol sigue siendo el de producción."""
        self.app.dependency_overrides[get_current_user] = lambda: user

    def dia(self, delta: int) -> date:
        """Día Colombia relativo a hoy: todo lo que se mide acá se mide contra
        hoy, no contra una fecha fija del calendario."""
        return self.hoy + timedelta(days=delta)

    def momento(self, d: date, hora: int) -> datetime:
        """Instante UTC de las `hora`:00 COLOMBIA del día `d`.

        Los turnos y los traslados se anclan con esto y no con `utcnow()` porque
        el término se calcula comparando INSTANTES (`fecha <= hasta`): un turno
        que abre y un traslado que sale en el mismo microsegundo caen del lado
        equivocado del borde y el test se vuelve una moneda al aire.

        Ojo con el doble sistema: `momento(d, 23)` cae a las 04:00 UTC del día
        calendario SIGUIENTE. Es a propósito — es el caso que separa "instante"
        de "día Colombia", y hay tests que lo usan justamente para eso.
        """
        return inicio_dia_col_utc(d) + timedelta(hours=hora)

    # ── Helpers de turno (servicios reales, apertura y cierre anclados) ──────

    def _anclar_cuadre(self, turno, momento: datetime):
        """Backdatea el CUADRE de apertura, que es cosa distinta de la apertura.

        `_ts_conteo_base_real` ancla el delta prestado acá y no en
        `fecha_apertura`, y la diferencia entre los dos instantes es una ventana
        real: entre que el turno abre y la barista cuenta el efectivo pasa el
        conteo de inventario, que son horas. Los helpers los mueven por separado
        justamente para que esa ventana exista en los tests — si se movieran
        juntos, la regla que la protege quedaría sin medir (y en su momento
        quedó: el test que la cubre nació de una mutación que sobrevivió).
        """
        for e in (self.db.query(EntregaTurno)
                  .filter(EntregaTurno.turno_id == turno.id,
                          EntregaTurno.tipo == "apertura").all()):
            e.fecha_hora = momento
        self.db.commit()

    def _anclar_apertura(self, turno, momento: datetime):
        """Backdatea la apertura del turno (y su cuadre, si nació con ella).

        `abrir_caja` sella `fecha_apertura` con `utcnow()`, así que un arco de
        varios días solo se puede armar corriendo el reloj a mano. En el cuadre
        UNIFICADO el cuadre nace junto con la apertura y viaja con ella; en el
        diferido todavía no existe y lo ancla `cuadre_inicial` aparte.
        """
        turno.fecha_apertura = momento
        self._anclar_cuadre(turno, momento)

    def abrir(self, *, base_real, momento, tienda=None, justificacion=None):
        """Turno con CUADRE UNIFICADO: se cuenta el efectivo al abrir."""
        tienda = tienda or self.palmetto
        turno = svc.abrir_caja(self.db, tienda.id, base_real, justificacion,
                               self.admin.id, barista_ids=[self.barista.id],
                               tipo_turno="apertura")
        self._anclar_apertura(turno, momento)
        return turno

    def abrir_diferido(self, *, momento, tienda=None):
        """Turno con CUADRE DIFERIDO — el flujo real de la sede: el turno abre
        con las baristas y el efectivo se cuenta después del conteo de inventario,
        vía `registrar_cuadre_inicial`."""
        tienda = tienda or self.palmetto
        turno = svc.abrir_caja(self.db, tienda.id, None, None, self.admin.id,
                               barista_ids=[self.barista.id], tipo_turno="apertura")
        self._anclar_apertura(turno, momento)
        return turno

    def cuadre_inicial(self, turno, *, efectivo_real, momento, justificacion=None,
                       saldos_incluidos=None):
        """El conteo del efectivo tras el conteo de inventario.

        `saldos_incluidos` elige la OTRA rama del esperado: la barista marca qué
        días pendientes por consignar están físicamente en la caja y el esperado
        se arma desde la CONTABILIDAD, no desde el conteo del cierre anterior. Es
        la rama que nunca supo de la caja fuerte, así que hay tests para las dos.
        """
        svc.registrar_cuadre_inicial(self.db, turno.id, self.admin.id,
                                     efectivo_real=efectivo_real,
                                     justificacion=justificacion,
                                     saldos_incluidos=saldos_incluidos)
        # Solo el cuadre: la apertura del turno ya quedó anclada donde correspondía
        # y moverla acá borraría la ventana del conteo de inventario.
        self._anclar_cuadre(turno, momento)
        self.db.refresh(turno)
        return turno

    def vender_efectivo(self, turno, monto):
        """Lo que hace el POS: acumular la venta en efectivo del turno."""
        turno.total_efectivo = (turno.total_efectivo or 0) + monto
        self.db.commit()

    def egreso(self, turno, monto, momento, concepto="Pago proveedor de contado"):
        """El pago al proveedor EN EFECTIVO: la salida que se come la venta del
        día y obliga a sacar la base de la caja fuerte."""
        self.db.add(MovimientoCaja(caja_turno_id=turno.id, tipo="egreso",
                                   concepto=concepto, valor=monto,
                                   usuario_id=self.admin.id, fecha=momento))
        self.db.commit()

    def ingreso(self, turno, monto, momento, concepto="Ingreso de caja"):
        """Plata que ENTRA a la registradora sin ser venta.

        Es uno de los tres caminos por los que la base de la caja fuerte puede
        colarse al consignable, y el que de verdad usó la barista de Palmetto.
        """
        self.db.add(MovimientoCaja(caja_turno_id=turno.id, tipo="ingreso",
                                   concepto=concepto, valor=monto,
                                   usuario_id=self.admin.id, fecha=momento))
        self.db.commit()

    def cerrar(self, turno, *, contado, momento, justificacion=None):
        """Cierra el turno de verdad y ancla el cierre en `momento`.

        `tiene_conteo_cierre` se marca a mano porque el conteo de inventario es
        otro módulo entero y acá lo que se mide es el cuadre del efectivo."""
        turno.tiene_conteo_cierre = True
        self.db.commit()
        svc.cerrar_caja(self.db, turno.id, contado, justificacion, self.admin.id)
        turno.fecha_cierre = momento
        self.db.commit()
        self.db.refresh(turno)
        return turno

    # ── Helpers del traslado (por HTTP: es la puerta real) ───────────────────

    def traslado(self, monto, *, sentido="saca", tienda=None, momento=None,
                 motivo=None, esperar=201):
        tienda = tienda or self.palmetto
        body = {"tienda_id": tienda.id, "sentido": sentido, "monto": monto}
        if momento is not None:
            body["fecha"] = momento.isoformat()
        if motivo is not None:
            body["motivo"] = motivo
        r = self.client.post("/api/v1/caja/prestamos-caja-fuerte", json=body)
        if esperar is not None:
            self.assertEqual(r.status_code, esperar, r.text)
        return r

    def saldo(self, tienda=None) -> float:
        """El saldo vigente por HTTP — el número que la pantalla muestra."""
        tienda = tienda or self.palmetto
        r = self.client.get("/api/v1/caja/prestamos-caja-fuerte",
                            params={"tienda_id": tienda.id})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["prestado_caja_fuerte"]

    def consignable(self, turno) -> float:
        """El esperado a consignar de un turno, tal como lo ve el dueño en
        Consignaciones. Es EL número del caso: el que pedía $697.900."""
        fila = next(f for f in consig_svc.get_resumen_admin(self.db, turno.tienda_id)
                    if f["turno_id"] == turno.id)
        return fila["esperado_consignar"]

    def esperado_a_contar(self, tienda=None) -> dict:
        """Lo que el kiosko le muestra a la barista antes de contar."""
        return svc.get_efectivo_inicio_esperado(self.db, (tienda or self.palmetto).id)

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


class SabadoDePalmettoTest(CajaFuerteBase):
    """EL CASO REAL, con sus números. Si de todo este archivo pasara un solo
    test, tiene que ser el primero de esta clase."""

    def _sabado(self, *, con_traslado: bool):
        """El sábado 15 de agosto en Palmetto, completo. `con_traslado` es el
        interruptor entre el sistema que miente y el que no: TODO lo demás —la
        venta, el pago al proveedor, el efectivo que quedó en el cajón— es
        idéntico, porque la plata física fue exactamente la misma. Lo único que
        cambia es si el sistema SABE que la base se movió.
        """
        sabado = self.dia(-3)
        turno = self.abrir(base_real=0, momento=self.momento(sabado, 8))

        # Vendieron $697.900 en efectivo.
        self.vender_efectivo(turno, 697_900)
        # Y le pagaron $500.000 de contado a los proveedores: la venta en efectivo
        # del día no alcanzó para cubrirlos con margen.
        self.egreso(turno, 500_000, self.momento(sabado, 11))
        if con_traslado:
            # Por eso sacaron la base de la caja fuerte, a media mañana. ESTE es
            # el dato que no existía.
            self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 12),
                          motivo="Para completar el pago a proveedores")

        # Al cierre, en el cajón hay: 0 de base + 697.900 vendidos − 500.000
        # pagados + 500.000 que salieron de la caja fuerte.
        contado = 0 + 697_900 - 500_000 + 500_000
        self.assertEqual(contado, 697_900)
        # Sin el traslado registrado el cierre ve $500.000 de más y exige
        # justificación: la barista escribe cualquier cosa y sigue. Con el
        # traslado no hay diferencia y no hace falta ninguna.
        self.cerrar(turno, contado=contado, momento=self.momento(sabado, 21),
                    justificacion=None if con_traslado else "no sé, sobró")
        return turno

    def test_el_esperado_a_consignar_del_sabado_da_197900(self):
        """EL NÚMERO. Lo que hay que mandar al banco es la venta del día menos lo
        que se pagó de contado: $697.900 − $500.000. Los otros $500.000 son la
        base de emergencia de la sede y se vuelven a guardar, no se bancan."""
        turno = self._sabado(con_traslado=True)
        self.assertEqual(self.consignable(turno), 197_900)

    def test_sin_el_traslado_el_sistema_pide_bancar_la_base_de_la_sede(self):
        """El bug medido, tal cual. Es el ancla de la regresión: si alguien saca
        el término del cuadre, este test vuelve a pasar y el de arriba se cae.

        Fijate el mecanismo completo, porque el arreglo no toca ninguno de los
        dos últimos eslabones: el cuadre no espera la plata prestada → la lee
        como diferencia → la fórmula del consignable suma `diferencia_cierre` (y
        hace bien: una diferencia real SÍ hay que bancarla) → pide $697.900.
        """
        turno = self._sabado(con_traslado=False)
        self.assertEqual(turno.diferencia_cierre, 500_000)
        self.assertEqual(self.consignable(turno), 697_900)

    def test_con_el_traslado_el_cierre_no_tiene_diferencia(self):
        """La diferencia en cero es lo que hace todo lo demás: sin diferencia no
        hay nada que sumarle al consignable, y la fórmula del consignable no se
        toca ni una línea."""
        turno = self._sabado(con_traslado=True)
        self.assertEqual(turno.diferencia_cierre, 0)

    def test_el_cierre_cuadrado_no_exige_justificacion(self):
        """No es cosmética. Sin el término, cada sábado que la sede saca la base
        el cierre le exige a la barista justificar $500.000 que ella no perdió ni
        encontró — y la costumbre de escribir cualquier cosa para poder cerrar es
        la que después tapa un descuadre de verdad."""
        turno = self._sabado(con_traslado=True)
        self.assertIsNone(turno.justificacion_cierre)

    def test_el_consignable_se_lee_igual_por_http(self):
        """La cadena entera, por la puerta que usa el dueño: teclea el traslado en
        Caja y el número cambia en Consignaciones. Es el desacuerdo que un mock
        entre las dos mitades no encontraría."""
        turno = self._sabado(con_traslado=True)
        r = self.client.get("/api/v1/consignaciones/resumen-admin",
                            params={"tienda_id": self.palmetto.id})
        self.assertEqual(r.status_code, 200, r.text)
        fila = next(f for f in r.json() if f["turno_id"] == turno.id)
        self.assertEqual(fila["esperado_consignar"], 197_900)
        self.assertEqual(fila["diferencia_cierre"], 0)

    def test_la_base_prestada_no_se_resta_del_consignable(self):
        """LA TRAMPA DEL PRÓXIMO QUE LEA ESTO. Es tentador «arreglarlo» restando
        los $500.000 en la fórmula del consignable, que es donde se ve el síntoma.
        Sería restarlos DOS VECES —el cuadre ya los cuenta— y el sistema pediría
        consignar $500.000 DE MENOS, o sea $302.100 negativos de error hacia el
        lado que nadie audita. Este test fija que $197.900 sale del cuadre, no de
        una resta en consignaciones."""
        turno = self._sabado(con_traslado=True)
        self.assertEqual(self.consignable(turno),
                         697_900 - 500_000)     # venta − pagos de contado, y nada más
        self.assertEqual(turno.sobrante_consignable, None)


class ElSabadoQueYaHabiaCerradoTest(CajaFuerteBase):
    """EL CASO DEL DUEÑO DE VERDAD, y por poco se nos escapa.

    El sábado 15 ya está cerrado. `diferencia_cierre` y `sobrante_consignable` se
    escriben AL CERRAR y nadie las reescribe después, así que cargar el traslado
    hoy —martes 18— no las toca: sin `_sobrante_explicado_por_la_base` el sábado
    seguiría pidiendo $697.900 y el arreglo serviría para los sábados que vienen
    y no para el que él necesita.

    Esta clase fija el orden REAL de los hechos: primero se cerró el turno con el
    fantasma adentro, después se enteró el sistema.
    """

    def _sabado_cerrado_sin_traslado(self):
        sabado = self.dia(-3)
        turno = self.abrir(base_real=0, momento=self.momento(sabado, 8))
        self.vender_efectivo(turno, 697_900)
        self.egreso(turno, 500_000, self.momento(sabado, 11))
        # Sacaron la base a media mañana, pero NADIE lo registró: el sistema ve
        # $500.000 que no sabe de dónde salieron y exige justificación.
        self.cerrar(turno, contado=697_900, momento=self.momento(sabado, 21),
                    justificacion="sobró plata, no sé de dónde")
        return turno, sabado

    def test_el_traslado_cargado_despues_corrige_el_sabado_ya_cerrado(self):
        turno, sabado = self._sabado_cerrado_sin_traslado()
        # Así queda el mundo viejo: pide bancar la base de emergencia.
        self.assertEqual(self.consignable(turno), 697_900)

        # Hoy, tres días después, el dueño carga el traslado con SU fecha real.
        self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 12),
                      motivo="Para completar el pago a proveedores")

        # Y el sábado se corrige solo, sin reescribir ninguna columna congelada.
        self.assertEqual(self.consignable(turno), 197_900)

    def test_borrar_el_traslado_devuelve_el_sabado_a_como_estaba(self):
        """Cargado por error, se borra y no queda rastro en la cuenta."""
        turno, sabado = self._sabado_cerrado_sin_traslado()
        r = self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 12))
        self.assertEqual(self.consignable(turno), 197_900)

        borrado = self.client.delete(
            f"/api/v1/caja/prestamos-caja-fuerte/{r.json()['prestamo']['id']}")
        self.assertEqual(borrado.status_code, 200, borrado.text)
        self.assertEqual(self.consignable(turno), 697_900)

    def test_no_cancela_mas_sobrante_del_que_hay(self):
        """EL TOPE, que es lo que impide que esto reste dos veces.

        Un traslado de $500.000 sobre un turno cuyo sobrante congelado es de
        $120.000 cancela $120.000 y ni un peso más. Sin el tope, la diferencia
        se comería venta real y el sistema pediría consignar de menos — el lado
        tranquilizador, que es el caro.
        """
        sabado = self.dia(-3)
        turno = self.abrir(base_real=0, momento=self.momento(sabado, 8))
        self.vender_efectivo(turno, 400_000)
        self.cerrar(turno, contado=520_000, momento=self.momento(sabado, 21),
                    justificacion="sobró plata")
        self.assertEqual(self.consignable(turno), 520_000)   # 400.000 + 120.000

        self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 12))
        # Cancela los $120.000 de sobrante y deja la venta intacta.
        self.assertEqual(self.consignable(turno), 400_000)

    def test_un_faltante_no_lo_explica_la_base(self):
        """El otro tope: solo se cancela SOBRANTE. Un turno al que le FALTA plata
        no se arregla porque haya una base afuera — eso es una novedad de caja,
        y taparla con el traslado escondería un faltante real."""
        sabado = self.dia(-3)
        turno = self.abrir(base_real=0, momento=self.momento(sabado, 8))
        self.vender_efectivo(turno, 400_000)
        self.cerrar(turno, contado=350_000, momento=self.momento(sabado, 21),
                    justificacion="faltó plata")
        antes = self.consignable(turno)

        self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 12))
        self.assertEqual(self.consignable(turno), antes)


class LaBaseEntroComoIngresoDeCajaTest(CajaFuerteBase):
    """LA BASE PUEDE ENTRAR POR CUALQUIERA DE LOS TRES CAMINOS, y por poco se nos escapa.

    El dueño confirmó que su fórmula del consignable es
        ventas + ingresos de caja − egresos + diferencia de cierre + sobrante de apertura
    o sea que los tres términos que no son venta se quedan. Lo que NO puede pasar
    es que la base de la caja fuerte se cuele por alguno de ellos.

    La primera versión de `_sobrante_explicado_por_la_base` comparaba solo contra
    `diferencia_cierre + sobrante_consignable`. Con la base cargada como INGRESO
    DE CAJA —que es como la registró la barista— no cancelaba nada y el sábado
    seguía pidiendo $697.900. Ahora se compara contra los tres.

    Las cifras son las de la pantalla real de Palmetto, sábado 15 de agosto.
    """

    def _sabado_ya_cerrado(self):
        """El sábado tal como quedó en la base: la base entró como INGRESO y el
        turno cerró sin que existiera ningún traslado.

        El orden importa y es el real: primero cerró el turno, después nos
        enteramos. Registrar el traslado ANTES de cerrar sería contarlo dos veces
        —el ingreso ya está en el conteo y el traslado lo sumaría de nuevo al
        esperado del cuadre—, y el sistema con razón pediría justificación. De
        acá en adelante la base se carga COMO TRASLADO y no como ingreso; esta
        función reproduce cómo se venía haciendo.
        """
        sabado = self.dia(-3)
        turno = self.abrir(base_real=0, momento=self.momento(sabado, 8))
        self.vender_efectivo(turno, 293_205)
        self.ingreso(turno, 500_000, self.momento(sabado, 12),
                     concepto="Base de la caja fuerte")
        self.egreso(turno, 95_305, self.momento(sabado, 13))
        self.cerrar(turno, contado=293_205 + 500_000 - 95_305,
                    momento=self.momento(sabado, 21))
        return turno, sabado

    def test_sin_el_traslado_pide_los_697900_de_la_pantalla(self):
        """El estado de HOY, para que se vea que el test mide el caso real."""
        turno, _ = self._sabado_ya_cerrado()
        self.assertEqual(self.consignable(turno), 697_900)

    def test_con_el_traslado_pide_los_197900_que_pidio_el_dueno(self):
        turno, sabado = self._sabado_ya_cerrado()
        self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 12),
                      motivo="Para completar el pago a proveedores")
        self.assertEqual(self.consignable(turno), 197_900)

    def test_el_tope_no_deja_que_se_coma_la_venta(self):
        """Un traslado más grande que lo que no es venta cancela solo eso.

        Sin el tope, un traslado de $900.000 sobre un día con $500.000 que no son
        venta se comería $400.000 de venta real y el sistema pediría consignar de
        menos — el lado tranquilizador, que es el caro.
        """
        turno, sabado = self._sabado_ya_cerrado()
        self.traslado(900_000, sentido="saca", momento=self.momento(sabado, 12))
        # Cancela los $500.000 que no son venta y ni un peso de los $293.205.
        self.assertEqual(self.consignable(turno), 293_205 - 95_305)


class ElFantasmaNoVuelveAlDiaSiguienteTest(CajaFuerteBase):
    """EL BUG QUE HUNDIÓ EL DISEÑO ANTERIOR: el arreglo de un día reaparecía al
    siguiente.

    El domingo la barista abre y cuenta $697.900 en el cajón. Los $500.000
    prestados VIENEN ADENTRO de ese conteo. Si el cuadre del domingo volviera a
    sumar el saldo vigente, inventaría un sobrante de $500.000 — el mismo error
    del sábado, un día después y con el signo dado vuelta.

    Por eso hay DOS lecturas del mismo hecho y no son intercambiables: el CUADRE
    INICIAL suma el saldo vigente (todavía no hay `base_real` que lo contenga), y
    todo cuadre posterior suma solo el DELTA desde que se contó la base.
    """

    def setUp(self):
        super().setUp()
        self.sabado = self.dia(-3)
        self.domingo = self.dia(-2)
        # El sábado de Palmetto, resumido: la base sale y el cierre da exacto.
        sab = self.abrir(base_real=0, momento=self.momento(self.sabado, 8))
        self.vender_efectivo(sab, 697_900)
        self.egreso(sab, 500_000, self.momento(self.sabado, 11))
        self.traslado(500_000, sentido="saca", momento=self.momento(self.sabado, 12))
        self.cerrar(sab, contado=697_900, momento=self.momento(self.sabado, 21))
        self.sab = sab

    def test_el_kiosko_le_pide_a_la_barista_contar_los_697900(self):
        """Lo primero que ve la barista el domingo. `esperado` es lo que se
        cuenta; `base_propia` y `prestado_caja_fuerte` viajan aparte para que la
        pantalla lo pueda explicar en dos renglones en vez de mostrar un total
        inflado que nadie sabe de dónde sale."""
        inicio = self.esperado_a_contar()
        self.assertEqual(inicio["esperado"], 697_900)
        self.assertEqual(inicio["base_propia"], 197_900)
        self.assertEqual(inicio["prestado_caja_fuerte"], 500_000)

    def test_el_cuadre_inicial_del_domingo_no_dispara_diferencia_ni_sobrante(self):
        """El test central del día siguiente, por el flujo REAL: `abrir_caja`
        diferido y después `registrar_cuadre_inicial` con el efectivo contado.

        `sobrante_consignable` es el campo por el que el fantasma entraba al
        consignable, y tiene que quedar en CERO — no en None: el turno pasó por el
        cuadre y la respuesta es «no sobró nada», que es un hecho, no un dato que
        falte."""
        dom = self.abrir_diferido(momento=self.momento(self.domingo, 8))
        self.assertEqual(dom.base_sistema, 197_900)   # plata propia: el consignable de ayer

        self.cuadre_inicial(dom, efectivo_real=697_900,
                            momento=self.momento(self.domingo, 9))

        self.assertEqual(dom.base_real, 697_900)       # lo contado, física intacta
        self.assertEqual(dom.diferencia_apertura, 0)
        self.assertEqual(dom.sobrante_consignable, 0)

    def test_el_cuadre_armado_desde_la_contabilidad_tambien_lleva_el_termino(self):
        """LA OTRA RAMA DEL ESPERADO, que es la más expuesta de las dos.

        Con `saldos_incluidos` la barista marca qué días pendientes por consignar
        están físicamente en la caja, y el esperado se arma desde la CONTABILIDAD
        —la suma de esos saldos— en vez de salir del conteo del cierre anterior.
        Justamente por eso nunca supo de la caja fuerte: la contabilidad conoce
        los $197.900 que hay que bancar y no tiene forma de saber que en el mismo
        cajón hay $500.000 de la sede trabajando.

        Las DOS ramas tienen que sumar el término igual. Si una lo suma y la otra
        no, el sobrante fantasma queda latente esperando a la primera barista que
        use el otro camino — y ese es el bug que nadie va a poder reproducir.
        """
        dom = self.abrir_diferido(momento=self.momento(self.domingo, 8))
        self.cuadre_inicial(dom, efectivo_real=697_900,
                            momento=self.momento(self.domingo, 9),
                            saldos_incluidos=[self.sab.id])

        # La contabilidad dice $197.900; el cajón tiene $697.900; la brecha son
        # exactamente los $500.000 prestados, y el término la cierra.
        self.assertEqual(dom.base_sistema, 197_900)
        self.assertEqual(dom.diferencia_apertura, 0)
        self.assertEqual(dom.sobrante_consignable, 0)

    def test_sin_el_termino_el_domingo_fabrica_el_sobrante_fantasma(self):
        """EL ESPEJO, medido neutralizando el término y nada más.

        No se simula un mundo distinto —la plata, el conteo y los saldos
        pendientes son los mismos que en el test de arriba—: se hace valer cero
        `prestado_caja_fuerte` en el cuadre inicial, que es lo que pasaría si
        alguien sacara la línea. El fantasma vuelve entero y por su camino
        completo: diferencia de $500.000 → `sobrante_consignable` de $500.000 →
        y ese sobrante entra al esperado a consignar del domingo, o sea que el
        sistema termina pidiendo bancar la base de emergencia de la sede.

        HAY DOS REDES Y ESTE TEST LAS SEPARA, que es lo que lo hace útil:

          1. el término en el CUADRE evita que el fantasma se fabrique. Sin él,
             `diferencia_apertura` y `sobrante_consignable` quedan en $500.000 —y
             de paso la barista se come un «Diferencia detectada, se requiere
             justificación» cada mañana, que es fricción real en el local;
          2. `_sobrante_explicado_por_la_base` (services/consignaciones.py) cancela
             ese sobrante congelado si un traslado lo explica. Existe para los
             turnos que ya habían cerrado cuando se registró el traslado, y acá se
             la ve haciendo de segunda red.

        Por eso, con el término neutralizado, las columnas SÍ se ensucian pero la
        plata que se pide bancar sigue bien. Las dos redes están acotadas para no
        restar dos veces: la segunda solo cancela sobrante que EXISTE, así que
        cuando la primera funciona no tiene nada que hacer.
        """
        from unittest.mock import patch

        dom = self.abrir_diferido(momento=self.momento(self.domingo, 8))
        with patch("app.services.caja.prestado_caja_fuerte", return_value=0.0):
            self.cuadre_inicial(dom, efectivo_real=697_900,
                                momento=self.momento(self.domingo, 9),
                                saldos_incluidos=[self.sab.id],
                                justificacion="apareció plata, no sé de dónde")

        # La primera red no estaba: las columnas se ensuciaron.
        self.assertEqual(dom.diferencia_apertura, 500_000)
        self.assertEqual(dom.sobrante_consignable, 500_000)

        # Pero la SEGUNDA sí está, y es la que decide la plata: el domingo cierra
        # sin vender un peso en efectivo y el sistema NO reclama la base al banco.
        self.cerrar(dom, contado=697_900, momento=self.momento(self.domingo, 21))
        self.assertEqual(self.consignable(dom), 0)

    def test_el_cierre_del_domingo_no_vuelve_a_sumar_la_base_prestada(self):
        """La otra mitad de la misma trampa. El domingo NO se movió nada: el
        delta del turno es 0 aunque el saldo vigente siga siendo $500.000. Sumar
        el saldo vigente acá inventaría un faltante de $500.000 al cierre."""
        dom = self.abrir_diferido(momento=self.momento(self.domingo, 8))
        self.cuadre_inicial(dom, efectivo_real=697_900,
                            momento=self.momento(self.domingo, 9))
        self.vender_efectivo(dom, 300_000)
        self.cerrar(dom, contado=997_900, momento=self.momento(self.domingo, 21))

        self.assertEqual(dom.diferencia_cierre, 0)
        # Y el consignable del domingo es la venta del domingo, ni un peso más:
        # la base prestada no es venta y no se banca.
        self.assertEqual(self.consignable(dom), 300_000)

    def test_el_saldo_sigue_prestado_aunque_el_delta_del_turno_sea_cero(self):
        """Las dos lecturas, una al lado de la otra, para que se vea que no son
        la misma. El domingo: saldo vigente $500.000, delta del turno $0."""
        dom = self.abrir_diferido(momento=self.momento(self.domingo, 8))
        self.cuadre_inicial(dom, efectivo_real=697_900,
                            momento=self.momento(self.domingo, 9))
        self.assertEqual(svc.prestado_caja_fuerte(self.db, self.palmetto.id), 500_000)
        self.assertEqual(svc.prestado_del_turno(self.db, dom), 0)

    def test_el_desglose_del_cuadre_puede_explicar_el_numero(self):
        """La pantalla tiene que poder decir «de estos $697.900, $500.000 son la
        base prestada» en vez de rotularlo. Por eso el desglose expone DOS campos:
        el sumando que entró a ESTE cuadre y cuánto de la base seguía afuera de la
        caja fuerte en ese instante."""
        dom = self.abrir_diferido(momento=self.momento(self.domingo, 8))
        self.cuadre_inicial(dom, efectivo_real=697_900,
                            momento=self.momento(self.domingo, 9))
        entrega = (self.db.query(EntregaTurno)
                   .filter(EntregaTurno.turno_id == dom.id).first())

        r = self.client.get(f"/api/v1/caja/entrega/{entrega.id}/desglose")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["base"], 197_900)                     # plata propia
        self.assertEqual(d["prestado_caja_fuerte"], 500_000)     # el sumando de ESTE cuadre
        self.assertEqual(d["prestado_caja_fuerte_vigente"], 500_000)
        self.assertEqual(d["efectivo_esperado"], 697_900)        # y la suma cierra
        self.assertEqual(d["diferencia_efectivo"], 0)


class DevolucionTest(CajaFuerteBase):
    """CUANDO LA BASE VUELVE A LA CAJA FUERTE, el término vuelve a cero y todo
    sigue como antes. Sin esta mitad el arreglo sería una puerta de una sola
    dirección: el esperado quedaría inflado $500.000 para siempre."""

    def setUp(self):
        super().setUp()
        self.dia_saca = self.dia(-4)
        self.dia_vuelve = self.dia(-2)
        self.traslado(500_000, sentido="saca", momento=self.momento(self.dia_saca, 12))

    def test_devolver_todo_deja_el_saldo_en_cero(self):
        self.assertEqual(self.saldo(), 500_000)
        self.traslado(500_000, sentido="devuelve",
                      momento=self.momento(self.dia_vuelve, 15))
        self.assertEqual(self.saldo(), 0)

    def test_devolucion_parcial_deja_lo_que_sigue_afuera(self):
        """Pasa: devuelven lo que pueden y el resto sigue trabajando. El saldo no
        es un interruptor, es un número."""
        self.traslado(300_000, sentido="devuelve",
                      momento=self.momento(self.dia_vuelve, 15))
        self.assertEqual(self.saldo(), 200_000)

    def test_el_cierre_del_dia_de_la_devolucion_espera_MENOS_plata(self):
        """El caso que un `max(0, ...)` o un término solo-positivo rompería: el
        delta del turno es NEGATIVO y el cuadre tiene que esperar menos plata en
        el cajón, no más. Si el término no supiera restar, el cierre de ese día
        acusaría un faltante de $500.000 y mandaría una alerta de descuadre."""
        turno = self.abrir(base_real=500_000, momento=self.momento(self.dia_vuelve, 8))
        self.vender_efectivo(turno, 350_000)
        self.traslado(500_000, sentido="devuelve",
                      momento=self.momento(self.dia_vuelve, 15))

        self.assertEqual(svc.prestado_del_turno(self.db, turno), -500_000)
        # En el cajón quedan 500.000 + 350.000 − 500.000 que se guardaron.
        self.cerrar(turno, contado=350_000, momento=self.momento(self.dia_vuelve, 21))
        self.assertEqual(turno.diferencia_cierre, 0)

    def test_devolver_no_cambia_el_consignable(self):
        """Guardar la base no es venta ni egreso: no hay nada que bancar por eso.
        El consignable del día de la devolución es la venta del día, pelada."""
        turno = self.abrir(base_real=500_000, momento=self.momento(self.dia_vuelve, 8))
        self.vender_efectivo(turno, 350_000)
        self.traslado(500_000, sentido="devuelve",
                      momento=self.momento(self.dia_vuelve, 15))
        self.cerrar(turno, contado=350_000, momento=self.momento(self.dia_vuelve, 21))
        self.assertEqual(self.consignable(turno), 350_000)

    def test_devuelta_la_base_el_dia_siguiente_arranca_limpio(self):
        """El cierre del arco: con el saldo en cero, lo que se cuenta a la mañana
        vuelve a ser plata propia y nada más."""
        turno = self.abrir(base_real=500_000, momento=self.momento(self.dia_vuelve, 8))
        self.vender_efectivo(turno, 350_000)
        self.traslado(500_000, sentido="devuelve",
                      momento=self.momento(self.dia_vuelve, 15))
        self.cerrar(turno, contado=350_000, momento=self.momento(self.dia_vuelve, 21))

        inicio = self.esperado_a_contar()
        self.assertEqual(inicio["prestado_caja_fuerte"], 0)
        self.assertEqual(inicio["esperado"], inicio["base_propia"])


class ElPrestamoCruzaDiasTest(CajaFuerteBase):
    """SALE EL SÁBADO Y VUELVE EL MIÉRCOLES. Cinco cierres seguidos con la base
    afuera y ninguno puede inventar una diferencia.

    Este es el test que mide la propiedad de verdad. Los días del medio son los
    peligrosos: no se movió NADA de la caja fuerte, el saldo vigente sigue siendo
    $500.000, y cualquier confusión entre «saldo» y «delta» los descuadra a todos.

    El cajón se lleva a mano, peso por peso (`cajon`), y contra ese número físico
    se comparan los esperados del sistema. Entre un cierre y la apertura siguiente
    sale del cajón lo que se fue al banco — que es exactamente el consignable del
    turno anterior, la invariante que sostiene toda la fórmula del consignable.

    Las consignaciones no se registran como filas: la rama de DÍA NUEVO del
    cuadre no las lee (arranca del conteo físico del cierre menos la base), así
    que agregarlas sería ruido. Lo que sí se verifica, día por día, es que el
    esperado del sistema coincida con la plata que de verdad quedó en el cajón.
    """

    def test_el_arco_completo_sabado_a_jueves_sin_una_sola_diferencia(self):
        sabado, domingo = self.dia(-6), self.dia(-5)
        lunes, martes = self.dia(-4), self.dia(-3)
        miercoles, jueves = self.dia(-2), self.dia(-1)

        # ── SÁBADO: la base sale a trabajar ──────────────────────────────────
        cajon = 0
        turno = self.abrir(base_real=cajon, momento=self.momento(sabado, 8))
        self.vender_efectivo(turno, 697_900);        cajon += 697_900
        self.egreso(turno, 500_000, self.momento(sabado, 11)); cajon -= 500_000
        self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 12))
        cajon += 500_000
        self.cerrar(turno, contado=cajon, momento=self.momento(sabado, 21))
        self.assertEqual(turno.diferencia_cierre, 0)
        self.assertEqual(self.consignable(turno), 197_900)

        # ── DOMINGO, LUNES, MARTES: la base sigue afuera y nadie la toca ─────
        # Tres días normales. Ventas distintas cada día para que un test que
        # pasara por casualidad con números repetidos no pase acá.
        for dia_, venta, banco in ((domingo, 300_000, 0),
                                   (lunes, 250_000, 197_900),
                                   (martes, 400_000, 300_000)):
            # Al banco se va lo que quedó pendiente del turno anterior.
            cajon -= banco
            inicio = self.esperado_a_contar()
            self.assertEqual(inicio["esperado"], cajon,
                             f"el esperado del {dia_} no coincide con el cajón real")
            # La base prestada sigue declarada aparte todos estos días: es lo que
            # deja explicar por qué el cajón arranca con medio millón de más.
            self.assertEqual(inicio["prestado_caja_fuerte"], 500_000)

            turno = self.abrir_diferido(momento=self.momento(dia_, 8))
            self.cuadre_inicial(turno, efectivo_real=cajon,
                                momento=self.momento(dia_, 9))
            self.assertEqual(turno.diferencia_apertura, 0, f"apertura del {dia_}")
            self.assertEqual(turno.sobrante_consignable, 0, f"sobrante del {dia_}")

            self.vender_efectivo(turno, venta);      cajon += venta
            self.cerrar(turno, contado=cajon, momento=self.momento(dia_, 21))
            self.assertEqual(turno.diferencia_cierre, 0, f"cierre del {dia_}")
            self.assertEqual(self.consignable(turno), venta, f"consignable del {dia_}")

        # ── MIÉRCOLES: la base vuelve a la caja fuerte ───────────────────────
        cajon -= 250_000                       # al banco, lo del lunes
        self.assertEqual(self.esperado_a_contar()["esperado"], cajon)
        turno = self.abrir_diferido(momento=self.momento(miercoles, 8))
        self.cuadre_inicial(turno, efectivo_real=cajon,
                            momento=self.momento(miercoles, 9))
        self.assertEqual(turno.diferencia_apertura, 0)

        self.vender_efectivo(turno, 350_000);    cajon += 350_000
        self.traslado(500_000, sentido="devuelve", momento=self.momento(miercoles, 16))
        cajon -= 500_000
        self.cerrar(turno, contado=cajon, momento=self.momento(miercoles, 21))
        self.assertEqual(turno.diferencia_cierre, 0)
        self.assertEqual(self.consignable(turno), 350_000)
        self.assertEqual(self.saldo(), 0)

        # ── JUEVES: todo volvió a la normalidad ──────────────────────────────
        cajon -= 400_000                       # al banco, lo del martes
        inicio = self.esperado_a_contar()
        self.assertEqual(inicio["prestado_caja_fuerte"], 0)
        self.assertEqual(inicio["esperado"], cajon)
        # Y lo que se cuenta vuelve a ser plata propia y nada más: el término
        # desapareció sin dejar residuo, que es la prueba de que no era un ajuste.
        self.assertEqual(inicio["base_propia"], cajon)

        turno = self.abrir_diferido(momento=self.momento(jueves, 8))
        self.cuadre_inicial(turno, efectivo_real=cajon, momento=self.momento(jueves, 9))
        self.assertEqual(turno.diferencia_apertura, 0)
        self.assertEqual(turno.sobrante_consignable, 0)

    def test_la_base_del_dia_siguiente_es_exactamente_el_consignable_de_hoy(self):
        """La invariante que el diseño anterior rompía y que ésta conserva.

        `base_sistema` vale PLATA PROPIA —lo que hay por consignar— y no el
        efectivo a contar. Es lo que permite que las dos ramas del cuadre inicial
        (la de saldos seleccionados y la legacy) sumen el término igual, en vez de
        tener que tratarlo distinto en cada una — que es exactamente como se
        fabrica el próximo bug."""
        sabado, domingo = self.dia(-3), self.dia(-2)
        turno = self.abrir(base_real=0, momento=self.momento(sabado, 8))
        self.vender_efectivo(turno, 697_900)
        self.egreso(turno, 500_000, self.momento(sabado, 11))
        self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 12))
        self.cerrar(turno, contado=697_900, momento=self.momento(sabado, 21))

        dom = self.abrir_diferido(momento=self.momento(domingo, 8))
        self.assertEqual(dom.base_sistema, self.consignable(turno))
        self.assertEqual(dom.base_sistema, 197_900)


class PorSedeTest(CajaFuerteBase):
    """EL SALDO ES POR SEDE. Palmetto sacó su base; el cajón de Vida no se enteró.

    Mezclarlas dejaría a una sede en rojo y a la otra inflada — y son dos cajones
    físicos, en dos barrios distintos, con dos cajas fuertes distintas."""

    def test_un_prestamo_en_palmetto_no_toca_el_cuadre_de_vida(self):
        dia_ = self.dia(-2)
        pal = self.abrir(base_real=0, tienda=self.palmetto,
                         momento=self.momento(dia_, 8))
        vida = self.abrir(base_real=0, tienda=self.vida,
                          momento=self.momento(dia_, 8))
        self.vender_efectivo(pal, 400_000)
        self.vender_efectivo(vida, 400_000)
        self.traslado(500_000, sentido="saca", tienda=self.palmetto,
                      momento=self.momento(dia_, 12))

        # Palmetto espera la base prestada adentro del cajón; Vida no.
        self.cerrar(pal, contado=900_000, momento=self.momento(dia_, 21))
        self.cerrar(vida, contado=400_000, momento=self.momento(dia_, 21))
        self.assertEqual(pal.diferencia_cierre, 0)
        self.assertEqual(vida.diferencia_cierre, 0)
        # Y el consignable de las dos es su propia venta.
        self.assertEqual(self.consignable(pal), 400_000)
        self.assertEqual(self.consignable(vida), 400_000)

    def test_el_saldo_de_una_sede_no_se_ve_en_la_otra(self):
        self.traslado(500_000, sentido="saca", tienda=self.palmetto,
                      momento=self.momento(self.dia(-1), 12))
        self.assertEqual(self.saldo(self.palmetto), 500_000)
        self.assertEqual(self.saldo(self.vida), 0)

    def test_el_listado_no_mezcla_traslados_de_otra_sede(self):
        self.traslado(500_000, sentido="saca", tienda=self.palmetto,
                      momento=self.momento(self.dia(-1), 12))
        self.traslado(200_000, sentido="saca", tienda=self.vida,
                      momento=self.momento(self.dia(-1), 12))
        r = self.client.get("/api/v1/caja/prestamos-caja-fuerte",
                            params={"tienda_id": self.vida.id})
        items = r.json()["traslados"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["monto"], 200_000)
        self.assertEqual(items[0]["tienda_id"], self.vida.id)


class BordeDeLaFechaTest(CajaFuerteBase):
    """EL CORTE ES EL INSTANTE DEL TRASLADO, NO EL DÍA COLOMBIA.

    La base sale a media mañana y el cuadre de esa misma mañana no la vio. Si el
    término se acotara por día, un traslado de las 22:00 —con la sede ya cerrada—
    se colaría en el turno que cerró a las 20:00 del mismo día calendario, y el
    cuadre de ese turno pasaría a esperar plata que llegó después.

    Y hay una segunda trampa encima: `fecha` guarda instantes UTC y el negocio
    vive en Colombia (UTC−5), así que las 22:00 de un sábado en Cali son las 03:00
    del domingo en la columna. Comparar días sobre el timestamp pelado corre la
    frontera cinco horas.
    """

    def _turno_del(self, d: date, *, base=0):
        return self.abrir(base_real=base, momento=self.momento(d, 8))

    def test_un_traslado_anterior_al_cierre_entra_en_ese_turno(self):
        d = self.dia(-2)
        turno = self._turno_del(d)
        self.vender_efectivo(turno, 300_000)
        self.traslado(500_000, sentido="saca", momento=self.momento(d, 14))
        self.cerrar(turno, contado=800_000, momento=self.momento(d, 20))

        self.assertEqual(turno.diferencia_cierre, 0)
        flujo = svc.get_flujo_turno(self.db, turno.id)
        self.assertEqual(flujo["prestado_caja_fuerte"], 500_000)

    def test_un_traslado_posterior_al_cierre_no_entra_en_ese_turno(self):
        """Sede cerrada, plata quieta, y recién a la noche pasan a sacar la base
        para el día siguiente. Ese traslado es del turno de mañana."""
        d = self.dia(-2)
        turno = self._turno_del(d)
        self.vender_efectivo(turno, 300_000)
        self.cerrar(turno, contado=300_000, momento=self.momento(d, 20))
        self.traslado(500_000, sentido="saca", momento=self.momento(d, 22))

        flujo = svc.get_flujo_turno(self.db, turno.id)
        self.assertEqual(flujo["prestado_caja_fuerte"], 0)
        self.assertEqual(flujo["efectivo_esperado"], 300_000)

    def test_el_mismo_dia_colombia_no_alcanza_solo_cuenta_el_instante(self):
        """Las dos direcciones en un test: dos traslados el MISMO día Colombia,
        uno antes del cierre y otro después. Solo entra el primero. Si el corte
        fuera por día, el flujo del turno diría $700.000 en vez de $500.000."""
        d = self.dia(-2)
        turno = self._turno_del(d)
        self.vender_efectivo(turno, 300_000)
        self.traslado(500_000, sentido="saca", momento=self.momento(d, 14))
        self.cerrar(turno, contado=800_000, momento=self.momento(d, 20))
        self.traslado(200_000, sentido="saca", momento=self.momento(d, 22))

        flujo = svc.get_flujo_turno(self.db, turno.id)
        self.assertEqual(flujo["prestado_caja_fuerte"], 500_000)
        # El saldo de la SEDE sí subió: la plata está afuera de la caja fuerte,
        # aunque no pertenezca al turno que ya cerró.
        self.assertEqual(self.saldo(), 700_000)

    def test_un_traslado_de_las_23_pertenece_al_dia_colombia_no_al_utc(self):
        """Las 23:00 de un sábado en Cali son las 04:00 del domingo en la columna
        `fecha`. El listado tiene que ubicarlo el SÁBADO, que es el día en que el
        dueño lo va a buscar; si no, el traslado que explica el cuadre del sábado
        aparece un día corrido y nadie lo encuentra."""
        sabado = self.dia(-2)
        self.traslado(500_000, sentido="saca", momento=self.momento(sabado, 23))

        del_sabado = self.client.get("/api/v1/caja/prestamos-caja-fuerte", params={
            "tienda_id": self.palmetto.id, "desde": str(sabado), "hasta": str(sabado)})
        self.assertEqual(len(del_sabado.json()["traslados"]), 1)

        del_domingo = self.client.get("/api/v1/caja/prestamos-caja-fuerte", params={
            "tienda_id": self.palmetto.id,
            "desde": str(sabado + timedelta(days=1)),
            "hasta": str(sabado + timedelta(days=1))})
        self.assertEqual(del_domingo.json()["traslados"], [])

    def test_el_ancla_del_delta_es_el_CONTEO_y_no_la_apertura_del_turno(self):
        """LA VENTANA DEL CONTEO DE INVENTARIO, que dura horas y no es un detalle.

        El turno abre a las 07:00 con las baristas, y el efectivo recién se cuenta
        a las 09:00, después del conteo de inventario. Si la base sale de la caja
        fuerte a las 08:00 —en el medio— esos $500.000 YA ESTÁN sobre la mesa
        cuando ella cuenta: viajan adentro de `base_real`.

        Por eso el delta se ancla en el CUADRE y no en `fecha_apertura`. Anclarlo
        en la apertura contaría el mismo traslado dos veces —una adentro del
        conteo y otra como término— y el cierre de ese día reclamaría un faltante
        de medio millón que nadie se llevó.

        Este test existe porque la regla sobrevivió a una mutación: el ancla se
        podía mover a `fecha_apertura` y toda la suite seguía en verde.
        """
        d = self.dia(-1)
        turno = self.abrir_diferido(momento=self.momento(d, 7))
        self.traslado(500_000, sentido="saca", momento=self.momento(d, 8))
        self.cuadre_inicial(turno, efectivo_real=500_000, momento=self.momento(d, 9))
        self.assertEqual(turno.diferencia_apertura, 0)   # contó la base prestada

        # Ya está adentro de `base_real`: el delta del turno es CERO, no $500.000.
        self.assertEqual(svc.prestado_del_turno(self.db, turno), 0)

        self.vender_efectivo(turno, 300_000)
        self.cerrar(turno, contado=800_000, momento=self.momento(d, 21))
        self.assertEqual(turno.diferencia_cierre, 0)

    def test_un_traslado_despues_del_conteo_si_es_delta_del_turno(self):
        """El espejo de la ventana: mismo turno, misma base, pero el traslado pasa
        DESPUÉS de que ella contó. Ahí sí es un sumando — el cajón tiene medio
        millón más de lo que decía el conteo."""
        d = self.dia(-1)
        turno = self.abrir_diferido(momento=self.momento(d, 7))
        self.cuadre_inicial(turno, efectivo_real=0, momento=self.momento(d, 9))
        self.traslado(500_000, sentido="saca", momento=self.momento(d, 10))

        self.assertEqual(svc.prestado_del_turno(self.db, turno), 500_000)
        self.vender_efectivo(turno, 300_000)
        self.cerrar(turno, contado=800_000, momento=self.momento(d, 21))
        self.assertEqual(turno.diferencia_cierre, 0)

    def test_el_saldo_del_listado_es_el_vigente_y_no_la_suma_del_rango(self):
        """Un rango que arranque después del día en que la base salió listaría
        cero traslados. Si el saldo saliera de esas filas, diría que no hay nada
        prestado justo cuando sí lo hay — y ese es el número por el que se entra a
        esta pantalla."""
        self.traslado(500_000, sentido="saca", momento=self.momento(self.dia(-10), 12))
        r = self.client.get("/api/v1/caja/prestamos-caja-fuerte", params={
            "tienda_id": self.palmetto.id, "desde": str(self.dia(-2))})
        self.assertEqual(r.json()["traslados"], [])
        self.assertEqual(r.json()["prestado_caja_fuerte"], 500_000)


class SaldoNegativoTest(CajaFuerteBase):
    """DEVOLVER MÁS DE LO QUE SALIÓ DA NEGATIVO, Y SE MUESTRA TAL CUAL.

    No es un estado posible del mundo físico: significa que alguien cargó un
    traslado mal. Taparlo con un `max(0, ...)` convertiría un dato mal cargado en
    un cero tranquilizador y el error viviría para siempre adentro del esperado.
    El número absurdo en pantalla es lo que hace que alguien pregunte.
    """

    def test_devolver_mas_de_lo_que_salio_da_saldo_negativo(self):
        self.traslado(200_000, sentido="saca", momento=self.momento(self.dia(-2), 12))
        self.traslado(500_000, sentido="devuelve", momento=self.momento(self.dia(-1), 12))
        self.assertEqual(self.saldo(), -300_000)

    def test_el_negativo_no_se_pisa_a_cero_en_el_servicio(self):
        """Por HTTP y por el servicio: el clamp puede aparecer en cualquiera de
        las dos capas y el efecto es el mismo."""
        self.traslado(500_000, sentido="devuelve", momento=self.momento(self.dia(-1), 12))
        self.assertEqual(svc.prestado_caja_fuerte(self.db, self.palmetto.id), -500_000)
        self.assertLess(self.saldo(), 0)

    def test_el_negativo_llega_hasta_el_esperado_del_cuadre(self):
        """La consecuencia visible, que es la que sirve: con un traslado mal
        cargado el kiosko le pide a la barista contar menos plata de la que hay, y
        el descuadre aparece el mismo día. Con el clamp aparecería... nunca."""
        self.traslado(500_000, sentido="devuelve", momento=self.momento(self.dia(-1), 12))
        self.assertEqual(self.esperado_a_contar()["prestado_caja_fuerte"], -500_000)


class BorrarTrasladoTest(CajaFuerteBase):
    """BORRAR DEVUELVE TODO A SU VALOR ANTERIOR, EXACTO.

    El saldo se DERIVA de las filas vivas, así que sacar la fila arregla todo
    aguas abajo solo. Es también la única puerta para corregir un traslado: no hay
    edición, se borra y se vuelve a cargar."""

    def test_borrar_devuelve_el_saldo_al_valor_anterior(self):
        self.traslado(500_000, sentido="saca", momento=self.momento(self.dia(-3), 12))
        antes = self.saldo()
        r = self.traslado(200_000, sentido="saca", momento=self.momento(self.dia(-2), 12))
        pid = r.json()["prestamo"]["id"]
        self.assertEqual(self.saldo(), 700_000)

        borrado = self.client.delete(f"/api/v1/caja/prestamos-caja-fuerte/{pid}")
        self.assertEqual(borrado.status_code, 200, borrado.text)
        self.assertEqual(borrado.json()["ok"], True)
        self.assertEqual(borrado.json()["id"], pid)
        # La respuesta trae el saldo ya recalculado: la pantalla no tiene que
        # adivinarlo restando del lado del cliente.
        self.assertEqual(borrado.json()["prestado_caja_fuerte"], antes)
        self.assertEqual(self.saldo(), antes)

    def test_borrar_el_unico_traslado_devuelve_el_esperado_a_lo_de_siempre(self):
        """Un cero de más tecleado deja el esperado inflado. Borrar tiene que
        deshacerlo del todo, sin dejar rastro en el número que se cuenta."""
        dia_ = self.dia(-2)
        turno = self.abrir(base_real=0, momento=self.momento(dia_, 8))
        self.vender_efectivo(turno, 300_000)
        r = self.traslado(5_000_000, sentido="saca", momento=self.momento(dia_, 12))
        self.assertEqual(svc.get_flujo_turno(self.db, turno.id)["efectivo_esperado"],
                         5_300_000)

        self.client.delete(f"/api/v1/caja/prestamos-caja-fuerte/{r.json()['prestamo']['id']}")
        self.assertEqual(svc.get_flujo_turno(self.db, turno.id)["efectivo_esperado"],
                         300_000)
        self.assertEqual(self.saldo(), 0)

    def test_borrar_algo_que_no_existe_es_404_legible(self):
        r = self.client.delete("/api/v1/caja/prestamos-caja-fuerte/99999")
        self.assertEqual(r.status_code, 404)
        self.assertIsInstance(r.json()["detail"], str)


class TrasladosApiTest(CajaFuerteBase):
    """El contrato HTTP del alta. Lo que más importa acá son los 400: cada regla
    violada tiene que llegar a la pantalla como un texto que el dueño pueda leer y
    corregir."""

    def crear(self, **campos):
        body = {"tienda_id": self.palmetto.id, "sentido": "saca", "monto": 500_000}
        body.update(campos)
        return self.client.post("/api/v1/caja/prestamos-caja-fuerte", json=body)

    def crudo(self, body: dict):
        """`json.dumps` a mano (allow_nan por defecto) porque httpx se niega a
        mandar inf/NaN. Sin esto el caso más peligroso —el valor que revienta al
        serializar— nunca llegaría al servidor. El `json.loads` de Starlette sí
        acepta los literales, igual que un cliente real que los mande."""
        return self.client.post("/api/v1/caja/prestamos-caja-fuerte",
                                content=json.dumps(body),
                                headers={"content-type": "application/json"})

    # ── Alta ─────────────────────────────────────────────────────────────────

    def test_alta_devuelve_201_con_el_traslado_y_el_saldo(self):
        r = self.crear(motivo="  para pagar al proveedor  ")
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["prestamo"]["tienda_id"], self.palmetto.id)
        self.assertEqual(body["prestamo"]["sentido"], "saca")
        self.assertEqual(body["prestamo"]["monto"], 500_000)
        self.assertEqual(body["prestamo"]["motivo"], "para pagar al proveedor")  # strip()eado
        self.assertEqual(body["prestamo"]["usuario_nombre"], "Bryan")
        # El saldo vuelve en la misma respuesta: es lo que la pantalla muestra.
        self.assertEqual(body["prestado_caja_fuerte"], 500_000)

    def test_el_motivo_vacio_se_guarda_como_null_no_como_string_vacio(self):
        """Así el frontend puede preguntar `motivo ? ... : ...` sin casos
        especiales: un motivo de espacios no es un motivo."""
        r = self.crear(motivo="   ")
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIsNone(r.json()["prestamo"]["motivo"])

    def test_el_monto_va_positivo_y_el_sentido_pone_el_signo(self):
        """La convención de `MovimientoBanco`, por el mismo motivo: un monto
        negativo en una columna que ya se resta se resta dos veces y nadie lo ve
        hasta que el saldo no cuadra."""
        self.crear(sentido="saca", monto=500_000)
        self.crear(sentido="devuelve", monto=200_000)
        montos = [p.monto for p in self.db.query(PrestamoCajaFuerte).all()]
        self.assertTrue(all(m > 0 for m in montos), montos)
        self.assertEqual(self.saldo(), 300_000)

    def test_el_traslado_queda_colgado_del_turno_en_que_paso(self):
        """`caja_turno_id` es trazabilidad —la aritmética siempre sale de
        `fecha`— pero se resuelve por el MOMENTO del traslado y no por «el turno
        abierto ahora»: el dueño carga la salida de ayer con la sede cerrada, y
        colgarla del turno de hoy diría que la base salió de un cajón que en ese
        momento no existía."""
        ayer = self.dia(-1)
        turno = self.abrir(base_real=0, momento=self.momento(ayer, 8))
        self.cerrar(turno, contado=0, momento=self.momento(ayer, 21))

        dentro = self.crear(fecha=self.momento(ayer, 12).isoformat())
        self.assertEqual(dentro.json()["prestamo"]["caja_turno_id"], turno.id)

        fuera = self.crear(fecha=self.momento(ayer, 23).isoformat())
        self.assertIsNone(fuera.json()["prestamo"]["caja_turno_id"])

    def test_la_fecha_con_zona_horaria_se_guarda_en_la_convencion_del_repo(self):
        """Pydantic parsea "…-05:00" como datetime CON zona, y guardarlo así
        rompe toda comparación posterior contra columnas naive (TypeError entre
        aware y naive, justo adentro del cálculo del saldo). El handler lo
        normaliza a UTC-naive; el saldo tiene que poder calcularse igual."""
        d = self.dia(-1)
        r = self.crear(fecha=f"{d.isoformat()}T14:30:00-05:00")
        self.assertEqual(r.status_code, 201, r.text)
        guardado = self.db.query(PrestamoCajaFuerte).first()
        self.assertIsNone(guardado.fecha.tzinfo)
        self.assertEqual(guardado.fecha, datetime.combine(d, datetime.min.time())
                         + timedelta(hours=19, minutes=30))   # 14:30 COL = 19:30 UTC
        self.assertEqual(self.saldo(), 500_000)

    # ── Validaciones (todas en el handler, todas 400 con string) ─────────────

    def test_monto_en_cero_es_400(self):
        self.assert_400_legible(
            self.crear(monto=0),
            "El monto del traslado va en positivo: el sentido dice si sale o vuelve.")

    def test_monto_negativo_es_400(self):
        """Un traslado negativo sería «saqué menos que nada», que no es esta
        operación. Sin la guarda, un 'saca' de −500.000 BAJA el esperado en vez de
        subirlo y el descuadre aparece del otro lado."""
        self.assert_400_legible(
            self.crear(monto=-500_000),
            "El monto del traslado va en positivo: el sentido dice si sale o vuelve.")

    def test_monto_infinito_es_400_y_la_respuesta_se_serializa(self):
        r = self.crudo({"tienda_id": self.palmetto.id, "sentido": "saca",
                        "monto": float("inf")})
        self.assert_400_legible(r, "El monto del traslado debe ser un número válido.")

    def test_monto_absurdo_es_400(self):
        """No es una regla inventada: la columna es Numeric(12,2) y un monto más
        grande revienta el INSERT en Postgres con un error que no dice nada. El
        techo son $100.000.000 — la base de una sede es de $500.000, así que deja
        tres ceros de margen."""
        self.assert_400_legible(self.crear(monto=1e8 + 1),
                                "El monto del traslado es demasiado grande.")
        self.assertEqual(self.crear(monto=1e8).status_code, 201)

    def test_sentido_invalido_es_400(self):
        """`sentido` es un String(10) libre a nivel DB (mismo patrón que
        `MovimientoBanco.tipo`), así que el handler es LA guarda: un sentido que
        no sea 'saca' ni 'devuelve' lo ignoraría el cálculo del saldo en silencio,
        y eso es plata desaparecida sin ruido."""
        self.assert_400_legible(
            self.crear(sentido="presta"),
            "El traslado tiene que decir si la base 'saca' de la caja fuerte o "
            "si se 'devuelve' a ella.")

    def test_el_sentido_se_acepta_con_mayusculas_y_espacios(self):
        """Tolerancia de tipeo en la entrada, dato canónico adentro: lo que se
        guarda tiene que ser exactamente lo que el cálculo del saldo agrupa."""
        r = self.crear(sentido="  SACA ")
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["prestamo"]["sentido"], "saca")
        self.assertEqual(self.saldo(), 500_000)

    def test_fecha_futura_es_400(self):
        self.assert_400_legible(
            self.crear(fecha=self.momento(self.dia(1), 12).isoformat()),
            "No podés registrar un traslado de un día que todavía no llegó.")

    def test_el_traslado_de_hoy_se_acepta_aunque_el_server_corra_en_utc(self):
        """La frontera se mide con `hoy_col()` y no con `date.today()`: entre las
        19:00 y la medianoche de Colombia el servidor UTC ya pasó de día y
        rechazaría el traslado de ESTA tarde."""
        self.assertEqual(self.crear(fecha=self.momento(hoy_col(), 10).isoformat())
                         .status_code, 201)

    def test_el_traslado_de_ayer_se_acepta(self):
        """El dueño registra tarde: el de ayer, el de anteayer. Nada lo impide —
        y el saldo se recalcula solo, que es para lo que se deriva."""
        self.assertEqual(self.crear(fecha=self.momento(self.dia(-5), 12).isoformat())
                         .status_code, 201)

    def test_motivo_de_mas_de_200_es_400(self):
        """Sin el tope el INSERT explota en Postgres — ya pasó en este repo con
        otras columnas de texto libre."""
        self.assert_400_legible(self.crear(motivo="x" * 201),
                                "El motivo del traslado no puede pasar de 200 caracteres.")
        self.assertEqual(self.crear(motivo="x" * 200).status_code, 201)

    def test_sede_inexistente_es_400(self):
        self.assert_400_legible(self.crear(tienda_id=99999), "Esa sede no existe.")

    def test_sede_inactiva_es_400(self):
        """El select del formulario se llena con el catálogo de sedes activas: las
        dos puntas tienen que coincidir o la pantalla ofrece una sede que el POST
        rechaza."""
        cerrada = Tienda(nombre="Sede cerrada", direccion="x", activa=False)
        self.db.add(cerrada)
        self.db.commit()
        self.assert_400_legible(self.crear(tienda_id=cerrada.id), "Esa sede está inactiva.")

    def test_la_forma_mal_tipada_si_es_422_de_pydantic(self):
        """El único caso en que `detail` es una lista: el schema se ocupa de la
        FORMA (qué campos llegan y de qué tipo) y ninguna regla de NEGOCIO cae
        ahí. Este test fija esa frontera, que es la que hay que respetar cuando
        alguien quiera agregar un `Field(gt=0)` «para limpiar el handler»."""
        r = self.crear(monto="quinientos mil")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIsInstance(r.json()["detail"], list)

    def test_ninguna_validacion_rechazada_deja_fila_en_la_tabla(self):
        """El 400 tiene que ser total: media validación que igual escribe mueve el
        saldo con un dato que la pantalla nunca mostró."""
        for kwargs in ({"monto": 0}, {"monto": -1}, {"sentido": "presta"},
                       {"motivo": "x" * 201}, {"tienda_id": 99999},
                       {"fecha": self.momento(self.dia(1), 12).isoformat()}):
            self.crear(**kwargs)
        self.assertEqual(self.db.query(PrestamoCajaFuerte).count(), 0)
        self.assertEqual(self.saldo(), 0)

    # ── Listado ──────────────────────────────────────────────────────────────

    def test_listado_devuelve_items_del_mas_nuevo_al_mas_viejo(self):
        self.crear(monto=500_000, fecha=self.momento(self.dia(-5), 12).isoformat())
        self.crear(monto=200_000, sentido="devuelve",
                   fecha=self.momento(self.dia(-1), 12).isoformat())

        body = self.client.get("/api/v1/caja/prestamos-caja-fuerte",
                               params={"tienda_id": self.palmetto.id}).json()
        self.assertEqual(len(body["traslados"]), 2)
        self.assertEqual(body["traslados"][0]["monto"], 200_000)   # el más reciente primero
        self.assertEqual(body["prestado_caja_fuerte"], 300_000)

    def test_listado_vacio_devuelve_cero_y_no_null(self):
        """Acá el cero SÍ es cero: «esta sede no tiene nada prestado» es un hecho,
        no un dato ausente."""
        body = self.client.get("/api/v1/caja/prestamos-caja-fuerte",
                               params={"tienda_id": self.palmetto.id}).json()
        self.assertEqual(body["traslados"], [])
        self.assertEqual(body["prestado_caja_fuerte"], 0)
        self.assertIsNotNone(body["prestado_caja_fuerte"])

    def test_rango_al_reves_es_400_legible(self):
        r = self.client.get("/api/v1/caja/prestamos-caja-fuerte", params={
            "tienda_id": self.palmetto.id, "desde": str(self.hoy),
            "hasta": str(self.dia(-5))})
        self.assert_400_legible(
            r, "El rango de fechas está al revés: 'desde' es posterior a 'hasta'.")

    def test_el_listado_exige_sede(self):
        """Sin `tienda_id` la respuesta sería una mezcla de dos cajones y un saldo
        que no es de nadie. Es la única validación que sí vive en el Query, porque
        es de FORMA: falta un parámetro obligatorio."""
        r = self.client.get("/api/v1/caja/prestamos-caja-fuerte")
        self.assertEqual(r.status_code, 422)


class PermisosTest(CajaFuerteBase):
    """MOVER LA BASE ES DECISIÓN DEL DUEÑO.

    Si la barista pudiera cargar un traslado, el esperado de su propio cuadre se
    movería con lo que ella misma escribe: cualquier faltante se tapa tecleando un
    'saca'. Los tres endpoints son `require_admin` por eso."""

    def test_la_barista_no_puede_registrar_un_traslado(self):
        self.set_current_user(self.barista)
        r = self.client.post("/api/v1/caja/prestamos-caja-fuerte", json={
            "tienda_id": self.palmetto.id, "sentido": "saca", "monto": 500_000})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.db.query(PrestamoCajaFuerte).count(), 0)

    def test_la_barista_no_puede_borrar_un_traslado(self):
        r = self.traslado(500_000, momento=self.momento(self.dia(-1), 12))
        pid = r.json()["prestamo"]["id"]
        self.set_current_user(self.barista)
        self.assertEqual(
            self.client.delete(f"/api/v1/caja/prestamos-caja-fuerte/{pid}").status_code,
            403)
        self.assertEqual(self.db.query(PrestamoCajaFuerte).count(), 1)

    def test_la_barista_no_puede_listar_los_traslados(self):
        self.set_current_user(self.barista)
        r = self.client.get("/api/v1/caja/prestamos-caja-fuerte",
                            params={"tienda_id": self.palmetto.id})
        self.assertEqual(r.status_code, 403)

    def test_el_cuadre_de_la_barista_igual_espera_la_plata_prestada(self):
        """El otro lado de la misma moneda, y es lo que hace que el permiso no la
        perjudique: ella no puede CARGAR el traslado, pero el esperado que le toca
        contar ya lo incluye. Cuenta lo que hay en el cajón y le cuadra."""
        dia_ = self.dia(-1)
        turno = self.abrir(base_real=0, momento=self.momento(dia_, 8))
        self.vender_efectivo(turno, 300_000)
        self.traslado(500_000, sentido="saca", momento=self.momento(dia_, 12))

        self.set_current_user(self.barista)
        activo = self.client.get(f"/api/v1/caja/activo-pub/{self.palmetto.id}").json()
        self.assertEqual(activo["efectivo_esperado_actual"], 800_000)
        self.assertEqual(activo["prestado_caja_fuerte"], 500_000)


class TodosLosEsperadosTest(CajaFuerteBase):
    """LOS OTROS LUGARES DONDE SE ARMA EL ESPERADO DE LA REGISTRADORA.

    El término no vive en una función: vive en cada fórmula que dice «en el cajón
    tiene que haber ESTO», y en este módulo hay varias. Si queda una afuera, la
    diferencia fantasma no desaparece — se muda al camino que nadie probó, y
    aparece el día que la barista usa el otro botón.

    Esta clase recorre los que le tocan a la barista (cuadre de llegada, entrega
    de turno) y el que mira el dueño (el cajón del cockpit). El del cierre, el del
    cuadre inicial y el de la apertura ya están cubiertos arriba.
    """

    def setUp(self):
        super().setUp()
        self.d = self.dia(-1)
        # Turno con la base de la caja fuerte ya adentro del cajón: abre con 0,
        # vende $300.000 y a media mañana saca los $500.000.
        self.turno = self.abrir(base_real=0, momento=self.momento(self.d, 8))
        self.vender_efectivo(self.turno, 300_000)
        self.traslado(500_000, sentido="saca", momento=self.momento(self.d, 12))

    def test_el_cuadre_de_llegada_de_la_barista_entrante_espera_la_plata_prestada(self):
        """Entra la barista del segundo turno y cuenta el cajón sin cerrar nada.
        Cuenta $800.000 porque eso es lo que hay. Sin el término le marcaría un
        sobrante de medio millón en su primer minuto de turno."""
        entrega = svc.registrar_cuadre_llegada(self.db, self.turno.id, self.admin.id,
                                               efectivo_real=800_000,
                                               tipo_turno="intermedio")
        self.assertEqual(float(entrega.efectivo_esperado), 800_000)
        self.assertEqual(float(entrega.diferencia_efectivo), 0)

    def test_la_entrega_de_turno_espera_la_plata_prestada(self):
        """El cuadre de entrega, el que la barista saliente firma con foto. Mismo
        cajón, mismo número: $800.000 y diferencia cero."""
        self.turno.tiene_conteo_apertura = True
        self.db.commit()
        entrega = svc.registrar_entrega(self.db, self.turno.id, self.admin.id,
                                        efectivo_real=800_000,
                                        ventas_tarjeta_bold=0.0, imagen_url=None)
        self.assertEqual(float(entrega.efectivo_esperado), 800_000)
        self.assertEqual(float(entrega.diferencia_efectivo), 0)

    def test_el_cockpit_del_dueno_ve_la_plata_que_de_verdad_hay_en_el_cajon(self):
        """`_efectivo_en_registradora` (services/costos.py) replica la fórmula del
        cuadre a mano, y su propio docstring pide que las dos cambien en el mismo
        commit. Sin el término el cockpit mostraba medio millón DE MENOS en el
        cajón — justo en las semanas en que la sede tuvo que sacar la base, o sea
        justo cuando el dueño entra a mirar."""
        from app.services import costos as costos_svc
        efectivo, origen = costos_svc._efectivo_en_registradora(self.db, self.palmetto.id)
        self.assertEqual(origen, "turno_abierto")
        self.assertEqual(efectivo, 800_000)

    def test_el_numero_en_vivo_del_kiosko_incluye_lo_prestado(self):
        """Lo que la barista ve en la pantalla del POS mientras trabaja. Va con
        el saldo vigente al lado para que pueda leer «de estos $800.000, medio
        millón es la base», en vez de un total inflado sin explicación."""
        activo = svc.get_turno_activo(self.db, self.palmetto.id)
        self.assertEqual(activo.efectivo_esperado_actual, 800_000)
        self.assertEqual(activo.prestado_caja_fuerte, 500_000)


class RelevoDelMismoDiaTest(CajaFuerteBase):
    """LA OTRA RAMA DE `_base_desde_ultimo_cierre`: dos turnos el mismo día.

    Entre relevos la caja NO se vacía: el turno de la tarde arranca con todo el
    efectivo que dejó el de la mañana. Es una rama distinta y resta una cantidad
    distinta —el saldo vigente al cierre, no lo movido en el turno— porque cada
    figura contiene una cosa distinta: el relevo parte del cajón ENTERO, con todo
    lo prestado adentro.

    Tener dos ramas del mismo esperado con tratamiento distinto es exactamente
    como se fabrica el próximo bug, así que las dos se prueban.
    """

    def test_el_turno_de_la_tarde_hereda_el_cajon_con_la_base_prestada_adentro(self):
        # Mañana: abre en cero, vende $300.000 y saca la base para pagar.
        manana = self.abrir(base_real=0, momento=self.momento(self.hoy, 6))
        self.vender_efectivo(manana, 300_000)
        self.traslado(500_000, sentido="saca", momento=self.momento(self.hoy, 9))
        self.cerrar(manana, contado=800_000, momento=self.momento(self.hoy, 14))
        self.assertEqual(manana.diferencia_cierre, 0)

        # Tarde: el relevo no vacía la caja, así que espera los $800.000 enteros.
        inicio = self.esperado_a_contar()
        self.assertTrue(inicio["mismo_dia"])
        self.assertEqual(inicio["esperado"], 800_000)
        # Y los declara partidos: $300.000 propios (lo que hay por consignar) y
        # $500.000 de la caja fuerte. `base_propia` es el número que NO hay que
        # mostrarle a la barista como "contá esto".
        self.assertEqual(inicio["base_propia"], 300_000)
        self.assertEqual(inicio["prestado_caja_fuerte"], 500_000)

        tarde = self.abrir(base_real=800_000, momento=self.momento(self.hoy, 14))
        self.assertEqual(tarde.base_sistema, 300_000)
        self.assertEqual(tarde.diferencia_apertura, 0)

    def test_un_traslado_entre_los_dos_turnos_cae_del_lado_del_turno_nuevo(self):
        """La base sale con la sede abierta pero entre el cierre de la mañana y el
        conteo de la tarde. No es del turno que ya cerró —su cuadre está firmado—
        pero sí está en el cajón cuando la de la tarde cuenta."""
        manana = self.abrir(base_real=0, momento=self.momento(self.hoy, 6))
        self.vender_efectivo(manana, 300_000)
        self.cerrar(manana, contado=300_000, momento=self.momento(self.hoy, 14))
        self.assertEqual(manana.diferencia_cierre, 0)

        self.traslado(500_000, sentido="saca", momento=self.momento(self.hoy, 15))
        self.assertEqual(self.esperado_a_contar()["esperado"], 800_000)

        tarde = self.abrir(base_real=800_000, momento=self.momento(self.hoy, 16))
        self.assertEqual(tarde.diferencia_apertura, 0)
        self.assertEqual(tarde.base_sistema, 300_000)   # lo propio no se movió


class TablaNuevaTest(CajaFuerteBase):
    """La tabla la crea `Base.metadata.create_all` y no lleva ALTER en main.py.

    El loop de ALTERs corre ANTES de `create_all`, así que una tabla NUEVA no
    tiene entrada allí — solo las columnas nuevas de tablas que ya existen. Este
    test lo fija contra el metadata real para que nadie agregue un ALTER de más
    (que en Postgres falla) ni lo saque de los modelos."""

    def test_la_tabla_existe_con_sus_columnas(self):
        cols = {c.name for c in PrestamoCajaFuerte.__table__.columns}
        self.assertEqual(cols, {"id", "tienda_id", "caja_turno_id", "fecha",
                                "sentido", "monto", "motivo", "usuario_id",
                                "creado_en"})
        self.assertEqual(PrestamoCajaFuerte.__tablename__, "prestamos_caja_fuerte")

    def test_el_turno_es_opcional_y_la_sede_no(self):
        """El traslado es cierto aunque la sede esté cerrada: `caja_turno_id`
        nullable. La sede, en cambio, es de qué cajón salió la plata — sin eso el
        saldo no se puede calcular."""
        t = PrestamoCajaFuerte.__table__
        self.assertTrue(t.c.caja_turno_id.nullable)
        self.assertFalse(t.c.tienda_id.nullable)
        self.assertFalse(t.c.fecha.nullable)
        self.assertFalse(t.c.sentido.nullable)
        self.assertFalse(t.c.monto.nullable)


if __name__ == "__main__":
    unittest.main()
