"""Almuerzo del turno: descanso NO remunerado dentro del horario.

Lo que estas pruebas fijan, y por qué:

1. El descanso se saca de la FRANJA en la que cae. Un almuerzo a las 21:00 no
   descuenta lo mismo que uno a las 13:00, porque la hora nocturna vale más. Por
   eso el almuerzo se guarda con hora y no como un total de minutos.
2. Un turno SIN almuerzo liquida exactamente igual que antes de que la columna
   existiera. Todos los turnos ya cargados están así.
3. El almuerzo se descuenta también de lo REAL, usando la ventana planeada: la
   caja no marca la salida a almorzar, así que sin esto el resumen mostraría una
   hora extra todos los días.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    CajaTurno, ContratoBarista, EstadoTurnoEnum, RolEnum, Tienda, TurnoBarista,
    Usuario,
)
from app.services import horarios as svc
from app.services import nomina as nsvc
from app.services.horas import Tasa, descomponer, restar_pausas

COL = timedelta(hours=5)   # Colombia UTC-5: hora local + 5 = UTC


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi) + COL


def dt(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi)


TASA = Tasa(
    jornada_max_semanal=42.0, hora_inicio_nocturna=19, hora_fin_nocturna=6,
    recargo_nocturno=0.35, recargo_dominical=0.90,
    extra_diurna=0.25, extra_nocturna=0.75, divisor_hora_mensual=240.0,
)


# ─── Álgebra de intervalos (pura, sin base de datos) ────────────────────────

class RestarPausasTest(unittest.TestCase):
    def test_pausa_en_el_medio_parte_el_tramo_en_dos(self):
        r = restar_pausas(dt(2026, 8, 11, 7), dt(2026, 8, 11, 15),
                          [(dt(2026, 8, 11, 13), dt(2026, 8, 11, 14))])
        self.assertEqual(r, [(dt(2026, 8, 11, 7), dt(2026, 8, 11, 13)),
                             (dt(2026, 8, 11, 14), dt(2026, 8, 11, 15))])

    def test_pausa_que_no_toca_el_tramo_no_descuenta_nada(self):
        """Si la barista marcó salida y volvió a marcar entrada (dos tramos), el
        almuerzo cae en el hueco: no se puede descontar dos veces."""
        r = restar_pausas(dt(2026, 8, 11, 7), dt(2026, 8, 11, 13),
                          [(dt(2026, 8, 11, 13), dt(2026, 8, 11, 14))])
        self.assertEqual(r, [(dt(2026, 8, 11, 7), dt(2026, 8, 11, 13))])

    def test_pausa_que_se_sale_por_un_borde_descuenta_solo_lo_que_pisa(self):
        r = restar_pausas(dt(2026, 8, 11, 13, 30), dt(2026, 8, 11, 18),
                          [(dt(2026, 8, 11, 13), dt(2026, 8, 11, 14))])
        self.assertEqual(r, [(dt(2026, 8, 11, 14), dt(2026, 8, 11, 18))])

    def test_pausa_que_cubre_todo_deja_cero_horas(self):
        r = restar_pausas(dt(2026, 8, 11, 13), dt(2026, 8, 11, 14),
                          [(dt(2026, 8, 11, 12), dt(2026, 8, 11, 15))])
        self.assertEqual(r, [])

    def test_sin_pausas_devuelve_el_tramo_intacto(self):
        r = restar_pausas(dt(2026, 8, 11, 7), dt(2026, 8, 11, 15), [])
        self.assertEqual(r, [(dt(2026, 8, 11, 7), dt(2026, 8, 11, 15))])


# ─── Duración y tramos del turno planeado ──────────────────────────────────

class DuracionTest(unittest.TestCase):
    def test_sin_almuerzo_la_duracion_no_cambia(self):
        self.assertAlmostEqual(svc.duracion_horas("08:00", "16:00"), 8.0)
        self.assertAlmostEqual(svc.duracion_horas("08:00", "16:00", None), 8.0)
        self.assertAlmostEqual(svc.duracion_horas("08:00", "16:00", 0), 8.0)

    def test_el_almuerzo_se_resta_de_las_horas_trabajadas(self):
        self.assertAlmostEqual(svc.duracion_horas("07:00", "15:00", 60), 7.0)
        self.assertAlmostEqual(svc.duracion_horas("07:00", "15:00", 30), 7.5)

    def test_la_presencia_sigue_siendo_la_bruta(self):
        self.assertAlmostEqual(svc.duracion_bruta_horas("07:00", "15:00"), 8.0)

    def test_turno_sin_almuerzo_es_un_solo_tramo(self):
        tramos = svc.tramos_datetimes(date(2026, 8, 11), "08:00", "16:00")
        self.assertEqual(tramos, [(dt(2026, 8, 11, 8), dt(2026, 8, 11, 16))])

    def test_turno_con_almuerzo_son_dos_tramos(self):
        tramos = svc.tramos_datetimes(date(2026, 8, 11), "07:00", "15:00", "13:00", 60)
        self.assertEqual(tramos, [(dt(2026, 8, 11, 7), dt(2026, 8, 11, 13)),
                                  (dt(2026, 8, 11, 14), dt(2026, 8, 11, 15))])

    def test_en_turno_que_cruza_medianoche_el_almuerzo_es_del_dia_siguiente(self):
        """18:00→02:00 con almuerzo a las 00:30: las 00:30 son DESPUÉS de entrar,
        no dieciocho horas antes."""
        tramos = svc.tramos_datetimes(date(2026, 8, 11), "18:00", "02:00", "00:30", 30)
        self.assertEqual(tramos, [(dt(2026, 8, 11, 18), dt(2026, 8, 12, 0, 30)),
                                  (dt(2026, 8, 12, 1), dt(2026, 8, 12, 2))])


class FranjaDelAlmuerzoTest(unittest.TestCase):
    """El punto de guardar la HORA y no solo los minutos."""

    def test_almuerzo_diurno_descuenta_horas_diurnas(self):
        horas = self._horas("12:00", "22:00", "13:00", 60)
        # 12:00→22:00 = 7 h diurnas (hasta las 19) + 3 nocturnas. El almuerzo de
        # las 13:00 sale de las diurnas.
        self.assertAlmostEqual(horas["ordinaria_diurna"], 6.0)
        self.assertAlmostEqual(horas["ordinaria_nocturna"], 3.0)

    def test_almuerzo_nocturno_descuenta_horas_nocturnas(self):
        horas = self._horas("12:00", "22:00", "20:00", 60)
        self.assertAlmostEqual(horas["ordinaria_diurna"], 7.0)
        self.assertAlmostEqual(horas["ordinaria_nocturna"], 2.0)

    def _horas(self, ini, fin, alm_ini, alm_min):
        total = {}
        for a, b in svc.tramos_datetimes(date(2026, 8, 11), ini, fin, alm_ini, alm_min):
            for cat, h in descomponer(a, b, TASA).items():
                total[cat] = total.get(cat, 0.0) + h
        return total


# ─── Validación ────────────────────────────────────────────────────────────

class ValidacionTest(unittest.TestCase):
    def test_sin_almuerzo_normaliza_a_none(self):
        self.assertEqual(svc.validar_almuerzo("08:00", "16:00", None, None), (None, None))
        self.assertEqual(svc.validar_almuerzo("08:00", "16:00", "", 0), (None, None))

    def test_hora_sin_minutos_se_rechaza(self):
        with self.assertRaises(HTTPException):
            svc.validar_almuerzo("08:00", "16:00", "13:00", None)

    def test_minutos_sin_hora_se_rechazan(self):
        """Sin la hora no se sabe de qué franja sacar el descanso."""
        with self.assertRaises(HTTPException):
            svc.validar_almuerzo("08:00", "16:00", None, 60)

    def test_hora_invalida_se_rechaza(self):
        with self.assertRaises(HTTPException):
            svc.validar_almuerzo("08:00", "16:00", "25:00", 60)

    def test_almuerzo_fuera_del_turno_se_rechaza(self):
        with self.assertRaises(HTTPException):
            svc.validar_almuerzo("08:00", "16:00", "18:00", 60)

    def test_almuerzo_que_se_pasa_de_la_salida_se_rechaza(self):
        with self.assertRaises(HTTPException):
            svc.validar_almuerzo("08:00", "16:00", "15:30", 60)

    def test_almuerzo_pegado_a_la_entrada_se_rechaza(self):
        """Eso no es un descanso: es entrar más tarde, y conviene escribirlo así."""
        with self.assertRaises(HTTPException):
            svc.validar_almuerzo("08:00", "16:00", "08:00", 60)

    def test_almuerzo_valido_en_turno_que_cruza_medianoche(self):
        self.assertEqual(svc.validar_almuerzo("18:00", "02:00", "00:30", 30),
                         ("00:30", 30))


# ─── Grilla semanal y persistencia ─────────────────────────────────────────

class SemanaBase(unittest.TestCase):
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
        self.db.add_all([self.admin, self.cath])
        self.db.flush()
        self.db.add(ContratoBarista(usuario_id=self.cath.id, salario_mensual=1_800_000))
        self.db.commit()
        self.lunes = date(2026, 8, 10)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)


class GrillaTest(SemanaBase):
    def test_el_total_de_la_semana_descuenta_el_almuerzo(self):
        for i in range(5):
            svc.guardar_turno(self.db, self.t.id, self.cath.id,
                              self.lunes + timedelta(days=i), "07:00", "15:00",
                              creado_por_id=self.admin.id,
                              almuerzo_inicio="13:00", almuerzo_minutos=60)
        s = svc.semana(self.db, self.t.id, self.lunes)
        fila = [b for b in s["baristas"] if b["usuario_id"] == self.cath.id][0]
        self.assertAlmostEqual(fila["total_horas"], 35.0)   # 5 × 7, no 5 × 8
        self.assertEqual(fila["minutos_almuerzo"], 300)
        self.assertFalse(fila["excede_jornada"])

    def test_el_turno_serializado_lleva_las_dos_duraciones(self):
        svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                          "07:00", "15:00", creado_por_id=self.admin.id,
                          almuerzo_inicio="13:00", almuerzo_minutos=60)
        s = svc.semana(self.db, self.t.id, self.lunes)
        t = s["baristas"][0]["turnos"][0]
        self.assertAlmostEqual(t["horas"], 7.0)
        self.assertAlmostEqual(t["horas_brutas"], 8.0)
        self.assertEqual(t["almuerzo_inicio"], "13:00")
        self.assertEqual(t["almuerzo_minutos"], 60)
        self.assertEqual(t["almuerzo_fin"], "14:00")

    def test_turno_sin_almuerzo_serializa_en_none(self):
        svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                          "08:00", "16:00", creado_por_id=self.admin.id)
        t = svc.semana(self.db, self.t.id, self.lunes)["baristas"][0]["turnos"][0]
        self.assertIsNone(t["almuerzo_inicio"])
        self.assertIsNone(t["almuerzo_minutos"])
        self.assertIsNone(t["almuerzo_fin"])
        self.assertAlmostEqual(t["horas"], t["horas_brutas"])

    def test_volver_a_guardar_edita_el_almuerzo(self):
        svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                          "07:00", "15:00", creado_por_id=self.admin.id,
                          almuerzo_inicio="13:00", almuerzo_minutos=60)
        tp = svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                               "07:00", "15:00", creado_por_id=self.admin.id,
                               almuerzo_inicio="12:00", almuerzo_minutos=30)
        self.assertEqual(tp.almuerzo_inicio, "12:00")
        self.assertEqual(tp.almuerzo_minutos, 30)

    def test_guardar_sin_almuerzo_lo_saca(self):
        svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                          "07:00", "15:00", creado_por_id=self.admin.id,
                          almuerzo_inicio="13:00", almuerzo_minutos=60)
        tp = svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                               "07:00", "15:00", creado_por_id=self.admin.id)
        self.assertIsNone(tp.almuerzo_inicio)
        self.assertIsNone(tp.almuerzo_minutos)

    def test_copiar_la_semana_se_lleva_el_almuerzo(self):
        svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                          "07:00", "15:00", creado_por_id=self.admin.id,
                          almuerzo_inicio="13:00", almuerzo_minutos=60)
        svc.copiar_semana(self.db, self.t.id, self.lunes,
                          self.lunes + timedelta(days=7), self.admin.id)
        s = svc.semana(self.db, self.t.id, self.lunes + timedelta(days=7))
        copia = s["baristas"][0]["turnos"][0]
        self.assertEqual(copia["almuerzo_inicio"], "13:00")
        self.assertEqual(copia["almuerzo_minutos"], 60)


# ─── Resumen mensual: lo real también descuenta el almuerzo ────────────────

class ResumenConAlmuerzoTest(SemanaBase):
    def real(self, entrada_utc, salida_utc):
        turno = CajaTurno(tienda_id=self.t.id, usuario_apertura_id=self.cath.id,
                          base_real=0.0, estado=EstadoTurnoEnum.cerrado,
                          fecha_apertura=entrada_utc, fecha_cierre=salida_utc)
        self.db.add(turno)
        self.db.flush()
        self.db.add(TurnoBarista(turno_id=turno.id, usuario_id=self.cath.id,
                                 nombre_snapshot=self.cath.nombre,
                                 created_at=entrada_utc, salida_at=salida_utc))
        self.db.commit()

    def planear(self, fecha, ini, fin, alm_ini=None, alm_min=None):
        svc.guardar_turno(self.db, self.t.id, self.cath.id, fecha, ini, fin,
                          creado_por_id=self.admin.id,
                          almuerzo_inicio=alm_ini, almuerzo_minutos=alm_min)
        svc.publicar_semana(self.db, self.t.id, svc.lunes_de(fecha), self.admin.id)

    def resumen_cath(self):
        r = nsvc.resumen_mensual(self.db, self.t.id, 2026, 8)
        return [b for b in r["baristas"] if b["usuario_id"] == self.cath.id][0]

    def test_planeado_y_real_descuentan_el_mismo_almuerzo(self):
        """El caso que motivó todo: sin descontar el almuerzo de lo real, el
        resumen mostraba una hora extra fantasma todos los días."""
        martes = date(2026, 8, 11)
        self.planear(martes, "07:00", "15:00", "13:00", 60)
        self.real(utc(2026, 8, 11, 7), utc(2026, 8, 11, 15))
        c = self.resumen_cath()
        self.assertAlmostEqual(c["total_planeado"], 7.0)
        self.assertAlmostEqual(c["total_real"], 7.0)
        self.assertAlmostEqual(c["diferencia_horas"], 0.0)

    def test_el_almuerzo_sale_de_la_franja_correcta_en_lo_real(self):
        martes = date(2026, 8, 11)
        self.planear(martes, "12:00", "22:00", "20:00", 60)
        self.real(utc(2026, 8, 11, 12), utc(2026, 8, 11, 22))
        c = self.resumen_cath()
        self.assertAlmostEqual(c["horas_reales"]["ordinaria_diurna"], 7.0)
        self.assertAlmostEqual(c["horas_reales"]["ordinaria_nocturna"], 2.0)

    def test_turno_sin_almuerzo_liquida_igual_que_siempre(self):
        """La regresión que importa: nada cambia para los turnos ya cargados."""
        martes = date(2026, 8, 11)
        self.planear(martes, "08:00", "16:00")
        self.real(utc(2026, 8, 11, 8), utc(2026, 8, 11, 16))
        c = self.resumen_cath()
        self.assertAlmostEqual(c["total_planeado"], 8.0)
        self.assertAlmostEqual(c["total_real"], 8.0)
        self.assertAlmostEqual(c["horas_reales"]["ordinaria_diurna"], 8.0)

    def test_si_marco_salida_y_volvio_no_se_descuenta_dos_veces(self):
        martes = date(2026, 8, 11)
        self.planear(martes, "07:00", "15:00", "13:00", 60)
        self.real(utc(2026, 8, 11, 7), utc(2026, 8, 11, 13))
        self.real(utc(2026, 8, 11, 14), utc(2026, 8, 11, 15))
        c = self.resumen_cath()
        self.assertAlmostEqual(c["total_real"], 7.0)

    def test_el_almuerzo_no_consume_cupo_de_jornada(self):
        """6 días × 8 h de presencia con 1 h de almuerzo = 42 h trabajadas: justo
        la jornada máxima, cero horas extra. Con el almuerzo adentro serían 48 y
        aparecerían 6 h extra que nadie trabajó."""
        for i in range(6):   # lunes a sábado
            self.planear(self.lunes + timedelta(days=i), "07:00", "15:00", "13:00", 60)
            self.real(utc(2026, 8, 10 + i, 7), utc(2026, 8, 10 + i, 15))
        c = self.resumen_cath()
        self.assertAlmostEqual(c["total_real"], 42.0)
        self.assertAlmostEqual(c["horas_reales"]["extra_diurna"], 0.0)


if __name__ == "__main__":
    unittest.main()
