import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import (
    CajaTurno,
    CategoriaProductoEnum,
    Consignacion,
    EstadoConsignacionEnum,
    EstadoSolicitudEnum,
    EstadoTurnoEnum,
    Producto,
    RolEnum,
    SolicitudPedido,
    SolicitudPedidoItem,
    Tienda,
    Inventario,
    Usuario,
)
from app.routers import auth, caja, consignaciones, conteos, dashboard, informes, inventario, mermas, pasteleria, solicitudes, ventas


def create_test_app():
    test_app = FastAPI(title="Sistema Cafe Test")
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.include_router(auth.router, prefix="/api/v1")
    test_app.include_router(caja.router, prefix="/api/v1")
    test_app.include_router(inventario.router, prefix="/api/v1")
    test_app.include_router(pasteleria.router, prefix="/api/v1")
    test_app.include_router(consignaciones.router, prefix="/api/v1")
    test_app.include_router(dashboard.router, prefix="/api/v1")
    test_app.include_router(ventas.router, prefix="/api/v1")
    test_app.include_router(conteos.router, prefix="/api/v1")
    test_app.include_router(mermas.router, prefix="/api/v1")
    test_app.include_router(solicitudes.router, prefix="/api/v1")
    test_app.include_router(informes.router, prefix="/api/v1")
    return test_app


class BackendTestCase(unittest.TestCase):
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

        self.tienda_1 = Tienda(nombre="Sede 1", direccion="Calle 1")
        self.tienda_2 = Tienda(nombre="Sede 2", direccion="Calle 2")
        self.db.add_all([self.tienda_1, self.tienda_2])
        self.db.flush()

        self.barista_1 = Usuario(
            nombre="Barista Uno",
            email="barista1@test.local",
            password_hash="hash",
            rol=RolEnum.barista,
            tienda_id=self.tienda_1.id,
            activo=True,
        )
        self.barista_2 = Usuario(
            nombre="Barista Dos",
            email="barista2@test.local",
            password_hash="hash",
            rol=RolEnum.barista,
            tienda_id=self.tienda_2.id,
            activo=True,
        )
        self.admin = Usuario(
            nombre="Admin",
            email="admin@test.local",
            password_hash="hash",
            rol=RolEnum.admin,
            tienda_id=self.tienda_1.id,
            activo=True,
        )
        self.db.add_all([self.barista_1, self.barista_2, self.admin])
        self.db.flush()

        self.producto = Producto(
            nombre="Cafe",
            categoria=CategoriaProductoEnum.bebida,
            unidad_medida="unidad",
        )
        self.db.add(self.producto)
        self.db.commit()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def set_current_user(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def create_turno(self, tienda_id, usuario_id, **overrides):
        turno = CajaTurno(
            tienda_id=tienda_id,
            usuario_apertura_id=usuario_id,
            base_sistema=overrides.get("base_sistema", 0.0),
            base_real=overrides.get("base_real", 100000.0),
            diferencia_apertura=overrides.get("diferencia_apertura", 0.0),
            justificacion_apertura=overrides.get("justificacion_apertura"),
            total_ventas=overrides.get("total_ventas", 0.0),
            total_efectivo=overrides.get("total_efectivo", 0.0),
            total_tarjeta=overrides.get("total_tarjeta", 0.0),
            tiene_conteo_apertura=overrides.get("tiene_conteo_apertura", False),
            tiene_ventas=overrides.get("tiene_ventas", False),
            tiene_conteo_cierre=overrides.get("tiene_conteo_cierre", False),
            estado=overrides.get("estado", EstadoTurnoEnum.abierto),
        )
        self.db.add(turno)
        self.db.commit()
        self.db.refresh(turno)
        return turno

    def create_solicitud_pedido(self, tienda_id, usuario_id):
        solicitud = SolicitudPedido(
            tienda_id=tienda_id,
            usuario_id=usuario_id,
            estado=EstadoSolicitudEnum.pendiente,
        )
        self.db.add(solicitud)
        self.db.flush()
        self.db.add(
            SolicitudPedidoItem(
                solicitud_id=solicitud.id,
                producto_id=self.producto.id,
                cantidad_solicitada=2,
            )
        )
        self.db.commit()
        self.db.refresh(solicitud)
        return solicitud

    def create_consignacion(self, tienda_id, usuario_id):
        consignacion = Consignacion(
            tienda_id=tienda_id,
            valor=50000.0,
            usuario_id=usuario_id,
            estado=EstadoConsignacionEnum.pendiente,
        )
        self.db.add(consignacion)
        self.db.commit()
        self.db.refresh(consignacion)
        return consignacion

    def create_inventario(self, tienda_id, producto_id=None, **overrides):
        inventario = Inventario(
            producto_id=producto_id or self.producto.id,
            tienda_id=tienda_id,
            stock_actual=overrides.get("stock_actual", 20.0),
            stock_minimo=overrides.get("stock_minimo", 5.0),
        )
        self.db.add(inventario)
        self.db.commit()
        self.db.refresh(inventario)
        return inventario


class CajaFlowTests(BackendTestCase):
    def test_apertura_exitosa_con_justificacion(self):
        self.set_current_user(self.barista_1)

        turno_cerrado = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            estado=EstadoTurnoEnum.cerrado,
            base_real=90000.0,
        )
        turno_cerrado.efectivo_final_real = 90000.0
        self.db.commit()

        response = self.client.post(
            "/api/v1/caja/abrir",
            json={
                "tienda_id": self.tienda_1.id,
                "base_real": 95000.0,
                "justificacion_apertura": "Diferencia explicada",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["base_sistema"], 90000.0)
        self.assertEqual(body["base_real"], 95000.0)
        self.assertEqual(body["diferencia_apertura"], 5000.0)

    def test_apertura_requiere_justificacion_si_hay_diferencia(self):
        self.set_current_user(self.barista_1)

        turno_cerrado = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            estado=EstadoTurnoEnum.cerrado,
            base_real=80000.0,
            total_efectivo=20000.0,
        )
        turno_cerrado.efectivo_final_real = 80000.0
        self.db.commit()

        response = self.client.post(
            "/api/v1/caja/abrir",
            json={
                "tienda_id": self.tienda_1.id,
                "base_real": 75000.0,
                "justificacion_apertura": None,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Se requiere", response.json()["detail"])

    def test_venta_se_bloquea_sin_conteo_de_apertura(self):
        self.set_current_user(self.barista_1)
        self.create_turno(self.tienda_1.id, self.barista_1.id, tiene_conteo_apertura=False)

        response = self.client.post(
            "/api/v1/ventas/",
            json={
                "tienda_id": self.tienda_1.id,
                "venta_total": 50000,
                "nota_credito": 0,
                "vales": 0,
                "tarjetas": 10000,
                "nota": None,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Debes completar el conteo de apertura primero")

    def test_venta_exitosa_actualiza_totales_del_turno(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            tiene_conteo_apertura=True,
        )

        response = self.client.post(
            "/api/v1/ventas/",
            json={
                "tienda_id": self.tienda_1.id,
                "venta_total": 50000,
                "nota_credito": 2000,
                "vales": 3000,
                "tarjetas": 10000,
                "nota": "venta test",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(turno)
        self.assertEqual(turno.total_ventas, 50000.0)
        self.assertEqual(turno.total_efectivo, 35000.0)
        self.assertEqual(turno.total_tarjeta, 10000.0)
        self.assertTrue(turno.tiene_ventas)

    def test_venta_rechaza_total_en_cero(self):
        self.set_current_user(self.barista_1)
        self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            tiene_conteo_apertura=True,
        )

        response = self.client.post(
            "/api/v1/ventas/",
            json={
                "tienda_id": self.tienda_1.id,
                "venta_total": 0,
                "nota_credito": 0,
                "vales": 0,
                "tarjetas": 0,
                "nota": None,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("mayor a 0", response.json()["detail"])

    def test_venta_rechaza_desglose_incoherente(self):
        self.set_current_user(self.barista_1)
        self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            tiene_conteo_apertura=True,
        )

        response = self.client.post(
            "/api/v1/ventas/",
            json={
                "tienda_id": self.tienda_1.id,
                "venta_total": 10000,
                "nota_credito": 2000,
                "vales": 3000,
                "tarjetas": 6000,
                "nota": None,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no puede superar", response.json()["detail"])

    def test_entrega_se_bloquea_si_siigo_no_coincide(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            total_ventas=50000.0,
            total_efectivo=40000.0,
            total_tarjeta=10000.0,
            tiene_conteo_apertura=True,
            tiene_ventas=True,
        )

        response = self.client.post(
            f"/api/v1/caja/{turno.id}/entrega",
            data={
                "efectivo_real": "140000",
                "ventas_tarjeta_bold": "10000",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no coincide", response.json()["detail"])

    def test_entrega_exitosa_guarda_diferencias(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            base_real=100000.0,
            total_ventas=50000.0,
            total_efectivo=40000.0,
            total_tarjeta=10000.0,
            tiene_conteo_apertura=True,
            tiene_ventas=True,
        )

        response = self.client.post(
            f"/api/v1/caja/{turno.id}/entrega",
            data={
                "efectivo_real": "140000",
                "ventas_tarjeta_bold": "10000",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["efectivo_esperado"], 140000.0)
        self.assertEqual(body["diferencia_efectivo"], 0.0)
        self.assertEqual(body["diferencia_tarjeta"], 0.0)

    def test_cierre_se_bloquea_sin_conteo_de_cierre(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            total_ventas=50000.0,
            total_efectivo=40000.0,
            total_tarjeta=10000.0,
            tiene_conteo_apertura=True,
            tiene_ventas=True,
            tiene_conteo_cierre=False,
        )

        response = self.client.post(
            f"/api/v1/caja/{turno.id}/cerrar",
            json={
                "efectivo_final_real": 140000,
                "datafono_real": 10000,
                "justificacion_cierre": None,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("conteo de cierre", response.json()["detail"])

    def test_cierre_exige_datafono_si_hubo_tarjeta(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            total_ventas=50000.0,
            total_efectivo=40000.0,
            total_tarjeta=10000.0,
            tiene_conteo_apertura=True,
            tiene_ventas=True,
            tiene_conteo_cierre=True,
        )

        response = self.client.post(
            f"/api/v1/caja/{turno.id}/cerrar",
            json={
                "efectivo_final_real": 140000,
                "datafono_real": None,
                "justificacion_cierre": None,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Bold", response.json()["detail"])

    def test_cierre_exitoso_con_justificacion_cierra_turno(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            base_real=100000.0,
            total_ventas=50000.0,
            total_efectivo=40000.0,
            total_tarjeta=10000.0,
            tiene_conteo_apertura=True,
            tiene_ventas=True,
            tiene_conteo_cierre=True,
        )

        response = self.client.post(
            f"/api/v1/caja/{turno.id}/cerrar",
            json={
                "efectivo_final_real": 141000,
                "datafono_real": 10000,
                "justificacion_cierre": "Sobrante controlado",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(turno)
        self.assertEqual(turno.estado, EstadoTurnoEnum.cerrado)
        self.assertEqual(turno.diferencia_cierre, 1000.0)
        self.assertEqual(turno.diferencia_tarjeta, 0.0)
        self.assertEqual(turno.justificacion_cierre, "Sobrante controlado")

    def test_barista_no_puede_consultar_otra_tienda(self):
        self.set_current_user(self.barista_1)

        response = self.client.get(f"/api/v1/inventario/tienda/{self.tienda_2.id}")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "No tienes acceso a esta tienda")

    def test_admin_puede_consultar_otra_tienda(self):
        self.set_current_user(self.admin)

        response = self.client.get(f"/api/v1/inventario/tienda/{self.tienda_2.id}")

        self.assertEqual(response.status_code, 200)


class PermissionTests(BackendTestCase):
    def test_barista_no_puede_ver_dashboard(self):
        self.set_current_user(self.barista_1)

        response = self.client.get(f"/api/v1/dashboard/{self.tienda_1.id}")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Se requiere rol admin")

    def test_admin_puede_ver_dashboard_de_otra_tienda(self):
        self.set_current_user(self.admin)

        response = self.client.get(f"/api/v1/dashboard/{self.tienda_2.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tienda_id"], self.tienda_2.id)

    def test_barista_no_puede_ver_informes(self):
        self.set_current_user(self.barista_1)

        response = self.client.get(
            "/api/v1/informes/ventas",
            params={
                "tienda_id": self.tienda_1.id,
                "fecha_desde": "2026-04-01",
                "fecha_hasta": "2026-04-30",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Se requiere rol admin")

    def test_admin_puede_ver_informes(self):
        self.set_current_user(self.admin)

        response = self.client.get(
            "/api/v1/informes/ventas",
            params={
                "tienda_id": self.tienda_1.id,
                "fecha_desde": "2026-04-01",
                "fecha_hasta": "2026-04-30",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("filas", response.json())
        self.assertIn("totales", response.json())

    def test_barista_no_puede_aprobar_solicitud(self):
        solicitud = self.create_solicitud_pedido(self.tienda_1.id, self.barista_1.id)
        self.set_current_user(self.barista_1)

        response = self.client.patch(f"/api/v1/solicitudes/pedido/{solicitud.id}/aprobar")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Se requiere rol admin")

    def test_admin_puede_aprobar_solicitud(self):
        solicitud = self.create_solicitud_pedido(self.tienda_1.id, self.barista_1.id)
        self.set_current_user(self.admin)

        response = self.client.patch(f"/api/v1/solicitudes/pedido/{solicitud.id}/aprobar")

        self.assertEqual(response.status_code, 200)
        self.db.refresh(solicitud)
        self.assertEqual(solicitud.estado, EstadoSolicitudEnum.aprobada)
        self.assertEqual(solicitud.usuario_aprobacion_id, self.admin.id)

    def test_barista_no_puede_confirmar_consignacion(self):
        consignacion = self.create_consignacion(self.tienda_1.id, self.barista_1.id)
        self.set_current_user(self.barista_1)

        response = self.client.patch(f"/api/v1/consignaciones/{consignacion.id}/confirmar")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Se requiere rol admin")

    def test_admin_puede_confirmar_consignacion(self):
        consignacion = self.create_consignacion(self.tienda_1.id, self.barista_1.id)
        self.set_current_user(self.admin)

        response = self.client.patch(f"/api/v1/consignaciones/{consignacion.id}/confirmar")

        self.assertEqual(response.status_code, 200)
        self.db.refresh(consignacion)
        self.assertEqual(consignacion.estado, EstadoConsignacionEnum.realizada)


class ConteoAndMovementTests(BackendTestCase):
    def test_movimiento_caja_invalido_por_tipo(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(self.tienda_1.id, self.barista_1.id)

        response = self.client.post(
            f"/api/v1/caja/{turno.id}/movimiento",
            json={
                "tipo": "retiro",
                "concepto": "Prueba",
                "valor": 5000,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ingreso o egreso", response.json()["detail"])

    def test_movimiento_caja_invalido_por_valor_no_positivo(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(self.tienda_1.id, self.barista_1.id)

        response = self.client.post(
            f"/api/v1/caja/{turno.id}/movimiento",
            json={
                "tipo": "egreso",
                "concepto": "Cambio",
                "valor": 0,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("mayor a 0", response.json()["detail"])

    def test_turno_activo_expone_efectivo_esperado_con_movimientos(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            base_real=100000.0,
            total_efectivo=30000.0,
        )

        self.client.post(
            f"/api/v1/caja/{turno.id}/movimiento",
            json={"tipo": "ingreso", "concepto": "Cambio", "valor": 5000},
        )
        self.client.post(
            f"/api/v1/caja/{turno.id}/movimiento",
            json={"tipo": "egreso", "concepto": "Domicilio", "valor": 2000},
        )

        response = self.client.get(f"/api/v1/caja/activo/{self.tienda_1.id}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ingresos_movimientos"], 5000.0)
        self.assertEqual(body["egresos_movimientos"], 2000.0)
        self.assertEqual(body["efectivo_esperado_actual"], 133000.0)

    def test_conteo_apertura_exitosa_activa_flag(self):
        self.set_current_user(self.barista_1)
        turno = self.create_turno(self.tienda_1.id, self.barista_1.id, tiene_conteo_apertura=False)
        self.create_inventario(self.tienda_1.id, stock_actual=12.0)

        response = self.client.post(
            "/api/v1/conteos/",
            json={
                "tienda_id": self.tienda_1.id,
                "tipo": "apertura",
                "items": [
                    {
                        "producto_id": self.producto.id,
                        "cantidad_real": 12,
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(turno)
        self.assertTrue(turno.tiene_conteo_apertura)
        self.assertEqual(response.json()["items"][0]["diferencia"], 0.0)

    def test_conteo_cierre_se_bloquea_sin_ventas(self):
        self.set_current_user(self.barista_1)
        self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            tiene_conteo_apertura=True,
            tiene_ventas=False,
        )

        response = self.client.post(
            "/api/v1/conteos/",
            json={
                "tienda_id": self.tienda_1.id,
                "tipo": "cierre",
                "items": [
                    {
                        "producto_id": self.producto.id,
                        "cantidad_real": 10,
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ventas primero", response.json()["detail"])

    def test_conteo_no_permite_duplicado(self):
        self.set_current_user(self.barista_1)
        self.create_turno(
            self.tienda_1.id,
            self.barista_1.id,
            tiene_conteo_apertura=True,
        )

        response = self.client.post(
            "/api/v1/conteos/",
            json={
                "tienda_id": self.tienda_1.id,
                "tipo": "apertura",
                "items": [
                    {
                        "producto_id": self.producto.id,
                        "cantidad_real": 10,
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ya fue registrado", response.json()["detail"])

    def test_inventario_no_permite_stock_negativo(self):
        self.set_current_user(self.barista_1)
        self.create_inventario(self.tienda_1.id, stock_actual=3.0)

        response = self.client.post(
            "/api/v1/inventario/movimiento",
            json={
                "producto_id": self.producto.id,
                "tienda_id": self.tienda_1.id,
                "tipo": "salida",
                "cantidad": 5,
                "motivo": "Consumo",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Stock insuficiente")

    def test_inventario_ajuste_actualiza_stock(self):
        self.set_current_user(self.barista_1)
        inventario = self.create_inventario(self.tienda_1.id, stock_actual=8.0)

        response = self.client.post(
            "/api/v1/inventario/movimiento",
            json={
                "producto_id": self.producto.id,
                "tienda_id": self.tienda_1.id,
                "tipo": "ajuste",
                "cantidad": 15,
                "motivo": "Conteo",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.db.refresh(inventario)
        self.assertEqual(inventario.stock_actual, 15.0)

    def test_inventario_lotes_exige_admin(self):
        self.set_current_user(self.barista_1)
        self.create_inventario(self.tienda_1.id, stock_actual=8.0)

        response = self.client.get(f"/api/v1/inventario/lotes/{self.tienda_1.id}/{self.producto.id}")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Se requiere rol admin")


if __name__ == "__main__":
    unittest.main()
