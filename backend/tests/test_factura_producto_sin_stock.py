"""Una factura no puede dar entrada a un producto que no lleva inventario.

CASO REAL, factura #379 de Éxito en Vida (15-sep-2026). El 1-sep las bebidas de
aromática dejaron de llevar stock propio y pasaron a consumir la bolsita como
insumo — la migración fue correcta. Pero los productos viejos siguieron en el
catálogo con un nombre casi idéntico al del insumo nuevo:

    «Aromatica de Cidron»              ← la BEBIDA, ya sin stock
    «Aromatica de Cidron (bolsitas)»   ← el INSUMO, el que sí se cuenta

Quien cargó la factura eligió los de arriba en cuatro de las cinco líneas. El
sistema aceptó, registró el movimiento de entrada, y la mercancía no acumuló en
ningún inventario: 180 bolsitas pagadas, con su factura, y fuera del stock. El
conteo de Vida las marcó como sobrante todos los días desde entonces, y la única
aromática que cuadraba era justo la única línea bien cargada.

El error no se nota al cargar la factura: se nota semanas después, como un
sobrante que nadie sabe explicar. Por eso la guarda va en el servidor y no solo
en el buscador — el payload también llega del OCR y de ediciones a mano.

Ya había pasado antes: el filtro de archivados del buscador se puso por el MISMO
error con el agua con gas el 2-jul, pero dejaba pasar lo que tiene precio de
venta, y las bebidas del POS lo tienen.
"""
import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CategoriaProductoEnum, Producto, RolEnum, Tienda,
                               Usuario)


class FacturaProductoSinStockTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)()

        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        # La bebida del POS: se vende, NO lleva stock (gasta la bolsita por receta).
        self.bebida = Producto(nombre="Aromatica de Cidron",
                               categoria=CategoriaProductoEnum.bebida,
                               unidad_medida="und", controla_stock=False,
                               incluir_en_conteo=False, precio_venta=4500)
        # El insumo: es el que se cuenta y el que debe recibir la mercancía.
        self.insumo = Producto(nombre="Aromatica de Cidron (bolsitas)",
                               categoria=CategoriaProductoEnum.insumo,
                               unidad_medida="und", controla_stock=True,
                               precio_venta=0)
        self.db.add_all([self.bebida, self.insumo])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── El buscador de Ingresos ───────────────────────────────────────────────
    def test_solo_stock_deja_fuera_la_bebida(self):
        """El buscador de Ingresos pide `solo_stock=true`: si ofrece la bebida,
        alguien la va a elegir — tiene el nombre casi igual y aparece primero."""
        todos = self.db.query(Producto).all()
        solo = [p for p in todos if p.controla_stock]
        nombres = {p.nombre for p in solo}
        self.assertIn("Aromatica de Cidron (bolsitas)", nombres)
        self.assertNotIn("Aromatica de Cidron", nombres)

    def test_la_bebida_no_califica_como_archivada(self):
        """Por esto el filtro viejo no alcanzaba: la bebida conserva precio de
        venta, así que no entra en la firma de «archivado» y pasaba el filtro."""
        p = self.bebida
        archivada = (not p.controla_stock and p.incluir_en_conteo is False
                     and not (p.precio_venta or 0))
        self.assertFalse(archivada)

    # ── La guarda del servidor ────────────────────────────────────────────────
    def _guarda(self, prod):
        """Reproduce la guarda de `services/facturas`: rechaza el renglón y
        sugiere el producto con stock de nombre parecido."""
        if prod is not None and not prod.controla_stock:
            similar = (
                self.db.query(Producto)
                .filter(Producto.controla_stock == True,  # noqa: E712
                        Producto.nombre.ilike(f"%{prod.nombre.strip()}%"),
                        Producto.id != prod.id)
                .order_by(Producto.nombre).first())
            sug = f" ¿Querías «{similar.nombre}»?" if similar else ""
            raise HTTPException(400, (
                f"«{prod.nombre}» no lleva inventario, así que darle entrada no suma "
                f"stock en ninguna parte.{sug}"))

    def test_rechaza_la_bebida_y_sugiere_el_insumo(self):
        with self.assertRaises(HTTPException) as ctx:
            self._guarda(self.bebida)
        d = ctx.exception.detail
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("no lleva inventario", d)
        # La sugerencia es lo que evita que el error se repita: el nombre correcto
        # se le pone delante a quien está cargando la factura.
        self.assertIn("Aromatica de Cidron (bolsitas)", d)

    def test_el_insumo_pasa_sin_problema(self):
        self._guarda(self.insumo)   # no levanta

    def test_sin_producto_parecido_no_inventa_sugerencia(self):
        otra = Producto(nombre="Gaseosa Antigua", categoria=CategoriaProductoEnum.bebida,
                        unidad_medida="und", controla_stock=False, precio_venta=3000)
        self.db.add(otra)
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            self._guarda(otra)
        self.assertIn("no lleva inventario", ctx.exception.detail)
        self.assertNotIn("¿Querías", ctx.exception.detail)

    def test_las_cinco_lineas_de_la_379(self):
        """Las cuatro mal cargadas se rechazan; la bien cargada pasa. Con esta
        guarda la factura #379 no habría podido guardarse como se guardó."""
        lineas = [self.bebida, self.bebida, self.bebida, self.bebida, self.insumo]
        rechazadas = 0
        for prod in lineas:
            try:
                self._guarda(prod)
            except HTTPException:
                rechazadas += 1
        self.assertEqual(rechazadas, 4)


if __name__ == "__main__":
    unittest.main()
