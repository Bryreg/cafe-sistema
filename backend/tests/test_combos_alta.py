"""Alta y edición de combos desde la app.

Hasta ahora un combo SOLO se podía crear corriendo `cargar_combos.py` contra la
base: o sea entrando al servidor. Dar de alta el combo de una sede era una tarea
de infraestructura, no de administración, y por eso quedaba pendiente días.

El armado es la MISMA función que usa el script (`sincronizar_combo`). Estos
tests cuidan las guardas del alta, que son las que evitan un combo que cobra
bien y no descuenta nada — la falla que no se nota, porque no falla.
"""
import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CategoriaProductoEnum, Combo, ComboOpcionProducto,
                               ComboTienda, Producto, RolEnum, Tienda, Usuario)
from app.services import combos as svc


class AltaCombosTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.palmetto = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.moka = self._prod("Mokaccino Medium", 12900)
        self.croissant = self._prod("Croissant Mantequilla", 7900)
        self.db.commit()

    def _prod(self, nombre, precio, controla_stock=True):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.bebida,
                     unidad_medida="und", controla_stock=controla_stock,
                     precio_venta=precio)
        self.db.add(p)
        self.db.flush()
        return p

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _definicion(self, **over):
        d = {
            "nombre": "Combo Borondo", "precio": 18000, "orden": 4,
            "grupos": [
                {"nombre": "Bebida", "opciones": [
                    {"nombre": "Mokaccino Medium",
                     "productos": [{"producto_id": self.moka.id, "cantidad": 1}]}]},
                {"nombre": "Acompañamiento", "opciones": [
                    {"nombre": "Croissant Mantequilla",
                     "productos": [{"producto_id": self.croissant.id, "cantidad": 1}]}]},
            ],
        }
        d.update(over)
        return d

    # ── Camino feliz ──────────────────────────────────────────────────────────
    def test_crea_el_combo_con_su_sombra_inerte_y_su_sede(self):
        r = svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        self.assertEqual(r["nombre"], "Combo Borondo")
        self.assertEqual(r["precio_venta"], 18000.0)
        self.assertEqual(r["tienda_ids"], [self.palmetto.id])

        combo = self.db.query(Combo).filter_by(nombre="Combo Borondo").first()
        # La sombra tiene que ser invisible en la grilla del POS (filtra precio>0)
        # y no puede tener stock propio, o el combo descontaría de más.
        self.assertEqual(float(combo.producto.precio_venta), 0.0)
        self.assertFalse(combo.producto.controla_stock)
        self.assertFalse(combo.producto.incluir_en_conteo)
        # Y descuenta lo de la receta
        consumos = {cp.producto_id: cp.cantidad for g in combo.grupos
                    for o in g.opciones for cp in o.productos}
        self.assertEqual(consumos, {self.moka.id: 1, self.croissant.id: 1})

    def test_un_grupo_de_una_sola_opcion_es_fijo(self):
        """Los dos grupos del Borondo tienen una opción: el POS los
        auto-selecciona y el combo se vende de un toque."""
        svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        combo = self.db.query(Combo).filter_by(nombre="Combo Borondo").first()
        self.assertTrue(all(len(g.opciones) == 1 for g in combo.grupos))

    # ── Las guardas: un combo que cobra y no descuenta ────────────────────────
    def test_sin_grupos_no_se_crea(self):
        """La peor falla posible: cobra el combo completo y el inventario no se
        mueve. No falla nunca, así que nadie la descubre."""
        with self.assertRaises(HTTPException) as ctx:
            svc.crear(self.db, self._definicion(grupos=[]), [self.palmetto.id], self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self.db.query(Combo).count(), 0)

    def test_una_opcion_sin_productos_no_se_crea(self):
        """Igual que la anterior pero solo cuando el cliente elige JUSTO esa
        opción: aparece semanas después y como fuga inexplicada."""
        d = self._definicion()
        d["grupos"][0]["opciones"][0]["productos"] = []
        with self.assertRaises(HTTPException):
            svc.crear(self.db, d, [self.palmetto.id], self.admin.id)
        self.assertEqual(self.db.query(Combo).count(), 0)

    def test_cantidad_cero_no_se_crea(self):
        d = self._definicion()
        d["grupos"][0]["opciones"][0]["productos"][0]["cantidad"] = 0
        with self.assertRaises(HTTPException):
            svc.crear(self.db, d, [self.palmetto.id], self.admin.id)

    def test_precio_cero_no_se_crea(self):
        """Precio 0 dejaría el combo gratis en la grilla del POS."""
        with self.assertRaises(HTTPException):
            svc.crear(self.db, self._definicion(precio=0), [self.palmetto.id], self.admin.id)

    def test_sin_sede_no_se_crea(self):
        """Un combo sin sede no se vende en ninguna parte y la pantalla de
        Combos lo muestra igual: es el error que nadie descubre."""
        with self.assertRaises(HTTPException) as ctx:
            svc.crear(self.db, self._definicion(), [], self.admin.id)
        self.assertIn("sede", ctx.exception.detail.lower())
        self.assertEqual(self.db.query(Combo).count(), 0)

    def test_sede_inexistente_no_se_crea(self):
        with self.assertRaises(HTTPException):
            svc.crear(self.db, self._definicion(), [9999], self.admin.id)
        self.assertEqual(self.db.query(Combo).count(), 0)

    def test_producto_inexistente_no_se_crea(self):
        d = self._definicion()
        d["grupos"][0]["opciones"][0]["productos"][0]["producto_id"] = 9999
        with self.assertRaises(HTTPException) as ctx:
            svc.crear(self.db, d, [self.palmetto.id], self.admin.id)
        self.assertIn("9999", ctx.exception.detail)
        self.assertEqual(self.db.query(Combo).count(), 0)

    def test_nombre_repetido_no_se_crea(self):
        svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        with self.assertRaises(HTTPException) as ctx:
            svc.crear(self.db, self._definicion(), [self.vida.id], self.admin.id)
        self.assertIn("Ya existe", ctx.exception.detail)
        self.assertEqual(self.db.query(Combo).count(), 1)

    def test_grupos_con_el_mismo_nombre_no_se_crean(self):
        """El sincronizado matchea por nombre normalizado: dos «Bebida» se
        pisarían y la segunda se perdería en silencio."""
        d = self._definicion()
        d["grupos"][1]["nombre"] = "bebida"   # mismo nombre normalizado
        with self.assertRaises(HTTPException):
            svc.crear(self.db, d, [self.palmetto.id], self.admin.id)

    def test_no_adopta_un_producto_real_como_sombra(self):
        """Si ya hay un producto real con ese nombre, el combo descontaría su
        stock ADEMÁS de los de la receta."""
        self._prod("Combo Borondo", 15000, controla_stock=True)
        with self.assertRaises(HTTPException) as ctx:
            svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        self.assertIn("producto real", ctx.exception.detail)
        self.assertEqual(self.db.query(Combo).count(), 0)

    # ── Edición ───────────────────────────────────────────────────────────────
    def test_editar_cambia_precio_y_composicion(self):
        r = svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        d = self._definicion(precio=19500)
        d["grupos"][0]["opciones"][0]["productos"][0]["cantidad"] = 2
        r2 = svc.editar(self.db, r["id"], d, self.admin.id)
        self.assertEqual(r2["precio_venta"], 19500.0)
        combo = self.db.query(Combo).filter_by(id=r["id"]).first()
        cant = {cp.producto_id: cp.cantidad for g in combo.grupos
                for o in g.opciones for cp in o.productos}
        self.assertEqual(cant[self.moka.id], 2)

    def test_renombrar_arrastra_el_nombre_de_la_sombra(self):
        """La sombra es lo que el ticket MUESTRA. Si no se renombra, el
        histórico dice un nombre y la pantalla otro."""
        r = svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        svc.editar(self.db, r["id"], self._definicion(nombre="Combo Borondo Plus"),
                   self.admin.id)
        combo = self.db.query(Combo).filter_by(id=r["id"]).first()
        self.assertEqual(combo.nombre, "Combo Borondo Plus")
        self.assertEqual(combo.producto.nombre, "Combo Borondo Plus")

    def test_editar_no_toca_las_sedes(self):
        """Quitar una sede es una decisión distinta a cambiar la composición y
        no tiene por qué viajar en el mismo guardado."""
        r = svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        svc.editar(self.db, r["id"], self._definicion(precio=20000), self.admin.id)
        sedes = [ct.tienda_id for ct in
                 self.db.query(ComboTienda).filter_by(combo_id=r["id"]).all()]
        self.assertEqual(sedes, [self.palmetto.id])

    def test_editar_retira_lo_que_ya_no_esta(self):
        r = svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        d = self._definicion()
        d["grupos"] = d["grupos"][:1]   # se va el acompañamiento
        svc.editar(self.db, r["id"], d, self.admin.id)
        combo = self.db.query(Combo).filter_by(id=r["id"]).first()
        self.assertEqual([g.nombre for g in combo.grupos], ["Bebida"])
        # y sus consumos no quedan huérfanos
        self.assertEqual(
            self.db.query(ComboOpcionProducto).filter_by(producto_id=self.croissant.id).count(), 0)

    def test_editar_a_una_definicion_invalida_no_rompe_el_combo(self):
        r = svc.crear(self.db, self._definicion(), [self.palmetto.id], self.admin.id)
        with self.assertRaises(HTTPException):
            svc.editar(self.db, r["id"], self._definicion(grupos=[]), self.admin.id)
        self.db.rollback()
        combo = self.db.query(Combo).filter_by(id=r["id"]).first()
        self.assertEqual(len(combo.grupos), 2)

    def test_editar_combo_inexistente_es_404(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.editar(self.db, 9999, self._definicion(), self.admin.id)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
