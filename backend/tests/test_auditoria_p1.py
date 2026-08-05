"""Fixes P1 de la auditoría de inventario: conversión empaques→gramos en facturas,
guard anti-unidades, y bloqueo del atajo 'Todo coincide' en conteos."""
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, Producto, Inventario, RolEnum, CategoriaProductoEnum,
)
from app.services import facturas as fac
from app.services import conteos as cont


class AuditoriaP1Test(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        # Licor en gramos con empaque de 1000 (botella)
        self.licor = Producto(nombre="Licor Baileys x1000ml", categoria=CategoriaProductoEnum.insumo,
                              unidad_medida="gr", controla_stock=True, contenido_por_empaque=1000)
        self.db.add(self.licor)
        self.db.flush()
        self.db.add(Inventario(producto_id=self.licor.id, tienda_id=self.t.id, stock_actual=0))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _data(self, cantidad, en_empaques):
        return SimpleNamespace(
            tipo_pago="credito",
            items=[SimpleNamespace(producto_id=self.licor.id, cantidad=cantidad,
                                   precio_unitario=None, numero_lote=None,
                                   fecha_vencimiento=None, en_empaques=en_empaques)],
            valor_total=100000, tienda_id=self.t.id, proveedor="Altipal",
            numero_factura="F1", numero_lote=None, fecha_recibido=date.today(),
        )

    def _stock(self):
        return self.db.query(Inventario).filter_by(
            producto_id=self.licor.id, tienda_id=self.t.id).first().stock_actual

    def test_empaques_convierte_a_gramos(self):
        fac.crear_factura(self.db, self._data(2, True), None, self.admin.id)
        self.assertEqual(self._stock(), 2000)   # 2 botellas × 1000

    def test_guard_rechaza_unidades_en_producto_granel(self):
        with self.assertRaises(HTTPException) as ctx:
            fac.crear_factura(self.db, self._data(2, False), None, self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("empaques", ctx.exception.detail.lower())

    def test_gramos_reales_pasan_sin_conversion(self):
        fac.crear_factura(self.db, self._data(1500, False), None, self.admin.id)
        self.assertEqual(self._stock(), 1500)

    def test_empaques_implausibles_se_rechazan_en_el_servidor(self):
        # en_empaques llega del cliente y multiplica stock real. El tope de 50 vivía
        # SOLO en la ruta del escáner: un payload armado a mano entraba sin límite
        # (50 "botellas" × 1000 = 50.000 gr de golpe). Ahora el servidor lo corta.
        with self.assertRaises(HTTPException) as ctx:
            fac.crear_factura(self.db, self._data(50, True), None, self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("rara", ctx.exception.detail.lower())
        self.assertEqual(self._stock(), 0)   # no escribió nada

    def test_empaques_justo_bajo_el_tope_pasan(self):
        fac.crear_factura(self.db, self._data(49, True), None, self.admin.id)
        self.assertEqual(self._stock(), 49000)

    def test_conteo_rechaza_es_atajo(self):
        with self.assertRaises(HTTPException) as ctx:
            cont.registrar_conteo(self.db, self.t.id, "cierre",
                                  [{"producto_id": self.licor.id, "cantidad_real": 5}],
                                  self.admin.id, es_atajo=True)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("atajo", ctx.exception.detail.lower())


if __name__ == "__main__":
    unittest.main()
