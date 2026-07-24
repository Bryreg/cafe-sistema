"""FASE 2 del OCR de facturas: ENTRENAMIENTO real — aliases proveedor→producto.

El sistema aprende cómo llama CADA proveedor a cada producto del inventario
(texto del renglón de la factura → producto), y usa esa verdad confirmada
ANTES que la IA y que el fuzzy:

  - upsert de alias: nuevo / refuerzo / conflicto (correccion gana, el resto no toca)
  - mapear_items resuelve por alias primero, con origen_match "alias"|"ia"|"fuzzy"
  - crear factura aprende de la corrección y de la confirmación (y el alias
    NUNCA puede hacer fallar el guardado de la factura)
  - el backfill aprende del match confiable (bootstrap) y NO del dudoso
  - un 422 de UNA factura no corta el lote del backfill; proveedor caído sí
  - normalización consistente con cargar_menu_venta.norm (NFKD sin tildes,
    espacios colapsados, MAYÚSCULAS)
"""
import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import (
    CategoriaProductoEnum, FacturaCompra, FacturaCompraItem, Producto,
    ProductoAlias, RolEnum, Tienda, TipoPagoEnum, Usuario,
)
from app.routers import rentabilidad as rentabilidad_router
from app.services import factura_ocr
from app.services import facturas as fac
from app.services import producto_alias
from app.services.factura_ocr import _precios_para_factura, mapear_items
from app.services.producto_alias import (
    _MAX_LARGO_ALIAS, clave_alias, contar_aliases, normalizar_alias,
    upsert_alias,
)


def prod_ns(id=1, nombre="Café", unidad="gr", cpe=None, precio_venta=0):
    """Producto plano (SimpleNamespace) como los que materializa el escaneo."""
    return SimpleNamespace(
        id=id, nombre=nombre, unidad_medida=unidad,
        contenido_por_empaque=cpe, categoria="insumos", precio_venta=precio_venta,
    )


class NormalizacionTest(unittest.TestCase):
    """La MISMA normalización que cargar_menu_venta.norm: NFKD → ascii (sin
    tildes/ñ) → espacios colapsados → strip → MAYÚSCULAS. No se importa el
    script (su import ejecuta create_all sobre la DB real): se fija acá el
    contrato de comportamiento."""

    def test_tildes_y_mayusculas(self):
        self.assertEqual(normalizar_alias("café Alta Tostión"), "CAFE ALTA TOSTION")

    def test_espacios_colapsados_y_strip(self):
        self.assertEqual(normalizar_alias("  leche   entera  "), "LECHE ENTERA")

    def test_enie_se_degrada_como_en_menu_venta(self):
        # NFKD descompone ñ→n+tilde y el encode ascii tira la tilde: "NONO".
        self.assertEqual(normalizar_alias("Ñoño"), "NONO")

    def test_no_string_y_none_devuelven_vacio(self):
        self.assertEqual(normalizar_alias(None), "")
        self.assertEqual(normalizar_alias("   "), "")


class _DBTestCase(unittest.TestCase):
    """sqlite temporal con el metadata real (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def crear_producto(self, nombre="Café alta tostión", unidad="gr", cpe=None,
                       precio_venta=0):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, contenido_por_empaque=cpe,
                     precio_venta=precio_venta, controla_stock=True)
        self.db.add(p)
        self.db.commit()
        return p


class UpsertAliasTest(_DBTestCase):
    def setUp(self):
        super().setUp()
        self.cafe = self.crear_producto("Café alta tostión")
        self.leche = self.crear_producto("Leche entera", unidad="ml", cpe=1100)

    def test_alias_nuevo_se_crea_normalizado_con_snapshot(self):
        alias = upsert_alias(self.db, "  Café del PROVEEDOR x kg ", self.cafe.id, "correccion")
        self.db.commit()
        self.assertIsNotNone(alias)
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.alias_normalizado, "CAFE DEL PROVEEDOR X KG")
        self.assertEqual(fila.alias_original, "  Café del PROVEEDOR x kg ".strip())
        self.assertEqual(fila.producto_id, self.cafe.id)
        self.assertEqual(fila.origen, "correccion")
        self.assertEqual(fila.veces_visto, 1)
        self.assertIsNotNone(fila.actualizado_en)

    def test_refuerzo_mismo_producto_incrementa_veces_visto(self):
        upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo")
        self.db.commit()
        alias = upsert_alias(self.db, "cafe   x kg", self.cafe.id, "escaneo")
        self.db.commit()
        self.assertIsNotNone(alias)
        filas = self.db.query(ProductoAlias).all()
        self.assertEqual(len(filas), 1)          # upsert, no duplicado
        self.assertEqual(filas[0].veces_visto, 2)

    def test_conflicto_correccion_gana(self):
        # El alias apuntaba a leche (escaneo); un humano corrige → café manda.
        upsert_alias(self.db, "CAFE X KG", self.leche.id, "escaneo")
        self.db.commit()
        alias = upsert_alias(self.db, "CAFE X KG", self.cafe.id, "correccion")
        self.db.commit()
        self.assertIsNotNone(alias)
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.producto_id, self.cafe.id)
        self.assertEqual(fila.origen, "correccion")
        self.assertEqual(fila.veces_visto, 1)    # verdad nueva: contador reinicia

    def test_conflicto_sin_correccion_no_toca(self):
        # El alias fue confirmado por un humano: un escaneo/bootstrap NO lo pisa.
        upsert_alias(self.db, "CAFE X KG", self.cafe.id, "correccion")
        self.db.commit()
        for origen in ("escaneo", "bootstrap"):
            resultado = upsert_alias(self.db, "CAFE X KG", self.leche.id, origen)
            self.assertIsNone(resultado)
        self.db.commit()
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.producto_id, self.cafe.id)
        self.assertEqual(fila.origen, "correccion")
        self.assertEqual(fila.veces_visto, 1)

    def test_alias_vacio_o_sin_producto_no_escribe(self):
        self.assertIsNone(upsert_alias(self.db, "   ", self.cafe.id, "escaneo"))
        self.assertIsNone(upsert_alias(self.db, "CAFE", None, "escaneo"))
        self.db.commit()
        self.assertEqual(contar_aliases(self.db), 0)

    def test_origen_invalido_no_escribe(self):
        self.assertIsNone(upsert_alias(self.db, "CAFE", self.cafe.id, "magia"))
        self.db.commit()
        self.assertEqual(contar_aliases(self.db), 0)

    def test_contar_aliases(self):
        self.assertEqual(contar_aliases(self.db), 0)
        upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo")
        upsert_alias(self.db, "LECHE X6", self.leche.id, "bootstrap")
        self.db.commit()
        self.assertEqual(contar_aliases(self.db), 2)


class MapearItemsConAliasTest(_DBTestCase):
    """Orden nuevo por renglón: (1) alias exacto normalizado — verdad confirmada,
    gana siempre y sin advertencia de identidad; (2) producto_id de la IA;
    (3) fuzzy como está; (4) sin match. origen_match lo dice."""

    def setUp(self):
        super().setUp()
        self.cafe = self.crear_producto("Café alta tostión", unidad="gr")
        self.leche = self.crear_producto("Leche entera", unidad="ml", cpe=1100)
        self.catalogo = [
            prod_ns(id=self.cafe.id, nombre="Café alta tostión", unidad="gr"),
            prod_ns(id=self.leche.id, nombre="Leche entera", unidad="ml", cpe=1100),
        ]

    def _item(self, desc, producto_id=None, cantidad=2, unidad="kg"):
        return {"descripcion": desc, "cantidad": cantidad, "unidad": unidad,
                "precio_unitario": None, "subtotal": None,
                "numero_lote": None, "fecha_vencimiento": None,
                "producto_id": producto_id}

    def test_alias_gana_sobre_producto_id_de_la_ia(self):
        # La IA dice leche (mal); el alias confirmado dice café → café, sin dudas.
        upsert_alias(self.db, "CAFE DEL CAMPO X KG", self.cafe.id, "correccion")
        self.db.commit()
        it = mapear_items(
            {"items": [self._item("cafe del campo   x kg", producto_id=self.leche.id)]},
            self.catalogo, self.db)[0]
        self.assertEqual(it["producto_id"], self.cafe.id)
        self.assertEqual(it["origen_match"], "alias")
        self.assertEqual(it["cantidad"], 2000.0)   # 2 kg → gr
        self.assertIsNone(it["advertencia"])       # confianza alta: sin advertencia

    def test_alias_gana_sobre_fuzzy_y_no_advierte_similitud(self):
        # Sin alias este texto caería al fuzzy (con advertencia "similitud").
        upsert_alias(self.db, "CAFE ALTA TOSTION X KG", self.cafe.id, "escaneo")
        self.db.commit()
        it = mapear_items(
            {"items": [self._item("CAFE ALTA TOSTION X KG")]},
            self.catalogo, self.db)[0]
        self.assertEqual(it["producto_id"], self.cafe.id)
        self.assertEqual(it["origen_match"], "alias")
        self.assertIsNone(it["advertencia"])

    def test_sin_alias_el_id_de_la_ia_marca_origen_ia(self):
        it = mapear_items(
            {"items": [self._item("CAFE X KG", producto_id=self.cafe.id)]},
            self.catalogo, self.db)[0]
        self.assertEqual(it["producto_id"], self.cafe.id)
        self.assertEqual(it["origen_match"], "ia")

    def test_sin_alias_ni_ia_el_fuzzy_marca_origen_fuzzy_y_advierte(self):
        it = mapear_items(
            {"items": [self._item("CAFE ALTA TOSTION X KG")]},
            self.catalogo, self.db)[0]
        self.assertEqual(it["producto_id"], self.cafe.id)
        self.assertEqual(it["origen_match"], "fuzzy")
        self.assertIn("similitud", it["advertencia"])

    def test_sin_match_origen_none_y_advertencia_actual(self):
        it = mapear_items(
            {"items": [self._item("SERVILLETAS CUADRADAS")]},
            self.catalogo, self.db)[0]
        self.assertIsNone(it["producto_id"])
        self.assertIsNone(it["origen_match"])
        self.assertIn("inventario", it["advertencia"])

    def test_alias_conserva_advertencias_de_conversion(self):
        # El alias resuelve la IDENTIDAD, no la cantidad: una unidad que no
        # cuadra sigue advirtiendo.
        upsert_alias(self.db, "CAFE DEL CAMPO", self.cafe.id, "correccion")
        self.db.commit()
        it = mapear_items(
            {"items": [self._item("CAFE DEL CAMPO", cantidad=2, unidad="lt")]},
            self.catalogo, self.db)[0]
        self.assertEqual(it["producto_id"], self.cafe.id)
        self.assertEqual(it["origen_match"], "alias")
        self.assertIsNone(it["cantidad"])
        self.assertIsNotNone(it["advertencia"])

    def test_sin_db_funciona_como_antes(self):
        it = mapear_items(
            {"items": [self._item("CAFE X KG", producto_id=self.cafe.id)]},
            self.catalogo)[0]
        self.assertEqual(it["producto_id"], self.cafe.id)
        self.assertEqual(it["origen_match"], "ia")


class CrearFacturaAprendeAliasTest(_DBTestCase):
    """El ciclo que se alimenta solo: registrar la factura upserta el alias por
    cada item con descripcion_original y producto confirmado. correccion si el
    humano cambió el producto; escaneo si confirmó sin cambiar. Y el alias
    JAMÁS puede hacer fallar el guardado."""

    def setUp(self):
        super().setUp()
        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()
        self.cafe = self.crear_producto("Café alta tostión", unidad="unidad")

    def _data(self, items):
        return SimpleNamespace(
            tipo_pago="credito",   # crédito: sin egreso de caja (no requiere turno)
            items=items, valor_total=6000, tienda_id=self.tienda.id,
            proveedor="Cafex coop", numero_factura="9080", numero_lote=None,
            fecha_recibido=date.today(),
        )

    def _item(self, **extra):
        base = dict(producto_id=self.cafe.id, cantidad=6, precio_unitario=1000,
                    numero_lote=None, fecha_vencimiento=None)
        base.update(extra)
        return SimpleNamespace(**base)

    def test_correccion_del_humano_aprende_alias_correccion(self):
        fac.crear_factura(self.db, self._data([self._item(
            descripcion_original="CAFE DEL PROVEEDOR X KG",
            origen_match="correccion")]), None, self.admin.id)
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.alias_normalizado, "CAFE DEL PROVEEDOR X KG")
        self.assertEqual(fila.producto_id, self.cafe.id)
        self.assertEqual(fila.origen, "correccion")

    def test_confirmacion_sin_cambiar_aprende_alias_escaneo(self):
        fac.crear_factura(self.db, self._data([self._item(
            descripcion_original="CAFE DEL PROVEEDOR X KG",
            origen_match="ia")]), None, self.admin.id)
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.origen, "escaneo")

    def test_sin_origen_match_usa_escaneo(self):
        fac.crear_factura(self.db, self._data([self._item(
            descripcion_original="CAFE DEL PROVEEDOR X KG")]), None, self.admin.id)
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.origen, "escaneo")

    def test_sin_descripcion_original_no_aprende(self):
        fac.crear_factura(self.db, self._data([self._item()]), None, self.admin.id)
        self.assertEqual(contar_aliases(self.db), 0)

    def test_alias_que_explota_no_hace_fallar_la_factura(self):
        with mock.patch("app.services.producto_alias.upsert_alias",
                        side_effect=RuntimeError("boom")):
            factura = fac.crear_factura(self.db, self._data([self._item(
                descripcion_original="CAFE DEL PROVEEDOR X KG",
                origen_match="correccion")]), None, self.admin.id)
        self.assertIsNotNone(factura.id)
        self.assertEqual(self.db.query(FacturaCompra).count(), 1)
        self.assertEqual(contar_aliases(self.db), 0)
        # La sesión queda usable después del rollback del alias.
        self.assertEqual(self.db.query(FacturaCompraItem).count(), 1)


class PreciosParaFacturaAliasTest(unittest.TestCase):
    """Bootstrap montado en el backfill: la MISMA lectura que rellena el precio
    devuelve los pares (texto del renglón → producto) de los matches CONFIABLES.
    Los dudosos (incoherentes, duplicados, implausibles) no entrenan nada."""

    CAFE = prod_ns(id=7, nombre="Café alta tostión", unidad="gr")

    def item_db(self, id, producto_id, cantidad, precio=None):
        return SimpleNamespace(id=id, producto_id=producto_id,
                               cantidad=cantidad, precio_unitario=precio)

    def test_match_confiable_devuelve_alias(self):
        ext = [{"descripcion": "CAFE DEL CAMPO X KG", "producto_id": 7, "cantidad": 2,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": 80000}]
        precios, advs, aliases = _precios_para_factura(
            ext, [self.item_db(1, 7, 2000)], 100000, {7: self.CAFE})
        self.assertEqual(precios, {1: 40.0})
        self.assertEqual(aliases, [("CAFE DEL CAMPO X KG", 7)])

    def test_match_por_nombre_tambien_entrena(self):
        ext = [{"descripcion": "CAFE ALTA TOSTION X KILO", "producto_id": None,
                "cantidad": 1, "unidad": "kg", "precio_unitario": 40000, "subtotal": 40000}]
        precios, advs, aliases = _precios_para_factura(
            ext, [self.item_db(1, 7, 1000)], 100000, {7: self.CAFE})
        self.assertEqual(precios, {1: 40.0})
        self.assertEqual(aliases, [("CAFE ALTA TOSTION X KILO", 7)])

    def test_match_dudoso_no_entrena(self):
        # Renglón incoherente (2×40.000 ≠ 50.000): ni precio ni alias.
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": 2,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": 50000}]
        precios, advs, aliases = _precios_para_factura(
            ext, [self.item_db(1, 7, 2000)], 100000, {7: self.CAFE})
        self.assertEqual(precios, {})
        self.assertEqual(aliases, [])

    def test_duplicado_no_entrena(self):
        ext = [
            {"descripcion": "CAFE 500G", "producto_id": 7, "cantidad": 0.5,
             "unidad": "kg", "precio_unitario": None, "subtotal": 18000},
            {"descripcion": "CAFE 2500G", "producto_id": 7, "cantidad": 2.5,
             "unidad": "kg", "precio_unitario": None, "subtotal": 90000},
        ]
        items = [self.item_db(1, 7, 2500), self.item_db(2, 7, 500)]
        precios, advs, aliases = _precios_para_factura(ext, items, 120000, {7: self.CAFE})
        self.assertEqual(precios, {})
        self.assertEqual(aliases, [])

    def test_sin_descripcion_no_entrena_pero_si_costea(self):
        ext = [{"descripcion": "", "producto_id": 7, "cantidad": 1,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": 40000}]
        precios, advs, aliases = _precios_para_factura(
            ext, [self.item_db(1, 7, 1000)], 100000, {7: self.CAFE})
        self.assertEqual(precios, {1: 40.0})
        self.assertEqual(aliases, [])


def _extr_ok(producto_id, desc="CAFE DEL CAMPO X KG", subtotal=40000,
             valor_total=100000.0):
    return {"error": None, "proveedor": "Cafex", "numero_factura": None,
            "fecha_factura": None, "valor_total": valor_total, "tipo_pago": None,
            "items": [{"descripcion": desc, "cantidad": 1, "unidad": "kg",
                       "precio_unitario": None, "subtotal": subtotal,
                       "numero_lote": None, "fecha_vencimiento": None,
                       "producto_id": producto_id}],
            "advertencias": []}


class BackfillLoteTest(_DBTestCase):
    """El backfill entrena mientras costea, y un 422 de UNA factura (foto
    ilegible / no-factura) NO corta el lote: se anota como no legible y sigue.
    Los errores de PROVEEDOR (503 de cuota, key mala) sí cortan como hoy."""

    def setUp(self):
        super().setUp()
        factura_ocr._backfill_no_legibles.clear()
        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()
        self.cafe = self.crear_producto("Café alta tostión", unidad="gr")
        # Dos facturas con foto y items sin precio. El lote las procesa por id
        # DESC: la "primera" en procesarse es f2.
        self.f1 = self._factura("F-1")
        self.f2 = self._factura("F-2")

    def tearDown(self):
        factura_ocr._backfill_no_legibles.clear()
        super().tearDown()

    def _factura(self, numero):
        f = FacturaCompra(
            tienda_id=self.tienda.id, proveedor="Cafex", numero_factura=numero,
            valor_total=100000, tipo_pago=TipoPagoEnum.credito,
            imagen_url=f"http://fotos.test/{numero}.jpg", usuario_id=self.admin.id,
        )
        self.db.add(f)
        self.db.flush()
        self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=self.cafe.id,
                                      cantidad=1000, precio_unitario=None))
        self.db.commit()
        return f

    def _correr(self, extraer_side_effect):
        with mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", "gm"), \
             mock.patch("httpx.get",
                        return_value=SimpleNamespace(content=b"jpegbytes")), \
             mock.patch.object(factura_ocr, "_compress", side_effect=lambda b, **kw: b), \
             mock.patch.object(factura_ocr, "_extraer",
                               side_effect=extraer_side_effect):
            return factura_ocr.backfill_costos_facturas(self.db, self.admin.id, limite=5)

    def test_422_de_una_factura_no_corta_el_lote(self):
        # f2 (primera del lote) es ilegible → se salta y f1 SÍ se procesa.
        out = self._correr([HTTPException(422, "No se pudo leer la factura: borrosa"),
                            _extr_ok(self.cafe.id)])
        self.assertNotIn("detenido_por", out)
        self.assertEqual(out["procesadas"], 2)
        self.assertEqual(out["items_actualizados"], 1)
        self.assertIn(self.f2.id, factura_ocr._backfill_no_legibles)
        item_f1 = (self.db.query(FacturaCompraItem)
                   .filter_by(factura_id=self.f1.id).one())
        self.assertAlmostEqual(float(item_f1.precio_unitario), 40.0)

    def test_error_de_proveedor_si_corta_el_lote(self):
        out = self._correr([HTTPException(503, "Se agotó la cuota gratis del DÍA")])
        self.assertIn("detenido_por", out)
        self.assertEqual(out["items_actualizados"], 0)
        # Proveedor caído es transitorio: la factura NO se marca ilegible.
        self.assertNotIn(self.f2.id, factura_ocr._backfill_no_legibles)

    def test_backfill_aprende_aliases_y_los_reporta(self):
        out = self._correr([_extr_ok(self.cafe.id, desc="CAFE DEL CAMPO X KG"),
                            _extr_ok(self.cafe.id, desc="CAFE DEL CAMPO X KG")])
        self.assertEqual(out["items_actualizados"], 2)
        self.assertEqual(out["aliases_aprendidos"], 2)  # nuevo + refuerzo
        self.assertEqual(out["aliases_conocidos"], 1)
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.alias_normalizado, "CAFE DEL CAMPO X KG")
        self.assertEqual(fila.producto_id, self.cafe.id)
        self.assertEqual(fila.origen, "bootstrap")
        self.assertEqual(fila.veces_visto, 2)

    def test_alias_que_explota_no_rompe_la_escritura_de_precios(self):
        with mock.patch("app.services.producto_alias.upsert_alias",
                        side_effect=RuntimeError("boom")):
            out = self._correr([_extr_ok(self.cafe.id),
                                _extr_ok(self.cafe.id)])
        self.assertEqual(out["items_actualizados"], 2)
        self.assertEqual(out["aliases_aprendidos"], 0)
        item_f1 = (self.db.query(FacturaCompraItem)
                   .filter_by(factura_id=self.f1.id).one())
        self.assertAlmostEqual(float(item_f1.precio_unitario), 40.0)

    def test_fallo_parcial_de_un_alias_conserva_los_demas(self):
        """Fallo REAL (IntegrityError que deja la sesión caída) en el alias N:
        el aprendizaje es per-item con try/except + commit individual (mismo
        patrón robusto de crear_factura) — los demás aliases del lote se
        aprenden igual, no se descarta lo ya hecho."""
        real = producto_alias.upsert_alias

        def selectivo(db, texto, producto_id, origen, **kw):
            if "MALO" in str(texto):
                return _upsert_unique_roto(db, texto, producto_id, origen, **kw)
            return real(db, texto, producto_id, origen, **kw)

        # El lote procesa por id DESC: f2 (MALO) primero, f1 (BUENO) después.
        with mock.patch("app.services.producto_alias.upsert_alias",
                        side_effect=selectivo):
            out = self._correr([_extr_ok(self.cafe.id, desc="CAFE MALO X KG"),
                                _extr_ok(self.cafe.id, desc="CAFE BUENO X KG")])
        self.assertEqual(out["items_actualizados"], 2)   # costos intactos
        self.assertEqual(out["aliases_aprendidos"], 1)   # solo el que no explotó
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.alias_normalizado, "CAFE BUENO X KG")
        self.assertEqual(fila.origen, "bootstrap")


# ─── Corrección acotada Fase 2 (4R): F1(b)/F1(c)/F2/F3/F4 ─────────────────────


class ClaveAliasTest(_DBTestCase):
    """F4(a): UNA sola función de CLAVE (normaliza + trunca al largo de la
    columna) usada al GUARDAR y al BUSCAR. Truncar solo al guardar hacía que
    una descripción >200 chars se guardara recortada pero se buscara completa
    — y jamás matcheara."""

    def test_clave_alias_trunca_al_largo_de_columna(self):
        texto = "café del proveedor " + "x" * 300
        clave = clave_alias(texto)
        self.assertEqual(clave, normalizar_alias(texto)[:_MAX_LARGO_ALIAS])
        self.assertEqual(len(clave), _MAX_LARGO_ALIAS)

    def test_descripcion_larguisima_guarda_y_luego_matchea(self):
        cafe = self.crear_producto("Café alta tostión", unidad="gr")
        texto = "CAFE ALTA TOSTION SELECCION ESPECIAL " + "Z" * 250
        self.assertIsNotNone(upsert_alias(self.db, texto, cafe.id, "correccion"))
        self.db.commit()
        catalogo = [prod_ns(id=cafe.id, nombre="Café alta tostión", unidad="gr")]
        it = mapear_items(
            {"items": [{"descripcion": texto, "cantidad": 2, "unidad": "kg",
                        "precio_unitario": None, "subtotal": None,
                        "numero_lote": None, "fecha_vencimiento": None,
                        "producto_id": None}]},
            catalogo, self.db)[0]
        self.assertEqual(it["producto_id"], cafe.id)
        self.assertEqual(it["origen_match"], "alias")


class _FacturaTestCase(_DBTestCase):
    """Base con tienda/admin/productos para los tests de crear_factura."""

    def setUp(self):
        super().setUp()
        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()
        self.cafe = self.crear_producto("Café alta tostión", unidad="unidad")
        self.leche = self.crear_producto("Leche entera", unidad="unidad")

    def _data(self, items):
        return SimpleNamespace(
            tipo_pago="credito",
            items=items, valor_total=6000, tienda_id=self.tienda.id,
            proveedor="Cafex coop", numero_factura="9080", numero_lote=None,
            fecha_recibido=date.today(),
        )

    def _item(self, **extra):
        base = dict(producto_id=self.cafe.id, cantidad=6, precio_unitario=1000,
                    numero_lote=None, fecha_vencimiento=None)
        base.update(extra)
        return SimpleNamespace(**base)


class DerivacionServerSideOrigenTest(_FacturaTestCase):
    """F2: el privilegio de SOBRESCRIBIR un alias existente se deriva en el
    SERVIDOR (alias conocido vs producto que el humano guardó), nunca de la
    etiqueta origen_match del payload — esa queda como metadata."""

    def test_conflicto_real_repunta_aunque_el_cliente_no_diga_correccion(self):
        # Alias conocido: "CAFE X KG" → leche. El humano guardó CAFÉ para ese
        # texto (etiqueta del cliente: "ia", o sea sin privilegio declarado).
        # Guardar OTRO producto que el alias ES la corrección → repuntar.
        upsert_alias(self.db, "CAFE X KG", self.leche.id, "escaneo")
        self.db.commit()
        fac.crear_factura(self.db, self._data([self._item(
            descripcion_original="CAFE X KG",
            origen_match="ia")]), None, self.admin.id)
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.producto_id, self.cafe.id)
        self.assertEqual(fila.origen, "correccion")

    def test_etiqueta_correccion_con_alias_igual_es_solo_refuerzo(self):
        # El cliente grita "correccion" pero guardó el MISMO producto que el
        # alias: no hay verdad nueva — refuerzo (+1), el origen no cambia.
        upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo")
        self.db.commit()
        fac.crear_factura(self.db, self._data([self._item(
            descripcion_original="CAFE X KG",
            origen_match="correccion")]), None, self.admin.id)
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.veces_visto, 2)
        self.assertEqual(fila.origen, "escaneo")

    def test_alias_nuevo_usa_la_etiqueta_solo_como_informacion(self):
        # Para CREAR no hay privilegio en juego: "correccion" si el cliente lo
        # dice, si no "escaneo" (incluso con etiquetas basura).
        fac.crear_factura(self.db, self._data([
            self._item(descripcion_original="CAFE NUEVO", origen_match="correccion"),
            self._item(producto_id=self.leche.id,
                       descripcion_original="LECHE NUEVA", origen_match="hacker"),
        ]), None, self.admin.id)
        filas = {f.alias_normalizado: f for f in self.db.query(ProductoAlias).all()}
        self.assertEqual(filas["CAFE NUEVO"].origen, "correccion")
        self.assertEqual(filas["LECHE NUEVA"].origen, "escaneo")


def _upsert_unique_roto(db, texto, producto_id, origen, **kw):
    """Fallo REAL de SQLAlchemy (no un RuntimeError mockeado): dos INSERTs con
    la misma clave única → IntegrityError genuino en el flush, que deja la
    sesión DEACTIVE (pending rollback), como una carrera de UNIQUE real."""
    db.add(ProductoAlias(alias_normalizado="CHOQUE", alias_original="CHOQUE",
                         producto_id=producto_id, origen="escaneo", veces_visto=1))
    db.flush()
    db.add(ProductoAlias(alias_normalizado="CHOQUE", alias_original="CHOQUE",
                         producto_id=producto_id, origen="escaneo", veces_visto=1))
    db.flush()  # ← IntegrityError REAL


class AprendizajePorItemRobustoTest(_FacturaTestCase):
    """F3: un fallo REAL del flush/commit del alias (UNIQUE en carrera) deja la
    sesión DEACTIVE; el except debe hacer rollback ANTES de loguear y el log
    debe usar el id capturado como int — no factura.id (PendingRollbackError
    → 500 con la factura YA commiteada → doble registro por reintento)."""

    def test_unique_real_en_el_aprendizaje_no_rompe_la_request(self):
        with mock.patch("app.services.producto_alias.upsert_alias",
                        side_effect=_upsert_unique_roto):
            with self.assertLogs("app.services.facturas", level="ERROR") as cm:
                factura = fac.crear_factura(self.db, self._data([self._item(
                    descripcion_original="CAFE DEL PROVEEDOR X KG",
                    origen_match="correccion")]), None, self.admin.id)
        # La request terminó OK y la factura quedó commiteada.
        self.assertIsNotNone(factura.id)
        self.assertEqual(self.db.query(FacturaCompra).count(), 1)
        # El log corrió y usó el id de la factura (capturado antes del commit).
        self.assertTrue(any(str(factura.id) in linea for linea in cm.output))
        # La sesión queda usable (no PendingRollbackError).
        self.assertEqual(self.db.query(FacturaCompraItem).count(), 1)
        self.assertEqual(contar_aliases(self.db), 0)

    def test_un_alias_roto_no_mata_el_aprendizaje_de_los_demas(self):
        real = producto_alias.upsert_alias

        def selectivo(db, texto, producto_id, origen, **kw):
            if "MALO" in str(texto):
                return _upsert_unique_roto(db, texto, producto_id, origen, **kw)
            return real(db, texto, producto_id, origen, **kw)

        with mock.patch("app.services.producto_alias.upsert_alias",
                        side_effect=selectivo):
            with self.assertLogs("app.services.facturas", level="ERROR"):
                fac.crear_factura(self.db, self._data([
                    self._item(descripcion_original="RENGLON MALO"),
                    self._item(producto_id=self.leche.id,
                               descripcion_original="RENGLON BUENO"),
                ]), None, self.admin.id)
        filas = self.db.query(ProductoAlias).all()
        self.assertEqual([f.alias_normalizado for f in filas], ["RENGLON BUENO"])
        self.assertEqual(self.db.query(FacturaCompra).count(), 1)


class UpsertCarreraTest(_DBTestCase):
    """F4(c): carrera del upsert — otro request inserta la misma clave entre el
    SELECT y el INSERT. El IntegrityError genuino se captura, se re-consulta y
    se trata como REFUERZO (la señal no se pierde); si aún así no hay fila, el
    log dice alias y producto (no genérico)."""

    def setUp(self):
        super().setUp()
        self.cafe = self.crear_producto("Café alta tostión")

    def test_carrera_de_insert_se_recupera_como_refuerzo(self):
        upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo")
        self.db.commit()
        real = producto_alias._existente_por_clave
        llamadas = {"n": 0}

        def con_carrera(db, clave):
            # 1ª consulta (pre-INSERT) no ve la fila → INSERT → UNIQUE real;
            # la re-consulta de recuperación sí la ve.
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                return None
            return real(db, clave)

        with mock.patch.object(producto_alias, "_existente_por_clave",
                               side_effect=con_carrera):
            fila = upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo")
        self.assertIsNotNone(fila)
        self.db.commit()
        unica = self.db.query(ProductoAlias).one()
        self.assertEqual(unica.veces_visto, 2)   # refuerzo, no señal perdida

    def test_carrera_irrecuperable_loguea_alias_y_producto(self):
        upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo")
        self.db.commit()
        with mock.patch.object(producto_alias, "_existente_por_clave",
                               return_value=None):
            with self.assertLogs("app.services.producto_alias", level="WARNING") as cm:
                fila = upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo")
        self.assertIsNone(fila)
        salida = "\n".join(cm.output)
        self.assertIn("CAFE X KG", salida)
        self.assertIn(str(self.cafe.id), salida)
        # La sesión sigue usable tras el savepoint.
        self.assertEqual(self.db.query(ProductoAlias).count(), 1)


class AliasAutoriaTest(_FacturaTestCase):
    """F1(c): autoría plana barista_id/barista_nombre (patrón X-Barista-Id) —
    quién enseñó cada alias."""

    def test_upsert_guarda_autoria(self):
        fila = upsert_alias(self.db, "CAFE K", self.cafe.id, "escaneo",
                            barista_id=7, barista_nombre="Sofía")
        self.db.commit()
        self.assertEqual(fila.barista_id, 7)
        self.assertEqual(fila.barista_nombre, "Sofía")

    def test_correccion_actualiza_autoria(self):
        upsert_alias(self.db, "CAFE K", self.leche.id, "escaneo",
                     barista_id=7, barista_nombre="Sofía")
        self.db.commit()
        upsert_alias(self.db, "CAFE K", self.cafe.id, "correccion",
                     barista_id=9, barista_nombre="Meli")
        self.db.commit()
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.barista_id, 9)
        self.assertEqual(fila.barista_nombre, "Meli")

    def test_crear_factura_propaga_barista_al_alias(self):
        fac.crear_factura(self.db, self._data([self._item(
            descripcion_original="CAFE DEL PROVEEDOR X KG",
            origen_match="correccion")]), None, self.admin.id,
            barista_id=9, barista_nombre="Meli")
        fila = self.db.query(ProductoAlias).one()
        self.assertEqual(fila.barista_id, 9)
        self.assertEqual(fila.barista_nombre, "Meli")


class AliasesAdminEndpointTest(_DBTestCase):
    """F1(b): administración mínima de aliases (solo admin) en el router de
    rentabilidad — listar (con producto, origen, veces_visto, actualizado_en y
    quién lo enseñó) y borrar por id."""

    def setUp(self):
        super().setUp()
        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.barista = Usuario(nombre="Bari", email="b@t.local", password_hash="h",
                               rol=RolEnum.barista, tienda_id=self.tienda.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.db.commit()
        self.cafe = self.crear_producto("Café alta tostión")

        app = FastAPI(title="Test aliases admin")
        app.include_router(rentabilidad_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        super().tearDown()

    def test_listar_aliases_devuelve_todo_lo_necesario(self):
        upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo",
                     barista_id=self.barista.id, barista_nombre="Bari")
        self.db.commit()
        r = self.client.get("/api/v1/rentabilidad/aliases")
        self.assertEqual(r.status_code, 200)
        filas = r.json()
        self.assertEqual(len(filas), 1)
        fila = filas[0]
        self.assertEqual(fila["alias_original"], "CAFE X KG")
        self.assertEqual(fila["producto_nombre"], "Café alta tostión")
        self.assertEqual(fila["origen"], "escaneo")
        self.assertEqual(fila["veces_visto"], 1)
        self.assertEqual(fila["barista_nombre"], "Bari")
        self.assertIn("actualizado_en", fila)
        self.assertIn("id", fila)

    def test_delete_elimina_por_id(self):
        fila = upsert_alias(self.db, "CAFE X KG", self.cafe.id, "escaneo")
        self.db.commit()
        r = self.client.delete(f"/api/v1/rentabilidad/aliases/{fila.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(contar_aliases(self.db), 0)

    def test_delete_inexistente_404(self):
        r = self.client.delete("/api/v1/rentabilidad/aliases/99999")
        self.assertEqual(r.status_code, 404)

    def test_solo_admin(self):
        self.app.dependency_overrides[get_current_user] = lambda: self.barista
        self.assertEqual(self.client.get("/api/v1/rentabilidad/aliases").status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/rentabilidad/aliases/1").status_code, 403)


if __name__ == "__main__":
    unittest.main()
