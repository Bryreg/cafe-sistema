"""registrar_preparacion es idempotente: una misma idempotency_key aplicada dos
veces (doble tap, reintento de red) descuenta insumos y suma rendimiento UNA sola
vez. Es la red de seguridad del servidor contra el doble-submit."""
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, Producto, ProductoInsumo, Inventario, RolEnum, CategoriaProductoEnum,
)
from app.services import inventario as svc


class PreparacionIdempotenteTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t = Tienda(nombre="Palmetto", direccion="x")
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        # Insumo de la receta
        self.azucar = Producto(nombre="Azúcar a Granel", categoria=CategoriaProductoEnum.insumo,
                               unidad_medida="gr", controla_stock=True)
        self.db.add(self.azucar)
        self.db.flush()
        # Preparable: controla stock, sin precio de venta, con rendimiento por tanda
        self.mezcla = Producto(nombre="Mezcla Granizado", categoria=CategoriaProductoEnum.insumo,
                               unidad_medida="gr", controla_stock=True,
                               precio_venta=0, contenido_por_unidad=2820)
        self.db.add(self.mezcla)
        self.db.flush()
        self.db.add(ProductoInsumo(producto_id=self.mezcla.id, insumo_id=self.azucar.id, cantidad=360))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _inv(self, pid, stock):
        self.db.add(Inventario(producto_id=pid, tienda_id=self.t.id, stock_actual=stock))
        self.db.commit()

    def _stk(self, pid):
        r = self.db.query(Inventario).filter_by(producto_id=pid, tienda_id=self.t.id).first()
        return r.stock_actual if r else None

    def test_misma_llave_aplica_una_sola_vez(self):
        self._inv(self.azucar.id, 1000)
        self._inv(self.mezcla.id, 0)
        r1 = svc.registrar_preparacion(self.db, self.mezcla.id, self.t.id, 2, self.admin.id,
                                       idempotency_key="doble-tap-abc")
        self.assertFalse(r1.get("duplicada"))
        self.assertEqual(self._stk(self.azucar.id), 280)    # 1000 - 360*2
        self.assertEqual(self._stk(self.mezcla.id), 5640)   # 0 + 2820*2

        # Segundo disparo con la MISMA llave: no re-aplica nada.
        r2 = svc.registrar_preparacion(self.db, self.mezcla.id, self.t.id, 2, self.admin.id,
                                       idempotency_key="doble-tap-abc")
        self.assertTrue(r2.get("duplicada"))
        self.assertEqual(self._stk(self.azucar.id), 280)    # sin cambios
        self.assertEqual(self._stk(self.mezcla.id), 5640)   # sin cambios

    def test_llaves_distintas_aplican_dos_veces(self):
        self._inv(self.azucar.id, 1000)
        self._inv(self.mezcla.id, 0)
        svc.registrar_preparacion(self.db, self.mezcla.id, self.t.id, 1, self.admin.id, idempotency_key="k1")
        svc.registrar_preparacion(self.db, self.mezcla.id, self.t.id, 1, self.admin.id, idempotency_key="k2")
        self.assertEqual(self._stk(self.azucar.id), 280)    # 1000 - 360 - 360
        self.assertEqual(self._stk(self.mezcla.id), 5640)   # 0 + 2820 + 2820

    def test_sin_llave_es_backward_compatible(self):
        self._inv(self.azucar.id, 1000)
        self._inv(self.mezcla.id, 0)
        svc.registrar_preparacion(self.db, self.mezcla.id, self.t.id, 1, self.admin.id)
        svc.registrar_preparacion(self.db, self.mezcla.id, self.t.id, 1, self.admin.id)
        self.assertEqual(self._stk(self.azucar.id), 280)    # sin llave = comportamiento previo
        self.assertEqual(self._stk(self.mezcla.id), 5640)


if __name__ == "__main__":
    unittest.main()
