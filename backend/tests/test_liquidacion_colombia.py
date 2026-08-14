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

    def _set_exo(self, valor: bool):
        self.db.query(ParametroNomina).filter(
            ParametroNomina.vigente_desde == date(2026, 1, 1)
        ).update({"exonerado_114_1": valor})
        self.db.commit()

    def exonerar(self):
        self._set_exo(True)

    def no_exonerar(self):
        """MEDIUM CAFÉ viene exonerada por default (persona natural con 2+
        trabajadores), así que el escenario SIN exoneración hay que pedirlo."""
        self._set_exo(False)


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
        """El escenario de la persona natural con UN solo empleado, o de quien
        no declara renta: paga los tres aportes completos."""
        self.no_exonerar()
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertFalse(r["aportes_empleador"]["exonerado"])
        self.assertAlmostEqual(r["aportes_empleador"]["total"], 525_657.0, delta=5)
        self.assertAlmostEqual(r["prestaciones"]["total"], 426_288.0, delta=5)
        self.assertAlmostEqual(r["costo_empleador"], 2_951_945.0, delta=15)
        self.assertAlmostEqual(r["factor_costo"], 1.686, places=2)

    def test_con_exoneracion_baja_pero_la_caja_se_sigue_pagando(self):
        """El art. 114-1 apaga salud patronal, SENA e ICBF. La caja NO: es el
        error que más se ve cuando alguien dice «estoy exonerado de parafiscales»."""
        ap = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)["aportes_empleador"]
        self.assertEqual(ap["salud"], 0.0)
        self.assertEqual(ap["sena"], 0.0)
        self.assertEqual(ap["icbf"], 0.0)
        self.assertAlmostEqual(ap["caja_compensacion"], round(SMMLV_2026 * 0.04, 2))
        self.assertGreater(ap["pension"], 0.0)
        self.assertGreater(ap["arl"], 0.0)

    def test_con_exoneracion_el_costo_total_baja_a_1_55(self):
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertAlmostEqual(r["costo_empleador"], 2_715_573.0, delta=15)
        self.assertAlmostEqual(r["factor_costo"], 1.551, places=2)

    def test_la_exoneracion_vale_236_mil_al_mes_por_barista(self):
        """El número que hay que poder mostrar en pantalla: lo que costaría
        tener este flag mal puesto, en cualquiera de los dos sentidos."""
        r = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.assertAlmostEqual(r["aportes_empleador"]["ahorro_por_exoneracion"],
                               236_372.0, delta=5)

    def test_el_ahorro_declarado_es_exactamente_la_diferencia_medida(self):
        """No es un número decorativo: tiene que ser la resta de verdad."""
        con_exo = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
        self.no_exonerar()
        sin_exo = liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)
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
        self.assertGreater(r["costo_empleador"], r["neto_a_pagar"] * 1.4)
        self.no_exonerar()
        self.assertGreater(liq.liquidar(self.p(), SMMLV_2026, SMMLV_2026, 30)["costo_empleador"],
                           r["neto_a_pagar"] * 1.5)

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


class LaExoneracionDeUnaPersonaNaturalTest(ParametrosBase):
    """MEDIUM CAFÉ es PERSONA NATURAL con ~5 baristas.

    El art. 114-1 ET exonera a la persona natural empleadora que tenga DOS O
    MÁS trabajadores. Con un solo empleado NO aplica, y esa condición se puede
    perder sin que nadie toque el sistema: alcanza con que se vaya gente.
    """

    def test_viene_prendida_por_default(self):
        self.assertTrue(self.p().exonerado_114_1)

    def test_todas_las_vigencias_sembradas_la_traen_igual(self):
        """Si 2025 quedara sin exonerar, comparar años mostraría un salto de
        costo que no ocurrió: sería un cambio de criterio disfrazado de dato."""
        for fila in pn.listar(self.db):
            self.assertTrue(fila.exonerado_114_1)

    def test_con_dos_contratos_activos_no_avisa_nada(self):
        for uid in (1, 2):
            self.db.add(ContratoBarista(usuario_id=uid, salario_mensual=0.0,
                                        salario_en_smmlv=1.0, activo=True))
        self.db.commit()
        self.assertIsNone(pn.alerta_exoneracion(self.db, self.p()))

    def test_con_un_solo_trabajador_avisa_que_se_pierde(self):
        self.db.add(ContratoBarista(usuario_id=1, salario_mensual=0.0,
                                    salario_en_smmlv=1.0, activo=True))
        self.db.commit()
        aviso = pn.alerta_exoneracion(self.db, self.p())
        self.assertIsNotNone(aviso)
        self.assertIn("SENA", aviso)

    def test_los_contratos_inactivos_no_cuentan_como_trabajadores(self):
        self.db.add(ContratoBarista(usuario_id=1, salario_mensual=0.0,
                                    salario_en_smmlv=1.0, activo=True))
        self.db.add(ContratoBarista(usuario_id=2, salario_mensual=0.0,
                                    salario_en_smmlv=1.0, activo=False))
        self.db.commit()
        self.assertIsNotNone(pn.alerta_exoneracion(self.db, self.p()))

    def test_apagada_la_exoneracion_no_hay_nada_que_avisar(self):
        """El aviso es sobre un riesgo de la exoneración. Sin ella, no aplica."""
        self.no_exonerar()
        self.assertIsNone(pn.alerta_exoneracion(self.db, self.p()))

    def test_el_aviso_dice_lo_que_el_sistema_VE_y_no_acusa(self):
        """El conteo son los contratos de ESTE sistema, que pueden ser menos que
        los trabajadores reales (un cocinero, alguien de aseo). El mensaje no
        puede afirmar que la exoneración esté mal: un aviso que se equivoca
        seguido termina ignorado, y éste tiene que doler el día que importe."""
        self.db.add(ContratoBarista(usuario_id=1, salario_mensual=0.0,
                                    salario_en_smmlv=1.0, activo=True))
        self.db.commit()
        aviso = pn.alerta_exoneracion(self.db, self.p())
        self.assertIn("1 contrato activo", aviso)
        self.assertIn("Si en total", aviso)


class LasClavesDeNovedadExistenDeVerdadTest(ParametrosBase):
    """La guarda del bug que ningún test podía ver.

    NOVEDADES_SIN_AUXILIO nació con tres claves INVENTADAS que no existían en
    el enum. Nunca matchearon con nada, así que la licencia cobraba el auxilio
    entero mientras la pantalla y el CSV prometían que no. Un nombre que no
    matchea no revienta: simplemente no hace nada, y por eso sobrevive callado.
    """

    def test_todas_las_claves_son_novedades_que_existen(self):
        from app.services import novedades_nomina as nsvc
        fantasmas = liq.NOVEDADES_SIN_AUXILIO - set(nsvc.TIPOS)
        self.assertEqual(fantasmas, set(),
                         f"claves que no existen en novedades_nomina.TIPOS: {fantasmas}")

    def test_todas_son_valores_validos_del_enum(self):
        from app.models.models import TipoNovedadNominaEnum
        validos = {t.value for t in TipoNovedadNominaEnum}
        self.assertTrue(liq.NOVEDADES_SIN_AUXILIO <= validos)

    def test_la_licencia_suspende_el_auxilio(self):
        """El caso que se pagaba de más: 5 días de licencia costaban $41.516."""
        self.assertIn("licencia", liq.NOVEDADES_SIN_AUXILIO)

    def test_quien_trabajo_en_otro_horario_NO_pierde_el_auxilio(self):
        """cambio_turno = se desplazó igual, solo que a otra hora."""
        self.assertNotIn("cambio_turno", liq.NOVEDADES_SIN_AUXILIO)

    def test_el_permiso_remunerado_conserva_el_auxilio(self):
        """Decisión declarada: no hay fuente que diga que lo pierde, y quitarle
        plata a la trabajadora necesita una norma detrás, no una deducción."""
        self.assertNotIn("permiso_remunerado", liq.NOVEDADES_SIN_AUXILIO)


class LosParafiscalesNoTienenPisoTest(ParametrosBase):
    """Seguridad social sobre el IBC (con piso); parafiscales sobre lo devengado.

    Son DOS bases y solo se separan cuando alguien devenga menos de un mínimo,
    o sea justo en el medio tiempo. Con una sola base se le cobraban $35.036 de
    más al mes por barista de media jornada.
    """

    def test_la_caja_se_liquida_sobre_lo_devengado_y_no_sobre_el_piso(self):
        medio = SMMLV_2026 / 2
        ap = liq.liquidar(self.p(), medio, medio, 30)["aportes_empleador"]
        self.assertAlmostEqual(ap["base_ibc"], SMMLV_2026, places=2)      # con piso
        self.assertAlmostEqual(ap["base_parafiscales"], medio, places=2)  # sin piso
        self.assertAlmostEqual(ap["caja_compensacion"], round(medio * 0.04, 2))

    def test_salud_pension_y_arl_si_usan_el_piso(self):
        medio = SMMLV_2026 / 2
        self.no_exonerar()
        ap = liq.liquidar(self.p(), medio, medio, 30)["aportes_empleador"]
        self.assertAlmostEqual(ap["salud"], round(SMMLV_2026 * 0.085, 2))
        self.assertAlmostEqual(ap["pension"], round(SMMLV_2026 * 0.12, 2))
        self.assertAlmostEqual(ap["arl"], round(SMMLV_2026 * 0.00522, 2))

    def test_sena_e_icbf_tampoco_llevan_piso(self):
        medio = SMMLV_2026 / 2
        self.no_exonerar()
        ap = liq.liquidar(self.p(), medio, medio, 30)["aportes_empleador"]
        self.assertAlmostEqual(ap["sena"], round(medio * 0.02, 2))
        self.assertAlmostEqual(ap["icbf"], round(medio * 0.03, 2))

    def test_arriba_del_minimo_las_dos_bases_coinciden(self):
        """La separación solo se nota abajo del mínimo: si divergiera arriba,
        alguna de las dos estaría mal."""
        ap = liq.liquidar(self.p(), SMMLV_2026 * 1.5, SMMLV_2026 * 1.5,
                          30)["aportes_empleador"]
        self.assertAlmostEqual(ap["base_ibc"], ap["base_parafiscales"], places=2)

    def test_el_ahorro_declarado_sigue_siendo_la_resta_real_en_medio_tiempo(self):
        """Con dos bases el ahorro es fácil de calcular mal: se pincha."""
        medio = SMMLV_2026 / 2
        con = liq.liquidar(self.p(), medio, medio, 30)
        self.no_exonerar()
        sin = liq.liquidar(self.p(), medio, medio, 30)
        self.assertAlmostEqual(con["aportes_empleador"]["ahorro_por_exoneracion"],
                               sin["costo_empleador"] - con["costo_empleador"], places=2)


class LaAlertaLlegaAlResumenTest(unittest.TestCase):
    """La guarda no sirve de nada si no la ve nadie.

    `alerta_exoneracion` existía pero no estaba cableada a ningún router ni
    servicio: solo la usaban sus propios tests. Una alarma que no suena en
    ninguna pantalla es código muerto con forma de seguridad.
    """

    def setUp(self):
        from test_nomina_resumen import NominaBase
        self._caso = NominaBase("run")
        self._caso.setUp()
        self.db = self._caso.db
        pn.sembrar(self.db)

    def tearDown(self):
        self._caso.tearDown()

    def _advertencias(self):
        from app.services import nomina as nsvc
        return nsvc.resumen_mensual(self.db, self._caso.t.id, 2026, 8)["advertencias"]

    def test_con_un_solo_contrato_activo_el_resumen_lo_avisa(self):
        textos = " ".join(self._advertencias())
        self.assertIn("exoneración de aportes está prendida", textos)

    def test_con_dos_contratos_el_resumen_no_avisa_nada(self):
        from app.models.models import ContratoBarista
        self.db.add(ContratoBarista(usuario_id=self._caso.admin.id,
                                    salario_mensual=0.0, salario_en_smmlv=1.0,
                                    activo=True))
        self.db.commit()
        textos = " ".join(self._advertencias())
        self.assertNotIn("exoneración de aportes está prendida", textos)

    def test_las_advertencias_fijas_siguen_estando(self):
        from app.services import nomina as nsvc
        for fija in nsvc.ADVERTENCIAS:
            self.assertIn(fija, self._advertencias())


class TenerContratoNoEsTenerSueldoTest(unittest.TestCase):
    """La tercera vez que aparece el mismo bug en esta sesión.

    `tiene_contrato` es «existe la fila» y el PUT de la pestaña Sueldos crea la
    fila con salario 0. Decidiendo por la fila, la pantalla escribía «sueldo $0
    ÷ el divisor» —presentando el cero como un sueldo que alguien cargó— y el
    aviso agregado no la contaba: el dueño leía «2 sin sueldo» cuando eran 3, y
    el costo del mes quedaba corto sin que nada lo dijera.
    """

    def setUp(self):
        from test_nomina_resumen import NominaBase
        self._caso = NominaBase("run")
        self._caso.setUp()
        self.db = self._caso.db
        pn.sembrar(self.db)

    def tearDown(self):
        self._caso.tearDown()

    def _cath(self):
        from app.services import nomina as nsvc
        r = nsvc.resumen_mensual(self.db, self._caso.t.id, 2026, 8)
        return [b for b in r["baristas"] if b["usuario_id"] == self._caso.cath.id][0], r

    def test_un_contrato_en_cero_tiene_fila_pero_no_tiene_sueldo(self):
        from app.models.models import ContratoBarista
        c = self.db.query(ContratoBarista).filter(
            ContratoBarista.usuario_id == self._caso.cath.id).first()
        c.salario_mensual = 0.0
        c.salario_en_smmlv = None
        self.db.commit()
        b, r = self._cath()
        self.assertTrue(b["tiene_contrato"])          # la fila está
        self.assertFalse(b["tiene_sueldo"])           # la plata no
        self.assertGreaterEqual(r["totales"]["sin_sueldo"], 1)

    def test_con_sueldo_cargado_las_dos_banderas_coinciden(self):
        b, r = self._cath()
        self.assertTrue(b["tiene_contrato"])
        self.assertTrue(b["tiene_sueldo"])

    def test_sin_sueldo_cuenta_mas_que_sin_contrato_cuando_hay_filas_en_cero(self):
        """El caso exacto que hacía mentir al aviso."""
        from app.models.models import ContratoBarista
        c = self.db.query(ContratoBarista).filter(
            ContratoBarista.usuario_id == self._caso.cath.id).first()
        c.salario_mensual = 0.0
        c.salario_en_smmlv = None
        self.db.commit()
        _b, r = self._cath()
        self.assertGreater(r["totales"]["sin_sueldo"], r["totales"]["sin_contrato"])


class DosSedesNoDuplicanLaNominaTest(unittest.TestCase):
    """El auxilio, el piso del IBC, los aportes y las prestaciones son
    mensuales POR TRABAJADOR, no por local.

    `resumen_mensual` es por sede y quien cubre en las dos aparece en las dos.
    Liquidando cada pantalla con su propio devengado, la misma barista cobraba
    el auxilio ENTERO en cada una y llevaba un juego completo de aportes en
    cada una — dos obligaciones donde hay una.

    La liquidación es de la PERSONA y no se parte. Se probó prorratearla por
    fracción de devengado y salió peor: el redondeo no cerraba, el CSV quedó
    con otro criterio que la pantalla, y la fila decía una cosa y el total
    otra. Ahora se muestra ENTERA en las dos pantallas —es la misma obligación
    mirada dos veces— y el sistema declara que dos resúmenes NO se suman.
    """

    def setUp(self):
        from test_nomina_resumen import NominaBase
        from app.models.models import Tienda, ContratoBarista
        self._caso = NominaBase("run")
        self._caso.setUp()
        self.db = self._caso.db
        pn.sembrar(self.db)
        self.otra = Tienda(nombre="Centro", direccion="y")
        self.db.add(self.otra)
        self.db.commit()
        c = self.db.query(ContratoBarista).filter(
            ContratoBarista.usuario_id == self._caso.cath.id).first()
        c.salario_en_smmlv = 1.0
        self.db.commit()

    def tearDown(self):
        self._caso.tearDown()

    def _habiles(self):
        return [date(2026, 8, d) for d in range(1, 32)
                if date(2026, 8, d).weekday() < 5]

    def _resumen(self, tienda):
        from app.services import nomina as nsvc
        return nsvc.resumen_mensual(self.db, tienda.id, 2026, 8)

    def _cath(self, tienda):
        r = self._resumen(tienda)
        return [b for b in r["baristas"] if b["usuario_id"] == self._caso.cath.id][0]

    def _trabajar(self, dias_en_la_primera: int, con_almuerzo: bool = True):
        """Marca los días hábiles alternando sedes, con el turno PUBLICADO en la
        sede donde se trabaja.

        El almuerzo importa y por eso va por default: se descuenta con la
        ventana del horario, y ese horario vive en la sede donde está publicado.
        Si el consolidado leyera solo los almuerzos de la sede que se está
        mirando, daría un número distinto en cada pantalla — que es exactamente
        el bug que este escenario tiene que poder ver.
        """
        from test_nomina_resumen import utc
        from app.services import horarios as hsvc, nomina as nsvc
        for i, d in enumerate(self._habiles()):
            sede = self._caso.t if i < dias_en_la_primera else self.otra
            if con_almuerzo:
                hsvc.guardar_turno(self.db, sede.id, self._caso.cath.id, d,
                                   "08:00", "16:00",
                                   creado_por_id=self._caso.admin.id,
                                   almuerzo_inicio="12:00", almuerzo_minutos=60)
                hsvc.publicar_semana(self.db, sede.id, nsvc.lunes_de(d),
                                     self._caso.admin.id)
            self._caso.real(self._caso.cath, utc(2026, 8, d.day, 8),
                            utc(2026, 8, d.day, 16), tienda=sede)

    def test_la_liquidacion_es_la_misma_obligacion_en_las_dos_pantallas(self):
        """EL TEST QUE IMPORTA: una persona, una nómina. No dos, ni dos mitades."""
        self._trabajar(dias_en_la_primera=10)
        a, b = self._cath(self._caso.t), self._cath(self.otra)
        for campo in ("devengado", "neto_a_pagar", "costo_empleador"):
            self.assertAlmostEqual(a["liquidacion"][campo], b["liquidacion"][campo],
                                   places=2, msg=f"{campo} difiere entre sedes")
        self.assertAlmostEqual(a["liquidacion"]["auxilio"]["total"],
                               AUXILIO_2026, places=0)

    def test_da_lo_mismo_que_si_hubiera_trabajado_todo_en_una_sede(self):
        """El consolidado no puede depender de qué pantalla se esté mirando: el
        almuerzo se descuenta de TODAS las sedes, no solo de la que se abre."""
        self._trabajar(dias_en_la_primera=10)
        repartida = self._cath(self._caso.t)["liquidacion"]["costo_empleador"]
        self._caso.tearDown()
        self.setUp()
        self._trabajar(dias_en_la_primera=99)          # todas en la primera
        entera = self._cath(self._caso.t)["liquidacion"]["costo_empleador"]
        self.assertAlmostEqual(repartida, entera, places=2)

    def test_cada_pantalla_dice_cuanto_se_devengo_ACA(self):
        """Sin prorratear la obligación, pero diciendo qué parte del tiempo
        corresponde a este local: es el dato honesto que sí existe."""
        self._trabajar(dias_en_la_primera=10)
        a, b = self._cath(self._caso.t), self._cath(self.otra)
        suma = (a["liquidacion"]["devengado_en_esta_sede"]
                + b["liquidacion"]["devengado_en_esta_sede"])
        self.assertAlmostEqual(suma, a["liquidacion"]["devengado"], places=2)

    def test_las_dos_pantallas_declaran_que_trabajo_en_otra_sede(self):
        self._trabajar(dias_en_la_primera=10)
        self.assertTrue(self._cath(self._caso.t)["liquidacion"]["en_varias_sedes"])
        self.assertTrue(self._cath(self.otra)["liquidacion"]["en_varias_sedes"])
        self.assertEqual(self._resumen(self._caso.t)["totales"]["en_varias_sedes"], 1)

    def test_quien_trabaja_en_una_sola_sede_no_queda_marcada(self):
        self._trabajar(dias_en_la_primera=99)
        b = self._cath(self._caso.t)
        self.assertFalse(b["liquidacion"]["en_varias_sedes"])
        self.assertAlmostEqual(b["liquidacion"]["devengado_en_esta_sede"],
                               b["liquidacion"]["devengado"], places=2)
        t = self._resumen(self._caso.t)["totales"]
        self.assertAlmostEqual(t["total_costo_empleador"],
                               b["liquidacion"]["costo_empleador"], places=2)

    def test_el_csv_marca_la_columna_y_avisa_que_no_se_suman(self):
        """El archivo que arma la PILA se reenvía sin la pantalla que lo explica."""
        from app.services import nomina as nsvc
        self._trabajar(dias_en_la_primera=10)
        csv = nsvc.csv_mensual(self.db, self._caso.t.id, 2026, 8)
        self.assertIn("También trabajó en otra sede", csv)
        self.assertIn("Devengado en esta sede ($)", csv)
        self.assertIn("SUMAR LOS DOS ARCHIVOS LA CUENTA DOS VECES", csv)
        fila = [l for l in csv.splitlines() if l.startswith(self._caso.cath.nombre)][0]
        self.assertIn(";SI;", fila)
