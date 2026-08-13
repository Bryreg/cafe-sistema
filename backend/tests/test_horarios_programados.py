"""Horario PLANEADO: armar la semana, ver el total contra la jornada vigente,
publicarlo y avisar a cada barista."""
import os
import tempfile
import unittest
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    Tienda, Usuario, RolEnum, TurnoProgramado, EstadoProgramadoEnum, Notificacion,
)
from app.services import horarios as svc


class HorariosBase(unittest.TestCase):
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
        self.eli = Usuario(nombre="Eliana", email="eli@t.local", password_hash="h",
                           rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add_all([self.admin, self.cath, self.eli])
        self.db.commit()
        # Lunes 2026-08-10 → domingo 2026-08-16
        self.lunes = date(2026, 8, 10)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def prog(self, usuario, dia_offset, ini="08:00", fin="16:00"):
        from datetime import timedelta
        return svc.guardar_turno(self.db, self.t.id, usuario.id,
                                 self.lunes + timedelta(days=dia_offset), ini, fin,
                                 creado_por_id=self.admin.id)


class ArmadoTest(HorariosBase):
    def test_guardar_crea_en_borrador(self):
        tp = self.prog(self.cath, 0)
        self.assertEqual(tp.estado, EstadoProgramadoEnum.borrador)
        self.assertEqual(tp.nombre_snapshot, "Catherin")
        self.assertIsNone(tp.publicado_at)

    def test_horas_invalidas_se_rechazan(self):
        for ini, fin in [("25:00", "16:00"), ("08:00", "8:0"), ("ocho", "16:00"), ("08:00", "")]:
            with self.subTest(ini=ini, fin=fin):
                with self.assertRaises(HTTPException):
                    svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                                      ini, fin, creado_por_id=self.admin.id)

    def test_turno_de_cero_horas_se_rechaza(self):
        with self.assertRaises(HTTPException):
            svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                              "08:00", "08:00", creado_por_id=self.admin.id)

    def test_cruce_de_medianoche_es_valido_y_dura_lo_correcto(self):
        tp = self.prog(self.cath, 0, "18:00", "02:00")
        self.assertAlmostEqual(svc.duracion_horas(tp.hora_inicio, tp.hora_fin), 8.0)

    def test_semana_devuelve_la_grilla_por_barista(self):
        self.prog(self.cath, 0)
        self.prog(self.cath, 1)
        self.prog(self.eli, 0, "14:00", "22:00")
        data = svc.semana(self.db, self.t.id, self.lunes)
        self.assertEqual(data["lunes"], self.lunes.isoformat())
        self.assertEqual(len(data["dias"]), 7)
        por_barista = {b["usuario_id"]: b for b in data["baristas"]}
        self.assertAlmostEqual(por_barista[self.cath.id]["total_horas"], 16.0)
        self.assertAlmostEqual(por_barista[self.eli.id]["total_horas"], 8.0)

    def test_la_semana_trae_la_jornada_maxima_vigente_de_esa_semana(self):
        data = svc.semana(self.db, self.t.id, self.lunes)
        # 2026-08-10 → la vigencia sembrada del 16-jul-2026 (42 h/semana).
        self.assertAlmostEqual(data["jornada_max_semanal"], 42.0)
        self.assertIn("tasa", data)

    def test_marca_a_quien_se_pasa_de_la_jornada(self):
        for d in range(6):
            self.prog(self.cath, d)  # 6 × 8h = 48h > 42
        data = svc.semana(self.db, self.t.id, self.lunes)
        cath = [b for b in data["baristas"] if b["usuario_id"] == self.cath.id][0]
        self.assertTrue(cath["excede_jornada"])
        self.assertAlmostEqual(cath["horas_sobre_jornada"], 6.0)

    def test_no_marca_a_quien_esta_dentro(self):
        for d in range(5):
            self.prog(self.cath, d)  # 40h
        data = svc.semana(self.db, self.t.id, self.lunes)
        cath = [b for b in data["baristas"] if b["usuario_id"] == self.cath.id][0]
        self.assertFalse(cath["excede_jornada"])

    def test_editar_el_mismo_dia_y_hora_actualiza_en_vez_de_duplicar(self):
        tp = self.prog(self.cath, 0, "08:00", "16:00")
        tp2 = svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                                "08:00", "17:00", creado_por_id=self.admin.id)
        self.assertEqual(tp.id, tp2.id)
        self.assertEqual(
            self.db.query(TurnoProgramado).filter(TurnoProgramado.fecha == self.lunes).count(), 1)

    def test_borrar_quita_el_turno(self):
        tp = self.prog(self.cath, 0)
        svc.borrar_turno(self.db, tp.id)
        self.assertIsNone(self.db.query(TurnoProgramado).filter(TurnoProgramado.id == tp.id).first())


class PublicacionTest(HorariosBase):
    def test_publicar_marca_estado_y_fecha(self):
        self.prog(self.cath, 0)
        self.prog(self.eli, 1)
        out = svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        self.assertEqual(out["publicados"], 2)
        for tp in self.db.query(TurnoProgramado).all():
            self.assertEqual(tp.estado, EstadoProgramadoEnum.publicado)
            self.assertIsNotNone(tp.publicado_at)

    def test_publicar_avisa_por_el_canal_existente(self):
        self.prog(self.cath, 0)
        svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        notifs = self.db.query(Notificacion).filter(
            Notificacion.tipo == "horario_publicado").all()
        self.assertTrue(notifs)
        self.assertIn("Catherin", notifs[0].mensaje)

    def test_publicar_una_semana_vacia_no_avisa_a_nadie(self):
        out = svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        self.assertEqual(out["publicados"], 0)
        self.assertEqual(self.db.query(Notificacion).count(), 0)

    def test_republicar_no_reenvia_a_quien_no_cambio(self):
        self.prog(self.cath, 0)
        svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        n1 = self.db.query(Notificacion).count()
        svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        self.assertEqual(self.db.query(Notificacion).count(), n1)

    def test_cambiar_un_turno_ya_publicado_avisa_del_cambio(self):
        self.prog(self.cath, 0, "08:00", "16:00")
        svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        self.db.query(Notificacion).delete()
        self.db.commit()
        svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                          "08:00", "20:00", creado_por_id=self.admin.id)
        notifs = self.db.query(Notificacion).filter(
            Notificacion.tipo == "horario_cambiado").all()
        self.assertTrue(notifs)
        self.assertIn("20:00", notifs[0].mensaje)

    def test_cambiar_un_borrador_no_molesta_a_nadie(self):
        self.prog(self.cath, 0, "08:00", "16:00")
        svc.guardar_turno(self.db, self.t.id, self.cath.id, self.lunes,
                          "08:00", "20:00", creado_por_id=self.admin.id)
        self.assertEqual(self.db.query(Notificacion).count(), 0)

    def test_borrar_un_turno_publicado_avisa(self):
        tp = self.prog(self.cath, 0)
        svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        self.db.query(Notificacion).delete()
        self.db.commit()
        svc.borrar_turno(self.db, tp.id)
        self.assertTrue(self.db.query(Notificacion).filter(
            Notificacion.tipo == "horario_cambiado").count())


class MiHorarioTest(HorariosBase):
    def test_la_barista_solo_ve_lo_publicado(self):
        self.prog(self.cath, 0)
        self.assertEqual(svc.mi_horario(self.db, self.cath.id, self.lunes,
                                        self.lunes.replace(day=16)), [])
        svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        turnos = svc.mi_horario(self.db, self.cath.id, self.lunes, date(2026, 8, 16))
        self.assertEqual(len(turnos), 1)
        self.assertEqual(turnos[0]["hora_inicio"], "08:00")

    def test_no_ve_el_horario_de_otra(self):
        self.prog(self.eli, 0)
        svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        self.assertEqual(svc.mi_horario(self.db, self.cath.id, self.lunes, date(2026, 8, 16)), [])


class CopiarSemanaTest(HorariosBase):
    def test_copiar_la_semana_anterior_trae_los_turnos_como_borrador(self):
        self.prog(self.cath, 0)
        self.prog(self.eli, 2, "14:00", "22:00")
        svc.publicar_semana(self.db, self.t.id, self.lunes, self.admin.id)
        siguiente = date(2026, 8, 17)
        creados = svc.copiar_semana(self.db, self.t.id, self.lunes, siguiente, self.admin.id)
        self.assertEqual(creados, 2)
        nuevos = self.db.query(TurnoProgramado).filter(
            TurnoProgramado.fecha >= siguiente).all()
        self.assertEqual(len(nuevos), 2)
        for tp in nuevos:
            self.assertEqual(tp.estado, EstadoProgramadoEnum.borrador)

    def test_copiar_no_pisa_lo_que_ya_hay_en_la_semana_destino(self):
        self.prog(self.cath, 0, "08:00", "16:00")
        siguiente = date(2026, 8, 17)
        svc.guardar_turno(self.db, self.t.id, self.cath.id, siguiente, "08:00", "12:00",
                          creado_por_id=self.admin.id)
        svc.copiar_semana(self.db, self.t.id, self.lunes, siguiente, self.admin.id)
        destino = self.db.query(TurnoProgramado).filter(
            TurnoProgramado.fecha == siguiente).all()
        self.assertEqual(len(destino), 1)
        self.assertEqual(destino[0].hora_fin, "12:00")


if __name__ == "__main__":
    unittest.main()
