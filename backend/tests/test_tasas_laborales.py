"""Tasas de ley con VIGENCIA: nunca constantes en el código.

Un turno se liquida SIEMPRE con la tasa de SU fecha, aunque hoy rija otra. Eso
hace que recalcular un mes viejo dé un resultado estable, y que un cambio de ley
sea una fila nueva y no un deploy.
"""
import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import TasaLaboral
from app.services.tasas_laborales import (
    SIEMBRA, sembrar_tasas, tasa_vigente, tasa_para, listar,
)


class SiembraTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_siembra_es_idempotente(self):
        sembrar_tasas(self.db)
        n1 = self.db.query(TasaLaboral).count()
        sembrar_tasas(self.db)
        self.assertEqual(self.db.query(TasaLaboral).count(), n1)
        self.assertEqual(n1, len(SIEMBRA))

    def test_la_siembra_no_pisa_lo_que_edito_el_contador(self):
        sembrar_tasas(self.db)
        fila = self.db.query(TasaLaboral).order_by(TasaLaboral.vigente_desde.desc()).first()
        fila.recargo_dominical = 0.99
        self.db.commit()
        sembrar_tasas(self.db)
        self.db.refresh(fila)
        self.assertAlmostEqual(fila.recargo_dominical, 0.99)

    def test_toda_fila_sembrada_declara_de_donde_sale(self):
        sembrar_tasas(self.db)
        for t in self.db.query(TasaLaboral).all():
            self.assertTrue((t.nota or "").strip(), f"tasa {t.vigente_desde} sin nota")

    def test_hay_filas_marcadas_para_confirmar_con_el_contador(self):
        sembrar_tasas(self.db)
        pendientes = [t for t in self.db.query(TasaLaboral).all() if t.confirmar_contador]
        self.assertTrue(pendientes, "ninguna tasa quedó marcada como 'confirmar'")

    def test_vigencias_unicas_y_ordenadas(self):
        sembrar_tasas(self.db)
        fechas = [t.vigente_desde for t in listar(self.db)]
        self.assertEqual(fechas, sorted(fechas))
        self.assertEqual(len(fechas), len(set(fechas)))


class VigenciaTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([
            TasaLaboral(vigente_desde=date(2020, 1, 1), jornada_max_semanal=48,
                        hora_inicio_nocturna=21, hora_fin_nocturna=6,
                        recargo_nocturno=0.35, recargo_dominical=0.75,
                        extra_diurna=0.25, extra_nocturna=0.75,
                        divisor_hora_mensual=240, nota="base"),
            TasaLaboral(vigente_desde=date(2025, 1, 1), jornada_max_semanal=44,
                        hora_inicio_nocturna=19, hora_fin_nocturna=6,
                        recargo_nocturno=0.35, recargo_dominical=0.80,
                        extra_diurna=0.25, extra_nocturna=0.75,
                        divisor_hora_mensual=240, nota="cambio"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_resuelve_por_la_fecha_del_turno_no_por_hoy(self):
        vieja = tasa_vigente(self.db, date(2024, 6, 15))
        self.assertAlmostEqual(vieja.jornada_max_semanal, 48)
        self.assertAlmostEqual(vieja.recargo_dominical, 0.75)
        self.assertEqual(vieja.hora_inicio_nocturna, 21)

    def test_el_dia_exacto_de_vigencia_ya_usa_la_nueva(self):
        t = tasa_vigente(self.db, date(2025, 1, 1))
        self.assertAlmostEqual(t.jornada_max_semanal, 44)

    def test_el_dia_anterior_todavia_usa_la_vieja(self):
        t = tasa_vigente(self.db, date(2024, 12, 31))
        self.assertAlmostEqual(t.jornada_max_semanal, 48)

    def test_fecha_anterior_a_toda_vigencia_cae_en_la_mas_antigua(self):
        # Preferible a reventar: se usa la más vieja y la pantalla lo advierte.
        t = tasa_vigente(self.db, date(2015, 5, 5))
        self.assertAlmostEqual(t.jornada_max_semanal, 48)

    def test_sin_ninguna_fila_siembra_y_responde(self):
        self.db.query(TasaLaboral).delete()
        self.db.commit()
        t = tasa_vigente(self.db, date(2026, 8, 13))
        self.assertIsNotNone(t)
        self.assertGreater(t.jornada_max_semanal, 0)

    def test_devuelve_la_Tasa_pura_lista_para_el_calculo(self):
        from app.services.horas import Tasa, descomponer
        t = tasa_para(self.db, date(2024, 6, 15))
        self.assertIsInstance(t, Tasa)
        # Con la tasa de 2024 la franja nocturna arranca a las 21:00.
        from datetime import datetime
        h = descomponer(datetime(2024, 6, 12, 19), datetime(2024, 6, 12, 22), t)
        self.assertAlmostEqual(h["ordinaria_diurna"], 2.0)
        self.assertAlmostEqual(h["ordinaria_nocturna"], 1.0)

    def test_la_tasa_de_2025_corre_la_franja_nocturna_a_las_19(self):
        from app.services.horas import descomponer
        from datetime import datetime
        t = tasa_para(self.db, date(2025, 6, 12))
        h = descomponer(datetime(2025, 6, 12, 19), datetime(2025, 6, 12, 22), t)
        self.assertAlmostEqual(h["ordinaria_diurna"], 0.0)
        self.assertAlmostEqual(h["ordinaria_nocturna"], 3.0)


if __name__ == "__main__":
    unittest.main()
