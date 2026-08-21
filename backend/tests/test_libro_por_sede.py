"""El libro por sede: Vida y Palmetto por separado desde agosto, y «Ambas» = la
suma. Antes del corte (≤ julio) el libro sigue combinado —el histórico no está
marcado por sede y no se puede repartir hacia atrás—.

La transición no rompe nada: mientras ninguna sede tenga su ancla cargada, «Ambas»
es el libro global de siempre; recién cuando el dueño carga el saldo de una sede
la vista pasa a sumar sedes y cada movimiento nuevo de agosto tiene que elegir una.
"""
import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Configuracion, RolEnum, Tienda, Usuario
from app.services import banco as banco_svc
from app.services.banco import (ancla, fijar_ancla_sede, libro, por_sede_activo,
                               registrar, sembrar_cuentas)

AGO = date(2026, 8, 1)   # el corte
JUL = date(2026, 7, 1)   # antes del corte


class Base_(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.vida = Tienda(nombre="Vida", direccion="x", activa=True)
        self.palm = Tienda(nombre="Palmetto", direccion="y", activa=True)
        self.db.add_all([self.vida, self.palm]); self.db.flush()
        self.admin = Usuario(nombre="B", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin); self.db.commit()
        sembrar_cuentas(self.db)
        self.occ = self.db.query(banco_svc.CuentaBancaria).filter_by(
            nombre="Occidente").first()

    def tearDown(self):
        self.db.close(); self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def ancla_global(self, saldo, fecha):
        self.db.add(Configuracion(clave=banco_svc.CLAVE_SALDO, valor=str(saldo)))
        self.db.add(Configuracion(clave=banco_svc.CLAVE_SALDO_FECHA, valor=fecha.isoformat()))
        self.db.commit()

    def mov(self, fecha, tipo, monto, tienda_id=None, concepto="x"):
        return registrar(self.db, fecha, self.occ.id, tipo, monto, concepto,
                         usuario_id=self.admin.id, tienda_id=tienda_id)

    def dia(self, l, iso):
        return next(d for d in l["dias"] if d["fecha"] == iso)


class LibroPorSedeTest(Base_):

    def test_cada_sede_ve_solo_lo_suyo(self):
        fijar_ancla_sede(self.db, 1_000_000, AGO, self.vida.id)
        fijar_ancla_sede(self.db, 500_000, AGO, self.palm.id)
        self.mov(date(2026, 8, 2), "entrada", 300_000, self.vida.id)
        self.mov(date(2026, 8, 2), "entrada", 70_000, self.palm.id)
        lv = libro(self.db, date(2026, 8, 1), date(2026, 8, 3), self.vida.id)
        lp = libro(self.db, date(2026, 8, 1), date(2026, 8, 3), self.palm.id)
        self.assertEqual(self.dia(lv, "2026-08-02")["total_entradas"], 300_000)
        self.assertEqual(self.dia(lv, "2026-08-03")["final"], 1_300_000)
        self.assertEqual(self.dia(lp, "2026-08-02")["total_entradas"], 70_000)
        self.assertEqual(self.dia(lp, "2026-08-03")["final"], 570_000)

    def test_ambas_suma_las_sedes(self):
        fijar_ancla_sede(self.db, 1_000_000, AGO, self.vida.id)
        fijar_ancla_sede(self.db, 500_000, AGO, self.palm.id)
        self.mov(date(2026, 8, 2), "entrada", 300_000, self.vida.id)
        self.mov(date(2026, 8, 2), "salida", 70_000, self.palm.id)
        la = libro(self.db, date(2026, 8, 1), date(2026, 8, 3))  # None = Ambas
        self.assertIsNone(la["tienda_id"])
        d3 = self.dia(la, "2026-08-03")
        # Vida cierra 1.300.000, Palmetto 430.000 → Ambas 1.730.000.
        self.assertEqual(d3["final"], 1_730_000)
        d2 = self.dia(la, "2026-08-02")
        self.assertEqual(d2["total_entradas"], 300_000)   # la de Vida
        self.assertEqual(d2["total_salidas"], 70_000)     # la de Palmetto

    def test_ambas_no_inventa_el_total_si_falta_un_ancla(self):
        """Con una sola sede anclada, «Ambas» no puede sumar: el total va en null
        (la otra sede no se sabe), pero los movimientos igual se ven."""
        fijar_ancla_sede(self.db, 1_000_000, AGO, self.vida.id)
        # Palmetto sin ancla, pero con un movimiento (prende el modo por sede).
        self.mov(date(2026, 8, 2), "entrada", 300_000, self.vida.id)
        self.mov(date(2026, 8, 2), "entrada", 50_000, self.palm.id)
        la = libro(self.db, date(2026, 8, 1), date(2026, 8, 3))
        d3 = self.dia(la, "2026-08-03")
        self.assertIsNone(d3["final"])                    # no se inventa el total
        self.assertEqual(d3["total_entradas"], 0)         # ese día no hay entradas
        self.assertEqual(self.dia(la, "2026-08-02")["total_entradas"], 350_000)

    def test_antes_del_corte_sigue_combinado(self):
        """Julio (antes del corte) es el libro global aunque las sedes tengan
        ancla: el histórico no se reparte hacia atrás."""
        self.ancla_global(2_000_000, JUL)
        fijar_ancla_sede(self.db, 1_000_000, AGO, self.vida.id)
        self.mov(date(2026, 7, 2), "entrada", 400_000)   # sin sede (histórico)
        lj = libro(self.db, date(2026, 7, 1), date(2026, 7, 3))  # None
        self.assertIsNone(lj["tienda_id"])
        self.assertEqual(self.dia(lj, "2026-07-03")["final"], 2_400_000)

    def test_sin_arrancar_por_sede_agosto_sigue_global(self):
        """Agosto, sin ninguna ancla de sede: «Ambas» es todavía el libro global
        —la transición no rompe la vista mientras no haya nada por sede—."""
        self.assertFalse(por_sede_activo(self.db))
        self.ancla_global(1_000_000, AGO)
        self.mov(date(2026, 8, 2), "entrada", 500_000)   # sin sede: permitido
        la = libro(self.db, date(2026, 8, 1), date(2026, 8, 3))
        self.assertEqual(self.dia(la, "2026-08-03")["final"], 1_500_000)

    def test_cargar_un_ancla_de_sede_prende_el_modo(self):
        self.assertFalse(por_sede_activo(self.db))
        fijar_ancla_sede(self.db, 1_000_000, AGO, self.vida.id)
        self.assertTrue(por_sede_activo(self.db))
        # Y el ancla de la sede se lee por su cuenta, separada de la global.
        saldo, fecha = ancla(self.db, self.vida.id)
        self.assertEqual(saldo, 1_000_000)
        self.assertEqual(fecha, AGO)
        self.assertIsNone(ancla(self.db)[1])   # la global sigue vacía


if __name__ == "__main__":
    unittest.main()
