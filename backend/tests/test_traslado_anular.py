"""Anular/rehacer traslados entre sedes: reversa exacta del efecto en inventario."""
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, Producto, Inventario, Merma,
    RolEnum, CategoriaProductoEnum,
)
from app.services import mermas as svc


class TrasladoAnularTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t1 = Tienda(nombre="Origen", direccion="x")
        self.t2 = Tienda(nombre="Destino", direccion="y")
        self.db.add_all([self.t1, self.t2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.prod = Producto(nombre="Vaso", categoria=CategoriaProductoEnum.bebida,
                             unidad_medida="unidad", controla_stock=True)
        self.db.add(self.prod)
        self.db.flush()
        self.db.add_all([
            Inventario(producto_id=self.prod.id, tienda_id=self.t1.id, stock_actual=500),
            Inventario(producto_id=self.prod.id, tienda_id=self.t2.id, stock_actual=100),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _stock(self, tienda_id):
        return self.db.query(Inventario).filter_by(
            producto_id=self.prod.id, tienda_id=tienda_id).first().stock_actual

    def test_anular_recibido_revierte_ambas_sedes(self):
        m = svc.registrar_merma(self.db, self.t1.id, self.prod.id, 140, "t",
                                self.admin.id, tipo="traslado", tienda_destino_id=self.t2.id)
        self.assertEqual(self._stock(self.t1.id), 360)   # 500 - 140 (envío descontó origen)
        self.assertEqual(self._stock(self.t2.id), 100)   # destino intacto hasta recibir
        svc.recibir_traslado(self.db, m.id, self.t2.id, self.admin.id)
        self.assertEqual(self._stock(self.t2.id), 240)   # 100 + 140

        svc.anular_traslado(self.db, m.id, self.admin.id)
        self.assertEqual(self._stock(self.t1.id), 500)   # envío revertido
        self.assertEqual(self._stock(self.t2.id), 100)   # recibo revertido
        self.assertIsNone(self.db.query(Merma).filter_by(id=m.id).first())

    def test_anular_pendiente_solo_revierte_origen(self):
        m = svc.registrar_merma(self.db, self.t1.id, self.prod.id, 50, "t",
                                self.admin.id, tipo="traslado", tienda_destino_id=self.t2.id)
        self.assertEqual(self._stock(self.t1.id), 450)
        svc.anular_traslado(self.db, m.id, self.admin.id)
        self.assertEqual(self._stock(self.t1.id), 500)   # origen devuelto
        self.assertEqual(self._stock(self.t2.id), 100)   # destino nunca tocado

    def test_admin_traslado_permite_negativo(self):
        r = svc.registrar_merma(self.db, self.t1.id, self.prod.id, 600, "t",
                                self.admin.id, tipo="traslado", tienda_destino_id=self.t2.id,
                                confirmar=True, permitir_negativo=True)
        self.assertEqual(self._stock(self.t1.id), -100)  # 500 - 600, permitido
        svc.recibir_traslado(self.db, r.id, self.t2.id, self.admin.id)
        self.assertEqual(self._stock(self.t2.id), 700)   # 100 + 600

    def test_guard_bloquea_sin_permitir_negativo(self):
        with self.assertRaises(Exception):
            svc.registrar_merma(self.db, self.t1.id, self.prod.id, 600, "t",
                                self.admin.id, tipo="traslado", tienda_destino_id=self.t2.id)

    def test_anular_revierte_insumos_para_no_controla_stock(self):
        from app.models.models import ProductoInsumo
        # Bebida preparada SIN stock propio, con receta (2 de insumo por unidad).
        bebida = Producto(nombre="Granizado", categoria=CategoriaProductoEnum.bebida,
                          unidad_medida="unidad", controla_stock=False)
        insumo = Producto(nombre="Cafe insumo", categoria=CategoriaProductoEnum.bebida,
                          unidad_medida="g", controla_stock=True)
        self.db.add_all([bebida, insumo])
        self.db.flush()
        self.db.add(ProductoInsumo(producto_id=bebida.id, insumo_id=insumo.id, cantidad=2))
        self.db.add(Inventario(producto_id=insumo.id, tienda_id=self.t1.id, stock_actual=100))
        self.db.commit()

        m = svc.registrar_merma(self.db, self.t1.id, bebida.id, 3, "t", self.admin.id,
                                tipo="traslado", tienda_destino_id=self.t2.id)
        insumo_row = lambda: self.db.query(Inventario).filter_by(
            producto_id=insumo.id, tienda_id=self.t1.id).first().stock_actual
        self.assertEqual(insumo_row(), 94)   # 100 - 3*2 (envío descontó insumos)
        svc.recibir_traslado(self.db, m.id, self.t2.id, self.admin.id)

        svc.anular_traslado(self.db, m.id, self.admin.id)
        self.assertEqual(insumo_row(), 100)  # insumos del origen restaurados
        dest = self.db.query(Inventario).filter_by(
            producto_id=bebida.id, tienda_id=self.t2.id).first()
        self.assertEqual(dest.stock_actual, 0)  # recibo del destino revertido

    def test_permitir_negativo_crea_fila_origen_faltante(self):
        # Producto controla stock pero SIN fila de inventario en el origen.
        p2 = Producto(nombre="Antigrasa", categoria=CategoriaProductoEnum.bebida,
                      unidad_medida="unidad", controla_stock=True)
        self.db.add(p2)
        self.db.commit()
        self.assertIsNone(self.db.query(Inventario).filter_by(
            producto_id=p2.id, tienda_id=self.t1.id).first())
        svc.registrar_merma(self.db, self.t1.id, p2.id, 30, "t", self.admin.id,
                            tipo="traslado", tienda_destino_id=self.t2.id,
                            confirmar=True, permitir_negativo=True)
        fila = self.db.query(Inventario).filter_by(
            producto_id=p2.id, tienda_id=self.t1.id).first()
        self.assertIsNotNone(fila)
        self.assertEqual(fila.stock_actual, -30)   # 0 - 30


if __name__ == "__main__":
    unittest.main()
