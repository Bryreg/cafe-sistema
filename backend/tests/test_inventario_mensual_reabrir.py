"""Reabrir un conteo mensual cerrado por error: vuelve a en_proceso conservando
lo contado, limpia las diferencias del cierre prematuro y agrega al conteo los
productos con controla_stock creados después de iniciarlo (el conteo se congela
con el catálogo del momento de apertura)."""
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, Producto, Inventario, RolEnum, CategoriaProductoEnum,
)
from app.services import inventario_mensual as svc


class ReabrirMensualTest(unittest.TestCase):
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
        self.db.add(self.t1)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.prod = Producto(nombre="SERVILLETAS", categoria=CategoriaProductoEnum.insumo,
                             unidad_medida="und", controla_stock=True)
        self.db.add(self.prod)
        self.db.flush()
        self.db.add(Inventario(producto_id=self.prod.id, tienda_id=self.t1.id, stock_actual=10))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _producto_nuevo(self, nombre, stock):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida="und", controla_stock=True)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.t1.id, stock_actual=stock))
        self.db.commit()
        return p

    def test_reabrir_conserva_conteo_y_agrega_nuevos(self):
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        item_id = inv["items"][0]["id"]
        svc.guardar(self.db, inv["id"], [{"id": item_id, "cantidad_real": 8}])
        svc.cerrar(self.db, inv["id"], self.admin.id)
        # Producto creado DESPUÉS de iniciar (y cerrar) el conteo — el caso
        # COPA PAPEL 0,63 OZ del 31-jul.
        nuevo = self._producto_nuevo("COPA PAPEL 0,63 OZ", 200)

        out = svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)

        self.assertEqual(out["estado"], "en_proceso")
        self.assertIsNone(out["fecha_cierre"])
        self.assertEqual(out["valor_diferencia_total"], 0)
        por_pid = {i["producto_id"]: i for i in out["items"]}
        self.assertEqual(por_pid[self.prod.id]["cantidad_real"], 8)   # lo contado se conserva
        self.assertEqual(por_pid[self.prod.id]["diferencia"], 0)      # dif del cierre prematuro limpiada
        self.assertIn(nuevo.id, por_pid)                              # el producto nuevo entró
        self.assertEqual(por_pid[nuevo.id]["cantidad_sistema"], 200)  # sembrado con stock actual
        self.assertIsNone(por_pid[nuevo.id]["cantidad_real"])         # aún sin contar

    def test_reabrir_en_proceso_solo_agrega_faltantes(self):
        svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        nuevo = self._producto_nuevo("TENEDOR DESECHABLE X100", 5)

        out = svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)

        self.assertEqual(out["estado"], "en_proceso")
        pids = {i["producto_id"] for i in out["items"]}
        self.assertIn(nuevo.id, pids)
        self.assertEqual(len(pids), 2)

    def test_reabrir_sincroniza_unidad_y_sistema_del_producto_vivo(self):
        # El caso real del 31-jul: el conteo se abrió ANTES de la conversión a
        # gramos — quedó con unidad "botella", sistema en envases y conteos en
        # fracciones de envase (0.45). Al reabrir debe quedar en la unidad viva.
        salsa = Producto(nombre="Salsa Chocolate", categoria=CategoriaProductoEnum.insumo,
                         unidad_medida="botella", controla_stock=True)
        self.db.add(salsa)
        self.db.flush()
        inv_salsa = Inventario(producto_id=salsa.id, tienda_id=self.t1.id, stock_actual=2)
        self.db.add(inv_salsa)
        self.db.commit()

        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        por_pid = {i["producto_id"]: i for i in inv["items"]}
        svc.guardar(self.db, inv["id"], [
            {"id": por_pid[salsa.id]["id"], "cantidad_real": 0.45},   # fracción de botella
            {"id": por_pid[self.prod.id]["id"], "cantidad_real": 8},  # unidad sin cambio
        ])
        svc.cerrar(self.db, inv["id"], self.admin.id)

        # Conversión a gramos posterior a la apertura del conteo
        salsa.unidad_medida = "gr"
        inv_salsa.stock_actual = 3695
        self.db.commit()

        out = svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)

        por_pid = {i["producto_id"]: i for i in out["items"]}
        self.assertEqual(por_pid[salsa.id]["unidad_medida"], "gr")          # unidad viva
        self.assertEqual(por_pid[salsa.id]["cantidad_sistema"], 3695)      # sistema actual
        self.assertIsNone(por_pid[salsa.id]["cantidad_real"])              # 0.45 botellas no sirve en gr
        self.assertEqual(por_pid[self.prod.id]["cantidad_real"], 8)        # sin cambio de unidad: se conserva
        self.assertEqual(por_pid[self.prod.id]["cantidad_sistema"], 10)    # sistema refrescado (igual acá)

    def test_reabrir_sin_conteo_da_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            svc.reabrir(self.db, self.t1.id, 2026, 6, self.admin.id)


if __name__ == "__main__":
    unittest.main()
