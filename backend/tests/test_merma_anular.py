"""Anular una merma: devolver lo que descontó DE VERDAD, no lo que dice la receta.

Hasta ahora el sistema no tenía forma de deshacer una merma mal registrada. No
había endpoint (`/mermas/{id}/anular` solo aceptaba traslados) ni botón, así que
un doble toque en el formulario quedaba descontado para siempre y aparecía días
después como un faltante inexplicable en el conteo.

Pasó medido: el 21-sep en Palmetto una barista guardó cinco veces el mismo
consumo de «visita de los jueces» —2 mokaccinos + 2 cappuccinos cada vez—, 10
registros y 25 movimientos de inventario.

Y ese caso real trae la trampa que estos tests fijan: la receta del mokaccino
dice LECHE ENTERA, pero la entera de Palmetto estaba en cero, así que
`consumir_insumo` cascadeó y los 25 movimientos salieron de la DESLACTOSADA.
Una anulación que devolviera por receta le sumaría a la entera —que nunca se
tocó— y dejaría a la deslactosada corta para siempre: cambiaría el faltante de
lugar en vez de arreglarlo.

Lo que se fija acá:

- DEVUELVE DONDE SALIÓ, no donde dice la receta. Es el caso que motivó todo.
- CADA MERMA DEVUELVE LO SUYO. Cinco mermas idénticas no se pisan entre ellas:
  anular una devuelve una vez, y anular las cinco devuelve cinco veces — ni más
  (doble reversa) ni menos.
- EL PRODUCTO CON STOCK PROPIO vuelve a su valor anterior.
- UN TRASLADO sigue yendo por `anular_traslado`, que además deshace el recibo.
- LAS MERMAS VIEJAS (sin `merma_id` sellado) se emparejan por motivo y hora, que
  es lo que hace falta para los 10 registros que ya están en producción.
"""
import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    CategoriaProductoEnum, Inventario, Merma, MovimientoInventario, Producto,
    ProductoInsumo, RolEnum, Tienda, TipoMovInvEnum, Usuario,
)
from app.services import mermas as svc


class MermaAnularTest(unittest.TestCase):
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
        self.t2 = Tienda(nombre="Vida", direccion="y")
        self.db.add_all([self.t1, self.t2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()

        # Insumos: la entera tiene a la deslactosada como sustituto (igual que en
        # producción), más un insumo sin cascada para verificar el resto.
        self.deslactosada = Producto(nombre="Leche Deslactosada",
                                     categoria=CategoriaProductoEnum.insumo,
                                     unidad_medida="und", controla_stock=True)
        self.db.add(self.deslactosada)
        self.db.flush()
        self.entera = Producto(nombre="Leche Entera", categoria=CategoriaProductoEnum.insumo,
                               unidad_medida="und", controla_stock=True,
                               sustituto_id=self.deslactosada.id)
        self.salsa = Producto(nombre="Salsa Chocolate", categoria=CategoriaProductoEnum.insumo,
                              unidad_medida="gr", controla_stock=True)
        # Bebida preparada: no lleva stock propio, gasta su receta.
        self.bebida = Producto(nombre="Mokaccino Medium", categoria=CategoriaProductoEnum.bebida,
                               unidad_medida="und", controla_stock=False)
        # Producto de mostrador: lleva su propio stock.
        self.torta = Producto(nombre="Torta de Chocolate",
                              categoria=CategoriaProductoEnum.pasteleria,
                              unidad_medida="und", controla_stock=True)
        self.db.add_all([self.entera, self.salsa, self.bebida, self.torta])
        self.db.flush()
        self.db.add_all([
            ProductoInsumo(producto_id=self.bebida.id, insumo_id=self.entera.id, cantidad=0.2),
            ProductoInsumo(producto_id=self.bebida.id, insumo_id=self.salsa.id, cantidad=34),
        ])
        self.db.add_all([
            Inventario(producto_id=self.entera.id, tienda_id=self.t1.id, stock_actual=0),
            Inventario(producto_id=self.deslactosada.id, tienda_id=self.t1.id, stock_actual=10),
            Inventario(producto_id=self.salsa.id, tienda_id=self.t1.id, stock_actual=1000),
            Inventario(producto_id=self.torta.id, tienda_id=self.t1.id, stock_actual=8),
            Inventario(producto_id=self.torta.id, tienda_id=self.t2.id, stock_actual=3),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _stock(self, producto, tienda=None):
        return self.db.query(Inventario).filter_by(
            producto_id=producto.id, tienda_id=(tienda or self.t1).id).first().stock_actual

    def _consumo(self, cantidad=2, quien="jueces", motivo="visita de los jueces"):
        return svc.registrar_merma(self.db, self.t1.id, self.bebida.id, cantidad,
                                   motivo, self.admin.id, tipo="consumo", quien=quien)

    # ── El caso que motivó todo ────────────────────────────────────────────────
    def test_devuelve_al_sustituto_que_pago_la_cascada(self):
        """La receta dice entera, la cascada sacó deslactosada: se devuelve la
        deslactosada. Devolver por receta movería el faltante, no lo borraría."""
        m = self._consumo(cantidad=2)          # 0.4 und de leche + 68 gr de salsa
        self.assertEqual(self._stock(self.entera), 0)          # nunca se tocó
        self.assertAlmostEqual(self._stock(self.deslactosada), 9.6)  # 10 − 0.4
        self.assertEqual(self._stock(self.salsa), 932)         # 1000 − 68

        r = svc.anular_merma(self.db, m.id, self.admin.id)

        self.assertAlmostEqual(self._stock(self.deslactosada), 10)  # devuelta donde salió
        self.assertEqual(self._stock(self.entera), 0)          # NO se le sumó nada
        self.assertEqual(self._stock(self.salsa), 1000)
        self.assertTrue(r["sellados"])
        self.assertFalse(r["por_receta"])
        self.assertIsNone(self.db.query(Merma).filter_by(id=m.id).first())

    def test_cada_merma_duplicada_devuelve_solo_lo_suyo(self):
        """Cinco envíos idénticos del mismo formulario (el caso del 21-sep).
        Anular uno devuelve UNA vez; anular los cinco devuelve exactamente cinco."""
        mermas = [self._consumo(cantidad=2) for _ in range(5)]
        # assertAlmostEqual y no assertEqual: 0.2 no es exacto en binario y cinco
        # restas encadenadas dejan 7.999999999999998. Es ruido del float, no del
        # inventario, y clavarlo con == haría fallar el test por la coma.
        self.assertAlmostEqual(self._stock(self.deslactosada), 8.0)   # 10 − 5×0.4
        self.assertEqual(self._stock(self.salsa), 660)                # 1000 − 5×68

        svc.anular_merma(self.db, mermas[0].id, self.admin.id)
        self.assertAlmostEqual(self._stock(self.deslactosada), 8.4)   # una sola vuelta
        self.assertEqual(self._stock(self.salsa), 728)

        for m in mermas[1:]:
            svc.anular_merma(self.db, m.id, self.admin.id)
        self.assertAlmostEqual(self._stock(self.deslactosada), 10)    # ni más ni menos
        self.assertEqual(self._stock(self.salsa), 1000)
        self.assertEqual(self.db.query(Merma).count(), 0)

    def test_producto_con_stock_propio_vuelve_a_su_valor(self):
        m = svc.registrar_merma(self.db, self.t1.id, self.torta.id, 3,
                                "se cayó", self.admin.id, tipo="daño")
        self.assertEqual(self._stock(self.torta), 5)
        r = svc.anular_merma(self.db, m.id, self.admin.id)
        self.assertEqual(self._stock(self.torta), 8)
        self.assertEqual(r["tipo"], "daño")
        self.assertTrue(r["sellados"])

    def test_traslado_delega_y_deshace_el_recibo(self):
        m = svc.registrar_merma(self.db, self.t1.id, self.torta.id, 2, "t",
                                self.admin.id, tipo="traslado",
                                tienda_destino_id=self.t2.id)
        svc.recibir_traslado(self.db, m.id, self.t2.id, self.admin.id)
        self.assertEqual(self._stock(self.torta), 6)
        self.assertEqual(self._stock(self.torta, self.t2), 5)

        svc.anular_merma(self.db, m.id, self.admin.id)

        self.assertEqual(self._stock(self.torta), 8)            # envío revertido
        self.assertEqual(self._stock(self.torta, self.t2), 3)   # recibo revertido
        self.assertIsNone(self.db.query(Merma).filter_by(id=m.id).first())

    def test_merma_vieja_sin_sello_se_empareja_por_motivo_y_hora(self):
        """Las 10 que ya están en producción se registraron antes de que existiera
        `movimientos_inventario.merma_id`. Igual tienen que poder devolverse, y
        al sustituto correcto."""
        m = self._consumo(cantidad=2)
        # Simular el estado previo a la columna: los movimientos sin sellar.
        for mov in self.db.query(MovimientoInventario).filter_by(merma_id=m.id).all():
            mov.merma_id = None
        self.db.commit()

        r = svc.anular_merma(self.db, m.id, self.admin.id)

        self.assertFalse(r["sellados"])          # fue por el camino viejo
        self.assertFalse(r["por_receta"])        # pero encontró los movimientos
        self.assertAlmostEqual(self._stock(self.deslactosada), 10)
        self.assertEqual(self._stock(self.entera), 0)
        self.assertEqual(self._stock(self.salsa), 1000)

    def test_sin_movimientos_cae_a_la_receta_y_lo_avisa(self):
        """Sin sello y sin movimientos que emparejar no queda de dónde leer:
        devuelve por receta, que puede errarle al producto, y lo dice."""
        m = self._consumo(cantidad=2)
        self.db.query(MovimientoInventario).delete()
        self.db.commit()

        r = svc.anular_merma(self.db, m.id, self.admin.id)

        self.assertTrue(r["por_receta"])
        self.assertFalse(r["sellados"])
        # Por receta le suma a la ENTERA, que no era de donde había salido: es la
        # imprecisión que el camino sellado existe para evitar.
        self.assertAlmostEqual(self._stock(self.entera), 0.4)

    def test_merma_inexistente(self):
        with self.assertRaises(HTTPException) as cm:
            svc.anular_merma(self.db, 9999, self.admin.id)
        self.assertEqual(cm.exception.status_code, 404)

    def test_no_se_puede_anular_dos_veces(self):
        m = self._consumo(cantidad=2)
        svc.anular_merma(self.db, m.id, self.admin.id)
        with self.assertRaises(HTTPException) as cm:
            svc.anular_merma(self.db, m.id, self.admin.id)
        self.assertEqual(cm.exception.status_code, 404)
        self.assertAlmostEqual(self._stock(self.deslactosada), 10)  # no devolvió dos veces

    def test_insumo_sin_fila_de_inventario_no_rompe(self):
        """Si un insumo no tiene fila en la sede el descuento lo saltea; la
        reversa tiene que saltearlo igual y no abortar el resto."""
        canela = Producto(nombre="Canela", categoria=CategoriaProductoEnum.insumo,
                          unidad_medida="gr", controla_stock=True)
        self.db.add(canela)
        self.db.flush()
        self.db.add(ProductoInsumo(producto_id=self.bebida.id, insumo_id=canela.id, cantidad=2))
        self.db.commit()

        m = self._consumo(cantidad=1)
        r = svc.anular_merma(self.db, m.id, self.admin.id)

        self.assertEqual(self._stock(self.salsa), 1000)
        self.assertAlmostEqual(self._stock(self.deslactosada), 10)
        self.assertNotIn(canela.id, [d["producto_id"] for d in r["devuelto"]])

    def test_tienda_de_es_la_sede_de_origen(self):
        m = self._consumo(cantidad=1)
        self.assertEqual(svc.tienda_de(self.db, m.id), self.t1.id)
        with self.assertRaises(HTTPException):
            svc.tienda_de(self.db, 9999)


if __name__ == "__main__":
    unittest.main()
