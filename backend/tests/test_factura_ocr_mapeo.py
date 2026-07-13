"""Mapeo determinístico del escaneo de facturas: conversión de unidades de la
factura a la unidad del inventario. Acá se juega que el stock no quede en una
magnitud equivocada — todo lo dudoso debe salir como advertencia, nunca como
una cantidad adivinada."""
import unittest
from types import SimpleNamespace
from unittest import mock

from app.services import factura_ocr
from app.services.factura_ocr import (
    _convertir_cantidad, _extraer, _fecha_iso, _precios_para_factura,
    _reducir_para_groq, _validar_suma, hay_proveedor_ocr, mapear_items,
)


def prod(id=1, nombre="Café", unidad="gr", cpe=None):
    return SimpleNamespace(
        id=id, nombre=nombre, unidad_medida=unidad,
        contenido_por_empaque=cpe, categoria="insumos",
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
    """Backfill: derivar costo por unidad ALMACENADA desde el renglón leído.
    Regla de oro: solo se escribe si la cantidad de la factura coincide con la
    guardada — sin coincidencia, el precio va a mano."""

    LECHE = prod(id=3, nombre="Leche", unidad="ml", cpe=6600)
    CAFE = prod(id=7, nombre="Café", unidad="gr")

    def por_id(self):
        return {3: self.LECHE, 7: self.CAFE}

    def test_subtotal_sobre_cantidad_guardada(self):
        # Factura decía "2 CAJA = $33.000"; guardado hay 13.200 ml (2×6.600) ✓.
        ext = [{"descripcion": "LECHE X6", "producto_id": 3, "cantidad": 2,
                "unidad": "caja", "precio_unitario": 16500, "subtotal": 33000}]
        precios, advs = _precios_para_factura(ext, [item_db(10, 3, 13200)], 50000, self.por_id())
        self.assertEqual(precios, {10: 2.5})  # $/ml
        self.assertEqual(advs, [])

    def test_sin_subtotal_usa_cantidad_por_precio(self):
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": 2,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": None}]
        precios, advs = _precios_para_factura(ext, [item_db(1, 7, 2000)], 100000, self.por_id())
        self.assertEqual(precios, {1: 40.0})  # $/gr

    def test_no_pisa_precio_existente(self):
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": 1,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": 40000}]
        precios, _ = _precios_para_factura(ext, [item_db(1, 7, 1000, precio=35.0)], 100000, self.por_id())
        self.assertEqual(precios, {})

    def test_subtotal_mayor_al_total_se_ignora(self):
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": 1,
                "unidad": "kg", "precio_unitario": 900000, "subtotal": 900000}]
        precios, advs = _precios_para_factura(ext, [item_db(1, 7, 1000)], 100000, self.por_id())
        self.assertEqual(precios, {})
        self.assertEqual(len(advs), 1)

    def test_dos_renglones_mismo_producto_distinta_presentacion(self):
        # 2.5 kg ($90.000) y 0.5 kg ($18.000): cada subtotal debe caer en el item
        # con la cantidad que le corresponde, sin importar el orden.
        ext = [
            {"descripcion": "CAFE 500G", "producto_id": 7, "cantidad": 0.5,
             "unidad": "kg", "precio_unitario": None, "subtotal": 18000},
            {"descripcion": "CAFE 2500G", "producto_id": 7, "cantidad": 2.5,
             "unidad": "kg", "precio_unitario": None, "subtotal": 90000},
        ]
        items = [item_db(1, 7, 2500), item_db(2, 7, 500)]  # orden invertido a propósito
        precios, advs = _precios_para_factura(ext, items, 120000, self.por_id())
        self.assertEqual(precios, {2: 36.0, 1: 36.0})
        self.assertEqual(advs, [])

    def test_cantidad_guardada_que_no_coincide_no_escribe(self):
        # Caso legacy "fuga #1": botella registrada como 1 gr. La factura dice
        # "1 und" (= 6.600 ml) pero el sistema guardó 1 → NO dividir $80.000/1.
        ext = [{"descripcion": "BAILEYS", "producto_id": 3, "cantidad": 1,
                "unidad": "und", "precio_unitario": 80000, "subtotal": 80000}]
        precios, advs = _precios_para_factura(ext, [item_db(1, 3, 1)], 100000, self.por_id())
        self.assertEqual(precios, {})
        self.assertEqual(len(advs), 1)
        self.assertIn("no coincide", advs[0])

    def test_cantidad_de_factura_inconvertible_no_escribe(self):
        ext = [{"descripcion": "CAFE", "producto_id": 7, "cantidad": None,
                "unidad": "kg", "precio_unitario": 40000, "subtotal": 40000}]
        precios, advs = _precios_para_factura(ext, [item_db(1, 7, 1000)], 100000, self.por_id())
        self.assertEqual(precios, {})
        self.assertEqual(len(advs), 1)

    def test_sin_producto_id_o_sin_cifras_no_asigna(self):
        ext = [
            {"descripcion": "X", "producto_id": None, "cantidad": 1,
             "unidad": None, "precio_unitario": 100, "subtotal": 100},
            {"descripcion": "Y", "producto_id": 7, "cantidad": None,
             "unidad": None, "precio_unitario": None, "subtotal": None},
        ]
        precios, advs = _precios_para_factura(ext, [item_db(1, 7, 1000)], 100000, self.por_id())
        self.assertEqual(precios, {})
        self.assertEqual(len(advs), 1)  # solo Y advierte (X ni siquiera matchea)


class ProveedorDispatchTest(unittest.TestCase):
    """Preferencia de proveedor Groq → Gemini → Claude según la key disponible."""

    def test_reducir_para_groq_deja_pasar_lo_chico(self):
        chico = b"x" * 1000
        self.assertIs(_reducir_para_groq(chico), chico)

    def test_dispatcher_prefiere_groq(self):
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", "gm"), \
             mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", "ak"), \
             mock.patch.object(factura_ocr, "_extraer_con_groq", return_value={"via": "groq"}) as mg, \
             mock.patch.object(factura_ocr, "_extraer_con_gemini") as mgem, \
             mock.patch.object(factura_ocr, "_extraer_con_claude") as mcl:
            from datetime import date
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
            self.assertEqual(out, {"via": "groq"})
            mg.assert_called_once()
            mgem.assert_not_called()
            mcl.assert_not_called()

    def test_dispatcher_cae_a_gemini_sin_groq(self):
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", ""), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", "gm"), \
             mock.patch.object(factura_ocr, "_extraer_con_gemini", return_value={"via": "gemini"}) as mgem:
            from datetime import date
            out = _extraer(b"jpeg", "cat", date(2026, 7, 14))
            self.assertEqual(out, {"via": "gemini"})
            mgem.assert_called_once()

    def test_hay_proveedor_ocr(self):
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", ""), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", ""), \
             mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", ""):
            self.assertFalse(hay_proveedor_ocr())
        with mock.patch.object(factura_ocr.settings, "GROQ_API_KEY", "gk"), \
             mock.patch.object(factura_ocr.settings, "GEMINI_API_KEY", ""), \
             mock.patch.object(factura_ocr.settings, "ANTHROPIC_API_KEY", ""):
            self.assertTrue(hay_proveedor_ocr())


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
