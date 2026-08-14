"""El costo laboral entra al P&L calculado, no digitado.

Lo que fija este archivo:

1. El costo del período sale de las horas MARCADAS × los recargos de ley, con la
   misma cuenta que muestra el resumen mensual. Si los dos números se separan,
   uno de los dos está mintiendo.
2. Sin salario cargado en Contratos no hay costo: prender esto no le mueve el
   margen a nadie que todavía no usa el módulo de nómina.
3. Convivencia con lo cargado a mano: el mes que tiene una obligación de nómina
   usa ESA y descarta el cálculo. La misma plata nunca se cuenta dos veces, y la
   historia ya cargada no cambia ni un peso.
4. El corte por período es el de las horas, no el de un prorrateo: las horas de
   julio no entran a un rango de agosto.
5. El desglose sigue siendo una PARTICIÓN: Σ por_mes = Σ por_sede =
   Σ por_categoria = resumen.gastos.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    CajaTurno, ContratoBarista, CostoCategoria, EstadoTurnoEnum, Obligacion,
    RolEnum, Tienda, TurnoBarista, Usuario,
)
from app.services import horarios as hsvc
from app.services import nomina as nsvc
from app.services.rentabilidad import get_rentabilidad

COL = timedelta(hours=5)   # Colombia UTC-5: hora local + 5 = UTC

# Salario que hace la aritmética legible: 1.800.000 / 240 = $7.500 la hora
# ordinaria diurna, o sea $60.000 por un turno de 8 h.
SALARIO = 1_800_000.0
VALOR_HORA = SALARIO / 240.0


def utc(y, m, d, h, mi=0):
    """Instante UTC que corresponde a esa hora de RELOJ en Colombia."""
    return datetime(y, m, d, h, mi) + COL


class RentabilidadNominaBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.t1 = Tienda(nombre="Vida", direccion="x")
        self.t2 = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.t1, self.t2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.cath = Usuario(nombre="Catherin", email="cath@t.local", password_hash="h",
                            rol=RolEnum.barista, tienda_id=self.t1.id, activo=True)
        self.db.add_all([self.admin, self.cath])
        self.db.flush()

        self.cat_nomina = CostoCategoria(clave="nomina", nombre="Nómina",
                                         grupo="fijo", orden=0)
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                           grupo="fijo", orden=1)
        self.db.add_all([self.cat_nomina, self.cat_arriendo])
        self.db.commit()

        # Martes 2026-08-11 (semana del lunes 2026-08-10).
        self.martes = date(2026, 8, 11)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def con_contrato(self, salario=SALARIO, usuario=None):
        self.db.add(ContratoBarista(usuario_id=(usuario or self.cath).id,
                                    salario_mensual=salario))
        self.db.commit()

    def marcar(self, entrada_utc, salida_utc, tienda=None, usuario=None):
        """Un tramo REAL, como lo deja el flujo de caja."""
        u = usuario or self.cath
        turno = CajaTurno(tienda_id=(tienda or self.t1).id, usuario_apertura_id=u.id,
                          base_real=0.0, estado=EstadoTurnoEnum.cerrado,
                          fecha_apertura=entrada_utc, fecha_cierre=salida_utc)
        self.db.add(turno)
        self.db.flush()
        self.db.add(TurnoBarista(turno_id=turno.id, usuario_id=u.id,
                                 nombre_snapshot=u.nombre,
                                 created_at=entrada_utc, salida_at=salida_utc))
        self.db.commit()

    def turno_de_8h(self, dia: date, tienda=None, usuario=None):
        """08:00 → 16:00 hora Colombia: 8 h ordinarias diurnas."""
        self.marcar(utc(dia.year, dia.month, dia.day, 8),
                    utc(dia.year, dia.month, dia.day, 16), tienda, usuario)

    def obligacion(self, categoria, monto, devengo: date, tienda_id=None):
        self.db.add(Obligacion(tienda_id=tienda_id, categoria_id=categoria.id,
                               concepto="Cargada a mano", monto=monto,
                               fecha_devengo=devengo, usuario_id=self.admin.id,
                               anulada=False))
        self.db.commit()

    def pl(self, desde=None, hasta=None, tienda_id=None):
        d = desde or self.martes
        return get_rentabilidad(self.db, d, hasta or d, tienda_id=tienda_id)


# ─── El caso base: sin sueldo cargado, nada cambia ─────────────────────────

class SinContratoTest(RentabilidadNominaBase):
    def test_sin_salario_cargado_el_margen_no_se_mueve(self):
        """La garantía de que prender esto no rompe a nadie: quien todavía no
        cargó sueldos ve exactamente el mismo P&L de antes."""
        self.turno_de_8h(self.martes)
        r = self.pl()
        self.assertEqual(r["resumen"]["gastos"], 0)
        self.assertEqual(r["resumen"]["nomina_calculada"], 0)

    def test_pero_avisa_que_esas_horas_estan_valiendo_cero(self):
        self.turno_de_8h(self.martes)
        r = self.pl()
        self.assertEqual(r["resumen"]["nomina_sin_contrato"], 1)

    def test_sin_horas_ni_sueldo_no_hay_nada_que_decir(self):
        r = self.pl()
        self.assertEqual(r["resumen"]["nomina_calculada"], 0)
        self.assertEqual(r["resumen"]["nomina_personas"], 0)
        self.assertEqual(r["resumen"]["nomina_meses_calculados"], [])


# ─── El costo calculado entra al gasto ─────────────────────────────────────

class CostoCalculadoTest(RentabilidadNominaBase):
    def test_las_horas_marcadas_se_vuelven_gasto(self):
        self.con_contrato()
        self.turno_de_8h(self.martes)
        r = self.pl()
        self.assertAlmostEqual(r["resumen"]["nomina_calculada"], 8 * VALOR_HORA)
        self.assertAlmostEqual(r["resumen"]["gastos"], 8 * VALOR_HORA)
        self.assertAlmostEqual(r["resumen"]["margen_neto"], -8 * VALOR_HORA)
        self.assertAlmostEqual(r["resumen"]["nomina_horas"], 8.0)
        self.assertEqual(r["resumen"]["nomina_personas"], 1)
        self.assertEqual(r["resumen"]["nomina_sin_contrato"], 0)

    def test_el_recargo_nocturno_viaja_al_margen(self):
        """No es "horas × sueldo/240": es la liquidación con recargos. Un turno
        18:00→22:00 tiene 1 h diurna y 3 nocturnas al 35% adicional."""
        self.con_contrato()
        self.marcar(utc(2026, 8, 11, 18), utc(2026, 8, 11, 22))
        esperado = VALOR_HORA * (1 + 3 * 1.35)
        self.assertAlmostEqual(self.pl()["resumen"]["nomina_calculada"], esperado, places=2)

    def test_el_almuerzo_planeado_tambien_se_descuenta_del_costo(self):
        """El P&L hereda la regla del almuerzo: el descanso no se paga."""
        self.con_contrato()
        hsvc.guardar_turno(self.db, self.t1.id, self.cath.id, self.martes,
                           "08:00", "16:00", creado_por_id=self.admin.id,
                           almuerzo_inicio="12:00", almuerzo_minutos=60)
        hsvc.publicar_semana(self.db, self.t1.id, hsvc.lunes_de(self.martes), self.admin.id)
        self.turno_de_8h(self.martes)
        self.assertAlmostEqual(self.pl()["resumen"]["nomina_calculada"], 7 * VALOR_HORA)

    def test_cuenta_como_costo_fijo(self):
        """Si no contara, el negocio que dejó de cargar la nómina a mano
        aparecería como "sin costos fijos" justo cuando el dato mejoró."""
        self.con_contrato()
        self.turno_de_8h(self.martes)
        r = self.pl()
        self.assertTrue(r["resumen"]["tiene_costos_fijos"])
        self.assertAlmostEqual(r["resumen"]["costos_fijos_devengados"], 8 * VALOR_HORA)

    def test_coincide_al_peso_con_el_resumen_mensual(self):
        """EL TEST ANTI-DERIVA: la pantalla de nómina y el margen tienen que
        estar mirando el mismo número. Si alguien cambia el cálculo en un lado,
        esto se cae."""
        self.con_contrato()
        for i in range(5):                       # lunes a viernes
            self.turno_de_8h(date(2026, 8, 10) + timedelta(days=i))
        resumen = nsvc.resumen_mensual(self.db, self.t1.id, 2026, 8)
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31), tienda_id=self.t1.id)
        self.assertAlmostEqual(r["resumen"]["nomina_calculada"],
                               resumen["totales"]["estimado"], places=2)


# ─── Convivencia con la nómina cargada a mano ──────────────────────────────

class ConvivenciaConLoManualTest(RentabilidadNominaBase):
    def test_si_el_mes_tiene_nomina_a_mano_gana_la_mano(self):
        """Lo que evita el doble conteo: la obligación manual se suma (como
        siempre) y el cálculo de ESE mes se descarta entero."""
        self.con_contrato()
        self.turno_de_8h(self.martes)
        self.obligacion(self.cat_nomina, 2_000_000, date(2026, 8, 31))
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(r["resumen"]["gastos"], 2_000_000)
        self.assertEqual(r["resumen"]["nomina_calculada"], 0)
        self.assertEqual(r["resumen"]["nomina_meses_manuales"], ["2026-08"])
        self.assertEqual(r["resumen"]["nomina_meses_calculados"], [])

    def test_la_historia_ya_cargada_no_cambia_ni_un_peso(self):
        """Meses viejos con su nómina digitada quedan idénticos."""
        self.con_contrato()
        self.turno_de_8h(date(2026, 7, 14))
        self.obligacion(self.cat_nomina, 1_500_000, date(2026, 7, 31))
        r = self.pl(date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual(r["resumen"]["gastos"], 1_500_000)

    def test_se_decide_mes_por_mes_y_no_de_una_vez(self):
        """Julio tiene la nómina cargada a mano; agosto ya no. Cada mes usa su
        fuente, que es lo que hace que dejar de digitar sea toda la migración."""
        self.con_contrato()
        self.turno_de_8h(date(2026, 7, 14))
        self.obligacion(self.cat_nomina, 1_500_000, date(2026, 7, 31))
        self.turno_de_8h(self.martes)
        r = self.pl(date(2026, 7, 1), date(2026, 8, 31))
        self.assertAlmostEqual(r["resumen"]["nomina_calculada"], 8 * VALOR_HORA)
        self.assertAlmostEqual(r["resumen"]["gastos"], 1_500_000 + 8 * VALOR_HORA)
        self.assertEqual(r["resumen"]["nomina_meses_manuales"], ["2026-07"])
        self.assertEqual(r["resumen"]["nomina_meses_calculados"], ["2026-08"])

    def test_la_nomina_de_una_sede_no_borra_el_calculo_de_la_otra(self):
        """Una obligación de nómina puede ser de UNA sede. Si apagara el cálculo
        de todas, la plata de las demás no aparecería ni calculada ni manual:
        desaparecía del margen."""
        self.con_contrato()
        self.turno_de_8h(self.martes, tienda=self.t1)
        self.turno_de_8h(self.martes, tienda=self.t2)
        self.obligacion(self.cat_nomina, 900_000, date(2026, 8, 31), tienda_id=self.t1.id)
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31))
        # Vida usa la manual; Palmetto sigue con su costo calculado.
        self.assertAlmostEqual(r["resumen"]["nomina_calculada"], 8 * VALOR_HORA)
        self.assertAlmostEqual(r["resumen"]["gastos"], 900_000 + 8 * VALOR_HORA)
        por_sede = {s["tienda_id"]: s["gastos"] for s in r["por_sede"]}
        self.assertAlmostEqual(por_sede[self.t1.id], 900_000)
        self.assertAlmostEqual(por_sede[self.t2.id], 8 * VALOR_HORA)

    def test_la_nomina_corporativa_si_apaga_el_calculo_de_todas(self):
        """Sin sede es corporativa: cubre a todo el mundo."""
        self.con_contrato()
        self.turno_de_8h(self.martes, tienda=self.t1)
        self.turno_de_8h(self.martes, tienda=self.t2)
        self.obligacion(self.cat_nomina, 2_000_000, date(2026, 8, 31))
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(r["resumen"]["nomina_calculada"], 0)
        self.assertEqual(r["resumen"]["gastos"], 2_000_000)

    def test_dos_medias_ventanas_suman_lo_mismo_que_el_mes_entero(self):
        """El P&L es ADITIVO sobre ventanas disjuntas y este término no puede ser
        la excepción. La nómina manual se detecta por MES CALENDARIO y no por la
        ventana consultada: si no, mirar "del 1 a hoy" —el período por defecto de
        la pantalla— no vería una nómina devengada el 31, daría el mes por
        calculado y sumaría un costo que el mes completo considera cubierto."""
        self.con_contrato()
        self.turno_de_8h(date(2026, 8, 5))
        self.turno_de_8h(date(2026, 8, 20))
        self.obligacion(self.cat_nomina, 2_000_000, date(2026, 8, 31))
        primera = self.pl(date(2026, 8, 1), date(2026, 8, 15))
        segunda = self.pl(date(2026, 8, 16), date(2026, 8, 31))
        entero = self.pl(date(2026, 8, 1), date(2026, 8, 31))
        self.assertAlmostEqual(primera["resumen"]["gastos"] + segunda["resumen"]["gastos"],
                               entero["resumen"]["gastos"])

    def test_el_mes_a_hoy_no_inventa_un_costo_que_el_mes_entero_no_tiene(self):
        """El caso concreto del período por defecto de la pantalla."""
        self.con_contrato()
        self.turno_de_8h(date(2026, 8, 5))
        self.obligacion(self.cat_nomina, 2_000_000, date(2026, 8, 31))
        mes_a_hoy = self.pl(date(2026, 8, 1), date(2026, 8, 15))
        self.assertEqual(mes_a_hoy["resumen"]["nomina_calculada"], 0)
        self.assertEqual(mes_a_hoy["resumen"]["nomina_meses_manuales"], ["2026-08"])

    def test_las_horas_reportadas_son_las_del_costo_reportado(self):
        """Si un mes se descarta, sus horas también: un total que no incluye un
        mes al lado de un contador de horas que sí lo incluye es un pie de página
        que miente."""
        self.con_contrato()
        self.turno_de_8h(date(2026, 7, 14))                              # mes manual
        self.obligacion(self.cat_nomina, 1_500_000, date(2026, 7, 31))
        self.turno_de_8h(self.martes)                                    # mes calculado
        r = self.pl(date(2026, 7, 1), date(2026, 8, 31))
        self.assertAlmostEqual(r["resumen"]["nomina_horas"], 8.0)

    def test_una_obligacion_de_otra_categoria_no_tapa_el_calculo(self):
        """El arriendo no es nómina: no tiene por qué desactivar el cálculo."""
        self.con_contrato()
        self.turno_de_8h(self.martes)
        self.obligacion(self.cat_arriendo, 900_000, date(2026, 8, 5))
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31))
        self.assertAlmostEqual(r["resumen"]["gastos"], 900_000 + 8 * VALOR_HORA)

    def test_una_nomina_anulada_no_tapa_el_calculo(self):
        self.con_contrato()
        self.turno_de_8h(self.martes)
        self.obligacion(self.cat_nomina, 2_000_000, date(2026, 8, 31))
        self.db.query(Obligacion).update({"anulada": True})
        self.db.commit()
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31))
        self.assertAlmostEqual(r["resumen"]["gastos"], 8 * VALOR_HORA)

    def test_la_vista_de_una_sede_ve_su_costo_calculado(self):
        """La nómina corporativa no se prorratea entre sedes (nunca se prorrateó),
        así que en la vista de una sede no hay nada que duplicar: ahí el cálculo
        entra y le da a esa sede un costo laboral que antes no tenía."""
        self.con_contrato()
        self.turno_de_8h(self.martes)
        self.obligacion(self.cat_nomina, 2_000_000, date(2026, 8, 31))   # corporativa
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31), tienda_id=self.t1.id)
        self.assertAlmostEqual(r["resumen"]["gastos"], 8 * VALOR_HORA)
        self.assertEqual(r["resumen"]["nomina_meses_manuales"], [])


# ─── Coherencia por período ────────────────────────────────────────────────

class CortePorPeriodoTest(RentabilidadNominaBase):
    def test_las_horas_de_otro_mes_no_entran(self):
        self.con_contrato()
        self.turno_de_8h(date(2026, 7, 14))
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(r["resumen"]["nomina_calculada"], 0)

    def test_un_rango_de_un_dia_trae_solo_ese_dia(self):
        self.con_contrato()
        self.turno_de_8h(date(2026, 8, 11))
        self.turno_de_8h(date(2026, 8, 12))
        r = self.pl(date(2026, 8, 11), date(2026, 8, 11))
        self.assertAlmostEqual(r["resumen"]["nomina_calculada"], 8 * VALOR_HORA)

    def test_una_semana_partida_por_el_mes_reparte_sus_dias(self):
        """La semana se liquida ENTERA (el umbral de extra es semanal) y recién
        después se corta: cada día cae en el mes al que pertenece."""
        self.con_contrato()
        self.turno_de_8h(date(2026, 8, 31))    # lunes
        self.turno_de_8h(date(2026, 9, 1))     # martes, misma semana, otro mes
        agosto = self.pl(date(2026, 8, 1), date(2026, 8, 31))
        septiembre = self.pl(date(2026, 9, 1), date(2026, 9, 30))
        self.assertAlmostEqual(agosto["resumen"]["nomina_calculada"], 8 * VALOR_HORA)
        self.assertAlmostEqual(septiembre["resumen"]["nomina_calculada"], 8 * VALOR_HORA)

    def test_el_costo_cae_en_el_mes_correcto_del_desglose(self):
        self.con_contrato()
        self.turno_de_8h(date(2026, 8, 11))
        r = self.pl(date(2026, 7, 1), date(2026, 8, 31))
        meses = {m["mes"]: m["gastos"] for m in r["por_mes"]}
        self.assertAlmostEqual(meses["2026-08"], 8 * VALOR_HORA)
        self.assertNotIn("2026-07", meses)


# ─── El desglose sigue siendo una partición ────────────────────────────────

class InvarianteDelDesgloseTest(RentabilidadNominaBase):
    def _pl_mixto(self):
        """Un período con las tres fuentes de gasto vivas a la vez."""
        self.con_contrato()
        self.turno_de_8h(date(2026, 8, 11), tienda=self.t1)
        self.turno_de_8h(date(2026, 8, 12), tienda=self.t2)
        self.obligacion(self.cat_arriendo, 900_000, date(2026, 8, 5))
        return self.pl(date(2026, 8, 1), date(2026, 8, 31))

    def test_la_suma_por_mes_da_el_total(self):
        r = self._pl_mixto()
        self.assertAlmostEqual(round(sum(m["gastos"] for m in r["por_mes"]), 2),
                               r["resumen"]["gastos"])

    def test_la_suma_por_sede_da_el_total(self):
        r = self._pl_mixto()
        self.assertAlmostEqual(round(sum(s["gastos"] for s in r["por_sede"]), 2),
                               r["resumen"]["gastos"])

    def test_la_suma_por_categoria_da_el_total(self):
        r = self._pl_mixto()
        self.assertAlmostEqual(
            round(sum(c["total"] for c in r["gastos_por_categoria"]), 2),
            r["resumen"]["gastos"])

    def test_cada_sede_carga_sus_propias_horas(self):
        r = self._pl_mixto()
        por_sede = {s["tienda_id"]: s["gastos"] for s in r["por_sede"]}
        self.assertAlmostEqual(por_sede[self.t1.id], 8 * VALOR_HORA)
        self.assertAlmostEqual(por_sede[self.t2.id], 8 * VALOR_HORA)
        self.assertAlmostEqual(por_sede[None], 900_000)   # corporativo

    def test_la_nomina_calculada_aparece_en_su_categoria(self):
        r = self._pl_mixto()
        nomina = [c for c in r["gastos_por_categoria"] if c["clave"] == "nomina"][0]
        self.assertAlmostEqual(nomina["total"], 16 * VALOR_HORA)
        self.assertEqual(nomina["grupo"], "fijo")


if __name__ == "__main__":
    unittest.main()


# ─── Lo que la pantalla tiene derecho a afirmar ────────────────────────────

class LaPantallaNoAfirmaDeMasTest(RentabilidadNominaBase):
    """Dos banderas que la pantalla usa para emitir veredictos sobre el margen.

    Las dos se prendían por la FORMA del dato y no por el MONTO, y una bandera
    prendida acá no es un detalle: es una frase en pantalla diciéndole al dueño
    que su margen ya tiene adentro un costo que no tiene adentro.
    """

    def test_horas_sin_sueldo_no_son_un_costo_fijo(self):
        """Sin contrato cargado el costo laboral es $0, y $0 no es un costo fijo.

        `nomina["pares"]` es un defaultdict: alcanza con que alguien tenga horas
        para que exista la clave en 0.0, y un dict con claves es True. La
        pantalla decía "el margen ya descuenta los costos fijos" con $0
        descontado — justo el caso en que MÁS falta el dato.
        """
        self.turno_de_8h(self.martes)                    # horas sí, sueldo no
        r = self.pl()["resumen"]
        self.assertEqual(r["nomina_calculada"], 0)
        self.assertGreater(r["nomina_sin_contrato"], 0)  # las horas están ahí
        self.assertFalse(r["tiene_costos_fijos"])

    def test_con_sueldo_cargado_si_hay_costo_fijo(self):
        self.con_contrato()
        self.turno_de_8h(self.martes)
        self.assertTrue(self.pl()["resumen"]["tiene_costos_fijos"])

    def test_la_nomina_manual_dentro_de_la_ventana_se_reporta_como_incluida(self):
        self.con_contrato()
        self.turno_de_8h(self.martes)
        self.obligacion(self.cat_nomina, 2_000_000, date(2026, 8, 31))
        r = self.pl(date(2026, 8, 1), date(2026, 8, 31))["resumen"]
        self.assertEqual(r["nomina_meses_manuales"], ["2026-08"])
        self.assertAlmostEqual(r["nomina_manual_en_ventana"], 2_000_000)

    def test_si_el_devengo_cae_afuera_la_ventana_no_tiene_ni_un_peso(self):
        """El caso que hacía mentir a la pantalla.

        El mes con nómina a mano descarta su cálculo SIEMPRE —esa es la regla
        que evita el doble conteo—, pero la plata manual entra en la ventana que
        contiene su fecha de devengo. Mirando "del 1 al 15" con la nómina
        devengada el 31, el costo laboral de ese mes no está en ningún lado: la
        pantalla no puede decir "se usó la cargada a mano" sin un peso adentro.
        """
        self.con_contrato()
        self.turno_de_8h(self.martes)                    # martes 11-ago
        self.obligacion(self.cat_nomina, 2_000_000, date(2026, 8, 31))
        r = self.pl(date(2026, 8, 1), date(2026, 8, 15))["resumen"]
        self.assertEqual(r["nomina_meses_manuales"], ["2026-08"])   # el mes está cubierto
        self.assertEqual(r["nomina_calculada"], 0)                  # y su cálculo, descartado
        self.assertEqual(r["nomina_manual_en_ventana"], 0)          # pero adentro no hay nada
