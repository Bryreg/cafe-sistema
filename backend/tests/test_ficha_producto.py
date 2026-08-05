"""Ficha del producto: GET /inventario/producto/{producto_id}/ficha?tienda_id=

Una sola llamada que junta lo que hoy está repartido en cuatro pantallas
(stock, lotes, conteos, movimientos) más la receta. Es un endpoint de LECTURA
agregada: no debe inventar lógica propia, sino devolver exactamente lo que ya
calculan las funciones vigentes (get_trazabilidad para el estado de los lotes,
ConteoFisicoItem para sistema/real/diferencia).
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import (
    CajaTurno, CategoriaProductoEnum, ConteoFisico, ConteoFisicoItem,
    EstadoTurnoEnum, Inventario, LoteInventario, MovimientoInventario, Producto,
    ProductoInsumo, RolEnum, Tienda, TipoConteoEnum, TipoMovInvEnum, Usuario,
)
from app.routers import inventario as inventario_router


class FichaProductoTest(unittest.TestCase):
    """sqlite temporal + router real de inventario (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda = Tienda(nombre="Vida", direccion="Sede Vida")
        self.otra_tienda = Tienda(nombre="Palmetto", direccion="Sede Palmetto")
        self.db.add_all([self.tienda, self.otra_tienda])
        self.db.flush()

        self.admin = Usuario(nombre="Admin", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.barista = Usuario(nombre="Barista Uno", email="barista1@test.local",
                               password_hash="h", rol=RolEnum.barista,
                               tienda_id=self.tienda.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.db.flush()

        # Producto principal: café en gramos, fraccionable (bolsa), con proveedor.
        self.cafe = Producto(nombre="Café Excelso", categoria=CategoriaProductoEnum.insumo,
                             unidad_medida="gr", controla_stock=True, proveedor="Tostadora X",
                             lead_time_dias=3, fraccionable=True, envase="bolsa",
                             contenido_por_empaque=2500, precio_venta=0)
        # Bebida que consume el café por receta.
        self.americano = Producto(nombre="Americano", categoria=CategoriaProductoEnum.bebida,
                                  unidad_medida="unidad", controla_stock=False, precio_venta=5000)
        self.db.add_all([self.cafe, self.americano])
        self.db.flush()

        self.db.add(ProductoInsumo(producto_id=self.americano.id, insumo_id=self.cafe.id,
                                   cantidad=18.0))
        self.db.add(Inventario(producto_id=self.cafe.id, tienda_id=self.tienda.id,
                               stock_actual=1200.0, stock_minimo=800.0,
                               stock_ideal=3000.0, stock_critico=400.0))
        self.db.add(Inventario(producto_id=self.americano.id, tienda_id=self.tienda.id,
                               stock_actual=0.0, stock_minimo=0.0))
        self.db.commit()

        app = FastAPI(title="Test ficha de producto")
        app.include_router(inventario_router.router, prefix="/api/v1")
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
        self.app.dependency_overrides[get_current_user] = lambda: user

    def ficha(self, producto_id=None, tienda_id=None):
        pid = producto_id if producto_id is not None else self.cafe.id
        tid = tienda_id if tienda_id is not None else self.tienda.id
        return self.client.get(f"/api/v1/inventario/producto/{pid}/ficha",
                               params={"tienda_id": tid})

    def crear_lote(self, cantidad_inicial, cantidad_restante, vencimiento, numero="L1"):
        lote = LoteInventario(
            producto_id=self.cafe.id, tienda_id=self.tienda.id,
            cantidad_inicial=cantidad_inicial, cantidad_restante=cantidad_restante,
            fecha_entrada=datetime.utcnow() - timedelta(days=5),
            fecha_vencimiento=vencimiento, usuario_id=self.admin.id,
            numero_lote=numero, proveedor="Tostadora X",
        )
        self.db.add(lote)
        self.db.commit()
        return lote

    def crear_movimiento(self, tipo, cantidad, motivo, dias_atras=0, barista_nombre=None):
        mov = MovimientoInventario(
            producto_id=self.cafe.id, tienda_id=self.tienda.id, tipo=tipo,
            cantidad=cantidad, fecha=datetime.utcnow() - timedelta(days=dias_atras),
            usuario_id=self.admin.id, motivo=motivo,
            barista_id=self.barista.id if barista_nombre else None,
            barista_nombre=barista_nombre,
        )
        self.db.add(mov)
        self.db.commit()
        return mov

    def crear_conteo(self, tipo, sistema, real, dias_atras=0, barista_nombre="Barista Uno"):
        turno = CajaTurno(tienda_id=self.tienda.id, usuario_apertura_id=self.admin.id,
                          base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add(turno)
        self.db.flush()
        conteo = ConteoFisico(
            tienda_id=self.tienda.id, turno_id=turno.id, tipo=tipo,
            fecha_registro=datetime.utcnow() - timedelta(days=dias_atras),
            usuario_id=self.admin.id, barista_id=self.barista.id,
            barista_nombre=barista_nombre,
        )
        self.db.add(conteo)
        self.db.flush()
        self.db.add(ConteoFisicoItem(conteo_id=conteo.id, producto_id=self.cafe.id,
                                     cantidad_sistema=sistema, cantidad_real=real,
                                     diferencia=real - sistema))
        self.db.commit()
        return conteo

    # ── Bloques completos ────────────────────────────────────────────────────

    def test_ficha_con_historial_trae_todos_los_bloques(self):
        self.crear_lote(2500, 1200, datetime.utcnow() + timedelta(days=30))
        self.crear_movimiento(TipoMovInvEnum.entrada, 2500, "Factura 001",
                              dias_atras=5, barista_nombre="Barista Uno")
        self.crear_conteo(TipoConteoEnum.cierre, 1250, 1200)

        r = self.ficha()
        self.assertEqual(r.status_code, 200)
        data = r.json()

        prod = data["producto"]
        self.assertEqual(prod["id"], self.cafe.id)
        self.assertEqual(prod["nombre"], "Café Excelso")
        self.assertEqual(prod["categoria"], "insumo")
        self.assertEqual(prod["unidad_medida"], "gr")
        self.assertTrue(prod["controla_stock"])
        self.assertTrue(prod["fraccionable"])
        self.assertEqual(prod["envase"], "bolsa")
        self.assertEqual(prod["proveedor"], "Tostadora X")
        self.assertEqual(prod["lead_time_dias"], 3)
        self.assertEqual(prod["contenido_por_empaque"], 2500)
        self.assertEqual(prod["precio_venta"], 0)

        stock = data["stock"]
        self.assertEqual(stock["stock_actual"], 1200.0)
        self.assertEqual(stock["stock_critico"], 400.0)
        self.assertEqual(stock["stock_minimo"], 800.0)
        self.assertEqual(stock["stock_ideal"], 3000.0)

        self.assertEqual(len(data["lotes"]), 1)
        self.assertEqual(len(data["movimientos"]), 1)
        self.assertEqual(len(data["conteos"]), 1)
        self.assertEqual(len(data["receta"]["insumos"]), 0)      # el café no lleva receta
        self.assertEqual(len(data["receta"]["usado_en"]), 1)     # pero el americano lo consume

    def test_ficha_de_otra_sede_no_mezcla_historial(self):
        # El mismo producto en otra sede: su movimiento no puede aparecer en la
        # ficha de Vida (el bloque es por producto+tienda, no por producto).
        self.db.add(Inventario(producto_id=self.cafe.id, tienda_id=self.otra_tienda.id,
                               stock_actual=50.0, stock_minimo=0.0))
        self.db.add(MovimientoInventario(
            producto_id=self.cafe.id, tienda_id=self.otra_tienda.id,
            tipo=TipoMovInvEnum.entrada, cantidad=999, fecha=datetime.utcnow(),
            usuario_id=self.admin.id, motivo="Entrada de Palmetto"))
        self.db.commit()
        self.crear_movimiento(TipoMovInvEnum.salida, 18, "Venta")

        data = self.ficha().json()
        self.assertEqual(len(data["movimientos"]), 1)
        self.assertEqual(data["movimientos"][0]["motivo"], "Venta")
        self.assertEqual(data["stock"]["stock_actual"], 1200.0)

    # ── Lotes: mismo estado que la trazabilidad ──────────────────────────────

    def test_lotes_conservan_el_estado_de_trazabilidad(self):
        from app.services.inventario import get_trazabilidad

        self.crear_lote(1000, 400, datetime.utcnow() - timedelta(days=2), numero="VENCIDO")
        self.crear_lote(2500, 2500, datetime.utcnow() + timedelta(days=60), numero="VIGENTE")

        data = self.ficha().json()
        por_numero = {l["numero_lote"]: l for l in data["lotes"]}
        self.assertEqual(por_numero["VENCIDO"]["estado"], "vencido")
        self.assertEqual(por_numero["VIGENTE"]["estado"], "activo")

        # Misma verdad que la pantalla de Lotes: no se reimplementa el cálculo.
        traza = {l["numero_lote"]: l for l in
                 get_trazabilidad(self.db, tienda_id=self.tienda.id, producto_id=self.cafe.id)}
        for numero, lote in por_numero.items():
            self.assertEqual(lote["estado"], traza[numero]["estado"], numero)
            self.assertEqual(lote["cantidad_restante"], traza[numero]["cantidad_restante"], numero)
            self.assertEqual(lote["consumido_pct"], traza[numero]["consumido_pct"], numero)

    def test_lote_agotado_reporta_estado_agotado(self):
        self.crear_lote(1000, 0, datetime.utcnow() + timedelta(days=60), numero="SECO")
        data = self.ficha().json()
        self.assertEqual(data["lotes"][0]["estado"], "agotado")
        self.assertEqual(data["lotes"][0]["consumido_pct"], 100.0)

    # ── Conteos ──────────────────────────────────────────────────────────────

    def test_conteos_muestran_sistema_real_y_diferencia(self):
        self.crear_conteo(TipoConteoEnum.cierre, 1250, 1200, dias_atras=0)

        conteo = self.ficha().json()["conteos"][0]
        self.assertEqual(conteo["tipo"], "cierre")
        self.assertEqual(conteo["cantidad_sistema"], 1250.0)
        self.assertEqual(conteo["cantidad_real"], 1200.0)
        self.assertEqual(conteo["diferencia"], -50.0)
        self.assertEqual(conteo["barista_nombre"], "Barista Uno")
        self.assertIsNotNone(conteo["turno_id"])
        self.assertIsNotNone(conteo["fecha"])

    def test_conteos_mas_recientes_primero_y_maximo_cinco(self):
        for i in range(7):
            self.crear_conteo(TipoConteoEnum.apertura, 100 + i, 100 + i, dias_atras=i)

        conteos = self.ficha().json()["conteos"]
        self.assertEqual(len(conteos), 5)
        # dias_atras=0 es el más reciente → cantidad_sistema 100.
        self.assertEqual(conteos[0]["cantidad_sistema"], 100.0)
        self.assertEqual(conteos[-1]["cantidad_sistema"], 104.0)

    # ── Movimientos ──────────────────────────────────────────────────────────

    def test_movimientos_mas_recientes_primero_y_maximo_veinte(self):
        for i in range(25):
            self.crear_movimiento(TipoMovInvEnum.salida, i + 1, f"Salida {i}", dias_atras=i)

        movs = self.ficha().json()["movimientos"]
        self.assertEqual(len(movs), 20)
        self.assertEqual(movs[0]["motivo"], "Salida 0")
        self.assertEqual(movs[0]["tipo"], "salida")
        self.assertEqual(movs[0]["cantidad"], 1.0)
        self.assertEqual(movs[-1]["motivo"], "Salida 19")

    def test_movimiento_reporta_la_barista_que_lo_registro(self):
        self.crear_movimiento(TipoMovInvEnum.ajuste, 1100, "Conteo físico",
                              barista_nombre="Barista Uno")
        mov = self.ficha().json()["movimientos"][0]
        self.assertEqual(mov["barista"], "Barista Uno")
        self.assertEqual(mov["tipo"], "ajuste")

    # ── Producto sin historial ───────────────────────────────────────────────

    def test_producto_sin_historial_devuelve_listas_vacias(self):
        r = self.ficha()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["lotes"], [])
        self.assertEqual(data["movimientos"], [])
        self.assertEqual(data["conteos"], [])
        self.assertEqual(data["stock"]["stock_actual"], 1200.0)

    # ── Receta: en los dos sentidos ──────────────────────────────────────────

    def test_receta_lista_los_insumos_del_producto(self):
        data = self.ficha(producto_id=self.americano.id).json()
        insumos = data["receta"]["insumos"]
        self.assertEqual(len(insumos), 1)
        self.assertEqual(insumos[0]["nombre"], "Café Excelso")
        self.assertEqual(insumos[0]["cantidad"], 18.0)
        self.assertEqual(insumos[0]["unidad_medida"], "gr")
        self.assertEqual(data["receta"]["usado_en"], [])

    def test_receta_lista_los_productos_que_consumen_el_insumo(self):
        data = self.ficha().json()
        usado_en = data["receta"]["usado_en"]
        self.assertEqual(len(usado_en), 1)
        self.assertEqual(usado_en[0]["nombre"], "Americano")
        self.assertEqual(usado_en[0]["cantidad"], 18.0)
        self.assertEqual(data["receta"]["insumos"], [])

    # ── Permisos y errores ───────────────────────────────────────────────────

    def test_barista_no_accede_a_la_ficha(self):
        self.set_current_user(self.barista)
        r = self.ficha()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"], "Se requiere rol admin")

    def test_admin_lee_la_ficha_de_cualquier_sede(self):
        # ensure_tienda_access deja pasar SIEMPRE al admin (deps.py:110-117): el
        # admin es global en este sistema. Igual que el vecino /lotes/{t}/{p}.
        self.db.add(Inventario(producto_id=self.cafe.id, tienda_id=self.otra_tienda.id,
                               stock_actual=77.0, stock_minimo=10.0))
        self.db.commit()
        r = self.ficha(tienda_id=self.otra_tienda.id)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["stock"]["stock_actual"], 77.0)

    def test_sin_fila_de_inventario_para_esa_sede_404(self):
        r = self.ficha(tienda_id=self.otra_tienda.id)
        self.assertEqual(r.status_code, 404)

    def test_producto_inexistente_404(self):
        r = self.ficha(producto_id=99999)
        self.assertEqual(r.status_code, 404)

    def test_tienda_id_es_obligatorio(self):
        r = self.client.get(f"/api/v1/inventario/producto/{self.cafe.id}/ficha")
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
