"""Pastelería «por impulsar», AGRUPADA POR PRODUCTO.

La tarjeta del panel listaba un renglón por LOTE: «Omelette 6 u.», «Omelette
2 u.», «Omelette 1 unidad»… el mismo producto tres veces y ningún total. El
dueño no quiere adivinar la suma en la cabeza; quiere una línea por producto que
diga cuánto hay EN TOTAL y, dentro de eso, cuánto queda del lote más viejo (lo
que hay que empujar primero, FIFO) y del más nuevo.

Este endpoint (`/inventario/pasteleria-impulso-resumen/{tienda}`) consolida por
producto. Lo que fijan estos tests:

  1. Dos lotes del mismo producto se funden en UN renglón con el total y el
     detalle del más viejo y el más nuevo (no dos renglones).
  2. El «total» y el «lote más nuevo» cuentan TODOS los lotes con stock —también
     un lote fresco de hoy—, no solo los que ya pasaron la ventana de rotación.
     El producto entra a la lista por tener un lote viejo, pero el total refleja
     la bodega completa.
  3. Un producto cuyo lote más viejo NO llega a 3 días no aparece: no hay nada
     por impulsar todavía.
  4. `urgente` se prende a los 5+ días del lote más viejo (pasó la ventana).
  5. Solo pastelería: otras categorías no entran aunque tengan lotes viejos.
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
from app.models.models import (CategoriaProductoEnum, LoteInventario, Producto,
                               RolEnum, Tienda, Usuario)
from app.routers import inventario as inventario_router


class ImpulsoResumenBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="Sede Vida", activa=True)
        self.palmetto = Tienda(nombre="Palmetto", direccion="Sede Palmetto", activa=True)
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()

        app = FastAPI(title="Test pastelería impulso resumen")
        app.include_router(inventario_router.router, prefix="/api/v1")
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

    # ── Fixtures ──────────────────────────────────────────────────────────────
    def producto(self, nombre, categoria=CategoriaProductoEnum.pasteleria):
        p = Producto(nombre=nombre, categoria=categoria, unidad_medida="und",
                     controla_stock=True, precio_venta=0.0)
        self.db.add(p)
        self.db.flush()
        self.db.commit()
        return p

    def lote(self, producto, cantidad, *, dias, tienda=None):
        """Un lote con `cantidad` restante que entró hace `dias` días."""
        l = LoteInventario(
            producto_id=producto.id,
            tienda_id=(tienda or self.vida).id,
            cantidad_inicial=cantidad,
            cantidad_restante=cantidad,
            fecha_entrada=datetime.utcnow() - timedelta(days=dias, hours=1),
            usuario_id=self.admin.id,
        )
        self.db.add(l)
        self.db.commit()
        return l

    def get(self, tienda=None):
        r = self.client.get(
            f"/api/v1/inventario/pasteleria-impulso-resumen/{(tienda or self.vida).id}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def fila(self, data, nombre):
        for f in data:
            if f["producto_nombre"] == nombre:
                return f
        return None


class ResumenTest(ImpulsoResumenBase):

    def test_dos_lotes_del_mismo_producto_son_un_renglon(self):
        """Antes: dos renglones «Omelette». Ahora: uno, con total y el detalle
        del viejo y el nuevo."""
        om = self.producto("Omelette")
        self.lote(om, 6, dias=5)     # viejo
        self.lote(om, 1, dias=3)     # nuevo

        data = self.get()
        omeletes = [f for f in data if f["producto_nombre"] == "Omelette"]
        self.assertEqual(len(omeletes), 1)
        f = omeletes[0]
        self.assertEqual(f["total_unidades"], 7)
        self.assertEqual(f["n_lotes"], 2)
        self.assertEqual(f["lote_viejo"]["cantidad"], 6)
        self.assertEqual(f["lote_viejo"]["dias"], 5)
        self.assertEqual(f["lote_nuevo"]["cantidad"], 1)
        self.assertEqual(f["lote_nuevo"]["dias"], 3)

    def test_total_y_nuevo_cuentan_el_lote_fresco(self):
        """El producto entra por tener un lote viejo, pero un lote FRESCO de hoy
        también suma al total y es el «más nuevo». Si no, el total mentiría."""
        torta = self.producto("Torta Chocolate")
        self.lote(torta, 4, dias=6)     # viejo → dispara el impulso
        self.lote(torta, 10, dias=0)    # fresco de hoy

        f = self.fila(self.get(), "Torta Chocolate")
        self.assertIsNotNone(f)
        self.assertEqual(f["total_unidades"], 14)
        self.assertEqual(f["lote_viejo"]["dias"], 6)
        self.assertEqual(f["lote_nuevo"]["cantidad"], 10)
        self.assertEqual(f["lote_nuevo"]["dias"], 0)
        self.assertTrue(f["urgente"])   # el viejo pasó los 5 días

    def test_producto_sin_lote_viejo_no_aparece(self):
        """Si el lote más viejo del producto no llega a 3 días, no hay nada por
        impulsar todavía: el producto no entra a la lista."""
        fresca = self.producto("Almojábana")
        self.lote(fresca, 42, dias=1)
        self.lote(fresca, 20, dias=0)

        self.assertIsNone(self.fila(self.get(), "Almojábana"))

    def test_urgente_a_los_cinco_dias(self):
        """3-4 días: se muestra pero no urgente. 5+: urgente (ya pasó la
        ventana de rotación)."""
        casi = self.producto("Croissant")
        self.lote(casi, 5, dias=4)
        f = self.fila(self.get(), "Croissant")
        self.assertIsNotNone(f)
        self.assertFalse(f["urgente"])

    def test_solo_pasteleria(self):
        """Un insumo viejo no es «pastelería por impulsar» aunque lleve semanas."""
        cafe = self.producto("Café en grano", categoria=CategoriaProductoEnum.insumo)
        self.lote(cafe, 100, dias=30)
        self.assertIsNone(self.fila(self.get(), "Café en grano"))

    def test_por_sede(self):
        """El resumen es de UNA sede: un lote viejo en Palmetto no aparece en
        el resumen de Vida."""
        om = self.producto("Omelette")
        self.lote(om, 6, dias=5, tienda=self.palmetto)
        self.assertIsNone(self.fila(self.get(self.vida), "Omelette"))
        self.assertIsNotNone(self.fila(self.get(self.palmetto), "Omelette"))
