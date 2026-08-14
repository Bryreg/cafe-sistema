"""Los cinco números de una nómina colombiana, contra la ley y contra la calle.

Cada caso de acá se puede verificar a mano con una calculadora y un decreto. Si
alguno se cae, el sistema está liquidando distinto de lo que manda la norma: no
es un test de refactor, es un test de plata.
"""
import inspect
import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import ParametroNomina, ContratoBarista
from app.services import parametros_nomina as pn
from app.services import liquidacion as liq

SMMLV_2026 = 1_750_905.0
AUXILIO_2026 = 249_095.0
SMMLV_2025 = 1_423_500.0


class ParametrosBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        pn.sembrar(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def p(self, fecha=date(2026, 3, 15)):
        return pn.para(self.db, fecha)

    def exonerar(self):
        self.db.query(ParametroNomina).filter(
            ParametroNomina.vigente_desde == date(2026, 1, 1)
        ).update({"exonerado_114_1": True})
        self.db.commit()


class VigenciaTest(ParametrosBase):
    def test_el_minimo_de_2026_es_el_del_decreto(self):
        p = self.p()
        self.assertAlmostEqual(p.smmlv, SMMLV_2026)
        self.assertAlmostEqual(p.auxilio_transporte, AUXILIO_2026)

    def test_un_mes_de_2025_se_liquida_con_el_minimo_de_2025(self):
        """La razón de ser de la tabla: recalcular el pasado no lo reescribe."""
        p = pn.para(self.db, date(2025, 6, 30))
        self.assertAlmostEqual(p.smmlv, SMMLV_2025)
        self.assertAlmostEqual(p.auxilio_transporte, 200_000.0)

    def test_el_31_de_diciembre_todavia_es_del_año_viejo(self):
        self.assertAlmostEqual(pn.para(self.db, date(2025, 12, 31)).smmlv, SMMLV_2025)
        self.assertAlmostEqual(pn.para(self.db, date(2026, 1, 1)).smmlv, SMMLV_2026)

    def test_sembrar_dos_veces_no_duplica_ni_pisa_lo_que_el_dueño_corrigio(self):
        self.db.query(ParametroNomina).filter(
            ParametroNomina.vigente_desde == date(2026, 1, 1)
        ).update({"arl": 0.02436})              # lo subió a clase III a mano
        self.db.commit()
        pn.sembrar(self.db)
        self.assertAlmostEqual(self.p().arl, 0.02436)
        self.assertEqual(len(pn.listar(self.db)), 2)

    def test_no_hay_ni_un_porcentaje_quemado_en_el_calculo(self):
        """La disciplina de TasaLaboral: la plata vive en la base, no en el .py.
        Si alguien vuelve a escribir un 0,04 acá, en enero el sistema miente."""
        fuente = inspect.getsource(liq)
        for prohibido in ("1750905", "1_750_905", "249095", "249_095",
                          "0.04", "0.085", "0.12", "0.0833"):
            self.assertNotIn(prohibido, fuente,
                             f"{prohibido} quemado en liquidacion.py")


class ElNetoDeLaCalleTest(ParametrosBase):
    def test_un_salario_minimo_completo_da_el_neto_publicado(self):
        """EL TEST ANCLA. Es el número que publican prensa y firmas contables
        para 2026: 1 SMMLV con auxilio deja $1.859.928 tras salud y pensión."""
        r = liq.liquidar(self.p(), devengado=SMMLV_2026,
                         salario_mensual=SMMLV_2026, dias_con_derecho_a_auxilio=30)
        self.assertAlmostEqual(r["devengado"], SMMLV_2026, places=2)
        self.assertAlmostEqual(r["auxilio"]["total"], AUXILIO_2026, places=0)
        self.assertAlmostEqual(r["deducciones"]["salud"], 70_036.20, places=2)
        self.assertAlmostEqual(r["deducciones"]["pension"], 70_036.20, places=2)
        self.assertAlmostEqual(r["deducciones"]["total"], 140_072.40, places=2)
        self.assertAlmostEqual(r["neto_a_pagar"], 1_859_927.60, places=0)

    def test_devengado_mas_auxilio_dan_los_dos_millones_exactos(self):
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertAlmostEqual(r["devengado"] + r["auxilio"]["total"],
                               2_000_000, places=0)

    def test_al_minimo_no_le_toca_fondo_de_solidaridad(self):
        """Solo desde 4 SMMLV. Cobrárselo sería quitarle $17.509 al mes."""
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertEqual(r["deducciones"]["fondo_solidaridad"], 0.0)

    def test_un_sueldo_de_cuatro_minimos_si_paga_fondo_de_solidaridad(self):
        alto = SMMLV_2026 * 4
        r = liq.liquidar(self.p(), alto, alto, 30)
        self.assertAlmostEqual(r["deducciones"]["fondo_solidaridad"],
                               round(alto * 0.01, 2))


class AuxilioDeTransporteTest(ParametrosBase):
    def test_se_prorratea_por_dia_con_divisor_30_fijo(self):
        p = self.p()
        self.assertAlmostEqual(p.auxilio_por_dia, AUXILIO_2026 / 30, places=2)
        r = liq.liquidar(p, SMMLV_2026, SMMLV_2026, 15)
        self.assertAlmostEqual(r["auxilio"]["total"], round(AUXILIO_2026 / 30 * 15, 2))

    def test_medio_tiempo_cobra_el_dia_COMPLETO_de_auxilio(self):
        """Concepto Mintrabajo 257/2020: no se prorratea por HORAS. Quien va
        medio día gasta el mismo pasaje. Prorratearlo sería quitarle plata."""
        medio = liq.liquidar(self.p(), SMMLV_2026 / 2, SMMLV_2026 / 2, 30)
        self.assertAlmostEqual(medio["auxilio"]["total"], AUXILIO_2026, places=0)

    def test_los_dias_de_incapacidad_no_generan_auxilio(self):
        self.assertEqual(liq.dias_con_auxilio(30, dias_sin_derecho=5), 25)
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026,
                         liq.dias_con_auxilio(30, 5))
        self.assertAlmostEqual(r["auxilio"]["total"], round(AUXILIO_2026 / 30 * 25, 2))

    def test_las_novedades_que_suspenden_el_auxilio_estan_declaradas(self):
        for clave in ("incapacidad", "vacaciones", "permiso_no_remunerado"):
            self.assertIn(clave, liq.NOVEDADES_SIN_AUXILIO)

    def test_arriba_de_dos_smmlv_no_hay_auxilio(self):
        alto = SMMLV_2026 * 2 + 1
        r = liq.liquidar(self.p(), alto, alto, 30)
        self.assertFalse(r["auxilio"]["tiene_derecho"])
        self.assertEqual(r["auxilio"]["total"], 0.0)
        self.assertIn("tope", r["auxilio"]["razon"])

    def test_justo_en_dos_smmlv_todavia_hay_auxilio(self):
        r = liq.liquidar(self.p(), SMMLV_2026 * 2, SMMLV_2026 * 2, 30)
        self.assertTrue(r["auxilio"]["tiene_derecho"])

    def test_el_auxilio_no_entra_en_la_base_de_aportes(self):
        """La base de una barista de mínimo es 1.750.905, no 2.000.000."""
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertAlmostEqual(r["deducciones"]["base_ibc"], SMMLV_2026, places=2)
        self.assertAlmostEqual(r["aportes_empleador"]["base_ibc"], SMMLV_2026, places=2)


class ElPisoDelIbcTest(ParametrosBase):
    def test_medio_tiempo_cotiza_sobre_un_minimo_COMPLETO(self):
        """EL GOTCHA CARO: los aportes NO se parten a la mitad con la jornada.
        Quien planee medio tiempo creyendo que el costo se divide por dos se
        lleva una sorpresa de varios cientos de miles al mes."""
        r = liq.liquidar(self.p(), devengado=SMMLV_2026 / 2,
                         salario_mensual=SMMLV_2026 / 2, dias_con_derecho_a_auxilio=30)
        self.assertAlmostEqual(r["deducciones"]["base_ibc"], SMMLV_2026, places=2)
        self.assertAlmostEqual(r["deducciones"]["salud"], round(SMMLV_2026 * 0.04, 2))

    def test_sin_horas_trabajadas_no_se_inventa_una_cotizacion(self):
        """El piso aplica a quien trabajó. Con devengado 0 no hay aporte."""
        r = liq.liquidar(self.p(), 0.0, SMMLV_2026, 0)
        self.assertEqual(r["deducciones"]["base_ibc"], 0.0)
        self.assertEqual(r["deducciones"]["total"], 0.0)
        self.assertEqual(r["costo_empleador"], 0.0)
        self.assertEqual(r["factor_costo"], 0.0)

    def test_por_encima_del_minimo_la_base_es_lo_devengado(self):
        con_extras = SMMLV_2026 + 300_000
        r = liq.liquidar(self.p(), con_extras, SMMLV_2026, 30)
        self.assertAlmostEqual(r["deducciones"]["base_ibc"], con_extras, places=2)

    def test_el_piso_se_mueve_con_el_año(self):
        r25 = liq.liquidar(pn.para(self.db, date(2025, 6, 1)), 500_000, 500_000, 30)
        self.assertAlmostEqual(r25["deducciones"]["base_ibc"], SMMLV_2025, places=2)


class CostoDelEmpleadorTest(ParametrosBase):
    def test_sin_exoneracion_el_costo_es_1_69_veces_el_sueldo(self):
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertFalse(r["aportes_empleador"]["exonerado"])
        self.assertAlmostEqual(r["aportes_empleador"]["total"], 525_657.0, delta=5)
        self.assertAlmostEqual(r["prestaciones"]["total"], 426_288.0, delta=5)
        self.assertAlmostEqual(r["costo_empleador"], 2_951_945.0, delta=15)
        self.assertAlmostEqual(r["factor_costo"], 1.686, places=2)

    def test_con_exoneracion_baja_pero_la_caja_se_sigue_pagando(self):
        """El art. 114-1 apaga salud patronal, SENA e ICBF. La caja NO: es el
        error que más se ve cuando alguien dice «estoy exonerado de parafiscales»."""
        self.exonerar()
        ap = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)["aportes_empleador"]
        self.assertEqual(ap["salud"], 0.0)
        self.assertEqual(ap["sena"], 0.0)
        self.assertEqual(ap["icbf"], 0.0)
        self.assertAlmostEqual(ap["caja_compensacion"], round(SMMLV_2026 * 0.04, 2))
        self.assertGreater(ap["pension"], 0.0)
        self.assertGreater(ap["arl"], 0.0)

    def test_con_exoneracion_el_costo_total_baja_a_1_55(self):
        self.exonerar()
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertAlmostEqual(r["costo_empleador"], 2_715_573.0, delta=15)
        self.assertAlmostEqual(r["factor_costo"], 1.551, places=2)

    def test_la_exoneracion_vale_236_mil_al_mes_por_barista(self):
        """El número exacto que el dueño tiene que confirmar con su contador."""
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertAlmostEqual(r["aportes_empleador"]["ahorro_por_exoneracion"],
                               236_372.0, delta=5)

    def test_el_ahorro_declarado_es_exactamente_la_diferencia_medida(self):
        """No es un número decorativo: tiene que ser la resta de verdad."""
        sin_exo = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.exonerar()
        con_exo = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertAlmostEqual(
            sin_exo["aportes_empleador"]["ahorro_por_exoneracion"],
            sin_exo["costo_empleador"] - con_exo["costo_empleador"], places=2)

    def test_las_prestaciones_usan_DOS_bases_distintas(self):
        """Prima/cesantías/intereses sobre sueldo+auxilio; vacaciones SIN auxilio.
        Es el error clásico y por eso se pincha explícitamente."""
        pr = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)["prestaciones"]
        self.assertAlmostEqual(pr["base_con_auxilio"], 2_000_000, places=0)
        self.assertAlmostEqual(pr["base_sin_auxilio"], SMMLV_2026, places=0)
        self.assertAlmostEqual(pr["prima"], 166_667, delta=2)
        self.assertAlmostEqual(pr["cesantias"], 166_667, delta=2)
        self.assertAlmostEqual(pr["intereses_cesantias"], 20_000, delta=2)
        self.assertAlmostEqual(pr["vacaciones"], 72_954, delta=2)
        self.assertNotAlmostEqual(pr["vacaciones"], round(2_000_000 * 0.0416667, 2),
                                  msg="las vacaciones NO llevan auxilio en la base")

    def test_el_costo_es_mucho_mayor_que_el_neto_que_recibe_la_barista(self):
        """El malentendido que este módulo existe para evitar."""
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertGreater(r["costo_empleador"], r["neto_a_pagar"] * 1.5)

    def test_los_cinco_numeros_cierran_entre_si(self):
        """Invariante: neto = devengado + auxilio − deducciones, y el costo es
        devengado + auxilio + aportes + prestaciones. Sin términos sueltos."""
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertAlmostEqual(
            r["neto_a_pagar"],
            r["devengado"] + r["auxilio"]["total"] - r["deducciones"]["total"], places=2)
        self.assertAlmostEqual(
            r["costo_empleador"],
            r["devengado"] + r["auxilio"]["total"]
            + r["aportes_empleador"]["total"] + r["prestaciones"]["total"], places=2)


class SalarioEnSmmlvTest(ParametrosBase):
    def test_un_contrato_en_smmlv_sube_solo_cada_enero(self):
        c = ContratoBarista(usuario_id=1, salario_mensual=0.0, salario_en_smmlv=1.0)
        self.assertAlmostEqual(
            pn.salario_del_contrato(c, pn.para(self.db, date(2025, 6, 1))), SMMLV_2025)
        self.assertAlmostEqual(
            pn.salario_del_contrato(c, pn.para(self.db, date(2026, 6, 1))), SMMLV_2026)

    def test_el_contrato_en_pesos_fijos_sigue_valiendo(self):
        c = ContratoBarista(usuario_id=1, salario_mensual=2_500_000.0)
        self.assertAlmostEqual(pn.salario_del_contrato(c, self.p()), 2_500_000.0)

    def test_smmlv_manda_sobre_el_numero_viejo(self):
        c = ContratoBarista(usuario_id=1, salario_mensual=SMMLV_2025,
                            salario_en_smmlv=1.0)
        self.assertAlmostEqual(pn.salario_del_contrato(c, self.p()), SMMLV_2026)

    def test_sin_contrato_no_hay_sueldo(self):
        self.assertEqual(pn.salario_del_contrato(None, self.p()), 0.0)

    def test_un_sueldo_de_1_5_smmlv_tambien_se_mueve_solo(self):
        c = ContratoBarista(usuario_id=1, salario_mensual=0.0, salario_en_smmlv=1.5)
        self.assertAlmostEqual(pn.salario_del_contrato(c, self.p()),
                               round(SMMLV_2026 * 1.5, 2))
