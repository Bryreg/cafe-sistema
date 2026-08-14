"""Los cinco números de la nómina colombiana, YA DENTRO del resumen mensual.

`test_liquidacion_colombia.py` prueba las funciones puras contra los decretos.
Esto prueba el CABLEADO: que el resumen que ve el dueño arme bien las tres
entradas de `liquidacion.liquidar` —devengado, sueldo del contrato y días con
derecho a auxilio— y que lo que sale por pantalla, por los totales y por el CSV
del contador sea el mismo número.

Los dos errores que estos tests existen para pinchar, porque los dos cuestan
plata de verdad y ninguno rompe nada al hacerse:

  1. Contar los días del auxilio por CALENDARIO. Agosto tiene 31 días: con el
     divisor 30 fijo de la ley, eso paga $257.398 en vez de $249.095 — y
     febrero paga $232.489, que además es ilegal porque el auxilio es un piso.
  2. Darle auxilio a quien no tiene contrato cargado. Su sueldo es $0, $0 está
     por debajo del tope, y el auxilio entero aparece solo, sin devengado.

Todo el archivo trabaja sobre agosto y febrero de 2026, con el mínimo y el
auxilio de los Decretos 1469 y 1470 de 2025.
"""
import calendar
import unittest
from datetime import date, timedelta

from app.models.models import ContratoBarista, RolEnum, Usuario
from app.services import nomina as svc
from app.services import novedades_nomina as nsvc
from app.services import parametros_nomina as pn

from test_nomina_resumen import NominaBase, utc

SMMLV_2026 = 1_750_905.0
AUXILIO_2026 = 249_095.0


class LiquidacionBase(NominaBase):
    """Reusa el andamiaje del resumen y le pone a Catherin un contrato EN SMMLV.

    El contrato en mínimos es el caso real de esta cafetería: las baristas
    ganan «un salario mínimo», no un número que alguien tecleó. Y es el caso
    que pincha el piso del IBC, porque un mes de días hábiles a jornada normal
    devenga MENOS que un mínimo mensual y aún así cotiza sobre uno entero.
    """

    def setUp(self):
        super().setUp()
        pn.sembrar(self.db)
        contrato = self.db.query(ContratoBarista).filter(
            ContratoBarista.usuario_id == self.cath.id).first()
        contrato.salario_mensual = 0.0
        contrato.salario_en_smmlv = 1.0
        self.db.commit()

    def trabajar(self, anio, mes, usuario=None, excepto=()):
        """Marca 08:00→16:00 todos los días hábiles del mes. Devuelve los días.

        8 h de lunes a viernes son 40 h semanales: por debajo de la jornada
        máxima, así que no aparecen extras y el devengado se puede razonar de
        cabeza. Lo que se está probando acá es el cableado, no el umbral —eso
        ya lo cubre `test_nomina_resumen`.
        """
        u = usuario or self.cath
        excluidos = set(excepto)
        hechos = []
        for numero in range(1, calendar.monthrange(anio, mes)[1] + 1):
            d = date(anio, mes, numero)
            if d.weekday() >= 5 or d in excluidos:
                continue
            self.real(u, utc(anio, mes, numero, 8), utc(anio, mes, numero, 16))
            hechos.append(d)
        return hechos

    def liq_de_cath(self, anio=2026, mes=8):
        return self.de_cath(self.resumen(anio, mes))["liquidacion"]


class LosCincoNumerosEnElResumenTest(LiquidacionBase):
    def test_un_mes_completo_trae_los_cinco_numeros_y_cierran_entre_si(self):
        self.trabajar(2026, 8)
        c = self.de_cath(self.resumen())
        lq = c["liquidacion"]

        # 1. El devengado ES el estimado: son la misma plata con dos nombres. Si
        #    alguna vez divergen, la pantalla y el bloque de liquidación estarían
        #    contando el mismo mes dos veces distintas.
        self.assertGreater(lq["devengado"], 0.0)
        self.assertAlmostEqual(lq["devengado"], c["estimado"]["total"], places=2)
        # 2, 3, 4 y 5 cierran sin términos sueltos.
        self.assertAlmostEqual(
            lq["neto_a_pagar"],
            lq["devengado"] + lq["auxilio"]["total"] - lq["deducciones"]["total"],
            places=2)
        self.assertAlmostEqual(
            lq["costo_empleador"],
            lq["devengado"] + lq["auxilio"]["total"]
            + lq["aportes_empleador"]["total"] + lq["prestaciones"]["total"],
            places=2)
        # El malentendido que todo esto existe para evitar: lo que sale del
        # negocio no es lo que recibe la barista.
        self.assertGreater(lq["costo_empleador"], lq["neto_a_pagar"])
        self.assertGreater(lq["factor_costo"], 1.5)

    def test_liquida_con_la_vigencia_del_periodo_no_con_la_de_hoy(self):
        self.trabajar(2026, 8)
        self.assertEqual(self.liq_de_cath()["vigencia_parametros"], "2026-01-01")
        self.assertTrue(self.liq_de_cath()["es_estimado"])

    def test_el_piso_del_IBC_llega_hasta_la_pantalla(self):
        """21 días hábiles de 8 h devengan menos de un mínimo mensual, y aun así
        la base de cotización es un mínimo ENTERO. Es el gotcha caro: quien
        planea jornadas cortas creyendo que los aportes bajan igual, se
        equivoca por varios cientos de miles."""
        self.trabajar(2026, 8)
        lq = self.liq_de_cath()
        self.assertLess(lq["devengado"], SMMLV_2026)
        self.assertAlmostEqual(lq["deducciones"]["base_ibc"], SMMLV_2026, places=2)
        self.assertAlmostEqual(lq["deducciones"]["salud"],
                               round(SMMLV_2026 * 0.04, 2), places=2)


class DiasDeAuxilioTest(LiquidacionBase):
    def test_un_mes_entero_paga_el_auxilio_ENTERO_aunque_agosto_tenga_31_dias(self):
        """EL TEST QUE PINCHA EL BUG DEL CALENDARIO.

        Si los días del período se cuentan como días de calendario, agosto manda
        31 contra un divisor de 30 y el auxilio sale $257.398 — $8.303 de más
        por barista y por mes, todos los meses de 31 días.
        """
        self.trabajar(2026, 8)
        lq = self.liq_de_cath()
        self.assertEqual(lq["auxilio"]["dias"], 30)
        self.assertAlmostEqual(lq["auxilio"]["total"], AUXILIO_2026, places=0)
        self.assertTrue(lq["auxilio"]["tiene_derecho"])

    def test_febrero_paga_exactamente_lo_mismo_que_agosto(self):
        """El otro lado del mismo bug, y el peor: contar 28 días le pagaría
        $232.489, y el auxilio es un PISO legal, no un promedio."""
        self.trabajar(2026, 2)
        feb = self.liq_de_cath(2026, 2)
        self.assertEqual(feb["auxilio"]["dias"], 30)
        self.assertAlmostEqual(feb["auxilio"]["total"], AUXILIO_2026, places=0)

    def test_el_mes_de_nomina_son_30_dias_tenga_28_o_31_el_calendario(self):
        p = pn.para(self.db, date(2026, 8, 1))
        for desde, hasta in ((date(2026, 2, 1), date(2026, 2, 28)),
                             (date(2026, 8, 1), date(2026, 8, 31)),
                             (date(2026, 9, 1), date(2026, 9, 30))):
            self.assertEqual(svc._dias_de_nomina(desde, hasta, p), 30,
                             f"{desde} → {hasta} tiene que ser un mes de 30 días")
        # Un período que NO es un mes entero sí cuenta sus días.
        self.assertEqual(
            svc._dias_de_nomina(date(2026, 8, 1), date(2026, 8, 10), p), 10)

    def test_una_incapacidad_recorta_los_dias_con_derecho_a_auxilio(self):
        """Sin desplazamiento no hay pasaje que reembolsar: los 5 días de
        incapacidad no generan auxilio, pero SÍ acreditan el tiempo."""
        incapacitada = [date(2026, 8, d) for d in range(10, 15)]
        self.trabajar(2026, 8, excepto=incapacitada)
        for d in incapacitada:
            self.planear(self.cath, d)
        nsvc.crear(self.db, self.t.id, self.cath.id, "incapacidad",
                   incapacitada[0], incapacitada[-1], creado_por_id=self.admin.id)

        lq = self.liq_de_cath()
        self.assertEqual(lq["auxilio"]["dias"], 25)
        self.assertAlmostEqual(lq["auxilio"]["total"],
                               round(AUXILIO_2026 / 30 * 25, 2), places=2)
        # Y el tiempo de esos días sigue acreditado: el auxilio baja, el
        # devengado no. Confundir las dos cosas le quitaría el sueldo a alguien
        # que estaba enferma con certificado.
        self.assertGreater(self.de_cath(self.resumen())["total_acreditado"], 0.0)

    def test_el_descanso_normal_NO_recorta_el_auxilio(self):
        """Los domingos y los festivos entran dentro de los 30 días. Restarlos
        —«solo trabajó 21 días»— le pagaría $174.366 en vez de $249.095."""
        self.trabajar(2026, 8)
        self.assertEqual(self.liq_de_cath()["auxilio"]["dias"], 30)

    def test_un_permiso_no_remunerado_tambien_suspende_el_auxilio(self):
        self.trabajar(2026, 8, excepto=[date(2026, 8, 10)])
        nsvc.crear(self.db, self.t.id, self.cath.id, "permiso_no_remunerado",
                   date(2026, 8, 10), date(2026, 8, 10), creado_por_id=self.admin.id)
        self.assertEqual(self.liq_de_cath()["auxilio"]["dias"], 29)

    def test_un_cambio_de_turno_no_le_toca_el_auxilio_a_nadie(self):
        """No toda novedad suspende: un cambio de turno documenta quién cubrió
        a quién, la persona igual se desplazó y su pasaje se le paga."""
        self.trabajar(2026, 8)
        nsvc.crear(self.db, self.t.id, self.cath.id, "cambio_turno",
                   date(2026, 8, 10), date(2026, 8, 10), creado_por_id=self.admin.id)
        self.assertEqual(self.liq_de_cath()["auxilio"]["dias"], 30)


class SinContratoTest(LiquidacionBase):
    """Media cafetería puede estar sin contrato cargado el día que esto salga."""

    def eliana(self):
        u = Usuario(nombre="Eliana", email="eli@t.local", password_hash="h",
                    rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add(u)
        self.db.commit()
        return u

    def de_eliana(self, r, uid):
        return [b for b in r["baristas"] if b["usuario_id"] == uid][0]

    def test_sin_contrato_la_liquidacion_da_TODO_en_cero_pero_las_horas_estan(self):
        eli = self.eliana()
        self.trabajar(2026, 8, usuario=eli)
        b = self.de_eliana(self.resumen(), eli.id)
        lq = b["liquidacion"]

        self.assertFalse(b["tiene_contrato"])
        self.assertGreater(b["total_real"], 0.0)     # las horas SÍ se cuentan
        self.assertEqual(lq["devengado"], 0.0)
        # EL GUARDIA: sin devengado no hay auxilio. Un sueldo de $0 está por
        # debajo del tope de 2 SMMLV, así que sin esto `auxilio_del_periodo` le
        # daba derecho y aparecían $249.095 sueltos, sin sueldo que los explique.
        self.assertEqual(lq["auxilio"]["total"], 0.0)
        self.assertEqual(lq["auxilio"]["dias"], 0)
        self.assertEqual(lq["deducciones"]["total"], 0.0)
        self.assertEqual(lq["deducciones"]["base_ibc"], 0.0)
        self.assertEqual(lq["neto_a_pagar"], 0.0)
        self.assertEqual(lq["aportes_empleador"]["total"], 0.0)
        self.assertEqual(lq["prestaciones"]["total"], 0.0)
        self.assertEqual(lq["costo_empleador"], 0.0)
        self.assertEqual(lq["factor_costo"], 0.0)

    def test_una_barista_con_contrato_pero_sin_un_solo_dia_no_cobra_auxilio(self):
        """Alguien que se fue el mes pasado y sigue en la lista: aparece, con
        todo en cero. Pagarle el auxilio por existir sería inventar plata."""
        lq = self.liq_de_cath()
        self.assertEqual(lq["devengado"], 0.0)
        self.assertEqual(lq["auxilio"]["total"], 0.0)
        self.assertEqual(lq["costo_empleador"], 0.0)

    def test_el_resumen_no_se_cae_con_una_barista_sin_contrato_al_lado(self):
        eli = self.eliana()
        self.trabajar(2026, 8)
        self.trabajar(2026, 8, usuario=eli)
        r = self.resumen()
        self.assertEqual(r["totales"]["sin_contrato"], 1)
        for b in r["baristas"]:
            self.assertIn("liquidacion", b)
            self.assertIn("neto_a_pagar", b["liquidacion"])


class TotalesTest(LiquidacionBase):
    def setUp(self):
        super().setUp()
        self.eli = Usuario(nombre="Eliana", email="eli@t.local", password_hash="h",
                           rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add(self.eli)
        self.db.flush()
        self.db.add(ContratoBarista(usuario_id=self.eli.id, salario_mensual=0.0,
                                    salario_en_smmlv=1.0))
        self.db.commit()

    def test_los_totales_son_la_SUMA_de_las_baristas_no_un_recalculo(self):
        """Recalcular sobre el devengado agregado daría otro número y sería el
        equivocado: el piso del IBC y el tope del auxilio son POR PERSONA. Dos
        medios tiempos cotizan sobre dos mínimos enteros, no sobre uno."""
        self.trabajar(2026, 8)
        self.trabajar(2026, 8, usuario=self.eli, excepto=[date(2026, 8, 3)])
        r = self.resumen()
        t = r["totales"]
        bs = r["baristas"]

        self.assertAlmostEqual(t["total_devengado"],
                               sum(b["liquidacion"]["devengado"] for b in bs), places=2)
        self.assertAlmostEqual(t["total_auxilio"],
                               sum(b["liquidacion"]["auxilio"]["total"] for b in bs),
                               places=2)
        self.assertAlmostEqual(t["total_deducciones"],
                               sum(b["liquidacion"]["deducciones"]["total"] for b in bs),
                               places=2)
        self.assertAlmostEqual(t["total_neto"],
                               sum(b["liquidacion"]["neto_a_pagar"] for b in bs), places=2)
        self.assertAlmostEqual(t["total_costo_empleador"],
                               sum(b["liquidacion"]["costo_empleador"] for b in bs),
                               places=2)

    def test_dos_baristas_de_minimo_pagan_DOS_auxilios_enteros(self):
        self.trabajar(2026, 8)
        self.trabajar(2026, 8, usuario=self.eli)
        self.assertAlmostEqual(self.resumen()["totales"]["total_auxilio"],
                               AUXILIO_2026 * 2, places=0)

    def test_el_total_devengado_es_el_mismo_estimado_de_siempre(self):
        """El número viejo no se movió: lo que cambió es que ahora tiene cuatro
        hermanos al lado. Si esto se despega, el bloque nuevo estaría liquidando
        sobre horas distintas de las que muestra la tabla."""
        self.trabajar(2026, 8)
        self.trabajar(2026, 8, usuario=self.eli)
        t = self.resumen()["totales"]
        self.assertAlmostEqual(t["total_devengado"], t["estimado"], places=2)

    def test_el_costo_del_empleador_es_muy_superior_al_neto_del_mes(self):
        self.trabajar(2026, 8)
        self.trabajar(2026, 8, usuario=self.eli)
        t = self.resumen()["totales"]
        self.assertGreater(t["total_costo_empleador"], t["total_neto"] * 1.4)


class AdvertenciasTest(LiquidacionBase):
    def test_ya_no_dicen_que_falta_lo_que_ahora_SI_esta(self):
        """La advertencia vieja decía «no incluye auxilio de transporte,
        prestaciones, seguridad social ni deducciones». Desde que el payload
        los trae, esa frase es mentira — y una advertencia que miente hace que
        el dueño deje de leer todas las demás."""
        texto = " ".join(self.resumen()["advertencias"]).lower()
        self.assertNotIn("no incluye auxilio", texto)
        self.assertNotIn("ni deducciones", texto)

    def test_nombran_UNO_POR_UNO_los_descuentos_que_faltan(self):
        """«Es un estimado» a secas no le sirve a nadie para saber qué revisar."""
        texto = " ".join(self.resumen()["advertencias"]).lower()
        for falta in ("retención en la fuente", "embargo", "libranza",
                      "pila", "1990/2016", "66,67"):
            self.assertIn(falta, texto, f"la advertencia no nombra: {falta}")

    def test_explican_la_regla_del_auxilio_y_el_piso_del_IBC(self):
        texto = " ".join(self.resumen()["advertencias"]).lower()
        self.assertIn("30 días", texto)
        self.assertIn("salario mínimo entero", texto)

    def test_siguen_estando_las_advertencias_viejas_que_no_cambiaron(self):
        texto = " ".join(self.resumen()["advertencias"]).lower()
        self.assertIn("cierre de caja", texto)
        self.assertIn("borradores", texto)


class CsvDelContadorTest(LiquidacionBase):
    def csv(self, anio=2026, mes=8):
        lineas = svc.csv_mensual(self.db, self.t.id, anio, mes).splitlines()
        cabecera = lineas[0].split(";")
        fila = [l for l in lineas if l.startswith("Catherin;")][0].split(";")
        return cabecera, fila

    def test_el_csv_lleva_los_cinco_numeros_y_no_solo_el_devengado(self):
        self.trabajar(2026, 8)
        cabecera, fila = self.csv()
        lq = self.liq_de_cath()
        esperado = {
            "Devengado ($)": lq["devengado"],
            "Auxilio transporte ($)": lq["auxilio"]["total"],
            "Deducciones ($)": lq["deducciones"]["total"],
            "Neto a pagar ($)": lq["neto_a_pagar"],
            "Costo empleador ($)": lq["costo_empleador"],
        }
        for columna, valor in esperado.items():
            self.assertIn(columna, cabecera, f"falta la columna {columna}")
            self.assertEqual(fila[cabecera.index(columna)], f"{valor:.0f}",
                             f"la columna {columna} no coincide con el payload")

    def test_lleva_tambien_con_que_auditar_el_costo(self):
        """Un `costo_empleador` sin sus partes no se puede verificar, y lo que
        no se puede verificar el contador no lo usa. La base del IBC es además
        lo que necesita para armar la PILA."""
        self.trabajar(2026, 8)
        cabecera, fila = self.csv()
        lq = self.liq_de_cath()
        self.assertEqual(fila[cabecera.index("Base IBC ($)")],
                         f"{lq['deducciones']['base_ibc']:.0f}")
        self.assertEqual(fila[cabecera.index("Aportes empleador ($)")],
                         f"{lq['aportes_empleador']['total']:.0f}")
        self.assertEqual(fila[cabecera.index("Prestaciones ($)")],
                         f"{lq['prestaciones']['total']:.0f}")
        self.assertEqual(fila[cabecera.index("Días con auxilio")], "30")

    def test_la_columna_estimado_se_llama_ahora_devengado_y_no_esta_dos_veces(self):
        self.trabajar(2026, 8)
        cabecera, _ = self.csv()
        self.assertIn("Devengado ($)", cabecera)
        self.assertNotIn("Estimado ($)", cabecera)

    def test_el_pie_del_csv_dice_lo_que_falta(self):
        """El CSV se reenvía por WhatsApp sin la pantalla que lo explica: quien
        lo abre no vio ninguna advertencia."""
        pie = svc.csv_mensual(self.db, self.t.id, 2026, 8).splitlines()[-1].lower()
        self.assertIn("estimado", pie)
        self.assertIn("retención en la fuente", pie)
        self.assertIn("pila", pie)
        self.assertNotIn("no incluye prestaciones ni deducciones", pie)

    def test_una_barista_sin_contrato_sale_en_ceros_y_no_rompe_la_fila(self):
        eli = Usuario(nombre="Eliana", email="eli@t.local", password_hash="h",
                      rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add(eli)
        self.db.commit()
        self.trabajar(2026, 8, usuario=eli)
        lineas = svc.csv_mensual(self.db, self.t.id, 2026, 8).splitlines()
        cabecera = lineas[0].split(";")
        fila = [l for l in lineas if l.startswith("Eliana;")][0].split(";")
        self.assertEqual(len(fila), len(cabecera))
        self.assertEqual(fila[cabecera.index("Costo empleador ($)")], "0")
        self.assertEqual(fila[cabecera.index("Auxilio transporte ($)")], "0")


class SinParametrosCargadosTest(LiquidacionBase):
    """La base sin ni una vigencia: no puede tumbar la pantalla de nómina."""

    def test_la_forma_vacia_tiene_las_mismas_claves_que_una_liquidacion_real(self):
        """Si `_liquidacion_vacia` se queda corta, el día que falte una vigencia
        la pantalla revienta en el primer acceso a una clave que no está — y
        revienta en producción, que es cuando se descubre."""
        self.trabajar(2026, 8)
        real = self.liq_de_cath()
        vacia = svc._liquidacion_vacia()
        self.assertEqual(set(vacia), set(real))
        for clave in ("auxilio", "deducciones", "aportes_empleador", "prestaciones"):
            self.assertEqual(set(vacia[clave]), set(real[clave]),
                             f"la forma vacía de {clave} no coincide")

    def test_la_forma_vacia_esta_toda_en_cero_y_pide_confirmar(self):
        vacia = svc._liquidacion_vacia()
        self.assertEqual(vacia["devengado"], 0.0)
        self.assertEqual(vacia["neto_a_pagar"], 0.0)
        self.assertEqual(vacia["costo_empleador"], 0.0)
        self.assertTrue(vacia["confirmar_contador"])
        self.assertIsNone(vacia["vigencia_parametros"])


if __name__ == "__main__":
    unittest.main()
