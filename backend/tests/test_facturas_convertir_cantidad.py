"""POST /facturas/convertir-cantidad: expone la conversión determinística de
_convertir_cantidad (factura_ocr) para los renglones PENDIENTES del escaneo.

Un renglón sin match llega al form con la cantidad en la unidad de la FACTURA
(kg/lt/caja); al asignarle producto, el front pide acá la conversión a la
unidad del inventario — la MISMA función pura que ya usan los renglones
matcheados server-side. Regla de oro: nunca se adivina una cantidad — lo
dudoso devuelve cantidad null + advertencia y la barista digita.
"""
import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import CategoriaProductoEnum, Producto, RolEnum, Tienda, Usuario
from app.routers import facturas as facturas_router


class ConvertirCantidadEndpointTest(unittest.TestCase):
    """sqlite temporal + router real de facturas (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        # Admin: require_barista_en_turno lo exime (no necesita turno abierto).
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()

        self.cafe = self._producto("Café alta tostión", unidad="gr")               # granel sin cpe
        self.leche = self._producto("Leche entera", unidad="ml", cpe=1100)         # granel con empaque
        self.croissant = self._producto("Croissant", unidad="unidad")              # por unidades
        self.pulpa = self._producto("Pulpa de fruta", unidad="und", cpe=10)        # contable con empaque

        app = FastAPI(title="Test convertir-cantidad")
        app.include_router(facturas_router.router, prefix="/api/v1")
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

    def _producto(self, nombre, unidad="gr", cpe=None):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, contenido_por_empaque=cpe,
                     precio_venta=0, controla_stock=True)
        self.db.add(p)
        self.db.commit()
        return p

    def _post(self, producto_id, cantidad, unidad):
        return self.client.post("/api/v1/facturas/convertir-cantidad",
                                json={"producto_id": producto_id,
                                      "cantidad": cantidad, "unidad": unidad})

    def test_kg_a_gramos(self):
        r = self._post(self.cafe.id, 2, "KG")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["cantidad"], 2000.0)
        self.assertFalse(body["en_empaques"])
        self.assertIsNone(body["advertencia"])

    def test_unidad_desconocida_no_adivina(self):
        # Granel SIN contenido_por_empaque + unidad irreconocible: cantidad null
        # y advertencia — jamás se inventa una cifra.
        r = self._post(self.cafe.id, 2, "arrobas")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsNone(body["cantidad"])
        self.assertFalse(body["en_empaques"])
        self.assertIsNotNone(body["advertencia"])

    def test_cajas_de_granel_en_empaques(self):
        # 2 "cajas" de un granel con empaque configurado → nº de empaques
        # (en_empaques=True: el backend multiplica por cpe al registrar).
        r = self._post(self.leche.id, 2, "cajas")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["cantidad"], 2.0)
        self.assertTrue(body["en_empaques"])

    def test_conteo_implausible_de_empaques_no_adivina(self):
        # >_MAX_EMPAQUES_PLAUSIBLE sin unidad clara: casi seguro son gr/ml —
        # cantidad null + advertencia, que la barista digite.
        r = self._post(self.leche.id, 3500, "")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsNone(body["cantidad"])
        self.assertIsNotNone(body["advertencia"])

    def test_unidades_de_producto_por_unidad(self):
        r = self._post(self.croissant.id, 6, "und")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["cantidad"], 6.0)
        self.assertFalse(body["en_empaques"])
        self.assertIsNone(body["advertencia"])

    def test_unidades_de_contable_con_empaque_asume_empaques(self):
        # "2 und" de pulpa (bolsa x10): se asumen EMPAQUES (el backend
        # multiplica por cpe al registrar) — siempre con advertencia, porque en
        # un contable "und" también podría ser la unidad final del inventario.
        r = self._post(self.pulpa.id, 2, "und")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["cantidad"], 2.0)
        self.assertTrue(body["en_empaques"])
        self.assertIsNotNone(body["advertencia"])

    def test_producto_inexistente_404(self):
        r = self._post(99999, 2, "kg")
        self.assertEqual(r.status_code, 404)

    def test_requiere_autenticacion(self):
        # Sin token (sin override de get_current_user) el bearer rechaza.
        self.app.dependency_overrides.pop(get_current_user)
        r = self._post(self.cafe.id, 2, "kg")
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
