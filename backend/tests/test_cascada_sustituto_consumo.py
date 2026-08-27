"""Un regalo no se hace con otra leche que una venta.

El sistema NO SABE con qué leche se preparó una bebida, y ese es exactamente el
motivo de que exista la cascada al sustituto: cuando la leche entera se acaba, la
barista sigue haciendo cappuccinos con la deslactosada, y el descuento tiene que
seguirla. `consumir_insumo` hace eso, y el POS lo usa.

`registrar_merma` no. Descontaba la receta con `registrar_movimiento` directo —
con un comentario que afirmaba que era «el mismo mecanismo que la venta POS»,
que es justo lo que no era. La consecuencia, medida en producción:

  · Cappuccino VENDIDO con la entera en cero → sale de la deslactosada. Bien.
  · Cappuccino REGALADO con la entera en cero → sale de la entera igual, la cruza
    por debajo de cero y sigue cavando.

La leche entera de Palmetto llegó a −4 und así. Los 16 movimientos que la
hundieron en agosto son TODOS de consumo —«DESCARGA DE TARJETA VIRTUAL»,
«Consumo de LUISA», «Consumo de MANUEL»— ni una sola venta. Y no es casualidad:
una vez en negativo el POS ya no la tocaba, porque la cascada mandaba todo a la
deslactosada. Solo el camino sin cascada seguía restando.

Lo que fijan estos tests:

- EL CONSUMO CAE AL SUSTITUTO, igual que la venta.
- NO SE CRUZA EL CERO por la puerta del consumo.
- LA MERMA DE UN INSUMO EN SÍ NO CASCADEA. Si se cae al piso una bolsa de leche
  entera, se perdió LA ENTERA: reemplazarla por deslactosada sería inventar que
  se perdió algo que no se perdió. La cascada es para las bebidas, donde no se
  sabe qué se usó; no para el producto físico, donde sí se sabe.
"""
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CajaTurno, CategoriaProductoEnum, EstadoTurnoEnum,
                               Inventario, MovimientoInventario, Producto,
                               ProductoInsumo, RolEnum, Tienda, Usuario)
from app.services import mermas as merma_svc


class CascadaConsumoBase(unittest.TestCase):
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
        self.db.flush()
        self.db.add(CajaTurno(tienda_id=self.t.id, usuario_apertura_id=self.admin.id,
                              estado=EstadoTurnoEnum.abierto, base_real=0))
        self.db.commit()

        # Las dos leches, con la cascada configurada como en producción.
        self.desl = self.insumo("Leche Deslactosada", stock=50)
        self.entera = self.insumo("Leche Entera", stock=0.1, sustituto=self.desl)
        # Un cappuccino: no tiene stock propio, se descuenta por receta.
        self.cappu = self.bebida("Cappuccino Tradicional Medium",
                                 [(self.entera, 0.191)])

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def insumo(self, nombre, stock, sustituto=None, unidad="und"):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=True, precio_venta=0.0,
                     sustituto_id=(sustituto.id if sustituto else None))
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.t.id,
                               stock_actual=stock, stock_minimo=0))
        self.db.commit()
        return p

    def bebida(self, nombre, receta):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.bebida,
                     unidad_medida="und", controla_stock=False, precio_venta=8000)
        self.db.add(p)
        self.db.flush()
        for insumo, cant in receta:
            self.db.add(ProductoInsumo(producto_id=p.id, insumo_id=insumo.id, cantidad=cant))
        self.db.commit()
        return p

    def stock(self, p):
        return self.db.query(Inventario).filter_by(
            producto_id=p.id, tienda_id=self.t.id).first().stock_actual

    def regalar(self, bebida, cantidad=1, tipo="consumo"):
        return merma_svc.registrar_merma(
            self.db, self.t.id, bebida.id, cantidad,
            motivo="DESCARGA DE TARJETA VIRTUAL", usuario_id=self.admin.id, tipo=tipo)


class ElConsumoCascadeaTest(CascadaConsumoBase):

    def test_un_cappuccino_regalado_cae_al_sustituto_cuando_no_alcanza(self):
        # Queda 0,1 und de entera y el cappuccino pide 0,191.
        self.regalar(self.cappu)

        # La entera se vacía hasta CERO, nunca por debajo.
        self.assertAlmostEqual(self.stock(self.entera), 0.0, places=4)
        # Y el resto sale de la deslactosada, que es con la que realmente se hizo.
        self.assertAlmostEqual(self.stock(self.desl), 50 - (0.191 - 0.1), places=4)

    def test_con_la_entera_ya_en_cero_el_regalo_no_la_toca(self):
        # Este es el caso que hundió la leche de Palmetto: 16 consumos seguidos
        # con la entera agotada.
        self.db.query(Inventario).filter_by(
            producto_id=self.entera.id, tienda_id=self.t.id).update({"stock_actual": 0})
        self.db.commit()

        for _ in range(16):
            self.regalar(self.cappu)

        self.assertAlmostEqual(self.stock(self.entera), 0.0, places=4)
        self.assertAlmostEqual(self.stock(self.desl), 50 - 16 * 0.191, places=4)

    def test_el_movimiento_del_sustituto_dice_de_dónde_vino(self):
        self.regalar(self.cappu)
        movs = self.db.query(MovimientoInventario).filter(
            MovimientoInventario.producto_id == self.desl.id).all()
        self.assertEqual(len(movs), 1)
        # «(reserva de #N)» es lo que deja rastro de que fue una cascada y no un
        # descuento directo: sin eso, la deslactosada aparecería saliendo sola.
        self.assertIn(f"(reserva de #{self.entera.id})", movs[0].motivo)
        self.assertIn("DESCARGA DE TARJETA VIRTUAL", movs[0].motivo)

    def test_si_alcanza_no_cascadea(self):
        self.db.query(Inventario).filter_by(
            producto_id=self.entera.id, tienda_id=self.t.id).update({"stock_actual": 10})
        self.db.commit()
        self.regalar(self.cappu)

        self.assertAlmostEqual(self.stock(self.entera), 10 - 0.191, places=4)
        self.assertEqual(self.stock(self.desl), 50)


class LaMermaDelInsumoNoCascadeaTest(CascadaConsumoBase):
    """La cascada es para las bebidas, no para el producto físico."""

    def test_botar_una_bolsa_de_leche_entera_no_saca_deslactosada(self):
        # Si se cae al piso una bolsa de entera, se perdió LA ENTERA. Sacar
        # deslactosada en su lugar sería inventar una pérdida que no ocurrió.
        self.db.query(Inventario).filter_by(
            producto_id=self.entera.id, tienda_id=self.t.id).update({"stock_actual": 3})
        self.db.commit()
        merma_svc.registrar_merma(self.db, self.t.id, self.entera.id, 1,
                                  motivo="se cayó al piso", usuario_id=self.admin.id,
                                  tipo="daño")
        self.assertEqual(self.stock(self.entera), 2)
        self.assertEqual(self.stock(self.desl), 50)


class LaVentaYElRegaloHacenLoMismoTest(CascadaConsumoBase):
    """La prueba de que dejaron de ser dos caminos distintos."""

    def test_regalar_deja_el_mismo_stock_que_vender(self):
        from app.services import inventario as inv_svc
        antes = (self.stock(self.entera), self.stock(self.desl))

        # El camino del POS, tal cual lo llama pos.py.
        inv_svc.consumir_insumo(self.db, self.entera.id, self.t.id, 0.191,
                                "Venta POS — insumo de Cappuccino Tradicional Medium",
                                self.admin.id)
        self.db.commit()
        por_venta = (self.stock(self.entera), self.stock(self.desl))

        # Volver al principio y hacer el mismo cappuccino, pero regalado.
        self.db.query(Inventario).filter_by(
            producto_id=self.entera.id, tienda_id=self.t.id).update({"stock_actual": antes[0]})
        self.db.query(Inventario).filter_by(
            producto_id=self.desl.id, tienda_id=self.t.id).update({"stock_actual": antes[1]})
        self.db.commit()
        self.regalar(self.cappu)

        self.assertAlmostEqual(self.stock(self.entera), por_venta[0], places=4)
        self.assertAlmostEqual(self.stock(self.desl), por_venta[1], places=4)


if __name__ == "__main__":
    unittest.main()
