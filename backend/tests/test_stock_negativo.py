"""Menos que cero no es «se acabó»: es la prueba de que falta registrar algo.

En una nevera no existe menos que nada. Si el sistema llega ahí, solo puede ser
por una de dos cosas, y ninguna se arregla pidiendo más mercancía:

  · entró algo que nadie registró, o
  · una receta descuenta un insumo que no es.

El sistema los venía tratando igual. `clasificar_estado` mete el cero y el
negativo en el mismo balde —«agotado»— y el aviso decía «Producto X en nivel
agotado», que se lee como «se acabó, pedilo». Sirve para decidir un pedido y es
inútil para encontrar un error.

Lo que costó: el helado de chocolate de Palmetto estuvo en −400 gr desde julio.
Tres recetas —Malteada Chocolate, Moka y Moka Amaretto— descontaban 200 gr de un
helado que NUNCA se compró: cero facturas desde mayo, en ninguna de las dos
sedes; Mimos, el proveedor del helado, factura solo vainilla y salsas. Las
malteadas se hacen con vainilla y la salsa que ya estaba en la receta. Tres meses
en rojo, nadie enterado, y el helado que sí salía del congelador —la vainilla—
no se descontaba nunca.
"""
import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CategoriaProductoEnum, Inventario, Notificacion,
                               Producto, RolEnum, Tienda, Usuario)
from app.services import inventario as inv_svc
from app.services import notif_reglas


class StockNegativoBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.t = Tienda(nombre="Palmetto", direccion="x", activa=True)
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def producto(self, nombre, stock, minimo=0.0):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida="gr", controla_stock=True, precio_venta=0.0)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.t.id,
                               stock_actual=stock, stock_minimo=minimo))
        self.db.commit()
        return p

    def vender(self, producto, cantidad):
        """Una salida del POS: permite negativo, igual que `consumir_insumo`."""
        inv_svc.registrar_movimiento(
            self.db, producto.id, self.t.id, "salida", cantidad,
            motivo="Venta POS — insumo de Malteada Moka", usuario_id=self.admin.id,
            allow_negative=True)

    def avisos(self, tipo=None):
        q = self.db.query(Notificacion)
        if tipo:
            q = q.filter(Notificacion.tipo == tipo)
        return q.all()


class ElAvisoDistingueTest(StockNegativoBase):

    def test_cruzar_a_negativo_avisa_que_falta_registrar_algo(self):
        helado = self.producto("Helado Chocolate", stock=0)
        self.vender(helado, 200)

        negs = self.avisos("stock_negativo")
        self.assertEqual(len(negs), 1, "cruzar a negativo tiene que avisar")
        # El texto NO puede decir «agotado»: mandaría a pedir en vez de a buscar
        # el registro que falta.
        self.assertIn("menos que cero", negs[0].mensaje)
        self.assertIn("Helado Chocolate", negs[0].mensaje)
        self.assertNotIn("agotado", negs[0].mensaje.lower())
        # Y NO se dispara además el aviso de agotado: son dos cosas distintas y
        # mandar las dos deja al dueño eligiendo cuál creer.
        self.assertEqual(self.avisos("stock_agotado"), [])

    def test_quedar_exactamente_en_cero_sigue_siendo_agotado(self):
        # Cero SÍ es «se acabó»: es un estado normal del estante y se pide.
        cafe = self.producto("CAFE", stock=200)
        self.vender(cafe, 200)

        self.assertEqual(self.avisos("stock_negativo"), [])
        self.assertEqual(len(self.avisos("stock_agotado")), 1)

    def test_no_spamea_una_vez_por_venta(self):
        # Una malteada por hora durante un día no puede ser 12 avisos del mismo
        # insumo: el dedupe diario es lo que hace que el aviso se lea.
        helado = self.producto("Helado Chocolate", stock=0)
        for _ in range(5):
            self.vender(helado, 200)
        self.assertEqual(len(self.avisos("stock_negativo")), 1)

    def test_la_regla_existe_en_el_catalogo(self):
        # `disparar` no manda nada si el tipo no tiene regla. Sin esta entrada el
        # aviso se escribiría en el código y no saldría nunca — la peor
        # combinación posible: parece hecho y no avisa.
        r = notif_reglas.get_regla_efectiva(self.db, self.t.id, "stock_negativo")
        self.assertIsNotNone(r)
        self.assertTrue(r.activa)


class LaPantallaLoDiceTest(StockNegativoBase):
    """La bandera que la tabla de insumos y la ficha usan para pintarlo."""

    def test_la_fila_marca_el_negativo(self):
        from app.routers.inventario import _fila_insumo
        fila = _fila_insumo({"producto_id": 1, "producto_nombre": "Helado Chocolate",
                             "unidad_medida": "gr", "ventas": 1000.0,
                             "stock_esperado": -400.0}, None)
        self.assertTrue(fila["en_negativo"])
        self.assertEqual(fila["queda"], -400.0)

    def test_cero_no_es_negativo(self):
        from app.routers.inventario import _fila_insumo
        fila = _fila_insumo({"producto_id": 1, "producto_nombre": "CAFE",
                             "unidad_medida": "gr", "stock_esperado": 0.0}, None)
        self.assertFalse(fila["en_negativo"])


if __name__ == "__main__":
    unittest.main()
