"""Resumen mensual: PLANEADO vs REAL, novedades y estimado en pesos.

Las horas reales salen de `TurnoBarista` (created_at = entró, salida_at = salió),
que este repo viene guardando desde hace meses. Los timestamps están en UTC naive
y la jornada se parte en HORA COLOMBIA: todo el módulo pasa por core/tz.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, RolEnum, CajaTurno, TurnoBarista, EstadoTurnoEnum,
    ContratoBarista, NovedadNomina, TipoNovedadNominaEnum,
)
from app.services import nomina as svc
from app.services import horarios as hsvc
from app.services import novedades_nomina as nsvc

COL = timedelta(hours=5)   # Colombia UTC-5: hora local + 5 = UTC


def utc(y, m, d, h, mi=0):
    """Instante UTC que corresponde a esa hora de RELOJ en Colombia."""
    return datetime(y, m, d, h, mi) + COL


class NominaBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.t = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.cath = Usuario(nombre="Catherin", email="cath@t.local", password_hash="h",
                            rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.kiosk = Usuario(nombre="Kiosk", email="kiosk@tienda1.device", password_hash="h",
                             rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add_all([self.admin, self.cath, self.kiosk])
        self.db.flush()
        self.db.add(ContratoBarista(usuario_id=self.cath.id, salario_mensual=1_800_000))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def real(self, usuario, entrada_utc, salida_utc, tienda=None):
        """Registra un tramo REAL como lo hace el flujo de caja."""
        turno = CajaTurno(tienda_id=(tienda or self.t).id, usuario_apertura_id=usuario.id,
                          base_real=0.0, estado=EstadoTurnoEnum.cerrado,
                          fecha_apertura=entrada_utc, fecha_cierre=salida_utc)
        self.db.add(turno)
        self.db.flush()
        tb = TurnoBarista(turno_id=turno.id, usuario_id=usuario.id,
                          nombre_snapshot=usuario.nombre,
                          created_at=entrada_utc, salida_at=salida_utc)
        self.db.add(tb)
        self.db.commit()
        return tb

    def planear(self, usuario, fecha, ini="08:00", fin="16:00", publicar=True):
        tp = hsvc.guardar_turno(self.db, self.t.id, usuario.id, fecha, ini, fin,
                                creado_por_id=self.admin.id)
        if publicar:
            hsvc.publicar_semana(self.db, self.t.id, svc.lunes_de(fecha), self.admin.id)
        return tp

    def resumen(self, anio=2026, mes=8):
        return svc.resumen_mensual(self.db, self.t.id, anio, mes)

    def de_cath(self, r):
        return [b for b in r["baristas"] if b["usuario_id"] == self.cath.id][0]


class HorasRealesTest(NominaBase):
    def test_lee_las_horas_reales_en_hora_colombia(self):
        # Martes 2026-08-11, 08:00 → 16:00 hora Colombia (13:00 → 21:00 UTC).
        self.real(self.cath, utc(2026, 8, 11, 8), utc(2026, 8, 11, 16))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_real"], 8.0)
        self.assertAlmostEqual(c["horas_reales"]["ordinaria_diurna"], 8.0)
        self.assertAlmostEqual(c["horas_reales"]["ordinaria_nocturna"], 0.0)

    def test_el_recargo_nocturno_se_calcula_en_hora_local_no_utc(self):
        # 16:00 → 22:00 Colombia. En UTC eso es 21:00 → 03:00: si el cálculo se
        # hiciera sobre el timestamp crudo, TODO caería en franja nocturna.
        # Con la tasa vigente (nocturna desde las 19:00) son 3h diurnas + 3h nocturnas.
        self.real(self.cath, utc(2026, 8, 11, 16), utc(2026, 8, 11, 22))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["horas_reales"]["ordinaria_diurna"], 3.0)
        self.assertAlmostEqual(c["horas_reales"]["ordinaria_nocturna"], 3.0)

    def test_turno_que_cruza_la_medianoche_cuenta_en_el_dia_que_empezo(self):
        # Sábado 15-ago 20:00 → domingo 02:00.
        self.real(self.cath, utc(2026, 8, 15, 20), utc(2026, 8, 16, 2))
        c = self.de_cath(self.resumen())
        dias = {d["fecha"]: d for d in c["dias"]}
        self.assertIn("2026-08-15", dias)
        self.assertAlmostEqual(dias["2026-08-15"]["horas_reales"], 6.0)
        # Las 2h del domingo sí se clasifican como dominicales.
        self.assertAlmostEqual(c["horas_reales"]["dominical_nocturna"], 2.0)

    def test_domingo_va_a_la_categoria_dominical(self):
        self.real(self.cath, utc(2026, 8, 16, 8), utc(2026, 8, 16, 16))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["horas_reales"]["dominical_diurna"], 8.0)

    def test_festivo_va_a_la_categoria_dominical(self):
        # Lunes 17-ago-2026 es festivo (Asunción corrida por Ley Emiliani).
        self.real(self.cath, utc(2026, 8, 17, 8), utc(2026, 8, 17, 16))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["horas_reales"]["dominical_diurna"], 8.0)

    def test_tramo_sin_salida_no_inventa_horas_y_queda_advertido(self):
        turno = CajaTurno(tienda_id=self.t.id, usuario_apertura_id=self.cath.id,
                          base_real=0.0, estado=EstadoTurnoEnum.abierto,
                          fecha_apertura=utc(2026, 8, 11, 8))
        self.db.add(turno)
        self.db.flush()
        self.db.add(TurnoBarista(turno_id=turno.id, usuario_id=self.cath.id,
                                 nombre_snapshot="Catherin",
                                 created_at=utc(2026, 8, 11, 8), salida_at=None))
        self.db.commit()
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_real"], 0.0)
        self.assertEqual(c["tramos_sin_salida"], 1)

    def test_solo_cuenta_los_tramos_del_mes_pedido(self):
        self.real(self.cath, utc(2026, 7, 15, 8), utc(2026, 7, 15, 16))
        self.real(self.cath, utc(2026, 8, 11, 8), utc(2026, 8, 11, 16))
        self.assertAlmostEqual(self.de_cath(self.resumen(2026, 8))["total_real"], 8.0)
        self.assertAlmostEqual(self.de_cath(self.resumen(2026, 7))["total_real"], 8.0)

    def test_las_extras_se_deciden_por_semana_no_por_mes(self):
        # 6 días de 8h en UNA semana (lun 10 → sáb 15) = 48h. Con jornada 42
        # vigente: 42 ordinarias + 6 extras. Si el umbral se aplicara al mes,
        # no habría ninguna extra.
        for d in range(10, 16):
            self.real(self.cath, utc(2026, 8, d, 8), utc(2026, 8, d, 16))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_real"], 48.0)
        self.assertAlmostEqual(c["horas_reales"]["extra_diurna"], 6.0)
        self.assertAlmostEqual(c["horas_reales"]["ordinaria_diurna"], 42.0)

    def test_el_kiosko_no_es_una_persona_y_no_aparece_en_nomina(self):
        self.real(self.kiosk, utc(2026, 8, 11, 8), utc(2026, 8, 11, 16))
        ids = [b["usuario_id"] for b in self.resumen()["baristas"]]
        self.assertNotIn(self.kiosk.id, ids)


class PlaneadoVsRealTest(NominaBase):
    def test_planeado_y_real_se_reportan_los_dos(self):
        self.planear(self.cath, date(2026, 8, 11))
        self.real(self.cath, utc(2026, 8, 11, 8), utc(2026, 8, 11, 16))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_planeado"], 8.0)
        self.assertAlmostEqual(c["total_real"], 8.0)
        self.assertAlmostEqual(c["diferencia_horas"], 0.0)

    def test_dia_planeado_sin_real_y_sin_novedad_queda_sin_marcacion(self):
        self.planear(self.cath, date(2026, 8, 11))
        c = self.de_cath(self.resumen())
        self.assertEqual(c["dias_sin_marcacion"], ["2026-08-11"])
        dia = [d for d in c["dias"] if d["fecha"] == "2026-08-11"][0]
        self.assertEqual(dia["estado"], "sin_marcacion")

    def test_dia_trabajado_sin_planear_se_marca_como_no_programado(self):
        self.real(self.cath, utc(2026, 8, 11, 8), utc(2026, 8, 11, 16))
        c = self.de_cath(self.resumen())
        dia = [d for d in c["dias"] if d["fecha"] == "2026-08-11"][0]
        self.assertEqual(dia["estado"], "no_programado")
        self.assertEqual(c["dias_sin_marcacion"], [])

    def test_el_borrador_no_cuenta_como_planeado(self):
        self.planear(self.cath, date(2026, 8, 11), publicar=False)
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_planeado"], 0.0)

    def test_la_diferencia_es_acreditado_menos_planeado(self):
        self.planear(self.cath, date(2026, 8, 11), "08:00", "16:00")
        self.real(self.cath, utc(2026, 8, 11, 8), utc(2026, 8, 11, 14))  # se fue 2h antes
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["diferencia_horas"], -2.0)


class NovedadesTest(NominaBase):
    def novedad(self, tipo, desde, hasta=None, remunerada=None):
        return nsvc.crear(self.db, self.t.id, self.cath.id, tipo, desde,
                          hasta or desde, creado_por_id=self.admin.id,
                          remunerada=remunerada)

    def test_el_mapa_de_tipos_declara_si_cuenta_como_trabajado_y_por_que(self):
        for clave, meta in nsvc.TIPOS.items():
            self.assertIn("remunerada", meta)
            self.assertIn("acredita_horas", meta)
            self.assertTrue(meta.get("razon", "").strip(), f"{clave} sin razón")

    def test_incapacidad_acredita_las_horas_planeadas(self):
        self.planear(self.cath, date(2026, 8, 11))
        self.novedad("incapacidad", date(2026, 8, 11))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_real"], 0.0)
        self.assertAlmostEqual(c["total_acreditado"], 8.0)
        self.assertEqual(c["dias_sin_marcacion"], [])
        dia = [d for d in c["dias"] if d["fecha"] == "2026-08-11"][0]
        self.assertEqual(dia["estado"], "novedad_remunerada")

    def test_permiso_no_remunerado_justifica_pero_no_acredita(self):
        self.planear(self.cath, date(2026, 8, 11))
        self.novedad("permiso_no_remunerado", date(2026, 8, 11))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_acreditado"], 0.0)
        self.assertEqual(c["dias_sin_marcacion"], [])
        dia = [d for d in c["dias"] if d["fecha"] == "2026-08-11"][0]
        self.assertEqual(dia["estado"], "novedad_no_remunerada")

    def test_vacaciones_de_varios_dias_cubren_todo_el_rango(self):
        for d in (11, 12, 13):
            self.planear(self.cath, date(2026, 8, d))
        self.novedad("vacaciones", date(2026, 8, 11), date(2026, 8, 13))
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_acreditado"], 24.0)
        self.assertEqual(c["dias_sin_marcacion"], [])

    def test_la_novedad_remunerada_se_puede_forzar_a_no_remunerada(self):
        self.planear(self.cath, date(2026, 8, 11))
        self.novedad("incapacidad", date(2026, 8, 11), remunerada=False)
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["total_acreditado"], 0.0)

    def test_las_novedades_del_mes_aparecen_en_el_resumen(self):
        self.novedad("incapacidad", date(2026, 8, 11), date(2026, 8, 12))
        c = self.de_cath(self.resumen())
        self.assertEqual(len(c["novedades"]), 1)
        self.assertEqual(c["novedades"][0]["tipo"], "incapacidad")

    def test_una_novedad_que_pisa_un_turno_publicado_avisa_a_la_barista(self):
        from app.models.models import Notificacion
        self.planear(self.cath, date(2026, 8, 11))
        self.db.query(Notificacion).delete()
        self.db.commit()
        self.novedad("incapacidad", date(2026, 8, 11))
        self.assertTrue(self.db.query(Notificacion).filter(
            Notificacion.tipo == "novedad_laboral").count())

    def test_novedad_fuera_del_horario_publicado_no_manda_aviso(self):
        from app.models.models import Notificacion
        self.novedad("vacaciones", date(2026, 9, 1), date(2026, 9, 5))
        self.assertEqual(self.db.query(Notificacion).filter(
            Notificacion.tipo == "novedad_laboral").count(), 0)

    def test_novedad_con_rango_invertido_se_rechaza(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.novedad("vacaciones", date(2026, 8, 20), date(2026, 8, 10))

    def test_tipo_desconocido_se_rechaza(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.novedad("vacaciones_fiscales", date(2026, 8, 10))


class EstimadoTest(NominaBase):
    def test_el_estimado_usa_el_salario_del_contrato_y_la_tasa_vigente(self):
        self.real(self.cath, utc(2026, 8, 11, 8), utc(2026, 8, 11, 16))
        c = self.de_cath(self.resumen())
        # 1.800.000 / 240 = 7.500 la hora ordinaria · 8h diurnas ordinarias.
        self.assertAlmostEqual(c["estimado"]["valor_hora_ordinaria"], 7500.0)
        self.assertAlmostEqual(c["estimado"]["total"], 60_000.0)

    def test_sin_contrato_cargado_el_estimado_es_cero_pero_las_horas_estan(self):
        eli = Usuario(nombre="Eliana", email="eli@t.local", password_hash="h",
                      rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add(eli)
        self.db.commit()
        self.real(eli, utc(2026, 8, 11, 8), utc(2026, 8, 11, 16))
        b = [x for x in self.resumen()["baristas"] if x["usuario_id"] == eli.id][0]
        self.assertAlmostEqual(b["total_real"], 8.0)
        self.assertAlmostEqual(b["estimado"]["total"], 0.0)
        self.assertFalse(b["tiene_contrato"])

    def test_el_estimado_se_calcula_sobre_lo_ACREDITADO(self):
        self.planear(self.cath, date(2026, 8, 11))
        nsvc.crear(self.db, self.t.id, self.cath.id, "incapacidad",
                   date(2026, 8, 11), date(2026, 8, 11), creado_por_id=self.admin.id)
        c = self.de_cath(self.resumen())
        self.assertAlmostEqual(c["estimado"]["total"], 60_000.0)


class ContratoDelResumenTest(NominaBase):
    def test_el_resumen_declara_su_base_de_liquidacion_y_sus_limites(self):
        r = self.resumen()
        self.assertEqual(r["base_liquidacion"], "real")
        self.assertTrue(r["advertencias"])
        self.assertTrue(any("cierre" in a.lower() for a in r["advertencias"]))

    def test_el_resumen_dice_que_tasa_uso_cada_semana(self):
        r = self.resumen()
        self.assertTrue(r["semanas"])
        for s in r["semanas"]:
            self.assertIn("jornada_max_semanal", s)
            self.assertIn("vigente_desde", s)

    def test_mes_invalido_se_rechaza(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            svc.resumen_mensual(self.db, self.t.id, 2026, 13)


if __name__ == "__main__":
    unittest.main()


class UmbralSemanalTest(NominaBase):
    """Los dos bloqueantes que hacían que una barista cobrara de MENOS.

    Los dos fallaban del mismo modo: el umbral semanal —lo que decide si una hora
    vale 1,0 o 1,25— se calculaba sobre un pedazo de la semana en vez de sobre la
    semana entera de esa persona. Y los 125 tests del módulo pasaban en verde con
    los dos adentro, porque ninguno cruzaba el corte de mes ni usaba dos sedes.

    Horas en UTC: Colombia es UTC-5, así que 08:00 local == 13:00 UTC.
    """

    def _jornada(self, dia, usuario=None, horas=8, tienda=None):
        """Un turno de `horas` que arranca 08:00 hora Colombia."""
        ini = datetime.combine(dia, datetime.min.time()) + timedelta(hours=13)
        self.real(usuario or self.cath, ini, ini + timedelta(hours=horas), tienda=tienda)

    def test_la_semana_partida_por_el_mes_no_pierde_las_extras(self):
        """Lun 27-jul a dom 2-ago 2026: 56 h en UNA semana, jornada 42 h.

        Antes, julio liquidaba 40 h y agosto 16 h, las dos SIN extras: el umbral
        arrancaba de cero en cada mes. Se perdían 14 h extra."""
        for i in range(7):                       # lunes 27-jul → domingo 2-ago
            self._jornada(date(2026, 7, 27) + timedelta(days=i))

        jul = self.de_cath(self.resumen(2026, 7))
        ago = self.de_cath(self.resumen(2026, 8))
        extras_jul = sum(v for k, v in jul["horas_reales"].items() if "extra" in k)
        extras_ago = sum(v for k, v in ago["horas_reales"].items() if "extra" in k)

        # Los días siguen en su mes (5 en julio, 2 en agosto)…
        self.assertAlmostEqual(40.0, jul["total_real"], places=1)
        self.assertAlmostEqual(16.0, ago["total_real"], places=1)
        # …pero las extras existen: la semana se pasó de la jornada y alguien las
        # trabajó. Antes esto daba 0.0 en los dos meses.
        self.assertGreater(extras_jul + extras_ago, 0,
                           "una semana de 56 h con jornada de 42 tiene que generar extras")

    def test_las_horas_de_las_dos_sedes_suman_para_el_umbral(self):
        """La jornada máxima es un tope por TRABAJADOR, no por local.

        4 días en Vida + 2 en la otra sede = 48 h en una semana de 42."""
        otra = Tienda(nombre="Palmetto", direccion="y")
        self.db.add(otra)
        self.db.commit()
        lunes = date(2026, 8, 10)
        for i in range(4):
            self._jornada(lunes + timedelta(days=i))
        for i in (4, 5):
            self._jornada(lunes + timedelta(days=i), tienda=otra)

        r_vida = self.de_cath(self.resumen(2026, 8))
        r_otra = [x for x in svc.resumen_mensual(self.db, otra.id, 2026, 8)["baristas"]
                  if x["usuario_id"] == self.cath.id][0]
        extras = sum(v for k, v in r_vida["horas_reales"].items() if "extra" in k)                + sum(v for k, v in r_otra["horas_reales"].items() if "extra" in k)

        # Cada reporte sigue siendo de SU sede: 32 h en Vida, 16 en la otra.
        self.assertAlmostEqual(32.0, r_vida["total_real"], places=1)
        self.assertAlmostEqual(16.0, r_otra["total_real"], places=1)
        # Pero el umbral vio las 48 de la persona: las 6 h que pasan de 42 existen.
        # Caen en la sede donde se CRUZÓ el umbral (las últimas horas de la
        # semana), que es una atribución defendible; lo que no puede pasar —y
        # pasaba— es que no existan en ninguna de las dos.
        self.assertAlmostEqual(6.0, extras, places=1,
                               msg="48 h con jornada de 42 son 6 h extra, estén "
                                   "repartidas entre las sedes que estén")

    def test_cubrir_en_la_otra_sede_no_es_una_ausencia(self):
        """El día que fue a ayudar no puede aparecer como falta en su sede."""
        otra = Tienda(nombre="Palmetto", direccion="y")
        self.db.add(otra)
        self.db.commit()
        dia = date(2026, 8, 11)
        self.planear(self.cath, dia)             # estaba programada en Vida
        self._jornada(dia, tienda=otra)          # pero marcó en la otra

        b = self.de_cath(self.resumen(2026, 8))
        d = [x for x in b["dias"] if x["fecha"] == dia.isoformat()][0]
        self.assertEqual("cubrio_otra_sede", d["estado"])
        self.assertNotIn(dia.isoformat(), b["dias_sin_marcacion"])

    def test_el_estado_no_acusa_de_faltar(self):
        """El sistema sabe que no hay MARCACIÓN, no que la persona no vino."""
        dia = date(2026, 8, 12)
        self.planear(self.cath, dia)
        b = self.de_cath(self.resumen(2026, 8))
        d = [x for x in b["dias"] if x["fecha"] == dia.isoformat()][0]
        self.assertEqual("sin_marcacion", d["estado"])
        self.assertIn(dia.isoformat(), b["dias_sin_marcacion"])
        self.assertNotIn("ausencias_sin_justificar", b)
