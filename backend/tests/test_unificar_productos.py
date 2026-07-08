"""Unificar productos duplicados: mueve stock positivo al keeper, descarta
negativos fantasma, archiva el duplicado. Con dry_run no escribe nada."""
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


class UnificarProductosTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t1 = Tienda(nombre="Vida", direccion="x")
        self.t2 = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.t1, self.t2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.keeper = Producto(nombre="Bolsa Kraft", categoria=CategoriaProductoEnum.insumo,
                               unidad_medida="und", controla_stock=True, incluir_en_conteo=True)
        self.dup = Producto(nombre="BOLSA MEDIUM KRAFT", categoria=CategoriaProductoEnum.insumo,
                            unidad_medida="und", controla_stock=True, incluir_en_conteo=True,
                            grupo_conteo="desechables")
        self.db.add_all([self.keeper, self.dup])
        self.db.flush()
        # keeper: Vida 100. dup: Vida 8 (positivo a mover), Palmetto -5 (fantasma a descartar).
        self.db.add_all([
            Inventario(producto_id=self.keeper.id, tienda_id=self.t1.id, stock_actual=100),
            Inventario(producto_id=self.dup.id, tienda_id=self.t1.id, stock_actual=8),
            Inventario(producto_id=self.dup.id, tienda_id=self.t2.id, stock_actual=-5),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _stk(self, pid, tid):
        r = self.db.query(Inventario).filter_by(producto_id=pid, tienda_id=tid).first()
        return r.stock_actual if r else None

    def test_dry_run_no_escribe(self):
        out = svc.unificar_productos(self.db, self.keeper.id, [self.dup.id], self.admin.id, dry_run=True)
        self.assertTrue(out["dry_run"])
        self.assertEqual(self._stk(self.keeper.id, self.t1.id), 100)   # sin cambios
        self.assertEqual(self._stk(self.dup.id, self.t1.id), 8)
        self.db.refresh(self.dup)
        self.assertTrue(self.dup.incluir_en_conteo)                    # todavía activo

    def test_ejecuta_mueve_descarta_archiva(self):
        svc.unificar_productos(self.db, self.keeper.id, [self.dup.id], self.admin.id, dry_run=False)
        self.assertEqual(self._stk(self.keeper.id, self.t1.id), 108)   # 100 + 8 movidos
        self.assertEqual(self._stk(self.dup.id, self.t1.id), 0)        # positivo movido → 0
        self.assertEqual(self._stk(self.dup.id, self.t2.id), 0)        # negativo descartado → 0
        self.assertIsNone(self._stk(self.keeper.id, self.t2.id))       # keeper NO recibe fila por el negativo
        self.db.refresh(self.dup)
        self.assertFalse(self.dup.incluir_en_conteo)                   # archivado
        self.assertFalse(self.dup.controla_stock)
        self.assertIsNone(self.dup.grupo_conteo)                       # fuera del bucket desechables

    def test_keeper_en_archivados_falla(self):
        with self.assertRaises(Exception):
            svc.unificar_productos(self.db, self.keeper.id, [self.keeper.id], self.admin.id, dry_run=False)


if __name__ == "__main__":
    unittest.main()
