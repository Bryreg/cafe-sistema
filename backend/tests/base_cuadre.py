"""Base común de los tests que arman turnos REALES para medir el cuadre.

No es un archivo de tests: es el andamio que comparten los que miden el cuadre
de la caja y el consignable que sale de él. Vive fuera de `test_*.py` a propósito
—`unittest discover` no lo levanta— y nació adentro de un test que después se
borró, lo cual dejaba a media suite importando de un archivo que hablaba de otra
cosa.

LA IDEA: los turnos se abren y se cierran con `abrir_caja` /
`registrar_cuadre_inicial` / `cerrar_caja` DE VERDAD, no con fixtures que
escriben `diferencia_cierre` a mano. Lo que se mide vive adentro de esas
fórmulas, y una fixture que las saltea mide el andamio en vez del sistema.
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
from app.models.models import (EntregaTurno, MovimientoCaja, RolEnum, Tienda,
                               Usuario)
from app.routers import caja as caja_router
from app.routers import consignaciones as consignaciones_router
from app.services import caja as svc
from app.services import consignaciones as consig_svc


class CuadreCajaBase(unittest.TestCase):
    """sqlite temporal + los servicios y routers REALES (patrón de la suite).

    Se montan los dos routers en la misma app porque el cuadre y el consignable
    son una sola cuenta partida en dos módulos: el efectivo se teclea en `/caja`
    y el número que el dueño lee sale de `/consignaciones/resumen-admin`. Probar
    cada mitad contra un mock de la otra dejaría pasar justamente el desacuerdo
    entre las dos, que es donde vivieron los bugs caros.
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

        app = FastAPI(title="Test cuadre de caja")
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

        Los turnos se anclan con esto y no con `utcnow()` porque hay cuentas que
        comparan INSTANTES: dos hechos que caen en el mismo microsegundo se van
        cada uno para un lado del borde y el test se vuelve una moneda al aire.

        Ojo con el doble sistema: `momento(d, 23)` cae a las 04:00 UTC del día
        calendario SIGUIENTE. Es a propósito — es el caso que separa "instante"
        de "día Colombia", y hay tests que lo usan justamente para eso.
        """
        return inicio_dia_col_utc(d) + timedelta(hours=hora)

    # ── Helpers de turno (servicios reales, apertura y cierre anclados) ──────

    def _anclar_cuadre(self, turno, momento: datetime):
        """Backdatea el CUADRE de apertura, que es cosa distinta de la apertura.

        Entre que el turno abre y la barista cuenta el efectivo pasa el conteo de
        inventario, que son horas. Los helpers mueven los dos instantes por
        separado justamente para que esa ventana exista en los tests: si se
        movieran juntos, cualquier regla que dependa de ella quedaría sin medir.
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
        se arma desde la CONTABILIDAD, no desde el conteo del cierre anterior.
        Son dos caminos distintos hasta el mismo número, así que lo que se afirme
        de uno hay que medirlo también en el otro.
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
        """El pago al proveedor EN EFECTIVO: la salida que se come la venta en
        efectivo del día."""
        self.db.add(MovimientoCaja(caja_turno_id=turno.id, tipo="egreso",
                                   concepto=concepto, valor=monto,
                                   usuario_id=self.admin.id, fecha=momento))
        self.db.commit()

    def ingreso(self, turno, monto, momento, concepto="Ingreso de caja"):
        """Plata que ENTRA a la registradora sin ser venta.

        Suma al esperado del cuadre igual que una venta, y es el camino por el
        que la plata que no es del día se cuela al consignable si se carga acá
        algo que en realidad no era un ingreso.
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

    # ── Lecturas ─────────────────────────────────────────────────────────────

    def consignable(self, turno) -> float:
        """El esperado a consignar de un turno, tal como lo ve el dueño en
        Consignaciones."""
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
