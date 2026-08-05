"""Mapeo determinístico del escaneo de facturas: conversión de unidades de la
factura a la unidad del inventario. Acá se juega que el stock no quede en una
magnitud equivocada — todo lo dudoso debe salir como advertencia, nunca como
una cantidad adivinada."""
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from app.services import factura_ocr
from app.services.factura_ocr import (
    _convertir_cantidad, _extraer, _extraer_con_gemini, _extraer_con_groq,
    _fecha_iso, _json_de_texto, _modelos_gemini, _modelos_groq,
    _precios_para_factura, _reducir_para_groq, _validar_suma,
    hay_proveedor_ocr, mapear_items,
)


def prod(id=1, nombre="Café", unidad="gr", cpe=None, precio_venta=0):
    return SimpleNamespace(
        id=id, nombre=nombre, unidad_medida=unidad,
        contenido_por_empaque=cpe, categoria="insumos", precio_venta=precio_venta,
    )


class ConvertirCantidadTest(unittest.TestCase):
    def test_gramos_directo(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="gr"), 500, "gr")
        self.assertEqual((c, emp, factor, adv), (500.0, False, 1.0, None))

    def test_kilos_a_gramos(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="gr"), 2.5, "KG")
        self.assertEqual((c, emp, factor), (2500.0, False, 1000.0))
        self.assertIsNone(adv)

    def test_libra_colombiana_500gr(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="gr"), 3, "LB")
        self.assertEqual((c, factor), (1500.0, 500.0))
        self.assertIsNone(adv)

    def test_litros_a_ml(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="ml"), 2, "Lt")
        self.assertEqual((c, factor), (2000.0, 1000.0))
        self.assertIsNone(adv)

    def test_kilos_en_producto_ml_advierte(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="ml"), 2, "kg")
        self.assertIsNone(c)
        self.assertIsNotNone(adv)

    def test_unidades_producto_unidad(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="unidad"), 6, "UND")
        self.assertEqual((c, emp, adv), (6.0, False, None))

    def test_sin_unidad_producto_unidad(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="unidad"), 6, None)
        self.assertEqual((c, emp, adv), (6.0, False, None))

    def test_unidades_de_granel_con_cpe_son_empaques(self):
        # "2 UND" de leche (bolsa de 1100 ml) = 2 empaques; el backend multiplica.
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="ml", cpe=1100), 2, "und")
        self.assertEqual((c, emp, factor, adv), (2.0, True, 1100.0, None))

    def test_unidades_de_granel_sin_cpe_advierte(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="gr", cpe=None), 2, "und")
        self.assertIsNone(c)
        self.assertIn("gr", adv)

    def test_caja_con_cpe(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="ml", cpe=1000), 2, "CAJA X12")
        self.assertEqual((c, emp, factor, adv), (2.0, True, 1000.0, None))

    def test_caja_sin_cpe_advierte(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="gr"), 2, "caja")
        self.assertIsNone(c)
        self.assertIn("empaque", adv)

    def test_gramos_en_producto_de_unidades_advierte(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="unidad"), 500, "gr")
        self.assertIsNone(c)
        self.assertIsNotNone(adv)

    def test_cantidad_ilegible(self):
        c, emp, factor, adv = _convertir_cantidad(prod(), None, "gr")
        self.assertIsNone(c)
        self.assertIsNotNone(adv)

    def test_unidad_rara_en_granel_con_cpe_asume_empaques_con_advertencia(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="gr", cpe=2500), 3, "BTO VERDE")
        self.assertEqual((c, emp, factor), (3.0, True, 2500.0))
        self.assertIn("revisá", adv)

    def test_abreviatura_k_es_kilo(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="gr"), 2, "K")
        self.assertEqual((c, factor, adv), (2000.0, 1000.0, None))

    def test_sin_unidad_granel_pocos_asume_empaques_con_advertencia(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="ml", cpe=1100), 2, None)
        self.assertEqual((c, emp, factor), (2.0, True, 1100.0))
        self.assertIn("no trae unidad", adv)

    def test_sin_unidad_granel_cantidad_grande_no_adivina(self):
        # "3500" sin unidad en un granel con cpe NO puede volverse 3500 empaques.
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="ml", cpe=1100), 3500, None)
        self.assertIsNone(c)
        self.assertFalse(emp)
        self.assertIsNotNone(adv)

    def test_und_granel_cantidad_grande_no_adivina(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="gr", cpe=2500), 60, "und")
        self.assertIsNone(c)
        self.assertIsNotNone(adv)

    def test_cajas_cantidad_grande_no_adivina(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="ml", cpe=1000), 80, "caja")
        self.assertIsNone(c)
        self.assertIsNotNone(adv)

    def test_unidad_rara_en_unidades_pasa_con_advertencia(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="unidad"), 4, "REF-22")
        self.assertEqual((c, emp), (4.0, False))
        self.assertIsNotNone(adv)

    # ── Contables (unidad/und) CON contenido_por_empaque configurado ─────────
    # Casos reales: pulpa (1 bolsa = 10 und) y torta (1 torta = 12 porciones).
    # La factura dice "1 UND"/"1 TORTA" y sin el factor el form prellenaba 1.

    def test_unidades_de_contable_con_cpe_asume_empaques_con_advertencia(self):
        # "1 UND" de pulpa (bolsa x10): se asume el EMPAQUE (el backend
        # multiplica) — pero con advertencia, porque en un contable "und"
        # también podría ser la unidad final (a diferencia del granel).
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="und", cpe=10), 1, "UND")
        self.assertEqual((c, emp, factor), (1.0, True, 10.0))
        self.assertIsNotNone(adv)

    def test_sin_unidad_contable_con_cpe_asume_empaques_con_advertencia(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="unidad", cpe=12), 1, None)
        self.assertEqual((c, emp, factor), (1.0, True, 12.0))
        self.assertIsNotNone(adv)

    def test_bolsa_de_contable_con_cpe_sin_advertencia(self):
        # Empaque EXPLÍCITO en la factura: camino limpio que ya funcionaba
        # (la rama _U_EMPAQUE no filtra por granel) — se pinea.
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="und", cpe=10), 2, "bolsa")
        self.assertEqual((c, emp, factor, adv), (2.0, True, 10.0, None))

    def test_torta_es_empaque_explicito_sin_advertencia(self):
        # "1 TORTA" (12 porciones vendibles): unidad de empaque explícita →
        # camino limpio, sin advertencia.
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="unidad", cpe=12), 1, "TORTA")
        self.assertEqual((c, emp, factor, adv), (1.0, True, 12.0, None))

    def test_unidad_rara_en_contable_con_cpe_asume_empaques_con_advertencia(self):
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="und", cpe=10), 3, "REF-22")
        self.assertEqual((c, emp, factor), (3.0, True, 10.0))
        self.assertIn("revisá", adv)

    def test_und_contable_cantidad_grande_no_adivina(self):
        # >_MAX_EMPAQUES_PLAUSIBLE: casi seguro NO son empaques — no se adivina.
        c, emp, factor, adv = _convertir_cantidad(prod(unidad="und", cpe=10), 60, "und")
        self.assertEqual((c, emp, factor), (None, False, 1.0))
        self.assertIsNotNone(adv)


class MapearItemsTest(unittest.TestCase):
    def test_item_completo_con_precio_ajustado(self):
        cafe = prod(id=7, nombre="Café libra", unidad="gr")
        extr = {"items": [{
            "descripcion": "CAFE ALTA TOSTION X KG", "cantidad": 2, "unidad": "kg",
            "precio_unitario": 40000, "subtotal": 80000,
            "numero_lote": "L-9", "fecha_vencimiento": "2026-12-01", "producto_id": 7,
        }]}
        out = mapear_items(extr, [cafe])
        self.assertEqual(len(out), 1)
        it = out[0]
        self.assertEqual(it["producto_id"], 7)
        self.assertEqual(it["cantidad"], 2000.0)
        self.assertFalse(it["en_empaques"])
        self.assertAlmostEqual(it["precio_unitario"], 40.0)  # $/gr
        self.assertEqual(it["numero_lote"], "L-9")
        self.assertEqual(it["fecha_vencimiento"], "2026-12-01")
        self.assertIsNone(it["advertencia"])

    def test_precio_por_empaque_se_divide_por_cpe(self):
        leche = prod(id=3, nombre="Leche entera", unidad="ml", cpe=1100)
        extr = {"items": [{
            "descripcion": "LECHE X6", "cantidad": 6, "unidad": "und",
            "precio_unitario": 5500, "subtotal": 33000,
            "numero_lote": None, "fecha_vencimiento": None, "producto_id": 3,
        }]}
        it = mapear_items(extr, [leche])[0]
        self.assertTrue(it["en_empaques"])
        self.assertEqual(it["cantidad"], 6.0)
        self.assertAlmostEqual(it["precio_unitario"], 5.0)  # $/ml

    def test_precio_por_empaque_contable_se_divide_por_cpe(self):
        # Espejo del caso granel: pulpa CONTABLE (bolsa x10 und) — el precio de
        # la factura es por EMPAQUE y debe bajar a $/und.
        pulpa = prod(id=4, nombre="Pulpa de fruta", unidad="und", cpe=10)
        extr = {"items": [{
            "descripcion": "PULPA MORA X10", "cantidad": 1, "unidad": "und",
            "precio_unitario": 25000, "subtotal": 25000,
            "numero_lote": None, "fecha_vencimiento": None, "producto_id": 4,
        }]}
        it = mapear_items(extr, [pulpa])[0]
        self.assertTrue(it["en_empaques"])
        self.assertEqual(it["cantidad"], 1.0)
        self.assertAlmostEqual(it["precio_unitario"], 2500.0)  # $/und

    def test_producto_no_encontrado(self):
        extr = {"items": [{
            "descripcion": "SERVILLETAS", "cantidad": 2, "unidad": "paca",
            "precio_unitario": None, "subtotal": None,
            "numero_lote": None, "fecha_vencimiento": None, "producto_id": None,
        }]}
        it = mapear_items(extr, [prod()])[0]
        self.assertIsNone(it["producto_id"])
        self.assertIsNone(it["cantidad"])
        self.assertIn("inventario", it["advertencia"])

    def test_producto_id_inexistente_no_revienta(self):
        extr = {"items": [{
            "descripcion": "X", "cantidad": 1, "unidad": "und",
            "precio_unitario": None, "subtotal": None,
            "numero_lote": None, "fecha_vencimiento": None, "producto_id": 999,
        }]}
        it = mapear_items(extr, [prod(id=1)])[0]
        self.assertIsNone(it["producto_id"])
        self.assertIsNotNone(it["advertencia"])

    def test_renglon_que_no_cuadra_agrega_advertencia(self):
        # 2 kg × $40.000 = $80.000 pero el subtotal leído dice $50.000: alguien
        # leyó mal una cifra — el humano tiene que revisar.
        cafe = prod(id=7, nombre="Café libra", unidad="gr")
        extr = {"items": [{
            "descripcion": "CAFE X KG", "cantidad": 2, "unidad": "kg",
            "precio_unitario": 40000, "subtotal": 50000,
            "numero_lote": None, "fecha_vencimiento": None, "producto_id": 7,
        }]}
        it = mapear_items(extr, [cafe])[0]
        self.assertIsNotNone(it["advertencia"])
        self.assertIn("no cuadra", it["advertencia"])

    def test_fecha_vencimiento_invalida_se_descarta(self):
        extr = {"items": [{
            "descripcion": "X", "cantidad": 1, "unidad": "und",
            "precio_unitario": None, "subtotal": None,
            "numero_lote": None, "fecha_vencimiento": "31/12/2026", "producto_id": 1,
        }]}
        it = mapear_items(extr, [prod(id=1, unidad="unidad")])[0]
        self.assertIsNone(it["fecha_vencimiento"])


def item_db(id, producto_id, cantidad, precio=None):
    return SimpleNamespace(id=id, producto_id=producto_id,
                           cantidad=cantidad, precio_unitario=precio)


class PreciosParaFacturaTest(unittest.TestCase):
    """Backfill: derivar costo por unidad ALMACENADA = subtotal / cantidad
    GUARDADA. La cantidad guardada es la fuente de verdad; NO se valida contra
    la de la factura (el modelo la lee con ruido). Guardias: subtotal ≤ total,
    coherencia cant×precio, plausibilidad de granel, duplicados a mano."""

    LECHE = prod(id=3, nombre="Leche entera", unidad="ml", cpe=6600)
    CAFE = prod(id=7, nombre="Café alta tostión", unidad="gr")
    TORTA = prod(id=5, nombre="Torta Naranja Medium", unidad="unidad")

    def por_id(self):
        return {3: self.LECHE, 5: self.TORTA, 7: self.CAFE}

    def test_subtotal_sobre_cantidad_guardada(self):
        # Factura decía "2 CAJA = $33.000"; guardado hay 13.200 ml.
        ext = [{"descripcion": "LECHE X6", "producto_id": 3, "cantidad": 2,
                "unidad": "caja", "precio_unitario": 16500, "subtotal": 33000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(10, 3, 13200)], 50000, self.por_id())
        self.assertEqual(precios, {10: 2.5})  # $/ml
        self.assertEqual(advs, [])

    def test_sin_subtotal_usa_cantidad_por_precio(self):
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": 2,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": None}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 7, 2000)], 100000, self.por_id())
        self.assertEqual(precios, {1: 40.0})  # $/gr

    def test_unidad_product_usa_cantidad_guardada_no_la_de_factura(self):
        # La factura dice "1 und" (mal leído), pero se compraron 10 tortas → el
        # sistema guardó 10. Costo = 30.000 / 10 = 3.000, NO 30.000.
        ext = [{"descripcion": "Torta Naranja", "producto_id": 5, "cantidad": 1,
                "unidad": "und", "precio_unitario": None, "subtotal": 30000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(4, 5, 10)], 100000, self.por_id())
        self.assertEqual(precios, {4: 3000.0})

    def test_match_por_nombre_cuando_falta_id(self):
        # El modelo no puso producto_id: se pega por nombre al catálogo acotado.
        ext = [{"descripcion": "CAFE ALTA TOSTION X KILO", "producto_id": None,
                "cantidad": 1, "unidad": "kg", "precio_unitario": 40000, "subtotal": 40000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 7, 1000)], 100000, self.por_id())
        self.assertEqual(precios, {1: 40.0})

    def test_no_pisa_precio_existente(self):
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": 1,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": 40000}]
        precios, _, _aliases = _precios_para_factura(ext, [item_db(1, 7, 1000, precio=35.0)], 100000, self.por_id())
        self.assertEqual(precios, {})

    def test_subtotal_mayor_al_total_se_ignora(self):
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": 1,
                "unidad": "kg", "precio_unitario": 900000, "subtotal": 900000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 7, 1000)], 100000, self.por_id())
        self.assertEqual(precios, {})
        self.assertEqual(len(advs), 1)

    def test_renglon_incoherente_no_escribe(self):
        # 2×40.000=80.000 pero el subtotal dice 50.000 → una cifra mal leída.
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": 2,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": 50000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 7, 2000)], 100000, self.por_id())
        self.assertEqual(precios, {})
        self.assertIn("no cuadra", advs[0])

    def test_duplicado_mismo_producto_va_a_mano(self):
        # El mismo producto dos veces: no se puede repartir con certeza → a mano.
        ext = [
            {"descripcion": "CAFE 500G", "producto_id": 7, "cantidad": 0.5,
             "unidad": "kg", "precio_unitario": None, "subtotal": 18000},
            {"descripcion": "CAFE 2500G", "producto_id": 7, "cantidad": 2.5,
             "unidad": "kg", "precio_unitario": None, "subtotal": 90000},
        ]
        items = [item_db(1, 7, 2500), item_db(2, 7, 500)]
        precios, advs, _aliases = _precios_para_factura(ext, items, 120000, self.por_id())
        self.assertEqual(precios, {})
        self.assertTrue(any("más de una vez" in a for a in advs))

    def test_granel_costo_implausible_por_cantidad_legacy(self):
        # Legacy "fuga #1": botella guardada como 1 ml. $80.000/1 = $80.000/ml,
        # absurdo para un granel → lo atrapa el guardián de plausibilidad.
        ext = [{"descripcion": "BAILEYS", "producto_id": 3, "cantidad": 1,
                "unidad": "und", "precio_unitario": 80000, "subtotal": 80000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 3, 1)], 100000, self.por_id())
        self.assertEqual(precios, {})
        self.assertIn("mal registrada", advs[0])

    def test_granel_costo_plausible_se_escribe(self):
        # Café a $40/gr es plausible → se escribe aunque no validemos la cantidad.
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": None,
                "unidad": None, "precio_unitario": None, "subtotal": 40000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 7, 1000)], 100000, self.por_id())
        self.assertEqual(precios, {1: 40.0})

    def test_costo_mayor_al_precio_de_venta_no_escribe(self):
        # Gaseosa: caja de 24 registrada como 1 → costo $50.000 > venta $5.000.
        gaseosa = prod(id=9, nombre="Gaseosa", unidad="unidad", precio_venta=5000)
        ext = [{"descripcion": "Gaseosa", "producto_id": 9, "cantidad": 24,
                "unidad": "und", "precio_unitario": None, "subtotal": 50000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 9, 1)], 100000, {9: gaseosa})
        self.assertEqual(precios, {})
        self.assertIn("se vende a", advs[0])

    def test_reventa_costo_bajo_el_precio_se_escribe(self):
        # Gaseosa comprada a $2.000, vendida a $5.000 → costo válido.
        gaseosa = prod(id=9, nombre="Gaseosa", unidad="unidad", precio_venta=5000)
        ext = [{"descripcion": "Gaseosa", "producto_id": 9, "cantidad": 24,
                "unidad": "und", "precio_unitario": None, "subtotal": 48000}]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 9, 24)], 100000, {9: gaseosa})
        self.assertEqual(precios, {1: 2000.0})

    def test_nombre_ambiguo_no_adivina(self):
        # "LECHE" sin id: hay leche entera y deslactosada → empate → no escribe.
        entera = prod(id=3, nombre="Leche entera", unidad="ml")
        desl = prod(id=8, nombre="Leche deslactosada", unidad="ml")
        ext = [{"descripcion": "LECHE", "producto_id": None, "cantidad": 1000,
                "unidad": "ml", "precio_unitario": None, "subtotal": 2500}]
        precios, advs, _aliases = _precios_para_factura(
            ext, [item_db(1, 3, 1000), item_db(2, 8, 1000)], 100000, {3: entera, 8: desl})
        self.assertEqual(precios, {})

    def test_sin_cifras_no_asigna(self):
        ext = [
            {"descripcion": "ZZZ raro", "producto_id": None, "cantidad": 1,
             "unidad": None, "precio_unitario": 100, "subtotal": 100},
            {"descripcion": "Café", "producto_id": 7, "cantidad": None,
             "unidad": None, "precio_unitario": None, "subtotal": None},
        ]
        precios, advs, _aliases = _precios_para_factura(ext, [item_db(1, 7, 1000)], 100000, self.por_id())
        self.assertEqual(precios, {})
        self.assertTrue(any("sin subtotal" in a for a in advs))
        self.assertEqual(len(advs), 1)  # solo Y advierte (X ni siquiera matchea)


class ProveedorDispatchTest(unittest.TestCase):
    """Preferencia de proveedor Gemini → Groq → Claude según la key disponible.
    Gemini primero: schema estructurado, imagen a resolución completa y free
    tier que aguanta una lectura de visión. Groq quedó de respaldo: su tier
    gratis `on_demand` limita a 8.000 TPM y UNA sola request de visión
    (imagen + catálogo) supera ese tope → 429 seguro (producción 2026-07)."""

    def test_reducir_para_groq_achica_la_imagen(self):
        import io
        from PIL import Image
        # Imagen grande (2400px) → debe salir a ≤1280px y como JPEG válido.
        buf = io.BytesIO()
        Image.new("RGB", (2400, 1800), (200, 180, 120)).save(buf, format="JPEG", quality=90)
        out = _reducir_para_groq(buf.getvalue())
        w, h = Image.open(io.BytesIO(out)).size
        self.assertLessEqual(max(w, h), 1280)
        self.assertLessEqual(len(out), 2_800_000)

    def test_dispatcher_prefiere_gemini(self):
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", "gm"), \
             mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", "ak"), \
             mock.patch.object(factura_ocr, "_extraer_con_gemini", return_value={"via": "gemini"}) as mgem, \
             mock.patch.object(factura_ocr, "_extraer_con_groq") as mg, \
             mock.patch.object(factura_ocr, "_extraer_con_claude") as mcl:
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
            self.assertEqual(out, {"via": "gemini"})
            mgem.assert_called_once()
            mg.assert_not_called()
            mcl.assert_not_called()

    def test_con_las_tres_keys_el_primer_post_va_a_generativelanguage(self):
        # Nivel HTTP: con las tres keys puestas, la PRIMERA llamada de red sale
        # hacia Gemini (generativelanguage.googleapis.com), no hacia Groq.
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", "gm"), \
             mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", "ak"), \
             mock.patch("httpx.post", side_effect=[_gemini_200(_EXTR_OK)]) as mpost:
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, _EXTR_OK)
        self.assertEqual(mpost.call_count, 1)
        self.assertIn("generativelanguage.googleapis.com", mpost.call_args.args[0])

    def test_dispatcher_cae_a_groq_sin_gemini(self):
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", ""), \
             mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", ""), \
             mock.patch.object(factura_ocr, "_extraer_con_groq", return_value={"via": "groq"}) as mg:
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
            self.assertEqual(out, {"via": "groq"})
            mg.assert_called_once()

    def test_hay_proveedor_ocr(self):
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", ""), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", ""), \
             mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", ""):
            self.assertFalse(hay_proveedor_ocr())
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", ""), \
             mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", ""):
            self.assertTrue(hay_proveedor_ocr())


class FakeResp:
    """Respuesta HTTP mínima para mockear httpx.post."""

    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("sin json")
        return self._payload


def _groq_404_model():
    return FakeResp(404, {"error": {
        "message": "The model `viejo` does not exist or you do not have access to it.",
        "type": "invalid_request_error", "code": "model_not_found"}})


def _groq_200(extraccion):
    return FakeResp(200, {"choices": [{
        "finish_reason": "stop",
        "message": {"content": json.dumps(extraccion)},
    }]})


def _gemini_200(extraccion):
    return FakeResp(200, {"candidates": [{
        "finishReason": "STOP",
        "content": {"parts": [{"text": json.dumps(extraccion)}]},
    }]})


_EXTR_OK = {"error": None, "proveedor": "X", "numero_factura": None,
            "fecha_factura": None, "valor_total": None, "tipo_pago": None,
            "items": [], "advertencias": []}

# Forma REAL del 429 de Groq en producción (2026-07, primer escaneo con
# qwen3.6-27b): límite POR MINUTO (TPM 8000 del tier gratis `on_demand`, que
# una sola request de visión supera), con la coletilla comercial "Upgrade to
# Dev Tier today" al final — el "day" de ese "today" era lo que el clasificador
# viejo pescaba con `"day" in low` para decir "cuota del DÍA".
_GROQ_429_TPM_REAL = (
    "Rate limit reached for model `qwen/qwen3.6-27b` in organization "
    "`org_abc123` service tier `on_demand` on tokens per minute (TPM): "
    "Limit 8000, Used 0, Requested 9468. Please try again in 11.01s. "
    "Need more tokens? Upgrade to Dev Tier today at "
    "https://console.groq.com/settings/billing"
)


class ModelosGroqTest(unittest.TestCase):
    """Groq retiró llama-4-scout de un día para otro: el modelo configurado va
    primero y detrás una cadena de candidatos vigentes, sin duplicados."""

    def test_configurado_va_primero_y_sin_duplicar(self):
        with mock.patch.object(factura_ocr.settings, "GROQ_MODEL", "modelo-viejo"):
            cadena = _modelos_groq()
        self.assertEqual(cadena[0], "modelo-viejo")
        self.assertIn("qwen/qwen3.6-27b", cadena)
        self.assertEqual(len(cadena), len(set(cadena)))

    def test_default_ya_en_cadena_no_se_repite(self):
        with mock.patch.object(factura_ocr.settings, "GROQ_MODEL", "qwen/qwen3.6-27b"):
            cadena = _modelos_groq()
        self.assertEqual(cadena[0], "qwen/qwen3.6-27b")
        self.assertEqual(len(cadena), len(set(cadena)))

    def test_default_de_config_es_qwen(self):
        from app.config import Settings
        self.assertEqual(Settings.model_fields["GROQ_MODEL"].default, "qwen/qwen3.6-27b")


class ModelosGeminiTest(unittest.TestCase):
    """La cadena Gemini lleva SOLO nombres verificados vivos vía ListModels
    (v1beta, key de producción, 2026-07-23). Fuera de la cadena:
    gemini-2.5-flash (404 "no longer available to new users" en producción) y
    gemini-3-flash (404 "is not found for API version v1beta"). El default
    baja a 3.6-flash porque gemini-3.5-flash respondió 503 "high demand"
    PERSISTENTE (toda una noche y una mañana, no un pico)."""

    def test_cadena_verificada_orden_y_sin_2_5_flash(self):
        with mock.patch.object(factura_ocr.settings, "GEMINI_MODEL", "gemini-3.6-flash"):
            self.assertEqual(_modelos_gemini(),
                             ["gemini-3.6-flash", "gemini-3.5-flash",
                              "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"])

    def test_modelo_custom_va_primero_sin_nombres_muertos_ni_duplicados(self):
        with mock.patch.object(factura_ocr.settings, "GEMINI_MODEL", "gemini-x-custom"):
            cadena = _modelos_gemini()
        self.assertEqual(cadena[0], "gemini-x-custom")
        self.assertNotIn("gemini-3-flash", cadena)   # 404 real en producción
        self.assertNotIn("gemini-2.5-flash", cadena)  # 404 "no longer available to new users"
        self.assertIn("gemini-3.6-flash", cadena)
        self.assertIn("gemini-3.5-flash-lite", cadena)  # verificado en ListModels 2026-07-23
        self.assertEqual(len(cadena), len(set(cadena)))

    def test_default_de_config_es_gemini_3_6_flash(self):
        # 2026-07-23: gemini-3.5-flash lleva noche y mañana en 503 "high
        # demand" — el default pasa al flash más nuevo verificado vivo.
        from app.config import Settings
        self.assertEqual(Settings.model_fields["GEMINI_MODEL"].default, "gemini-3.6-flash")


class ExtraerConGeminiCadenaTest(unittest.TestCase):
    """Réplica de producción (2026-07): 503 "high demand" del primer modelo +
    404 de un nombre muerto consumían el tope de 2 intentos y NUNCA se llegaba
    al modelo vivo. Un 404 de modelo inexistente es instantáneo y no gasta
    tokens: NO consume intento."""

    def test_404_no_consume_intento_y_se_llega_al_modelo_vivo(self):
        alta_demanda = FakeResp(503, {"error": {"message": "The model is overloaded (high demand)"}})
        muerto = FakeResp(404, {"error": {"message":
            "models/gemini-3-flash is not found for API version v1beta, or is "
            "not supported for generateContent."}})
        with mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", "gm"), \
             mock.patch.object(factura_ocr, "_modelos_gemini",
                               return_value=["ocupado", "muerto", "vivo"]), \
             mock.patch("httpx.post",
                        side_effect=[alta_demanda, muerto, _gemini_200(_EXTR_OK)]) as mpost:
            out = _extraer_con_gemini(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, _EXTR_OK)
        self.assertEqual(mpost.call_count, 3)
        self.assertIn("vivo", mpost.call_args_list[2].args[0])


class ExtraerConGroqCadenaTest(unittest.TestCase):
    """Ante 404 model_not_found (modelo retirado) se prueba el siguiente de la
    cadena en la MISMA llamada, sin molestar al usuario."""

    def _con_groq(self, respuestas):
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr.settings, "GROQ_MODEL", "modelo-viejo"), \
             mock.patch.object(factura_ocr, "_reducir_para_groq", side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post", side_effect=respuestas) as mpost:
            out = _extraer_con_groq(b"jpeg", "cat", date(2026, 7, 14))
        return out, mpost

    def test_404_model_not_found_pasa_al_siguiente_modelo(self):
        out, mpost = self._con_groq([_groq_404_model(), _groq_200(_EXTR_OK)])
        self.assertEqual(out, _EXTR_OK)
        self.assertEqual(mpost.call_count, 2)
        modelos = [c.kwargs["json"]["model"] for c in mpost.call_args_list]
        self.assertEqual(modelos[0], "modelo-viejo")
        self.assertEqual(modelos[1], "qwen/qwen3.6-27b")

    def test_400_model_decommissioned_tambien_pasa_al_siguiente(self):
        decomisado = FakeResp(400, {"error": {
            "message": "The model `viejo` has been decommissioned.",
            "type": "invalid_request_error", "code": "model_decommissioned"}})
        out, mpost = self._con_groq([decomisado, _groq_200(_EXTR_OK)])
        self.assertEqual(out, _EXTR_OK)
        self.assertEqual(mpost.call_count, 2)

    def test_400_json_validate_failed_es_error_de_proveedor_502(self):
        # Producción 2026-07-23: qwen devolvió 400 code=json_validate_failed
        # con failed_generation vacío — el modelo no pudo emitir JSON con ESA
        # foto. No es un modelo muerto (no se recorre la cadena): es error de
        # proveedor 502, y la cascada de _extraer pasa al siguiente proveedor.
        invalido = FakeResp(400, {"error": {
            "message": "json_validate_failed: the model failed to generate valid JSON",
            "type": "invalid_request_error", "code": "json_validate_failed",
            "failed_generation": ""}})
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr, "_reducir_para_groq", side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post", side_effect=[invalido]) as mpost:
            with self.assertRaises(HTTPException) as ctx:
                _extraer_con_groq(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(mpost.call_count, 1)  # no prueba el siguiente modelo
        self.assertEqual(ctx.exception.status_code, 502)

    def test_cadena_agotada_lanza_error_de_proveedor(self):
        # Cadena de 2 modelos (dentro del tope): se agota la CADENA, no el
        # tope, y el error es el del proveedor (502 "ningún modelo").
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr, "_modelos_groq", return_value=["m1", "m2"]), \
             mock.patch.object(factura_ocr, "_reducir_para_groq", side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post", side_effect=[_groq_404_model()] * 2) as mpost:
            with self.assertRaises(HTTPException) as ctx:
                _extraer_con_groq(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(mpost.call_count, 2)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("ningún modelo", ctx.exception.detail)

    def test_404_no_consume_intento_y_el_tope_permite_el_modelo_vivo(self):
        # Dos nombres muertos (404 instantáneos, sin tokens) + el vivo: los 404
        # NO cuentan contra el tope de llamadas reales y el vivo SÍ se alcanza.
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr, "_modelos_groq", return_value=["m1", "m2", "m3"]), \
             mock.patch.object(factura_ocr, "_reducir_para_groq", side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post",
                        side_effect=[_groq_404_model(), _groq_404_model(),
                                     _groq_200(_EXTR_OK)]) as mpost:
            out = _extraer_con_groq(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, _EXTR_OK)
        self.assertEqual(mpost.call_count, 3)

    def test_cadena_entera_de_404_recorre_todo_y_da_error_de_proveedor(self):
        # Los 404 no consumen tope: la cadena completa se recorre y el error
        # final es el del proveedor (502 "ningún modelo"), no un falso
        # "se agotó el tiempo" por tope de intentos.
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr.settings, "GROQ_MODEL", "modelo-viejo"), \
             mock.patch.object(factura_ocr, "_reducir_para_groq", side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post", side_effect=[_groq_404_model()] * 6) as mpost:
            cadena = factura_ocr._modelos_groq()
            self.assertGreaterEqual(len(cadena), 3)
            with self.assertRaises(HTTPException) as ctx:
                _extraer_con_groq(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(mpost.call_count, len(cadena))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("ningún modelo", ctx.exception.detail)

    def test_429_tpm_real_de_produccion_clasifica_por_minuto_no_por_dia(self):
        # String real del 429 de producción (2026-07): el límite es POR MINUTO
        # (TPM) pero el mensaje termina en "Upgrade to Dev Tier today" — y el
        # clasificador viejo pescaba el "day" de "toDAY" y decía "cuota del DÍA".
        limitado = FakeResp(429, {"error": {"message": _GROQ_429_TPM_REAL}})
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr, "_reducir_para_groq", side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post", side_effect=[limitado]):
            with self.assertRaises(HTTPException) as ctx:
                _extraer_con_groq(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("esperá un minuto", ctx.exception.detail)
        self.assertNotIn("seguí mañana", ctx.exception.detail)

    def test_429_cuota_diaria_real_clasifica_por_dia(self):
        diario = FakeResp(429, {"error": {"message":
            "Rate limit reached for model `qwen/qwen3.6-27b` in organization "
            "`org_abc` service tier `on_demand` on tokens per day (TPD): "
            "Limit 500000, Used 499900, Requested 9468. "
            "Please try again in 4h32m."}})
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr, "_reducir_para_groq", side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post", side_effect=[diario]):
            with self.assertRaises(HTTPException) as ctx:
                _extraer_con_groq(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("seguí mañana", ctx.exception.detail)

    def test_429_no_prueba_otro_modelo_y_conserva_mensaje(self):
        limitado = FakeResp(429, {"error": {"message": "Rate limit reached, try again in 20s"}})
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr, "_reducir_para_groq", side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post", side_effect=[limitado]) as mpost:
            with self.assertRaises(HTTPException) as ctx:
                _extraer_con_groq(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(mpost.call_count, 1)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("esperá un minuto", ctx.exception.detail)

    def test_respuesta_con_razonamiento_antes_del_json(self):
        # qwen3.6-27b es un modelo con "thinking": puede razonar antes del JSON.
        texto = ("Analizo la factura. El total {parece} ser 80.000.\n\n"
                 "```json\n" + json.dumps(_EXTR_OK) + "\n```")
        resp = FakeResp(200, {"choices": [{
            "finish_reason": "stop", "message": {"content": texto}}]})
        out, _ = self._con_groq([resp])
        self.assertEqual(out, _EXTR_OK)


class PresupuestoEscaneoTest(unittest.TestCase):
    """C1/C2: cada escaneo tiene un deadline total (_BUDGET_SEG) COMPARTIDO por
    toda la cascada, y cada proveedor un tope PROPIO de
    _MAX_INTENTOS_POR_PROVEEDOR llamadas salientes (peor caso 2+2+1 = 5
    llamadas dentro del deadline). El front corta a los 120s: pasado el budget
    no se intenta nada más y el error lo dice."""

    def _keys(self, groq="", gemini="", claude=""):
        return (mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", groq),
                mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", gemini),
                mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", claude))

    def test_budget_agotado_no_intenta_el_siguiente_proveedor(self):
        # Gemini se comió todo el tiempo: Groq NI SE INTENTA y el error lo dice.
        reloj = {"ahora": 0.0}
        k1, k2, k3 = self._keys(groq="gk", gemini="gm")

        def gemini_lento(*a, **kw):
            reloj["ahora"] = factura_ocr._BUDGET_SEG + 1.0
            raise HTTPException(502, "El servicio de escaneo falló")

        with k1, k2, k3, \
             mock.patch.object(factura_ocr.time, "monotonic",
                               side_effect=lambda: reloj["ahora"]), \
             mock.patch.object(factura_ocr, "_extraer_con_gemini", side_effect=gemini_lento), \
             mock.patch.object(factura_ocr, "_extraer_con_groq") as mg:
            with self.assertRaises(HTTPException) as ctx:
                _extraer(b"jpeg", "cat", date(2026, 7, 14))
        mg.assert_not_called()
        self.assertEqual(ctx.exception.status_code, 503)
        low = ctx.exception.detail.lower()
        self.assertIn("se agotó el tiempo de lectura probando proveedores", low)
        # El último error real viaja en el mensaje para poder diagnosticar.
        self.assertIn("el servicio de escaneo falló", low)

    def test_gemini_caido_del_todo_groq_si_recibe_llamadas(self):
        # Gemini caído (toda su cadena con 5xx REALES): quema solo SUS intentos
        # y la cascada sigue con Groq, que rescata el escaneo. (El contrato
        # viejo de tope GLOBAL dejaba al siguiente sin llamadas — ese era el bug.)
        k1, k2, k3 = self._keys(groq="gk", gemini="gm")
        caido = FakeResp(503, {"error": {"message": "Service Unavailable"}})
        with k1, k2, k3, \
             mock.patch.object(factura_ocr.settings, "GEMINI_MODEL", "gemini-3.6-flash"), \
             mock.patch.object(factura_ocr, "_reducir_para_groq",
                               side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post",
                        side_effect=[caido, caido, _groq_200(_EXTR_OK)]) as mpost:
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, _EXTR_OK)
        self.assertEqual(mpost.call_count, 3)
        urls = [c.args[0] for c in mpost.call_args_list]
        self.assertTrue(all("googleapis.com" in u for u in urls[:2]))
        self.assertIn("api.groq.com", urls[2])

    def test_cada_proveedor_arranca_con_su_propio_tope(self):
        # Gemini (cadena de 3) quema SU tope de 2 con errores reales — su
        # tercer modelo NI SE LLAMA — y Groq arranca con contador PROPIO
        # y rescata el escaneo.
        k1, k2, k3 = self._keys(groq="gk", gemini="gm")
        alta_demanda = FakeResp(503, {"error": {"message": "high demand"}})
        tope = factura_ocr._MAX_INTENTOS_POR_PROVEEDOR
        with k1, k2, k3, \
             mock.patch.object(factura_ocr, "_modelos_gemini",
                               return_value=["m1", "m2", "m3"]), \
             mock.patch.object(factura_ocr, "_reducir_para_groq",
                               side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post",
                        side_effect=[alta_demanda] * tope
                                    + [_groq_200(_EXTR_OK)]) as mpost:
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, _EXTR_OK)
        self.assertEqual(mpost.call_count, tope + 1)
        urls = [c.args[0] for c in mpost.call_args_list]
        self.assertTrue(all("googleapis.com" in u for u in urls[:tope]))
        self.assertIn("api.groq.com", urls[tope])

    def test_tope_de_intentos_agotado_da_mensaje_de_proveedores_no_de_tiempo(self):
        # Producción: la cascada murió por TOPE de intentos, pero el usuario
        # leyó "se agotó el tiempo". El mensaje debe decir que los proveedores
        # fallaron, con el último error real — no culpar al reloj.
        k1, k2, k3 = self._keys(gemini="gm")
        alta_demanda = FakeResp(503, {"error": {"message": "The model is overloaded (high demand)"}})
        tope = factura_ocr._MAX_INTENTOS_POR_PROVEEDOR
        with k1, k2, k3, \
             mock.patch.object(factura_ocr, "_modelos_gemini",
                               return_value=["m1", "m2", "m3"]), \
             mock.patch("httpx.post", side_effect=[alta_demanda] * tope) as mpost:
            with self.assertRaises(HTTPException) as ctx:
                _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(mpost.call_count, tope)
        self.assertEqual(ctx.exception.status_code, 503)
        detalle = ctx.exception.detail
        self.assertNotIn("Se agotó el tiempo", detalle)
        self.assertIn("fallaron", detalle)
        self.assertIn("high demand", detalle)  # el último error real viaja

    def test_timeout_por_llamada_es_45_con_budget_completo(self):
        # Con el budget entero, cada llamada pide _TIMEOUT_LLAMADA (45s), no 120.
        k1, k2, k3 = self._keys(groq="gk")
        with k1, k2, k3, \
             mock.patch.object(factura_ocr, "_reducir_para_groq",
                               side_effect=lambda b, **kw: b), \
             mock.patch("httpx.post", side_effect=[_groq_200(_EXTR_OK)]) as mpost:
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, _EXTR_OK)
        self.assertEqual(mpost.call_args.kwargs["timeout"], factura_ocr._TIMEOUT_LLAMADA)

    def test_timeout_por_llamada_se_recorta_al_restante(self):
        # Quedan ~30s de budget: la llamada pide min(45, restante) = 30.
        reloj = {"ahora": 0.0}
        k1, k2, k3 = self._keys(groq="gk")

        def reducir_y_gastar(b, **kw):
            reloj["ahora"] = factura_ocr._BUDGET_SEG - 30.0  # quedan 30s
            return b

        with k1, k2, k3, \
             mock.patch.object(factura_ocr.time, "monotonic",
                               side_effect=lambda: reloj["ahora"]), \
             mock.patch.object(factura_ocr, "_reducir_para_groq",
                               side_effect=reducir_y_gastar), \
             mock.patch("httpx.post", side_effect=[_groq_200(_EXTR_OK)]) as mpost:
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, _EXTR_OK)
        self.assertAlmostEqual(mpost.call_args.kwargs["timeout"], 30.0)


class ClaudeClienteTest(unittest.TestCase):
    """Cableado observable del cliente Anthropic: timeout del presupuesto y
    max_retries=0 (los reintentos son de la cascada; con retries del SDK una
    llamada puede tardar 2× el timeout y romper el budget del escaneo)."""

    def test_timeout_y_max_retries_reales_del_cliente(self):
        import anthropic
        bloque = SimpleNamespace(type="text", text=json.dumps(_EXTR_OK))
        respuesta = SimpleNamespace(stop_reason="end_turn", content=[bloque])
        cliente = mock.MagicMock()
        cliente.messages.create.return_value = respuesta
        with mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", "ak"), \
             mock.patch.object(anthropic, "Anthropic", return_value=cliente) as mcls:
            out = factura_ocr._extraer_con_claude(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, _EXTR_OK)
        kwargs = mcls.call_args.kwargs
        self.assertEqual(kwargs["max_retries"], 0)
        self.assertEqual(kwargs["timeout"], factura_ocr._TIMEOUT_LLAMADA)


class JsonDeTextoTest(unittest.TestCase):
    def test_json_limpio(self):
        self.assertEqual(_json_de_texto('{"a": 1}'), {"a": 1})

    def test_razonamiento_antes_y_fence_markdown(self):
        texto = ("<think>el usuario quiere {'items': algo} raro</think>\n"
                 "```json\n{\"error\": null, \"items\": []}\n```")
        self.assertEqual(_json_de_texto(texto), {"error": None, "items": []})

    def test_prefiere_el_bloque_con_forma_de_extraccion(self):
        texto = '{"foo": 1} y la respuesta: {"error": null, "items": []}'
        self.assertEqual(_json_de_texto(texto), {"error": None, "items": []})

    def test_sin_json_lanza_valueerror(self):
        with self.assertRaises(ValueError):
            _json_de_texto("no hay nada parseable acá { roto")

    def test_llaves_literales_dentro_de_string(self):
        # Una descripción con llaves ("PROMO {2x1}") no rompe el escaneo de
        # llaves balanceadas: dentro de un string JSON las llaves son texto.
        obj = {"error": None, "items": [{"descripcion": "PROMO {2x1} CAFE"}]}
        texto = "el modelo razona un poco antes...\n" + json.dumps(obj)
        self.assertEqual(_json_de_texto(texto), obj)

    def test_json_truncado_lanza_valueerror(self):
        # Simula el recorte por max_tokens a mitad de estructura: debe lanzar
        # el error esperado (→ 502 "no se pudo interpretar"), no devolver basura.
        completo = json.dumps({"error": None, "items": [{"descripcion": "CAFE X KG"}]})
        with self.assertRaises(ValueError):
            _json_de_texto("```json\n" + completo[:len(completo) - 10])

    def test_texto_gigante_se_recorta_antes_de_escanear(self):
        # W2: por encima del cap el texto se recorta ANTES de escanear (con
        # max_tokens=4000 nunca llega legítimamente): un JSON que empieza
        # después del cap no se encuentra.
        relleno = "x" * (factura_ocr._MAX_TEXTO_JSON + 1)
        with self.assertRaises(ValueError):
            _json_de_texto(relleno + '{"error": null, "items": []}')


class FallbackProveedoresTest(unittest.TestCase):
    """_extraer intenta TODOS los proveedores con key, en orden Gemini → Groq
    → Claude, antes de rendirse."""

    def _keys(self, groq="", gemini="", claude=""):
        return (mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", groq),
                mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", gemini),
                mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", claude))

    def test_gemini_agotado_cae_a_groq(self):
        k1, k2, k3 = self._keys(groq="gk", gemini="gm")
        with k1, k2, k3, \
             mock.patch.object(factura_ocr, "_extraer_con_gemini",
                               side_effect=HTTPException(502, "El servicio de escaneo falló")) as mgem, \
             mock.patch.object(factura_ocr, "_extraer_con_groq",
                               return_value={"via": "groq"}) as mg:
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, {"via": "groq"})
        mgem.assert_called_once()
        mg.assert_called_once()

    def test_cuota_de_gemini_con_groq_disponible_no_molesta_al_usuario(self):
        k1, k2, k3 = self._keys(groq="gk", gemini="gm")
        err_cuota = HTTPException(503, "El escaneo gratis no tiene cuota disponible en ninguno de los modelos probados.")
        with k1, k2, k3, \
             mock.patch.object(factura_ocr, "_extraer_con_gemini", side_effect=err_cuota), \
             mock.patch.object(factura_ocr, "_extraer_con_groq",
                               return_value={"via": "groq"}):
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(out, {"via": "groq"})

    def test_429_sin_otro_proveedor_conserva_mensaje_actual(self):
        k1, k2, k3 = self._keys(groq="gk")
        detalle = "Se alcanzó el límite por minuto — esperá un minuto. (Groq: rate limit)"
        with k1, k2, k3, \
             mock.patch.object(factura_ocr, "_extraer_con_groq",
                               side_effect=HTTPException(503, detalle)):
            with self.assertRaises(HTTPException) as ctx:
                _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, detalle)

    def test_todos_caidos_mensaje_distinguible(self):
        k1, k2, k3 = self._keys(groq="gk", gemini="gm")
        with k1, k2, k3, \
             mock.patch.object(factura_ocr, "_extraer_con_groq",
                               side_effect=HTTPException(503, "Se agotó la cuota gratis del DÍA")), \
             mock.patch.object(factura_ocr, "_extraer_con_gemini",
                               side_effect=HTTPException(503, "El escaneo gratis no tiene cuota")):
            with self.assertRaises(HTTPException) as ctx:
                _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("caídos o sin cuota", ctx.exception.detail)

    def test_422_de_imagen_no_reintenta_con_otro_proveedor(self):
        # Si el modelo LEYÓ la imagen y dijo "esto no es una factura", cambiar
        # de proveedor no ayuda: se devuelve de una.
        k1, k2, k3 = self._keys(groq="gk", gemini="gm")
        with k1, k2, k3, \
             mock.patch.object(factura_ocr, "_extraer_con_gemini",
                               side_effect=HTTPException(422, "no es una factura")), \
             mock.patch.object(factura_ocr, "_extraer_con_groq") as mg:
            with self.assertRaises(HTTPException) as ctx:
                _extraer(b"jpeg", "cat", date(2026, 7, 14))
        self.assertEqual(ctx.exception.status_code, 422)
        mg.assert_not_called()


class FuzzyEnVivoTest(unittest.TestCase):
    """Cuando la IA no asigna producto_id, mapear_items intenta el match por
    nombre (mismos umbrales del backfill) antes de rendirse."""

    def test_fuzzy_matchea_nombre_distinto_con_advertencia(self):
        cafe = prod(id=7, nombre="Café alta tostión", unidad="gr")
        extr = {"items": [{
            "descripcion": "CAFE ALTA TOSTION X KG", "cantidad": 2, "unidad": "kg",
            "precio_unitario": 40000, "subtotal": 80000,
            "numero_lote": None, "fecha_vencimiento": None, "producto_id": None,
        }]}
        it = mapear_items(extr, [cafe])[0]
        self.assertEqual(it["producto_id"], 7)
        self.assertEqual(it["producto_nombre"], "Café alta tostión")
        self.assertEqual(it["cantidad"], 2000.0)
        self.assertAlmostEqual(it["precio_unitario"], 40.0)
        self.assertIn("similitud", it["advertencia"])
        self.assertIn("CAFE ALTA TOSTION X KG", it["advertencia"])

    def test_fuzzy_ambiguo_no_matchea(self):
        entera = prod(id=3, nombre="Leche entera", unidad="ml")
        desl = prod(id=8, nombre="Leche deslactosada", unidad="ml")
        extr = {"items": [{
            "descripcion": "LECHE", "cantidad": 1000, "unidad": "ml",
            "precio_unitario": None, "subtotal": None,
            "numero_lote": None, "fecha_vencimiento": None, "producto_id": None,
        }]}
        it = mapear_items(extr, [entera, desl])[0]
        self.assertIsNone(it["producto_id"])
        self.assertIn("inventario", it["advertencia"])

    def test_fuzzy_conserva_advertencia_de_conversion(self):
        # Matchea por nombre PERO la unidad no cuadra: las dos advertencias viajan.
        cafe = prod(id=7, nombre="Café alta tostión", unidad="unidad")
        extr = {"items": [{
            "descripcion": "CAFE ALTA TOSTION", "cantidad": 500, "unidad": "gr",
            "precio_unitario": None, "subtotal": None,
            "numero_lote": None, "fecha_vencimiento": None, "producto_id": None,
        }]}
        it = mapear_items(extr, [cafe])[0]
        self.assertEqual(it["producto_id"], 7)
        self.assertIn("similitud", it["advertencia"])
        self.assertIn("gramos", it["advertencia"])

    def test_descripcion_original_viaja_siempre(self):
        # La Fase 2 (aliases) necesita el texto TAL CUAL de la factura.
        cafe = prod(id=7, nombre="Café alta tostión", unidad="gr")
        extr = {"items": [
            {"descripcion": "CAFE ALTA TOSTION X KG", "cantidad": 1, "unidad": "kg",
             "precio_unitario": None, "subtotal": None,
             "numero_lote": None, "fecha_vencimiento": None, "producto_id": 7},
            {"descripcion": "SERVILLETAS CUADRADAS", "cantidad": 2, "unidad": "paca",
             "precio_unitario": None, "subtotal": None,
             "numero_lote": None, "fecha_vencimiento": None, "producto_id": None},
        ]}
        out = mapear_items(extr, [cafe])
        self.assertEqual(out[0]["descripcion"], "CAFE ALTA TOSTION X KG")
        self.assertEqual(out[1]["descripcion"], "SERVILLETAS CUADRADAS")


class HelpersTest(unittest.TestCase):
    def test_fecha_iso(self):
        self.assertEqual(_fecha_iso("2026-07-12"), "2026-07-12")
        self.assertEqual(_fecha_iso("2026-07-12T00:00:00"), "2026-07-12")
        self.assertIsNone(_fecha_iso("12/07/2026"))
        self.assertIsNone(_fecha_iso("2026-13-45"))
        self.assertIsNone(_fecha_iso(None))
        self.assertIsNone(_fecha_iso(20260712))

    def test_validar_suma_detecta_descuadre(self):
        advertencias = []
        _validar_suma({"valor_total": 100000, "items": [{"subtotal": 40000}, {"subtotal": 40000}]}, advertencias)
        self.assertEqual(len(advertencias), 1)
        self.assertIn("no coincide", advertencias[0])

    def test_validar_suma_ok_no_agrega(self):
        advertencias = []
        _validar_suma({"valor_total": 80000, "items": [{"subtotal": 40000}, {"subtotal": 40000}]}, advertencias)
        self.assertEqual(advertencias, [])

    def test_validar_suma_con_subtotal_ilegible_no_opina(self):
        advertencias = []
        _validar_suma({"valor_total": 100000, "items": [{"subtotal": 40000}, {"subtotal": None}]}, advertencias)
        self.assertEqual(advertencias, [])


if __name__ == "__main__":
    unittest.main()
