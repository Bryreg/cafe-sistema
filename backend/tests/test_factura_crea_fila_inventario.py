"""crear_factura debe poder recibir un producto que la sede aún no tiene en
inventario: crea la fila (como la recepción de mercancía) en vez de tirar
'Producto no encontrado en inventario de esta tienda'."""
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, Producto, Inventario, RolEnum, CategoriaProductoEnum,
)
from app.services import facturas as fac


class FacturaCreaFilaTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t1 = Tienda(nombre="Palmetto", direccion="x")
        self.db.add(self.t1)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        # Producto que la sede AÚN NO tiene en inventario (sin fila Inventario).
        self.prod = Producto(nombre="Cafe Libra Medium 500g", categoria=CategoriaProductoEnum.bebida,
                             unidad_medida="unidad", controla_stock=True)
        self.db.add(self.prod)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_factura_crea_fila_si_falta(self):
        self.assertIsNone(self.db.query(Inventario).filter_by(
            producto_id=self.prod.id, tienda_id=self.t1.id).first())
        data = SimpleNamespace(
            tipo_pago="credito",   # crédito: sin egreso de caja (no requiere turno)
            items=[SimpleNamespace(producto_id=self.prod.id, cantidad=6,
                                   precio_unitario=1000, numero_lote="L1",
                                   fecha_vencimiento=None)],
            valor_total=6000, tienda_id=self.t1.id, proveedor="Cafex coop",
            numero_factura="9080", numero_lote=None, fecha_recibido=date.today(),
        )
        fac.crear_factura(self.db, data, None, self.admin.id)

        inv = self.db.query(Inventario).filter_by(
            producto_id=self.prod.id, tienda_id=self.t1.id).first()
        self.assertIsNotNone(inv)          # fila creada
        self.assertEqual(inv.stock_actual, 6)  # entrada aplicada


if __name__ == "__main__":
    unittest.main()
