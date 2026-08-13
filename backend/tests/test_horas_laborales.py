"""Descomposición de un turno en tipos de hora (cálculo PURO, sin DB).

Es la matemática que decide el sueldo de una persona: acá va primero el test.
Todas las tasas entran por parámetro — el cálculo NO conoce ninguna constante de
ley. Las tasas de estos tests son valores de laboratorio ELEGIDOS PARA EL TEST
(no son "la ley"): así un cambio de norma no rompe la suite, y la suite sigue
probando la mecánica.
"""
import unittest
from datetime import datetime, date

from app.services.horas import (
    Tasa, CATEGORIAS, segmentar, descomponer, liquidar_semana, valorizar,
    factores, liquidar_semana_por_tramo,
)


# Tasa de laboratorio: nocturna 21:00-06:00, recargos redondos y fáciles de
# verificar a mano. NO es la tasa sembrada en la DB (esa se prueba aparte).
TASA = Tasa(
    jornada_max_semanal=44.0,
    hora_inicio_nocturna=21,
    hora_fin_nocturna=6,
    recargo_nocturno=0.35,
    recargo_dominical=0.75,
    extra_diurna=0.25,
    extra_nocturna=0.75,
    divisor_hora_mensual=240.0,
)


def dt(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi)


class DescomposicionTest(unittest.TestCase):
    """Un turno solo → horas por categoría (sin extras: eso es semanal)."""

    def test_turno_diurno_simple_martes(self):
        # Martes 2026-08-11, 08:00 → 16:00 = 8h todas diurnas ordinarias.
        h = descomponer(dt(2026, 8, 11, 8), dt(2026, 8, 11, 16), TASA)
        self.assertAlmostEqual(h["ordinaria_diurna"], 8.0)
        self.assertAlmostEqual(h["ordinaria_nocturna"], 0.0)
        self.assertAlmostEqual(h["dominical_diurna"], 0.0)
        self.assertAlmostEqual(h["dominical_nocturna"], 0.0)

    def test_cruza_medianoche_sabado_a_domingo(self):
        # Sábado 2026-08-15 18:00 → domingo 02:00.
        # 18-21 diurna ord (3h) · 21-24 nocturna ord (3h) · 00-02 domingo nocturna (2h).
        # El domingo arranca a las 00:00, no antes.
        h = descomponer(dt(2026, 8, 15, 18), dt(2026, 8, 16, 2), TASA)
        self.assertAlmostEqual(h["ordinaria_diurna"], 3.0)
        self.assertAlmostEqual(h["ordinaria_nocturna"], 3.0)
        self.assertAlmostEqual(h["dominical_diurna"], 0.0)
        self.assertAlmostEqual(h["dominical_nocturna"], 2.0)

    def test_borde_nocturno_de_entrada_madrugada(self):
        # Miércoles 04:00 → 09:00: 04-06 nocturna (2h), 06-09 diurna (3h).
        h = descomponer(dt(2026, 8, 12, 4), dt(2026, 8, 12, 9), TASA)
        self.assertAlmostEqual(h["ordinaria_nocturna"], 2.0)
        self.assertAlmostEqual(h["ordinaria_diurna"], 3.0)

    def test_borde_nocturno_de_salida_noche(self):
        # Miércoles 19:30 → 22:30: 19:30-21 diurna (1.5h), 21-22:30 nocturna (1.5h).
        h = descomponer(dt(2026, 8, 12, 19, 30), dt(2026, 8, 12, 22, 30), TASA)
        self.assertAlmostEqual(h["ordinaria_diurna"], 1.5)
        self.assertAlmostEqual(h["ordinaria_nocturna"], 1.5)

    def test_domingo_completo_diurno(self):
        h = descomponer(dt(2026, 8, 16, 8), dt(2026, 8, 16, 16), TASA)
        self.assertAlmostEqual(h["dominical_diurna"], 8.0)
        self.assertAlmostEqual(h["ordinaria_diurna"], 0.0)

    def test_festivo_lunes_por_ley_emiliani(self):
        # Lunes 2026-08-17 es festivo (Asunción, corrida desde el sábado 15).
        # El cálculo NO sabe de Emiliani: recibe es_festivo ya resuelto.
        festivos = {date(2026, 8, 17)}
        h = descomponer(dt(2026, 8, 17, 8), dt(2026, 8, 17, 16), TASA,
                        es_festivo=lambda d: d in festivos)
        self.assertAlmostEqual(h["dominical_diurna"], 8.0)
        self.assertAlmostEqual(h["ordinaria_diurna"], 0.0)

    def test_domingo_y_festivo_el_mismo_dia_no_se_suma_dos_veces(self):
        # 2026-11-01 es domingo Y (en el ejemplo) festivo: sigue siendo UNA sola
        # categoría dominical/festiva. La suma tiene que dar la duración exacta.
        festivos = {date(2026, 11, 1)}
        h = descomponer(dt(2026, 11, 1, 8), dt(2026, 11, 1, 16), TASA,
                        es_festivo=lambda d: d in festivos)
        self.assertAlmostEqual(h["dominical_diurna"], 8.0)
        self.assertAlmostEqual(sum(h.values()), 8.0)

    def test_turno_de_24_horas_cubre_todas_las_franjas(self):
        # Sábado 06:00 → domingo 06:00 (24h):
        # sáb 06-21 diurna ord (15h) · sáb 21-24 nocturna ord (3h) · dom 00-06 dominical nocturna (6h)
        h = descomponer(dt(2026, 8, 15, 6), dt(2026, 8, 16, 6), TASA)
        self.assertAlmostEqual(h["ordinaria_diurna"], 15.0)
        self.assertAlmostEqual(h["ordinaria_nocturna"], 3.0)
        self.assertAlmostEqual(h["dominical_nocturna"], 6.0)
        self.assertAlmostEqual(sum(h.values()), 24.0)

    def test_turno_vacio_o_invertido_da_cero(self):
        self.assertAlmostEqual(sum(descomponer(dt(2026, 8, 11, 8), dt(2026, 8, 11, 8), TASA).values()), 0.0)
        self.assertAlmostEqual(sum(descomponer(dt(2026, 8, 11, 16), dt(2026, 8, 11, 8), TASA).values()), 0.0)

    def test_todas_las_categorias_presentes_en_la_salida(self):
        h = descomponer(dt(2026, 8, 11, 8), dt(2026, 8, 11, 16), TASA)
        for c in ("ordinaria_diurna", "ordinaria_nocturna",
                  "dominical_diurna", "dominical_nocturna"):
            self.assertIn(c, h)


class IdentidadTest(unittest.TestCase):
    """LA identidad innegociable: la suma de las categorías == la duración del
    turno. Si no cierra, alguien cobra de menos."""

    CASOS = [
        (dt(2026, 8, 11, 8), dt(2026, 8, 11, 16)),          # diurno simple
        (dt(2026, 8, 11, 20, 45), dt(2026, 8, 12, 6, 15)),  # cruza medianoche y ambos bordes
        (dt(2026, 8, 15, 18), dt(2026, 8, 16, 2)),          # sábado → domingo
        (dt(2026, 8, 16, 22), dt(2026, 8, 17, 5)),          # domingo → lunes festivo
        (dt(2026, 8, 14, 5, 1), dt(2026, 8, 14, 6, 1)),     # un minuto a cada lado del borde
        (dt(2026, 8, 13, 0), dt(2026, 8, 16, 0)),           # 72h corridas (3 días)
        (dt(2026, 8, 12, 12), dt(2026, 8, 12, 12, 7)),      # 7 minutos
        (dt(2026, 12, 31, 21), dt(2027, 1, 1, 3)),          # cruza el año
    ]

    def test_suma_de_categorias_igual_duracion(self):
        festivos = {date(2026, 8, 17), date(2027, 1, 1)}
        for inicio, fin in self.CASOS:
            with self.subTest(inicio=inicio, fin=fin):
                h = descomponer(inicio, fin, TASA, es_festivo=lambda d: d in festivos)
                esperado = (fin - inicio).total_seconds() / 3600.0
                self.assertAlmostEqual(sum(h.values()), esperado, places=9)

    def test_segmentos_no_se_solapan_y_van_en_orden(self):
        segs = segmentar(dt(2026, 8, 15, 18), dt(2026, 8, 16, 6), TASA)
        self.assertTrue(all(horas > 0 for _, horas in segs))
        self.assertAlmostEqual(sum(h for _, h in segs), 12.0, places=9)

    def test_identidad_sobrevive_a_la_liquidacion_semanal(self):
        # liquidar_semana RECLASIFICA horas (ordinaria → extra), nunca las crea
        # ni las destruye: el total tiene que ser el mismo.
        tramos = [
            (dt(2026, 8, 10, 8), dt(2026, 8, 10, 16)),
            (dt(2026, 8, 11, 8), dt(2026, 8, 11, 16)),
            (dt(2026, 8, 12, 8), dt(2026, 8, 12, 16)),
            (dt(2026, 8, 13, 8), dt(2026, 8, 13, 16)),
            (dt(2026, 8, 14, 8), dt(2026, 8, 14, 16)),
            (dt(2026, 8, 15, 18), dt(2026, 8, 16, 2)),
        ]
        total = sum((f - i).total_seconds() / 3600.0 for i, f in tramos)
        h = liquidar_semana(tramos, TASA)
        self.assertAlmostEqual(sum(h.values()), total, places=9)


class ExtrasSemanalesTest(unittest.TestCase):
    """La hora extra se decide sobre el ACUMULADO SEMANAL, no por turno."""

    def test_seis_dias_de_ocho_horas_generan_cuatro_extras(self):
        # 6 × 8h = 48h con jornada máxima 44 → 44 ordinarias + 4 extra diurnas.
        tramos = [(dt(2026, 8, d, 8), dt(2026, 8, d, 16)) for d in range(10, 16)]
        h = liquidar_semana(tramos, TASA)
        self.assertAlmostEqual(h["ordinaria_diurna"], 44.0)
        self.assertAlmostEqual(h["extra_diurna"], 4.0)
        self.assertAlmostEqual(sum(h.values()), 48.0)

    def test_ningun_turno_pasa_la_jornada_pero_la_semana_si(self):
        # Ningún turno solo supera 44h; la semana sí. El extra aparece igual.
        tramos = [(dt(2026, 8, d, 8), dt(2026, 8, d, 17)) for d in range(10, 15)]  # 5 × 9h = 45
        h = liquidar_semana(tramos, TASA)
        self.assertAlmostEqual(h["ordinaria_diurna"], 44.0)
        self.assertAlmostEqual(h["extra_diurna"], 1.0)

    def test_las_extras_caen_en_las_ULTIMAS_horas_de_la_semana(self):
        # Lun-Vie 8h diurnas (40h) + sábado 18:00→domingo 02:00 (8h).
        # Quedan 4h ordinarias de cupo: 3h diurnas del sábado + 1h nocturna.
        # El resto: 2h extra nocturna + 2h extra dominical nocturna.
        tramos = [(dt(2026, 8, d, 8), dt(2026, 8, d, 16)) for d in range(10, 15)]
        tramos.append((dt(2026, 8, 15, 18), dt(2026, 8, 16, 2)))
        h = liquidar_semana(tramos, TASA)
        self.assertAlmostEqual(h["ordinaria_diurna"], 43.0)
        self.assertAlmostEqual(h["ordinaria_nocturna"], 1.0)
        self.assertAlmostEqual(h["extra_nocturna"], 2.0)
        self.assertAlmostEqual(h["extra_dominical_nocturna"], 2.0)
        self.assertAlmostEqual(sum(h.values()), 48.0)

    def test_el_orden_de_entrada_no_altera_el_resultado(self):
        # liquidar_semana ordena cronológicamente: pasarle los tramos desordenados
        # tiene que dar exactamente lo mismo.
        tramos = [(dt(2026, 8, d, 8), dt(2026, 8, d, 16)) for d in range(10, 16)]
        a = liquidar_semana(tramos, TASA)
        b = liquidar_semana(list(reversed(tramos)), TASA)
        self.assertEqual(a, b)

    def test_semana_corta_no_genera_extras(self):
        tramos = [(dt(2026, 8, d, 8), dt(2026, 8, d, 16)) for d in range(10, 15)]  # 40h
        h = liquidar_semana(tramos, TASA)
        self.assertAlmostEqual(h["extra_diurna"], 0.0)
        self.assertAlmostEqual(h["ordinaria_diurna"], 40.0)

    def test_dominical_tambien_cuenta_contra_la_jornada_semanal(self):
        # Decisión declarada: TODO tiempo trabajado consume cupo de jornada, el
        # dominical incluido. Domingo 8h + 5 días de 8h = 48h → 4 extras.
        tramos = [(dt(2026, 8, 16, 8), dt(2026, 8, 16, 16))]  # domingo (fin de semana)
        tramos += [(dt(2026, 8, d, 8), dt(2026, 8, d, 16)) for d in range(10, 15)]
        h = liquidar_semana(tramos, TASA)
        self.assertAlmostEqual(sum(h.values()), 48.0)
        self.assertAlmostEqual(h["ordinaria_diurna"] + h["dominical_diurna"], 44.0)
        self.assertAlmostEqual(h["extra_diurna"] + h["extra_dominical_diurna"], 4.0)

    def test_salida_siempre_trae_las_ocho_categorias(self):
        h = liquidar_semana([(dt(2026, 8, 11, 8), dt(2026, 8, 11, 16))], TASA)
        self.assertEqual(set(h.keys()), set(CATEGORIAS))
        self.assertEqual(len(CATEGORIAS), 8)


class DetallePorTramoTest(unittest.TestCase):
    """El resumen MENSUAL necesita saber a qué día pertenece cada hora, pero la
    extra se decide por SEMANA. `liquidar_semana_por_tramo` liquida la semana
    entera y devuelve el resultado desagregado por tramo, para poder sumar solo
    los días del mes sin perder el umbral semanal."""

    def test_devuelve_un_resultado_por_tramo_en_orden_cronologico(self):
        tramos = [(dt(2026, 8, d, 8), dt(2026, 8, d, 16)) for d in range(10, 16)]
        detalle = liquidar_semana_por_tramo(tramos, TASA)
        self.assertEqual(len(detalle), 6)
        self.assertEqual([t[0] for t in detalle], sorted(i for i, _ in tramos))

    def test_la_suma_del_detalle_es_igual_al_agregado(self):
        tramos = [(dt(2026, 8, d, 8), dt(2026, 8, d, 16)) for d in range(10, 16)]
        tramos.append((dt(2026, 8, 15, 18), dt(2026, 8, 16, 2)))
        agregado = liquidar_semana(tramos, TASA)
        detalle = liquidar_semana_por_tramo(tramos, TASA)
        for cat in CATEGORIAS:
            self.assertAlmostEqual(sum(h[cat] for _, h in detalle), agregado[cat], places=9)

    def test_las_extras_quedan_en_el_tramo_que_las_causo(self):
        # 6 × 8h: las 4 extras son del ÚLTIMO día, no repartidas.
        tramos = [(dt(2026, 8, d, 8), dt(2026, 8, d, 16)) for d in range(10, 16)]
        detalle = liquidar_semana_por_tramo(tramos, TASA)
        self.assertAlmostEqual(detalle[-1][1]["extra_diurna"], 4.0)
        self.assertAlmostEqual(detalle[0][1]["extra_diurna"], 0.0)


class ValorizacionTest(unittest.TestCase):
    """El dinero es un ESTIMADO derivado de la tasa — nunca de una constante."""

    def test_factores_salen_de_la_tasa(self):
        f = factores(TASA)
        self.assertAlmostEqual(f["ordinaria_diurna"], 1.0)
        self.assertAlmostEqual(f["ordinaria_nocturna"], 1.35)
        self.assertAlmostEqual(f["dominical_diurna"], 1.75)
        self.assertAlmostEqual(f["dominical_nocturna"], 2.10)   # 1 + .75 + .35
        self.assertAlmostEqual(f["extra_diurna"], 1.25)
        self.assertAlmostEqual(f["extra_nocturna"], 1.75)
        self.assertAlmostEqual(f["extra_dominical_diurna"], 2.00)   # 1 + .75 + .25
        self.assertAlmostEqual(f["extra_dominical_nocturna"], 2.50)  # 1 + .75 + .75

    def test_recargo_dominical_nocturno_explicito_manda_sobre_la_suma(self):
        tasa = Tasa(
            jornada_max_semanal=44.0, hora_inicio_nocturna=21, hora_fin_nocturna=6,
            recargo_nocturno=0.35, recargo_dominical=0.75,
            recargo_dominical_nocturno=1.50,   # cargado a mano por el contador
            extra_diurna=0.25, extra_nocturna=0.75, divisor_hora_mensual=240.0,
        )
        self.assertAlmostEqual(factores(tasa)["dominical_nocturna"], 2.50)

    def test_valor_hora_ordinaria_sale_del_divisor_de_la_tasa(self):
        v = valorizar({"ordinaria_diurna": 1.0}, TASA, salario_mensual=1_200_000)
        self.assertAlmostEqual(v["valor_hora_ordinaria"], 5000.0)  # 1.200.000 / 240
        self.assertAlmostEqual(v["total"], 5000.0)

    def test_valoriza_cada_categoria_con_su_factor(self):
        horas = {"ordinaria_diurna": 10.0, "ordinaria_nocturna": 2.0,
                 "dominical_diurna": 4.0, "extra_diurna": 1.0}
        v = valorizar(horas, TASA, salario_mensual=1_200_000)
        esperado = 5000 * (10 * 1.0 + 2 * 1.35 + 4 * 1.75 + 1 * 1.25)
        self.assertAlmostEqual(v["total"], esperado)
        self.assertAlmostEqual(v["detalle"]["dominical_diurna"], 5000 * 4 * 1.75)

    def test_sin_salario_el_estimado_es_cero_pero_no_revienta(self):
        v = valorizar({"ordinaria_diurna": 8.0}, TASA, salario_mensual=0)
        self.assertAlmostEqual(v["total"], 0.0)
        self.assertAlmostEqual(v["valor_hora_ordinaria"], 0.0)

    def test_divisor_cero_no_divide_por_cero(self):
        tasa = Tasa(
            jornada_max_semanal=44.0, hora_inicio_nocturna=21, hora_fin_nocturna=6,
            recargo_nocturno=0.35, recargo_dominical=0.75,
            extra_diurna=0.25, extra_nocturna=0.75, divisor_hora_mensual=0.0,
        )
        v = valorizar({"ordinaria_diurna": 8.0}, tasa, salario_mensual=1_200_000)
        self.assertAlmostEqual(v["total"], 0.0)


if __name__ == "__main__":
    unittest.main()
