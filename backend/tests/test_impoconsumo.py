"""El impoconsumo no es plata del negocio.

El precio de la carta lo lleva adentro: una aromática de $5.900 son $5.463 de
venta y $437 que se le giran a la DIAN. Cada caso de acá se verifica a mano.
"""
import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import ParametroTributario
from app.services import parametros_tributarios as pt


class TributosBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        pt.sembrar(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def t(self, fecha=date(2026, 7, 15)):
        return pt.para(self.db, fecha)


class SepararElImpuestoTest(TributosBase):
    def test_la_aromatica_de_5900_se_parte_como_dice_el_pos(self):
        """EL CASO ANCLA: es el desglose que imprime el POS Siigo."""
        neta, imp = self.t().separar(5_900)
        self.assertAlmostEqual(neta, 5_462.96, places=2)
        self.assertAlmostEqual(imp, 437.04, places=2)

    def test_el_impuesto_es_741_por_ciento_del_precio_final_no_el_8(self):
        """El error clásico: descontarle el 8% al precio final da de menos.
        Con tarifa 8% sobre la base, el impuesto es 7,41% de lo cobrado."""
        neta, imp = self.t().separar(100_000)
        self.assertAlmostEqual(imp / 100_000, 0.0741, places=4)
        self.assertNotAlmostEqual(imp, 8_000, places=0)

    def test_la_venta_neta_mas_el_impuesto_dan_lo_cobrado(self):
        for cobrado in (1_000, 5_900, 43_500, 1_234_567):
            neta, imp = self.t().separar(cobrado)
            self.assertAlmostEqual(neta + imp, cobrado, places=1)

    def test_el_impuesto_sobre_la_base_neta_si_es_el_8_por_ciento(self):
        neta, imp = self.t().separar(5_900)
        self.assertAlmostEqual(imp / neta, 0.08, places=4)

    def test_si_el_precio_NO_lo_incluye_lo_cobrado_ya_es_la_venta(self):
        self.db.query(ParametroTributario).update(
            {"precio_incluye_impoconsumo": False})
        self.db.commit()
        neta, imp = self.t().separar(5_900)
        self.assertAlmostEqual(neta, 5_900, places=2)
        self.assertEqual(imp, 0.0)

    def test_con_tarifa_en_cero_no_se_inventa_ningun_impuesto(self):
        self.db.query(ParametroTributario).update({"impoconsumo": 0.0})
        self.db.commit()
        neta, imp = self.t().separar(5_900)
        self.assertAlmostEqual(neta, 5_900, places=2)
        self.assertEqual(imp, 0.0)

    def test_cero_cobrado_no_rompe(self):
        self.assertEqual(self.t().separar(0), (0.0, 0.0))


class ContraElExcelDelDueñoTest(TributosBase):
    def test_reproduce_como_el_dueño_deriva_la_venta_en_su_hoja3(self):
        """Él calcula `venta = impoconsumo / 0.08`. Es correcto y el sistema
        tiene que dar lo mismo: si divergen, uno de los dos está mal."""
        impoconsumo_declarado = 3_480_840.0      # PALMETTO en su Hoja3
        venta_del_dueño = impoconsumo_declarado / 0.08
        self.assertAlmostEqual(venta_del_dueño, 43_510_500, places=0)
        # Partiendo de lo COBRADO (venta neta + impuesto) el sistema tiene que
        # devolver exactamente esa venta neta y ese impuesto.
        cobrado = venta_del_dueño + impoconsumo_declarado
        neta, imp = self.t().separar(cobrado)
        self.assertAlmostEqual(neta, venta_del_dueño, places=0)
        self.assertAlmostEqual(imp, impoconsumo_declarado, places=0)


class VigenciaTributariaTest(TributosBase):
    def test_siempre_devuelve_algo_aunque_la_fecha_sea_vieja(self):
        self.assertIsNotNone(pt.para(self.db, date(2019, 1, 1)))

    def test_sembrar_dos_veces_no_pisa_lo_que_el_dueño_corrigio(self):
        self.db.query(ParametroTributario).update({"impoconsumo": 0.16})
        self.db.commit()
        pt.sembrar(self.db)
        self.assertAlmostEqual(self.t().impoconsumo, 0.16)
        self.assertEqual(len(pt.listar(self.db)), 1)

    def test_sin_ninguna_fila_la_tarifa_es_CERO_y_no_se_inventa_nada(self):
        """Un impoconsumo desconocido no puede adivinarse: en cero el sistema
        muestra la venta como hasta ahora, en vez de restar un impuesto que
        quizá este negocio no cobra."""
        self.db.query(ParametroTributario).delete()
        self.db.commit()
        pt.SIEMBRA_ORIGINAL = pt.SIEMBRA
        try:
            pt.SIEMBRA = []
            t = pt.para(self.db, date(2026, 7, 15))
            self.assertEqual(t.impoconsumo, 0.0)
            self.assertEqual(t.separar(5_900), (5_900.0, 0.0))
            self.assertTrue(t.confirmar_contador)
        finally:
            pt.SIEMBRA = pt.SIEMBRA_ORIGINAL

    def test_el_gmf_esta_declarado(self):
        """4x1000: sale del banco en cada movimiento y ningún reporte lo veía."""
        self.assertAlmostEqual(self.t().gmf, 0.004)


class CadaMesConSuTarifaTest(TributosBase):
    """Una fila de mes usa la tarifa vigente ESE mes, no la del arranque del
    rango. Mirando «este año» con una reforma en el medio, todos los meses se
    liquidarían con la tarifa de enero — que es justo lo que las tablas con
    vigencia existen para evitar."""

    def test_una_vigencia_nueva_solo_afecta_de_su_fecha_en_adelante(self):
        self.db.add(ParametroTributario(
            vigente_desde=date(2026, 7, 1), impoconsumo=0.19,
            precio_incluye_impoconsumo=True, gmf=0.004))
        self.db.commit()
        self.assertAlmostEqual(pt.para(self.db, date(2026, 6, 30)).impoconsumo, 0.08)
        self.assertAlmostEqual(pt.para(self.db, date(2026, 7, 1)).impoconsumo, 0.19)

    def test_el_mes_viejo_se_recalcula_con_la_tarifa_vieja(self):
        self.db.add(ParametroTributario(
            vigente_desde=date(2026, 7, 1), impoconsumo=0.19,
            precio_incluye_impoconsumo=True, gmf=0.004))
        self.db.commit()
        junio = pt.para(self.db, date(2026, 6, 1)).separar(10_800)
        julio = pt.para(self.db, date(2026, 7, 1)).separar(10_800)
        self.assertAlmostEqual(junio[0], 10_000, places=0)     # 10.800/1,08
        self.assertNotAlmostEqual(junio[0], julio[0], places=0)


if __name__ == "__main__":
    unittest.main()
