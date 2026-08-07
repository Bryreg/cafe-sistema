"""Turnos ZOMBIE: un turno que queda abierto de un día anterior sigue recibiendo
ventas (el índice uq_one_turno_abierto impide abrir otro mientras tanto), y esas
ventas quedaban atribuidas al día operativo del turno viejo — el Informe Contador
las mostraba días antes de haberse cobrado.

El día del negocio se SELLA en el ticket al cobrar (Ticket.dia_operativo_id), y
el informe prefiere ese sello sobre el día del turno. Vender nunca se bloquea por
esto: la atribución es contabilidad, no un permiso.

Además: el admin tiene que poder rescatar un turno zombie sin conteo de cierre
(antes era un callejón sin salida) y el kiosko tiene que VER que el turno es de
otro día (aviso, nunca bloqueo).
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base, get_db
from app.services.caja import es_venta_de_turno_zombie
from app.models.models import (
    CajaTurno,
    CategoriaProductoEnum,
    DiaOperativo,
    EstadoDiaEnum,
    EstadoTurnoEnum,
    Producto,
    RolEnum,
    Ticket,
    Tienda,
    Usuario,
)
from app.core.deps import require_admin
from app.routers import caja as caja_router
from app.routers import pos as pos_router
from app.services import caja as caja_svc
from app.services.pos import get_informe_contador


def create_test_app():
    test_app = FastAPI(title="Sistema Cafe Test — Día operativo de la venta")
    test_app.include_router(pos_router.router, prefix="/api/v1")
    test_app.include_router(caja_router.router, prefix="/api/v1")
    return test_app


class DiaOperativoVentaTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.db = self.SessionLocal()
        self.app = create_test_app()
        self.client = TestClient(self.app)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_get_db

        self.tienda = Tienda(nombre="Vida", direccion="Sede Vida")
        self.db.add(self.tienda)
        self.db.flush()
        self.barista = Usuario(nombre="Barista Uno", email="barista1@test.local",
                               password_hash="hash", rol=RolEnum.barista,
                               tienda_id=self.tienda.id, activo=True)
        self.admin = Usuario(nombre="Admin", email="admin@test.local",
                             password_hash="hash", rol=RolEnum.admin,
                             tienda_id=self.tienda.id, activo=True)
        self.db.add_all([self.barista, self.admin])
        self.db.flush()
        self.producto = Producto(nombre="Americano Medium", categoria=CategoriaProductoEnum.bebida,
                                 unidad_medida="und", controla_stock=False, precio_venta=6900)
        self.db.add(self.producto)
        self.db.commit()

        self.hoy = hoy_col()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def set_current_user(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def crear_dia(self, fecha, estado=EstadoDiaEnum.abierto):
        dia = DiaOperativo(tienda_id=self.tienda.id, fecha_operativa=fecha,
                           estado=estado, abierto_por_id=self.admin.id)
        self.db.add(dia)
        self.db.commit()
        self.db.refresh(dia)
        return dia

    def crear_turno(self, dia=None, fecha_apertura=None, **overrides):
        """Turno OPERATIVO (cuadre + conteo hechos): el POS ya puede vender sobre él."""
        turno = CajaTurno(
            tienda_id=self.tienda.id,
            usuario_apertura_id=self.barista.id,
            base_sistema=0.0,
            base_real=100000.0,
            fecha_apertura=fecha_apertura or datetime.utcnow(),
            dia_operativo_id=dia.id if dia else None,
            tiene_conteo_apertura=overrides.get("tiene_conteo_apertura", True),
            tiene_cuadre_llegada=True,
            tiene_conteo_cierre=overrides.get("tiene_conteo_cierre", False),
            total_efectivo=overrides.get("total_efectivo", 0.0),
            total_tarjeta=overrides.get("total_tarjeta", 0.0),
            estado=EstadoTurnoEnum.abierto,
        )
        self.db.add(turno)
        self.db.commit()
        self.db.refresh(turno)
        return turno

    def vender(self, cantidad=1):
        self.set_current_user(self.barista)
        return self.client.post("/api/v1/pos/ticket", json={
            "tienda_id": self.tienda.id,
            "items": [{"producto_id": self.producto.id, "cantidad": cantidad}],
            "metodo_pago": "efectivo",
        })

    def dia_de(self, fecha):
        return self.db.query(DiaOperativo).filter(
            DiaOperativo.tienda_id == self.tienda.id,
            DiaOperativo.fecha_operativa == fecha,
        ).first()

    def ticket_de(self, respuesta):
        self.db.expire_all()
        return self.db.query(Ticket).filter(Ticket.id == respuesta.json()["id"]).first()


class VentaSobreTurnoZombieTests(DiaOperativoVentaTestCase):
    def test_la_venta_se_sella_con_el_dia_de_hoy_y_no_se_bloquea(self):
        # El turno quedó abierto hace 6 días (caso medido en producción). La venta
        # de hoy es de HOY, y sobre todo: SE COBRA. Nada de gates ni horas de gracia.
        hace_6 = self.hoy - timedelta(days=6)
        dia_viejo = self.crear_dia(hace_6)
        self.crear_turno(dia_viejo, fecha_apertura=inicio_dia_col_utc(hace_6) + timedelta(hours=13))

        r = self.vender()

        self.assertEqual(r.status_code, 201)
        ticket = self.ticket_de(r)
        dia_hoy = self.dia_de(self.hoy)
        self.assertIsNotNone(dia_hoy, "la venta debe resolver (o crear) el día operativo de hoy")
        self.assertEqual(ticket.dia_operativo_id, dia_hoy.id)
        self.assertNotEqual(ticket.dia_operativo_id, dia_viejo.id)

    def test_el_informe_contador_atribuye_la_venta_a_hoy_y_no_al_dia_del_turno(self):
        hace_6 = self.hoy - timedelta(days=6)
        dia_viejo = self.crear_dia(hace_6)
        self.crear_turno(dia_viejo, fecha_apertura=inicio_dia_col_utc(hace_6) + timedelta(hours=13))

        self.assertEqual(self.vender().status_code, 201)

        self.db.expire_all()
        informe = get_informe_contador(self.db, self.hoy.year, self.hoy.month, self.tienda.id)
        fechas = [d["fecha"] for d in informe["dias"]]
        self.assertIn(self.hoy.isoformat(), fechas)
        self.assertNotIn(dia_viejo.fecha_operativa.isoformat(), fechas)
        fila = next(d for d in informe["dias"] if d["fecha"] == self.hoy.isoformat())
        self.assertEqual(fila["total"], 6900.0)
        self.assertEqual(fila["facturas"], 1)

    def test_venta_normal_del_dia_NO_se_sella_y_queda_en_el_dia_del_turno(self):
        # Caso sano: el turno es de hoy. El ticket queda SIN sello a propósito y el
        # informe cae al día del turno — que es el que la barista firma en el cierre.
        # Sellar de más rompería esa igualdad en el cruce de medianoche.
        dia_hoy = self.crear_dia(self.hoy)
        self.crear_turno(dia_hoy)

        r = self.vender()

        self.assertEqual(r.status_code, 201)
        ticket = self.ticket_de(r)
        self.assertIsNone(ticket.dia_operativo_id)

        informe = get_informe_contador(self.db, self.hoy.year, self.hoy.month, self.tienda.id)
        self.assertEqual([d["fecha"] for d in informe["dias"]], [self.hoy.isoformat()])

    def test_turno_legacy_de_hoy_tampoco_se_sella(self):
        # Turno previo a la Fase 1 (dia_operativo_id NULL) pero abierto HOY: no es
        # zombie, así que no se sella y el informe lo resuelve por día Colombia.
        self.crear_turno(None)

        r = self.vender()

        self.assertEqual(r.status_code, 201)
        ticket = self.ticket_de(r)
        self.assertIsNone(ticket.dia_operativo_id)

        informe = get_informe_contador(self.db, self.hoy.year, self.hoy.month, self.tienda.id)
        self.assertEqual([d["fecha"] for d in informe["dias"]], [self.hoy.isoformat()])


class CierreAdministrativoSinConteoTests(DiaOperativoVentaTestCase):
    def test_sin_conteo_y_sin_omitir_sigue_bloqueado(self):
        turno = self.crear_turno(self.crear_dia(self.hoy - timedelta(days=1)))

        with self.assertRaises(HTTPException) as ctx:
            caja_svc.cerrar_turno_administrativo(self.db, turno.id, self.admin.id)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("conteo de cierre", ctx.exception.detail)

    def test_un_turno_de_hoy_no_puede_saltarse_el_conteo(self):
        # El escape es para rescatar turnos viejos, no para saltarse el inventario
        # del día en curso: hoy la sede SÍ puede registrar el conteo desde el PC.
        turno = self.crear_turno(self.crear_dia(self.hoy))

        with self.assertRaises(HTTPException) as ctx:
            caja_svc.cerrar_turno_administrativo(self.db, turno.id, self.admin.id,
                                                 omitir_conteo=True, motivo="se fueron sin cerrar")

        self.assertEqual(ctx.exception.status_code, 400)

    def test_omitir_el_conteo_exige_motivo(self):
        turno = self.crear_turno(self.crear_dia(self.hoy - timedelta(days=1)))

        for motivo in (None, "", "   "):
            with self.assertRaises(HTTPException) as ctx:
                caja_svc.cerrar_turno_administrativo(self.db, turno.id, self.admin.id,
                                                     omitir_conteo=True, motivo=motivo)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_dia_anterior_con_motivo_cierra_y_deja_rastro(self):
        turno = self.crear_turno(self.crear_dia(self.hoy - timedelta(days=2)),
                                 total_efectivo=50000.0)

        cerrado = caja_svc.cerrar_turno_administrativo(
            self.db, turno.id, self.admin.id,
            omitir_conteo=True, motivo="La sede nunca registró el conteo del lunes")

        self.assertEqual(cerrado.estado, EstadoTurnoEnum.cerrado)
        self.assertTrue(cerrado.cerrado_sin_conteo)
        self.assertIn("SIN conteo", cerrado.justificacion_cierre)
        self.assertIn("La sede nunca registró el conteo del lunes", cerrado.justificacion_cierre)

    def test_el_endpoint_sigue_aceptando_llamadas_sin_body(self):
        # El hub de Cuadres (CuadreTurnos.tsx) llama al endpoint SIN body: el nuevo
        # schema tiene que seguir siendo opcional o se rompe el botón existente.
        turno = self.crear_turno(self.crear_dia(self.hoy - timedelta(days=1)),
                                 tiene_conteo_cierre=True)
        self.app.dependency_overrides[require_admin] = lambda: self.admin
        self.app.dependency_overrides[get_current_user] = lambda: self.admin

        r = self.client.post(f"/api/v1/caja/{turno.id}/cerrar-administrativo")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["estado"], "cerrado")

    def test_el_endpoint_pasa_omitir_conteo_y_motivo(self):
        turno = self.crear_turno(self.crear_dia(self.hoy - timedelta(days=3)))
        self.app.dependency_overrides[require_admin] = lambda: self.admin
        self.app.dependency_overrides[get_current_user] = lambda: self.admin

        r = self.client.post(f"/api/v1/caja/{turno.id}/cerrar-administrativo",
                             json={"omitir_conteo": True, "motivo": "turno del viernes sin conteo"})

        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["cerrado_sin_conteo"])
        self.assertIn("turno del viernes sin conteo", r.json()["justificacion_cierre"])

    def test_con_conteo_de_cierre_el_cierre_administrativo_no_cambia(self):
        turno = self.crear_turno(self.crear_dia(self.hoy - timedelta(days=1)),
                                 tiene_conteo_cierre=True, total_efectivo=30000.0)

        cerrado = caja_svc.cerrar_turno_administrativo(self.db, turno.id, self.admin.id)

        self.assertEqual(cerrado.estado, EstadoTurnoEnum.cerrado)
        self.assertFalse(bool(cerrado.cerrado_sin_conteo))
        self.assertIn("Cierre administrativo", cerrado.justificacion_cierre)
        self.assertNotIn("SIN conteo", cerrado.justificacion_cierre)


class TurnoActivoDiaAnteriorTests(DiaOperativoVentaTestCase):
    """`es_de_dia_anterior` es CONSCIENTE DE LA HORA, así que el reloj se congela.

    `get_turno_activo` marca el turno contra `datetime.utcnow()` con el mismo
    criterio que el sello de la venta (`es_venta_de_turno_zombie`): entre 00:00 y
    las 06:00 de Colombia, el turno de ayer que sigue cobrando NO es un colgado
    sino un cierre en curso. Estos tests hablan del turno colgado en horario de
    operación, así que sin clavar la hora afirmaban lo contrario del módulo y
    fallaban en CI cualquier madrugada — una bomba de tiempo que además hacía
    imposible reportar la suite honestamente. No se toca `caja.py`: el
    comportamiento de producción es el correcto; lo que dependía del reloj de
    pared era el test.
    """

    def _reloj_a_las(self, hora: int = 10):
        """Clava el `utcnow()` que ve `caja` en esa hora Colombia de HOY."""
        from unittest.mock import patch
        p = patch("app.services.caja.datetime")
        dt = p.start()
        self.addCleanup(p.stop)
        dt.utcnow.return_value = inicio_dia_col_utc(self.hoy) + timedelta(hours=hora)

    def test_turno_de_hoy_no_se_marca_como_de_dia_anterior(self):
        self._reloj_a_las(10)
        self.crear_turno(self.crear_dia(self.hoy))

        turno = caja_svc.get_turno_activo(self.db, self.tienda.id)

        self.assertEqual(turno.dia_operativo_fecha, self.hoy.isoformat())
        self.assertFalse(turno.es_de_dia_anterior)

    def test_turno_de_ayer_se_marca_como_de_dia_anterior(self):
        # 10:00 de hoy: ya pasó la ventana del cruce de medianoche, así que el
        # turno de ayer que sigue abierto es un colgado y hay que avisarlo.
        self._reloj_a_las(10)
        ayer = self.hoy - timedelta(days=1)
        self.crear_turno(self.crear_dia(ayer))

        turno = caja_svc.get_turno_activo(self.db, self.tienda.id)

        self.assertEqual(turno.dia_operativo_fecha, ayer.isoformat())
        self.assertTrue(turno.es_de_dia_anterior)

    def test_turno_legacy_usa_el_dia_colombia_de_su_apertura(self):
        # Sin día operativo (previo a la Fase 1) el único dato es la apertura.
        self._reloj_a_las(10)
        ayer = self.hoy - timedelta(days=1)
        self.crear_turno(None, fecha_apertura=inicio_dia_col_utc(ayer) + timedelta(hours=13))

        turno = caja_svc.get_turno_activo(self.db, self.tienda.id)

        self.assertEqual(turno.dia_operativo_fecha, ayer.isoformat())
        self.assertTrue(turno.es_de_dia_anterior)


class CarreraDelDiaOperativoTests(DiaOperativoVentaTestCase):
    """La carrera del get-or-create tiene que dejar VIVA la transacción del caller.

    Hay UniqueConstraint(tienda_id, fecha_operativa): si dos dispositivos de la
    misma sede cobran a la vez y ambos pasan el SELECT, el segundo INSERT viola el
    UNIQUE. Ese IntegrityError sale de db.flush() y, sin SAVEPOINT, deja la sesión
    en rollback-required — atraparlo por fuera NO salva la venta, el commit
    siguiente falla igual. Con begin_nested se revierte solo el INSERT.
    """

    def test_el_dia_duplicado_no_mata_la_transaccion(self):
        from unittest.mock import patch
        existente = self.crear_dia(self.hoy)

        # Simula perder la carrera: el SELECT no ve el día (como el request que
        # entró antes de que el otro hiciera commit) y se va derecho al INSERT.
        real_first = caja_svc.DiaOperativo
        llamadas = {"n": 0}
        orig_query = self.db.query

        def query_ciego(*a, **k):
            q = orig_query(*a, **k)
            if a and a[0] is real_first and llamadas["n"] == 0:
                llamadas["n"] += 1
                class _Ciego:
                    def filter(self, *_a, **_k): return self
                    def first(self): return None
                return _Ciego()
            return q

        with patch.object(self.db, "query", side_effect=query_ciego):
            dia = caja_svc.get_or_create_dia(self.db, self.tienda.id, self.admin.id)

        # Se recuperó con el día que ya existía...
        self.assertEqual(dia.id, existente.id)
        # ...y lo que de verdad importa: la transacción sigue usable.
        self.db.add(Ticket(
            tienda_id=self.tienda.id, caja_turno_id=self.crear_turno(existente).id,
            usuario_id=self.barista.id, fecha=datetime.utcnow(), total=1000,
            estado="completado", metodo_pago="efectivo", monto_efectivo=1000,
        ))
        self.db.commit()   # sin el SAVEPOINT esto explota con PendingRollbackError
        self.assertEqual(self.db.query(Ticket).count(), 1)


class SenalesCoherentesTests(DiaOperativoVentaTestCase):
    """Las TRES señales del cambio tienen que usar el MISMO criterio.

    Se introdujeron juntas: el sello de la venta, el aviso del kiosko y el permiso
    de cierre sin conteo. Si el sello es consciente de la hora y las otras dos
    comparan fechas a secas, entre las 00:00 y las 06:00 se contradicen: el turno
    de cierre que sigue cobrando queda marcado "de un día anterior" y —lo grave—
    un admin puede cerrarlo salteando el conteo MIENTRAS las baristas cobran.
    """

    def _turno_de_ayer_cobrando_de_madrugada(self):
        from unittest.mock import patch
        ayer = self.hoy - timedelta(days=1)
        turno = self.crear_turno(self.crear_dia(ayer),
                                 fecha_apertura=inicio_dia_col_utc(ayer) + timedelta(hours=14))
        # "Ahora" = 00:30 hora Colombia de hoy → 05:30 UTC.
        ahora = inicio_dia_col_utc(self.hoy) + timedelta(minutes=30)
        return turno, ayer, patch("app.services.caja.datetime") , ahora

    def test_de_madrugada_el_turno_de_ayer_NO_se_marca_como_colgado(self):
        from unittest.mock import patch
        turno, ayer, _, ahora = self._turno_de_ayer_cobrando_de_madrugada()
        with patch("app.services.caja.datetime") as dt:
            dt.utcnow.return_value = ahora
            activo = caja_svc.get_turno_activo(self.db, self.tienda.id)
            self.assertFalse(activo.es_de_dia_anterior,
                             "a las 00:30 el cierre sigue en curso: avisar es ruido y contradice al sello")
        self.assertEqual(turno.dia_operativo_id, self.dia_de(ayer).id)

    def test_de_madrugada_el_admin_NO_puede_cerrar_sin_conteo(self):
        from unittest.mock import patch
        turno, _, _, ahora = self._turno_de_ayer_cobrando_de_madrugada()
        with patch("app.services.caja.datetime") as dt:
            dt.utcnow.return_value = ahora
            with self.assertRaises(HTTPException) as ctx:
                caja_svc.cerrar_turno_administrativo(
                    self.db, turno.id, self.admin.id, omitir_conteo=True, motivo="apuro")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("todavía está en curso", ctx.exception.detail)

    def test_en_horario_de_operacion_el_turno_colgado_si_se_puede_rescatar(self):
        # Mismo turno de ayer, pero a las 10:00 de hoy: ya no hay cierre en curso.
        from unittest.mock import patch
        turno, _, _, _ = self._turno_de_ayer_cobrando_de_madrugada()
        ahora = inicio_dia_col_utc(self.hoy) + timedelta(hours=10)
        with patch("app.services.caja.datetime") as dt:
            dt.utcnow.return_value = ahora
            caja_svc.cerrar_turno_administrativo(
                self.db, turno.id, self.admin.id, omitir_conteo=True, motivo="quedó colgado")
        self.db.refresh(turno)
        self.assertEqual(turno.estado, EstadoTurnoEnum.cerrado)
        self.assertTrue(turno.cerrado_sin_conteo)
        self.assertIn("quedó colgado", turno.justificacion_cierre)


class BaseDelTurnoSiguienteTests(DiaOperativoVentaTestCase):
    """El rescate de un zombie no puede dejar una bomba en el turno siguiente.

    El cierre administrativo no cuenta la plata: la CALCULA. Si esa fórmula ignora
    lo ya consignado, el esperado incluye plata que está en el banco — y ese
    esperado se vuelve la base del turno siguiente, así que la barista entrante
    tendría que contar un efectivo que nadie puede encontrar.
    """

    def _zombie_con_consignacion(self, efectivo, consignado):
        from app.models.models import Consignacion, EstadoConsignacionEnum
        ayer = self.hoy - timedelta(days=2)
        turno = self.crear_turno(self.crear_dia(ayer),
                                 fecha_apertura=inicio_dia_col_utc(ayer) + timedelta(hours=13),
                                 total_efectivo=efectivo)
        turno.base_real = 100000.0
        if consignado:
            self.db.add(Consignacion(
                tienda_id=self.tienda.id, caja_turno_id=turno.id, valor=consignado,
                usuario_id=self.barista.id, estado=EstadoConsignacionEnum.realizada))
        self.db.commit()
        return turno

    def test_el_esperado_descuenta_lo_ya_consignado(self):
        turno = self._zombie_con_consignacion(efectivo=900000.0, consignado=700000.0)

        caja_svc.cerrar_turno_administrativo(
            self.db, turno.id, self.admin.id, omitir_conteo=True, motivo="turno colgado")

        self.db.refresh(turno)
        # base 100.000 + efectivo 900.000 − consignado 700.000
        self.assertEqual(turno.efectivo_final_real, 300000.0)
        self.assertIn("consignados", turno.justificacion_cierre)

    def test_la_base_del_turno_siguiente_no_pide_plata_que_esta_en_el_banco(self):
        turno = self._zombie_con_consignacion(efectivo=900000.0, consignado=700000.0)
        caja_svc.cerrar_turno_administrativo(
            self.db, turno.id, self.admin.id, omitir_conteo=True, motivo="turno colgado")
        self.db.refresh(turno)

        # Rama "día nuevo": lo que debería quedar en la registradora.
        base = caja_svc._base_desde_ultimo_cierre(turno, 0.0)

        # 300.000 contados − 100.000 de base = 200.000 de ventas en efectivo que
        # NO se consignaron. Sin el descuento serían 900.000: 700.000 de faltante
        # fabricado para la barista que abre.
        self.assertEqual(base, 200000.0)

    def test_sin_consignaciones_el_esperado_no_cambia(self):
        turno = self._zombie_con_consignacion(efectivo=900000.0, consignado=0.0)

        caja_svc.cerrar_turno_administrativo(
            self.db, turno.id, self.admin.id, omitir_conteo=True, motivo="turno colgado")

        self.db.refresh(turno)
        self.assertEqual(turno.efectivo_final_real, 1000000.0)
        self.assertNotIn("consignados", turno.justificacion_cierre)


class CruceMedianocheVsZombieTest(unittest.TestCase):
    """La distinción que la aritmética de fechas confunde y el negocio no.

    Un cierre que sigue cobrando a las 00:30 NO es un turno zombie: esa venta entra
    en el cierre que la barista firma esa madrugada. Sellarla con el día siguiente
    la sacaría del día firmado y rompería la igualdad informe = cierre, que es la
    razón entera por la que el informe agrupa por día operativo.
    """

    def test_cruce_de_medianoche_no_es_zombie(self):
        dia_turno = date(2026, 7, 31)
        # 00:30 hora Colombia del 1-ago = 05:30 UTC
        self.assertFalse(es_venta_de_turno_zombie(dia_turno, datetime(2026, 8, 1, 5, 30)))

    def test_misma_fecha_no_es_zombie(self):
        dia_turno = date(2026, 7, 31)
        self.assertFalse(es_venta_de_turno_zombie(dia_turno, datetime(2026, 7, 31, 20, 0)))

    def test_al_otro_dia_en_horario_de_operacion_si_es_zombie(self):
        # 10:00 hora Colombia del 1-ago = 15:00 UTC. Ya no hay cierre en curso que
        # contenga esa venta: el turno quedó abierto y se está vendiendo sobre él.
        dia_turno = date(2026, 7, 31)
        self.assertTrue(es_venta_de_turno_zombie(dia_turno, datetime(2026, 8, 1, 15, 0)))

    def test_varios_dias_despues_si_es_zombie(self):
        dia_turno = date(2026, 7, 31)
        self.assertTrue(es_venta_de_turno_zombie(dia_turno, datetime(2026, 8, 3, 5, 30)))

    def test_sin_dia_de_turno_no_decide(self):
        self.assertFalse(es_venta_de_turno_zombie(None, datetime(2026, 8, 1, 15, 0)))


if __name__ == "__main__":
    unittest.main()
