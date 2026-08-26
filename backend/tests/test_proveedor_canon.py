"""Un proveedor, un nombre.

En producción había 41 nombres de proveedor para ~23 negocios reales: «Galerías»,
«Galerias» y «Galeria» eran el mismo supermercado con 17 facturas partidas en
tres. El nombre es texto libre que sale del tecleo o de la foto, así que cada
variante nacía un proveedor nuevo y «cuánto le compro a Galerías» daba un número
que no era.

Estos tests fijan las dos reglas del canon y —más importante— fijan LO QUE NO
DEBE FUNDIR: mezclar dos proveedores distintos es peor que dejar una grafía
suelta, porque junta la plata de dos negocios y eso no se nota mirando la
pantalla. Los casos son los REALES de producción.
"""
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import FacturaCompra, RolEnum, Tienda, TipoPagoEnum, Usuario
from app.services import proveedor_canon as canon


class ClaveTest(unittest.TestCase):
    """La huella: sin tildes, sin mayúsculas, sin puntuación, sin coletillas."""

    def test_tildes_y_mayusculas_dan_la_misma_clave(self):
        self.assertEqual(canon.clave("Galerías"), canon.clave("GALERIAS"))
        self.assertEqual(canon.clave("Galerías"), canon.clave("  galerias  "))

    def test_los_espacios_no_cuentan(self):
        # El caso «Cafex coop» vs «Cafexcoop», que estaba partido en producción.
        self.assertEqual(canon.clave("Cafexcoop"), canon.clave("Cafex coop"))

    def test_coletilla_juridica_se_va(self):
        self.assertEqual(canon.clave("KOS COLOMBIA"), canon.clave("KOS COLOMBIA S.A.S"))
        self.assertEqual(canon.clave("Quala"), canon.clave("Quala S.A."))
        self.assertEqual(canon.clave("Altipal"), canon.clave("ALTIPAL"))

    def test_generico_del_rubro_se_va(self):
        self.assertEqual(canon.clave("Wilenses"), canon.clave("PRODUCTOS WILENSES"))
        self.assertEqual(canon.clave("Alamo"), canon.clave("INDUSTRIA ALAMO S.A.S"))
        self.assertEqual(canon.clave("Maria Maria"), canon.clave("MARIA MARIA PASTELERIA"))

    def test_vacio_es_vacio(self):
        self.assertEqual(canon.clave(None), "")
        self.assertEqual(canon.clave("   "), "")
        self.assertEqual(canon.clave("S.A.S."), "")   # solo ruido: sin huella

    def test_negocios_distintos_no_comparten_clave(self):
        # La red de seguridad del módulo entero.
        for a, b in (("Makro", "Mimos"), ("Paola", "Provide"),
                     ("Delitas", "Velino"), ("Kolbitos", "Calipulpas")):
            self.assertNotEqual(canon.clave(a), canon.clave(b), f"{a} vs {b}")


class CanonizarTest(unittest.TestCase):
    """Contra la base: el nombre entrante se resuelve contra los que YA existen."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="x", activa=True)
        self.palmetto = Tienda(nombre="Palmetto", direccion="y", activa=True)
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()
        self.admin = Usuario(nombre="A", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def factura(self, proveedor, *, n=1, tienda=None):
        for _ in range(n):
            self.db.add(FacturaCompra(
                tienda_id=(tienda or self.vida).id, proveedor=proveedor,
                valor_total=1000.0, tipo_pago=TipoPagoEnum.contado,
                usuario_id=self.admin.id,
            ))
        self.db.commit()

    # ── Regla 1: misma clave ────────────────────────────────────────────────
    def test_grafia_distinta_devuelve_la_que_ya_existe(self):
        self.factura("Galerías", n=7)
        self.assertEqual(canon.canonizar(self.db, "Galerias"), "Galerías")
        self.assertEqual(canon.canonizar(self.db, "GALERIA"), "Galerías")

    def test_coletilla_juridica_cae_en_el_existente(self):
        self.factura("KOS Colombia", n=5)
        self.assertEqual(canon.canonizar(self.db, "KOS COLOMBIA S.A.S"), "KOS Colombia")

    def test_singular_y_plural_los_une_la_regla_de_contencion(self):
        # «Galeria» y «Galerías» NO comparten clave (la 's' del plural), pero una
        # empieza igual que la otra: los une la regla 2, no la 1. Fue el caso
        # real de producción con 17 facturas partidas.
        self.factura("Galerías", n=7)
        self.assertNotEqual(canon.clave("Galeria"), canon.clave("Galerías"))
        self.assertEqual(canon.canonizar(self.db, "Galeria"), "Galerías")

    def test_espacio_de_mas(self):
        self.factura("Cafexcoop", n=4)
        self.assertEqual(canon.canonizar(self.db, "Cafex coop"), "Cafexcoop")

    # ── Regla 2: uno contiene al otro ───────────────────────────────────────
    def test_razon_social_larga_cae_en_el_corto(self):
        self.factura("Calipulpas", n=9)
        self.assertEqual(canon.canonizar(self.db, "JUAN CARLOS PARRA/CALIPULPAS"), "Calipulpas")

    def test_prefijo_de_rubro_cae_en_el_corto(self):
        self.factura("Delitas", n=15)
        self.assertEqual(canon.canonizar(self.db, "INDUALIMENTOS DELITAS S.A.S."), "Delitas")

    def test_gana_el_mas_usado_cuando_hay_dos_grafias_viejas(self):
        # Las dos ya existen; el canon devuelve la de más facturas.
        self.factura("Maria Maria", n=20)
        self.factura("Maria maria", n=8)
        self.assertEqual(canon.canonizar(self.db, "MARIA MARIA PASTELERIA"), "Maria Maria")

    # ── Lo que NO debe fundir ───────────────────────────────────────────────
    def test_proveedor_nuevo_se_respeta_tal_cual(self):
        self.factura("Makro", n=12)
        self.assertEqual(canon.canonizar(self.db, "Pastelería El Trigal"), "Pastelería El Trigal")

    def test_no_funde_negocios_distintos(self):
        self.factura("Makro", n=12)
        self.factura("Mimos", n=12)
        self.factura("Paola", n=24)
        for nuevo in ("Éxito", "Provide", "Velino", "Kolbitos"):
            self.assertEqual(canon.canonizar(self.db, nuevo), nuevo)

    def test_entrante_corto_no_se_pega_a_uno_largo(self):
        # «Coop» termina igual que «Cafexcoop» pero es demasiado corto para
        # arriesgar la fusión: se respeta como proveedor nuevo.
        self.factura("Cafexcoop", n=4)
        self.assertEqual(canon.canonizar(self.db, "Coop"), "Coop")

    def test_base_vacia_no_revienta(self):
        self.assertEqual(canon.canonizar(self.db, "Proveedor Nuevo"), "Proveedor Nuevo")

    def test_nombre_vacio_pasa_derecho(self):
        self.factura("Makro", n=3)
        self.assertIsNone(canon.canonizar(self.db, None))
        self.assertEqual(canon.canonizar(self.db, "   "), "   ")

    # ── conocidos() ─────────────────────────────────────────────────────────
    def test_conocidos_ordena_por_uso_y_colapsa_grafias(self):
        self.factura("Maria Maria", n=20)
        self.factura("Maria maria", n=8)     # misma clave: no debe aparecer aparte
        self.factura("Makro", n=12)
        self.factura("Kolbitos", n=41)
        lista = canon.conocidos(self.db)
        self.assertEqual(lista, ["Kolbitos", "Maria Maria", "Makro"])

    def test_conocidos_mira_las_dos_sedes(self):
        # El mismo proveedor le vende a las dos: Palmetto no puede escribirlo
        # distinto solo porque la factura vieja era de Vida.
        self.factura("Galerías", n=7, tienda=self.vida)
        self.assertEqual(canon.canonizar(self.db, "Galerias"), "Galerías")
        self.assertIn("Galerías", canon.conocidos(self.db))


if __name__ == "__main__":
    unittest.main()
