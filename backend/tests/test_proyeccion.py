"""«Lo que viene»: el cierre estimado de los próximos meses.

La regla de oro de este módulo, y de todo el repo: NO INVENTAR UNA CALMA. Un
número proyectado sin base es peor que no dar ninguno — decide por el dueño con
un dato cerca del correcto. Por eso las dos puertas (`sin_base`) importan tanto
como la cuenta, y por eso la tendencia sale de la MEDIANA: un mes raro no puede
arrastrar la estimación entera.
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
from app.services.banco import proyeccion, registrar, sembrar_cuentas


class Base_(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.vida)
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()
        sembrar_cuentas(self.db)
        self.occ = self.db.query(banco_svc.CuentaBancaria).filter_by(
            nombre="Occidente").first()
        self.hoy = date(2026, 7, 15)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def ancla(self, saldo, fecha):
        self.db.add(Configuracion(clave=banco_svc.CLAVE_SALDO, valor=str(saldo)))
        self.db.add(Configuracion(clave=banco_svc.CLAVE_SALDO_FECHA,
                                  valor=fecha.isoformat()))
        self.db.commit()

    def ent(self, d, monto):
        registrar(self.db, d, self.occ.id, "entrada", monto, "x",
                  usuario_id=self.admin.id)

    def sal(self, d, monto):
        registrar(self.db, d, self.occ.id, "salida", monto, "x",
                  usuario_id=self.admin.id)

    def mes_normal(self, anio, mes, neto=1_000_000):
        """Un mes con neto conocido: entra neto+1M, sale 1M → queda `neto`."""
        self.ent(date(anio, mes, 10), neto + 1_000_000)
        self.sal(date(anio, mes, 20), 1_000_000)


class ProyeccionTest(Base_):

    def test_proyecta_desde_la_mediana_del_neto(self):
        self.ancla(1_000_000, date(2026, 4, 1))
        for mes in (4, 5, 6):              # tres meses completos, neto +1M cada uno
            self.mes_normal(2026, mes, 1_000_000)

        r = proyeccion(self.db, self.hoy, meses=3)
        self.assertIsNone(r["motivo"])
        self.assertEqual(r["base"]["neto_normal"], 1_000_000)
        self.assertEqual(r["base"]["meses_de_historial"], 3)
        # Los próximos tres meses: agosto, septiembre, octubre.
        self.assertEqual([m["mes"] for m in r["meses"]], [8, 9, 10])
        # Cada mes sube un «neto normal» sobre el anterior.
        cierres = [m["cierre_estimado"] for m in r["meses"]]
        self.assertEqual(cierres[1] - cierres[0], 1_000_000)
        self.assertEqual(cierres[2] - cierres[1], 1_000_000)
        # Y el primero arranca del saldo de HOY + un neto.
        self.assertEqual(cierres[0], r["base"]["saldo_hoy"] + 1_000_000)

    def test_la_mediana_ignora_el_mes_raro(self):
        """Un mes con una compra enorme no arrastra la tendencia: la mediana de
        [1M, 1M, 1M, 10M] es 1M, no el promedio 3,25M."""
        self.ancla(0, date(2026, 3, 1))
        self.mes_normal(2026, 3, 1_000_000)
        self.mes_normal(2026, 4, 1_000_000)
        self.mes_normal(2026, 5, 1_000_000)
        self.mes_normal(2026, 6, 10_000_000)
        r = proyeccion(self.db, self.hoy, meses=1)
        self.assertEqual(r["base"]["neto_normal"], 1_000_000)

    def test_el_mes_en_curso_no_cuenta_para_el_ritmo(self):
        """El mes a medias mentiría el promedio: entra en el saldo de hoy, pero
        NO en la tendencia."""
        self.ancla(0, date(2026, 4, 1))
        for mes in (4, 5, 6):
            self.mes_normal(2026, mes, 1_000_000)
        self.ent(date(2026, 7, 3), 50_000_000)     # un julio atípico, aún abierto
        r = proyeccion(self.db, self.hoy, meses=2)
        self.assertEqual(r["base"]["neto_normal"], 1_000_000)   # sigue siendo 1M
        self.assertGreater(r["base"]["saldo_hoy"], 50_000_000)  # pero el saldo lo ve

    def test_sin_ancla_no_hay_desde_donde(self):
        for mes in (4, 5, 6):
            self.mes_normal(2026, mes, 1_000_000)
        r = proyeccion(self.db, self.hoy, meses=3)
        self.assertIsNone(r["base"])
        self.assertEqual(r["meses"], [])
        self.assertIn("extracto", r["motivo"])

    def test_con_dos_meses_no_alcanza(self):
        """Dos meses son casualidad, no tendencia: se dice cuántos hay."""
        self.ancla(0, date(2026, 5, 1))
        self.mes_normal(2026, 5, 1_000_000)
        self.mes_normal(2026, 6, 1_000_000)
        r = proyeccion(self.db, self.hoy, meses=3)
        self.assertIsNone(r["base"])
        self.assertIn("2", r["motivo"])

    def test_un_mes_vacio_no_baja_la_mediana(self):
        """Un mes sin un peso movido no es un «mes normal» de neto cero: es un
        mes sin datos, y no entra a la ventana."""
        self.ancla(0, date(2026, 3, 1))
        self.mes_normal(2026, 3, 2_000_000)
        # abril quedó vacío a propósito (nada registrado)
        self.mes_normal(2026, 5, 2_000_000)
        self.mes_normal(2026, 6, 2_000_000)
        r = proyeccion(self.db, self.hoy, meses=1)
        self.assertEqual(r["base"]["meses_de_historial"], 3)  # marzo, mayo, junio
        self.assertEqual(r["base"]["neto_normal"], 2_000_000)


if __name__ == "__main__":
    unittest.main()
