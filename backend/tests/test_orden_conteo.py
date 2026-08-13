"""Orden fijo del conteo (el recorrido físico con que se camina el local).

El matching es la parte peligrosa: un match de más pone un producto en la
posición de OTRO y la barista cuenta la fila equivocada. Por eso la regla es
"solo con certeza" — igualdad normalizada o prefijo declarado — y todo lo
demás queda sin orden, al final, alfabético.
"""
import json
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Producto, CategoriaProductoEnum
from app.services import orden_conteo as svc


def _prod(nombre, **kw):
    return Producto(nombre=nombre, categoria=kw.pop("categoria", CategoriaProductoEnum.bebida),
                    unidad_medida=kw.pop("unidad_medida", "und"),
                    controla_stock=True, incluir_en_conteo=True, **kw)


# ── Catálogo de producción CONOCIDO (nombres reales vistos en capturas) ───────
# Es la única forma honesta de probar el matcher: contra los nombres que la
# base real tiene, no contra los que la lista del dueño usa.
CATALOGO_REAL = [
    "Café Alta Tostión x2500g", "Café Libra Medium 500g", "Libra Medium Cafe Exportacion",
    "Almojábanas", "Torta de almojabana",
    "Torta Chocolate", "Torta Naranja", "Torta Zanahoria", "Torta Red Velvet",
    "Pastel de Pollo", "Esponjado de Queso", "Omelette", "Omelette de Jamon y Queso",
    "Croissant de Chocolate", "Croissant Mantequilla", "Masa Pandebono",
    "Chai Latte", "Agua Normal Botella", "Agua con Gas Botella",
    "Licor Baileys x700ml", "Licor Baileys x1000ml",
    "Licor Whisky Black & White x700ml", "Licor Amaretto x750ml",
    "SABORIZANTE MACADAMIA", "Saborizante Vainilla", "Saborizante Canela",
    "Saborizante Frutos Amarillos", "Saborizante Kiwi Fresa",
    "PULPA DE MANGO", "Pulpa Lulo", "Pulpa Mora", "Pulpa Limón",
    "Leche Deslactosada", "Leche Entera", "LECHE CONDENSADA", "LECHE EN POLVO",
    "Sour Cream", "Salsa Chocolate", "Salsa Caramelo", "Salsa Frutos Rojos",
    "Salsa Maracuyá",
    "Aromatica de Cidron", "Aromática Manzanilla",
    "Azucar", "Azucar a Granel", "Azúcar Blanca Tubos",
    "MILO", "Galleta Oreo",
    # Fuera de la lista del dueño — deben quedar sin orden.
    "Helado Vainilla", "MEZCLA GRANIZADO (preparada)", "Café Descafeinado",
]


def _catalogo(nombres=None):
    """[(id, nombre)] con ids estables, como los entrega la DB."""
    return list(enumerate(nombres if nombres is not None else CATALOGO_REAL, start=1))


class EntradasJsonTest(unittest.TestCase):
    """El archivo que se despacha tiene que ser legible y coherente."""

    def setUp(self):
        self.entradas = svc.cargar_entradas()

    def test_los_tres_bloques_del_dueno(self):
        bloques = sorted({e["bloque"] for e in self.entradas})
        self.assertEqual([1, 2, 3], bloques)

    def test_ordenes_crecientes_y_con_salto_entre_bloques(self):
        ordenes = [e["orden_base"] for e in self.entradas]
        self.assertEqual(ordenes, sorted(ordenes), "el orden base debe ir creciendo")
        self.assertEqual(len(ordenes), len(set(ordenes)), "sin órdenes repetidos")
        # El salto entre bloques deja lugar para intercalar sin renumerar todo.
        b1 = [e["orden_base"] for e in self.entradas if e["bloque"] == 1]
        b2 = [e["orden_base"] for e in self.entradas if e["bloque"] == 2]
        self.assertGreaterEqual(min(b2) - max(b1), 100)

    def test_toda_entrada_declara_variantes_o_prefijo(self):
        for e in self.entradas:
            with self.subTest(entrada=e["entrada"]):
                self.assertTrue(e["variantes"] or e["prefijo"])


class MatchingConservadorTest(unittest.TestCase):
    """Los casos que el dueño puso como línea roja."""

    def setUp(self):
        self.entradas = svc.cargar_entradas()
        self.res = svc.emparejar(self.entradas, _catalogo())
        self.por_nombre = {n: i for i, n in _catalogo()}

    def _entrada_de(self, nombre_producto):
        """Qué entrada de la lista se quedó con este producto (o None)."""
        pid = self.por_nombre[nombre_producto]
        for e in self.res["por_entrada"]:
            if any(p["id"] == pid for p in e["productos"]):
                return e["entrada"]
        return None

    def _orden_de(self, nombre_producto):
        return self.res["asignaciones"].get(self.por_nombre[nombre_producto])

    # ── x700 no puede capturar al x1000 ──────────────────────────────────────
    def test_baileys_700_y_1000_van_a_entradas_distintas(self):
        self.assertEqual("LICOR BAILEYS X700ML", self._entrada_de("Licor Baileys x700ml"))
        self.assertEqual("LICOR BAILEYS X1000ML", self._entrada_de("Licor Baileys x1000ml"))
        self.assertNotEqual(self._orden_de("Licor Baileys x700ml"),
                            self._orden_de("Licor Baileys x1000ml"))

    def test_whisky_x1000_sin_producto_no_roba_el_x700(self):
        # En el catálogo real solo existe el x700ml. La entrada del x1000ml
        # tiene que quedar vacía, no llevarse el x700.
        self.assertEqual("LICOR WHISKY X700ML",
                         self._entrada_de("Licor Whisky Black & White x700ml"))

    # ── azúcar: tres cosas distintas ─────────────────────────────────────────
    def test_azucar_tubipack_no_se_lleva_la_granel(self):
        self.assertEqual("AZUCAR TUBIPACK", self._entrada_de("Azúcar Blanca Tubos"))

    def test_azucar_pelada_queda_sin_orden_pero_a_granel_matchea(self):
        # "Azucar" a secas NO esta en el recorrido: NULL. "Azucar a Granel" SI es
        # el bulto de 2.5 kg — no por adivinar, sino porque la tabla de alias del
        # propio dueno lo dice (_conteo_diario_lista.txt:45:
        # 'AZUCAR X 2.5 KG = Azucar a Granel x2500'). La primera version de este
        # test fijaba lo contrario y con eso mando el azucar al final en produccion.
        self.assertIsNone(self._orden_de("Azucar"))
        self.assertIsNone(self._entrada_de("Azucar"))
        self.assertEqual("AZUCAR X 2.5 KG", self._entrada_de("Azucar a Granel"))

    # ── torta ≠ salsa ────────────────────────────────────────────────────────
    def test_t_chocolate_es_torta_y_jamas_la_salsa(self):
        self.assertEqual("T CHOCOLATE", self._entrada_de("Torta Chocolate"))
        self.assertEqual("SALSA CHOCOLATE", self._entrada_de("Salsa Chocolate"))
        # La torta va en el bloque 1 (vitrina) y la salsa en el 2: muy lejos.
        self.assertLess(self._orden_de("Torta Chocolate"), self._orden_de("Salsa Chocolate"))

    def test_almojabanas_no_captura_la_torta_de_almojabana(self):
        self.assertEqual("ALMOJABANAS", self._entrada_de("Almojábanas"))
        self.assertIsNone(self._entrada_de("Torta de almojabana"))

    def test_omelette_pelado_no_captura_el_de_jamon_y_queso(self):
        self.assertEqual("OMELETTE", self._entrada_de("Omelette"))
        self.assertEqual("OMELETTE JAMON Y QUESO",
                         self._entrada_de("Omelette de Jamon y Queso"))

    # ── VELINO es la marca; el catálogo dice SABORIZANTE ─────────────────────
    def test_velino_matchea_saborizante(self):
        self.assertEqual("VELINO MACADAMIA", self._entrada_de("SABORIZANTE MACADAMIA"))
        self.assertEqual("VELINO VAINILLA", self._entrada_de("Saborizante Vainilla"))
        self.assertEqual("VELINO KIWI FRESA", self._entrada_de("Saborizante Kiwi Fresa"))

    # ── prefijo: una entrada expande a varios productos ──────────────────────
    def test_pulpas_expande_y_ordena_alfabetico_adentro(self):
        pulpas = [e for e in self.res["por_entrada"] if e["entrada"] == "PULPAS JUGO"][0]
        nombres = [p["nombre"] for p in pulpas["productos"]]
        self.assertEqual({"PULPA DE MANGO", "Pulpa Limón", "Pulpa Lulo", "Pulpa Mora"},
                         set(nombres))
        ordenes = [p["orden"] for p in pulpas["productos"]]
        self.assertEqual(ordenes, sorted(ordenes))
        # Alfabético normalizado entre ellas, y las cuatro juntas y contiguas.
        self.assertEqual(nombres, sorted(nombres, key=svc.normalizar))
        self.assertEqual(max(ordenes) - min(ordenes), len(ordenes) - 1)

    def test_aromaticas_expande_por_prefijo(self):
        aroma = [e for e in self.res["por_entrada"] if e["entrada"] == "AROMATICAS"][0]
        self.assertEqual({"Aromatica de Cidron", "Aromática Manzanilla"},
                         {p["nombre"] for p in aroma["productos"]})

    def test_una_entrada_de_prefijo_no_invade_el_orden_de_la_siguiente(self):
        for e in self.res["por_entrada"]:
            for p in e["productos"]:
                with self.subTest(entrada=e["entrada"], producto=p["nombre"]):
                    self.assertLess(p["orden"], e["orden_base"] + svc.PASO)

    # ── lo que no matchea queda afuera ───────────────────────────────────────
    def test_producto_sin_match_queda_sin_orden(self):
        for nombre in ("Helado Vainilla", "MEZCLA GRANIZADO (preparada)", "Café Descafeinado"):
            with self.subTest(nombre=nombre):
                self.assertIsNone(self._orden_de(nombre))
        sin = {n for _, n in self.res["sin_match"]}
        self.assertIn("Helado Vainilla", sin)

    def test_ningun_producto_recibe_dos_ordenes(self):
        vistos = [p["id"] for e in self.res["por_entrada"] for p in e["productos"]]
        self.assertEqual(len(vistos), len(set(vistos)),
                         "un producto no puede quedar en dos posiciones del recorrido")

    def test_entradas_sin_producto_se_reportan(self):
        # "BATI CREMA" no tiene producto en el catalogo (el dueno la lista aparte
        # de CHANTILLY, y ningun nombre del sistema dice bati crema).
        vacias = {e["entrada"] for e in self.res["por_entrada"] if not e["productos"]}
        self.assertIn("BATI CREMA", vacias)

    def test_catalogo_vacio_no_revienta(self):
        res = svc.emparejar(self.entradas, [])
        self.assertEqual({}, res["asignaciones"])
        self.assertEqual([], res["sin_match"])


class NormalizacionTest(unittest.TestCase):
    def test_reusa_la_normalizacion_de_alias(self):
        from app.services.producto_alias import normalizar_alias
        self.assertIs(svc.normalizar, normalizar_alias)

    def test_tildes_y_mayusculas_son_el_mismo_nombre(self):
        self.assertEqual(svc.normalizar("Salsa Maracuyá"), svc.normalizar("SALSA MARACUYA"))
        self.assertEqual(svc.normalizar("  Torta   Chocolate "), "TORTA CHOCOLATE")


class CargadorTest(unittest.TestCase):
    """El cargador escribe en la DB: idempotente y respetuoso del humano."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.db.add_all([_prod(n) for n in CATALOGO_REAL])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _orden(self, nombre):
        return self.db.query(Producto).filter_by(nombre=nombre).first().orden_conteo

    def _snapshot(self):
        return {p.nombre: p.orden_conteo for p in self.db.query(Producto).all()}

    def test_asigna_el_recorrido(self):
        r = svc.aplicar(self.db)
        self.assertGreater(r["asignados"], 20)
        self.assertLess(self._orden("Café Alta Tostión x2500g"), self._orden("Salsa Maracuyá"))
        self.assertIsNone(self._orden("Helado Vainilla"))

    def test_idempotente(self):
        svc.aplicar(self.db)
        antes = self._snapshot()
        r2 = svc.aplicar(self.db)
        self.assertEqual(antes, self._snapshot(), "correrlo dos veces cambió el estado")
        self.assertEqual(0, r2["asignados"])

    def test_no_pisa_un_orden_editado_a_mano(self):
        p = self.db.query(Producto).filter_by(nombre="Torta Chocolate").first()
        p.orden_conteo = 777
        self.db.commit()
        svc.aplicar(self.db)
        self.assertEqual(777, self._orden("Torta Chocolate"))

    def test_reasigna_si_el_humano_lo_devuelve_a_null(self):
        # La salida honesta: el admin borra la posición (PATCH con -1) y el
        # cargador la vuelve a sembrar en el próximo arranque.
        svc.aplicar(self.db)
        original = self._orden("Torta Chocolate")
        p = self.db.query(Producto).filter_by(nombre="Torta Chocolate").first()
        p.orden_conteo = None
        self.db.commit()
        svc.aplicar(self.db)
        self.assertEqual(original, self._orden("Torta Chocolate"))

    def test_json_malformado_no_tumba_el_arranque(self):
        ruta = os.path.join(tempfile.gettempdir(), "orden_conteo_roto.json")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("{ esto no es json")
        try:
            antes = self._snapshot()
            r = svc.sembrar(self.db, ruta=ruta)   # no debe levantar
            self.assertFalse(r["ok"])
            self.assertEqual(antes, self._snapshot(), "un JSON roto no puede escribir nada")
        finally:
            os.remove(ruta)

    def test_json_ausente_no_tumba_el_arranque(self):
        r = svc.sembrar(self.db, ruta=os.path.join(tempfile.gettempdir(), "no_existe_jamas.json"))
        self.assertFalse(r["ok"])

    def test_entrada_sin_variantes_ni_prefijo_es_json_invalido(self):
        ruta = os.path.join(tempfile.gettempdir(), "orden_conteo_incompleto.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "bloques": [{"entradas": [{"entrada": "X"}]}]}, f)
        try:
            r = svc.sembrar(self.db, ruta=ruta)
            self.assertFalse(r["ok"])
        finally:
            os.remove(ruta)


class ReporteTest(unittest.TestCase):
    """El reporte es la única forma de verificar contra el catálogo REAL."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.db.add_all([_prod(n) for n in CATALOGO_REAL])
        self.db.commit()
        svc.aplicar(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_dice_que_matcheo_con_que(self):
        rep = svc.reporte(self.db)
        entrada = [e for e in rep["entradas"] if e["entrada"] == "VELINO MACADAMIA"][0]
        self.assertEqual(["SABORIZANTE MACADAMIA"], [p["nombre"] for p in entrada["productos"]])

    def test_lista_las_entradas_sin_producto(self):
        # BATI CREMA: el dueno la lista aparte de CHANTILLY y ningun nombre del
        # sistema dice "bati crema" — queda sin producto y el reporte lo dice.
        # (AZUCAR X 2.5 KG ya NO va aca: la tabla de alias del dueno la resuelve.)
        rep = svc.reporte(self.db)
        self.assertIn("BATI CREMA", [e["entrada"] for e in rep["entradas_sin_producto"]])
        self.assertNotIn("AZUCAR X 2.5 KG", [e["entrada"] for e in rep["entradas_sin_producto"]])

    def test_lista_los_productos_sin_orden(self):
        rep = svc.reporte(self.db)
        sin = [p["nombre"] for p in rep["productos_sin_orden"]]
        self.assertIn("Helado Vainilla", sin)
        # "Azucar" pelada no esta en el recorrido; "Azucar a Granel" SI matchea
        # (tabla de alias del dueno) y por eso ya no aparece aca.
        self.assertIn("Azucar", sin)
        self.assertNotIn("Azucar a Granel", sin)
        self.assertNotIn("Torta Chocolate", sin)

    def test_marca_las_posiciones_editadas_a_mano(self):
        p = self.db.query(Producto).filter_by(nombre="Torta Chocolate").first()
        p.orden_conteo = 777
        self.db.commit()
        rep = svc.reporte(self.db)
        editados = {e["nombre"]: e for e in rep["editados_a_mano"]}
        self.assertIn("Torta Chocolate", editados)
        self.assertEqual(777, editados["Torta Chocolate"]["orden_actual"])

    def test_los_totales_cuadran(self):
        rep = svc.reporte(self.db)
        self.assertEqual(len(CATALOGO_REAL), rep["total_productos"])
        self.assertEqual(rep["total_productos"],
                         rep["con_orden"] + len(rep["productos_sin_orden"]))


if __name__ == "__main__":
    unittest.main()


class CatalogoRealDeVidaTest(unittest.TestCase):
    """El recorrido contra el catálogo que DE VERDAD se cargó en la sede.

    La primera versión de las variantes se escribió contra los nombres semilla
    de main.py::PRODUCTOS_REALES y pasó 32 tests — porque el fixture era un
    espejo de la misma suposición equivocada. En producción, el café con que
    ARRANCA el recorrido del dueño quedaba último en pantalla.

    Este test cierra esa clase de fallo entera: corre el matcher contra
    `backend/inventario_inicial.json` (la carga clean-slate real de Vida,
    commiteada) y exige que TODO el bloque 1 —la vitrina, donde empieza la
    caminata— tenga producto asignado."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        raiz = Path(__file__).resolve().parents[1]
        with open(raiz / "inventario_inicial.json", encoding="utf-8") as f:
            inv = json.load(f)
        # El universo del conteo diario: exactamente lo que la barista cuenta.
        cls.catalogo = [(i, item["nombre"]) for i, item in enumerate(inv) if item.get("diario")]
        cls.entradas = svc.cargar_entradas()
        cls.res = svc.emparejar(cls.entradas, cls.catalogo)
        cls.nombre_por_id = dict(cls.catalogo)

    def test_todo_el_bloque_1_tiene_producto_en_el_catalogo_real(self):
        sin_producto = [e["entrada"] for e in self.res["por_entrada"]
                        if e["bloque"] == 1 and not e["productos"]]
        self.assertEqual(sin_producto, [],
                         "Entradas del bloque 1 (la vitrina, el ARRANQUE del recorrido) "
                         f"sin producto en el catálogo real de Vida: {sin_producto}")

    def test_los_dos_cafes_arrancan_el_recorrido(self):
        """El defecto exacto que se corrigió: 'Cafe Alta Tostion (granel)' y
        'CAFÉ LIBRA MEDIUM CAFÉ EXPORTACION' iban al final por no matchear."""
        ordenes = {self.nombre_por_id[pid]: orden
                   for pid, orden in self.res["asignaciones"].items()}
        self.assertIn("Cafe Alta Tostion (granel)", ordenes)
        self.assertIn("CAFÉ LIBRA MEDIUM CAFÉ EXPORTACION", ordenes)
        resto = [o for n, o in ordenes.items()
                 if n not in ("Cafe Alta Tostion (granel)", "CAFÉ LIBRA MEDIUM CAFÉ EXPORTACION")]
        self.assertLess(ordenes["Cafe Alta Tostion (granel)"], min(resto))

    def test_azucar_a_granel_matchea_por_la_tabla_de_alias_del_dueno(self):
        """_conteo_diario_lista.txt:45: 'AZUCAR X 2.5 KG = Azúcar a Granel x2500'."""
        nombres = {self.nombre_por_id[pid] for pid in self.res["asignaciones"]}
        self.assertIn("Azucar a Granel", nombres)
