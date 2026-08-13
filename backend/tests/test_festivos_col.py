"""Festivos colombianos CALCULADOS (Ley 51 de 1983 «Emiliani» + Pascua).

No hay lista pegada: el código deriva Pascua con el algoritmo de Butcher y corre
al lunes siguiente los festivos que la ley traslada. Los años de contraste son
2024, 2025 y 2026 — calendarios públicos y verificables.
"""
import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Festivo
from app.services.festivos import (
    domingo_pascua, festivos_col, siguiente_lunes, es_festivo, fechas_festivas,
)


class PascuaTest(unittest.TestCase):
    def test_domingos_de_pascua_conocidos(self):
        self.assertEqual(domingo_pascua(2024), date(2024, 3, 31))
        self.assertEqual(domingo_pascua(2025), date(2025, 4, 20))
        self.assertEqual(domingo_pascua(2026), date(2026, 4, 5))
        self.assertEqual(domingo_pascua(2027), date(2027, 3, 28))
        self.assertEqual(domingo_pascua(2000), date(2000, 4, 23))

    def test_pascua_siempre_cae_domingo(self):
        for anio in range(2020, 2041):
            self.assertEqual(domingo_pascua(anio).weekday(), 6, f"año {anio}")


class EmilianiTest(unittest.TestCase):
    def test_lunes_se_queda_donde_esta(self):
        lunes = date(2026, 10, 12)
        self.assertEqual(lunes.weekday(), 0)
        self.assertEqual(siguiente_lunes(lunes), lunes)

    def test_cualquier_otro_dia_corre_al_lunes(self):
        self.assertEqual(siguiente_lunes(date(2026, 8, 15)), date(2026, 8, 17))  # sábado
        self.assertEqual(siguiente_lunes(date(2025, 11, 1)), date(2025, 11, 3))  # sábado
        self.assertEqual(siguiente_lunes(date(2026, 1, 6)), date(2026, 1, 12))   # martes


class Festivos2026Test(unittest.TestCase):
    """2026 — el año en curso. Lista completa para contrastar contra el calendario."""

    ESPERADOS = [
        date(2026, 1, 1),    # Año Nuevo
        date(2026, 1, 12),   # Reyes (6-ene martes → lunes)
        date(2026, 3, 23),   # San José (19-mar jueves → lunes)
        date(2026, 4, 2),    # Jueves Santo
        date(2026, 4, 3),    # Viernes Santo
        date(2026, 5, 1),    # Día del Trabajo
        date(2026, 5, 18),   # Ascensión (Pascua +43)
        date(2026, 6, 8),    # Corpus Christi (Pascua +64)
        date(2026, 6, 15),   # Sagrado Corazón (Pascua +71)
        date(2026, 6, 29),   # San Pedro y San Pablo (ya es lunes)
        date(2026, 7, 20),   # Independencia
        date(2026, 8, 7),    # Batalla de Boyacá
        date(2026, 8, 17),   # Asunción (15-ago sábado → lunes)
        date(2026, 10, 12),  # Día de la Raza (ya es lunes)
        date(2026, 11, 2),   # Todos los Santos (1-nov domingo → lunes)
        date(2026, 11, 16),  # Independencia de Cartagena (11-nov miércoles → lunes)
        date(2026, 12, 8),   # Inmaculada Concepción
        date(2026, 12, 25),  # Navidad
    ]

    def test_lista_exacta(self):
        self.assertEqual(sorted(festivos_col(2026).keys()), self.ESPERADOS)

    def test_son_dieciocho(self):
        self.assertEqual(len(self.ESPERADOS), 18)

    def test_los_fijos_no_se_mueven_aunque_caigan_fin_de_semana(self):
        # 2026-07-20 es lunes, pero 2027-07-20 es martes y NO se corre.
        self.assertIn(date(2027, 7, 20), festivos_col(2027))
        self.assertIn(date(2026, 12, 25), festivos_col(2026))


class Festivos2024y2025Test(unittest.TestCase):
    def test_2024_completo(self):
        esperados = [
            date(2024, 1, 1), date(2024, 1, 8), date(2024, 3, 25),
            date(2024, 3, 28), date(2024, 3, 29), date(2024, 5, 1),
            date(2024, 5, 13), date(2024, 6, 3), date(2024, 6, 10),
            date(2024, 7, 1), date(2024, 7, 20), date(2024, 8, 7),
            date(2024, 8, 19), date(2024, 10, 14), date(2024, 11, 4),
            date(2024, 11, 11), date(2024, 12, 8), date(2024, 12, 25),
        ]
        self.assertEqual(sorted(festivos_col(2024).keys()), esperados)

    def test_2025_tiene_17_fechas_porque_dos_festivos_colisionan(self):
        # Caso real: en 2025 el Sagrado Corazón (Pascua+71 = 30-jun) y San Pedro
        # y Pablo (29-jun domingo → lunes 30-jun) caen el MISMO día. Son dos
        # festivos, una sola fecha: el calendario tiene 17 días, no 18.
        f = festivos_col(2025)
        self.assertEqual(len(f), 17)
        self.assertIn(date(2025, 6, 30), f)
        nombre = f[date(2025, 6, 30)]
        self.assertIn("Sagrado Corazón", nombre)
        self.assertIn("San Pedro", nombre)

    def test_2025_fechas_clave(self):
        f = festivos_col(2025)
        self.assertIn(date(2025, 1, 6), f)    # Reyes: ya era lunes
        self.assertIn(date(2025, 4, 17), f)   # Jueves Santo
        self.assertIn(date(2025, 4, 18), f)   # Viernes Santo
        self.assertIn(date(2025, 7, 20), f)   # domingo, fijo, no se corre
        self.assertIn(date(2025, 12, 8), f)


class OverridesEnDBTest(unittest.TestCase):
    """La base la calcula el código; la tabla `festivos` solo AGREGA o QUITA."""

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

    def test_sin_overrides_manda_el_calculo(self):
        self.assertTrue(es_festivo(self.db, date(2026, 8, 17)))
        self.assertFalse(es_festivo(self.db, date(2026, 8, 18)))

    def test_agregar_un_dia_civico_local(self):
        self.db.add(Festivo(fecha=date(2026, 9, 3), nombre="Feria de Cali (cívico)",
                            es_festivo=True))
        self.db.commit()
        self.assertTrue(es_festivo(self.db, date(2026, 9, 3)))

    def test_quitar_un_festivo_calculado(self):
        self.db.add(Festivo(fecha=date(2026, 8, 17), nombre="Asunción",
                            es_festivo=False, nota="acá se trabaja normal"))
        self.db.commit()
        self.assertFalse(es_festivo(self.db, date(2026, 8, 17)))

    def test_fechas_festivas_de_un_rango_aplica_overrides(self):
        self.db.add(Festivo(fecha=date(2026, 8, 18), nombre="Cívico", es_festivo=True))
        self.db.add(Festivo(fecha=date(2026, 8, 7), nombre="Boyacá", es_festivo=False))
        self.db.commit()
        fechas = fechas_festivas(self.db, date(2026, 8, 1), date(2026, 8, 31))
        self.assertIn(date(2026, 8, 17), fechas)
        self.assertIn(date(2026, 8, 18), fechas)
        self.assertNotIn(date(2026, 8, 7), fechas)

    def test_rango_multianio(self):
        fechas = fechas_festivas(self.db, date(2026, 12, 20), date(2027, 1, 10))
        self.assertIn(date(2026, 12, 25), fechas)
        self.assertIn(date(2027, 1, 1), fechas)


if __name__ == "__main__":
    unittest.main()
