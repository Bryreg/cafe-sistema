"""consumir_insumo con cascada al sustituto: descuenta el insumo hasta 0 y el
resto del sustituto (ej. leche entera → deslactosada)."""
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, Producto, Inventario, RolEnum, CategoriaProductoEnum,
)
from app.services import inventario as svc


class ConsumirInsumoSustitutoTest(unittest.TestCase):
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
        self.desl = Producto(nombre="Leche Deslactosada", categoria=CategoriaProductoEnum.insumo,
                             unidad_medida="und", controla_stock=True)
        self.db.add(self.desl)
        self.db.flush()
        self.entera = Producto(nombre="Leche Entera", categoria=CategoriaProductoEnum.insumo,
                               unidad_medida="und", controla_stock=True, sustituto_id=self.desl.id)
        self.db.add(self.entera)
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

    def test_entera_alcanza_no_toca_sustituto(self):
        self._inv(self.entera.id, 10)
        self._inv(self.desl.id, 10)
        svc.consumir_insumo(self.db, self.entera.id, self.t.id, 5, "venta", self.admin.id)
        self.db.commit()
        self.assertEqual(self._stk(self.entera.id), 5)
        self.assertEqual(self._stk(self.desl.id), 10)

    def test_entera_parcial_cascada_al_sustituto(self):
        self._inv(self.entera.id, 3)
        self._inv(self.desl.id, 10)
        svc.consumir_insumo(self.db, self.entera.id, self.t.id, 5, "venta", self.admin.id)
        self.db.commit()
        self.assertEqual(self._stk(self.entera.id), 0)   # 3 - 3 (hasta 0)
        self.assertEqual(self._stk(self.desl.id), 8)     # 10 - 2 (resto)

    def test_entera_agotada_todo_del_sustituto(self):
        self._inv(self.entera.id, 0)
        self._inv(self.desl.id, 10)
        svc.consumir_insumo(self.db, self.entera.id, self.t.id, 5, "venta", self.admin.id)
        self.db.commit()
        self.assertEqual(self._stk(self.entera.id), 0)   # no baja de 0
        self.assertEqual(self._stk(self.desl.id), 5)     # 10 - 5

    def test_sin_sustituto_salida_normal_negativa(self):
        self._inv(self.desl.id, 2)  # deslactosada NO tiene sustituto
        svc.consumir_insumo(self.db, self.desl.id, self.t.id, 5, "venta", self.admin.id)
        self.db.commit()
        self.assertEqual(self._stk(self.desl.id), -3)    # salida normal, va a negativo


if __name__ == "__main__":
    unittest.main()
