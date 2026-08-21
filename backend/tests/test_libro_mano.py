"""La mano del dueño, DENTRO del libro: recogí = entrada, pago efectivo = salida.

El libro pasó de ser «el banco» a ser «toda la plata»: banco + mano, con dos
sub-saldos. El del banco sigue con su cadena contra el extracto (intacto — la
prueba de julio no se mueve); el de la mano es 100% DERIVADO (Σ recogidas − Σ
pagos en efectivo), sin ancla, porque la bolsa arrancó vacía y cada recogida y
cada pago quedan registrados. El total solo se conoce donde el banco tiene
cadena: sin el saldo del banco, banco + mano sería un número inventado.
"""
import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (Configuracion, Pago, RecogidaEfectivo, RolEnum,
                               Tienda, Usuario)
from app.services import banco as banco_svc
from app.services.banco import libro, registrar, sembrar_cuentas


class Base_(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.vida = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.vida); self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin); self.db.commit()
        sembrar_cuentas(self.db)
        self.occ = self.db.query(banco_svc.CuentaBancaria).filter_by(
            nombre="Occidente").first()

    def tearDown(self):
        self.db.close(); self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def ancla(self, saldo, fecha):
        self.db.add(Configuracion(clave=banco_svc.CLAVE_SALDO, valor=str(saldo)))
        self.db.add(Configuracion(clave=banco_svc.CLAVE_SALDO_FECHA, valor=fecha.isoformat()))
        self.db.commit()

    def recogida(self, fecha, monto):
        self.db.add(RecogidaEfectivo(tienda_id=self.vida.id, fecha=fecha,
                                     monto=monto, usuario_id=self.admin.id))
        self.db.commit()

    def pago_efectivo(self, fecha, monto):
        self.db.add(Pago(tienda_id=self.vida.id, monto=monto, fecha_pago=fecha,
                         metodo="efectivo", usuario_id=self.admin.id))
        self.db.commit()

    def dia(self, l, iso):
        return next(d for d in l["dias"] if d["fecha"] == iso)


class ManoDentroDelLibroTest(Base_):

    def test_recogi_es_entrada_de_la_mano(self):
        self.ancla(1_000_000, date(2026, 8, 1))
        self.recogida(date(2026, 8, 2), 500_000)
        l = libro(self.db, date(2026, 8, 1), date(2026, 8, 3))
        d2 = self.dia(l, "2026-08-02")
        self.assertEqual(d2["mano_entradas"], 500_000)
        self.assertEqual(d2["mano_saldo"], 500_000)
        self.assertEqual(len(d2["recogido"]), 1)
        # Y el banco NI se entera: la recogida no es un movimiento del banco.
        self.assertEqual(d2["total_entradas"], 0)
        self.assertEqual(d2["final"], 1_000_000)

    def test_pago_en_efectivo_es_salida_de_la_mano(self):
        self.ancla(1_000_000, date(2026, 8, 1))
        self.recogida(date(2026, 8, 2), 500_000)
        self.pago_efectivo(date(2026, 8, 3), 200_000)
        l = libro(self.db, date(2026, 8, 1), date(2026, 8, 5))
        d3 = self.dia(l, "2026-08-03")
        self.assertEqual(d3["mano_salidas"], 200_000)
        self.assertEqual(d3["mano_saldo"], 300_000)   # 500k − 200k
        # El banco tampoco lo ve: el efectivo salió de la mano, no de la cuenta.
        self.assertEqual(d3["total_salidas"], 0)

    def test_el_total_es_banco_mas_mano(self):
        self.ancla(1_000_000, date(2026, 8, 1))
        registrar(self.db, date(2026, 8, 2), self.occ.id, "entrada", 300_000, "x",
                  usuario_id=self.admin.id)       # banco sube a 1.300.000
        self.recogida(date(2026, 8, 2), 500_000)  # mano sube a 500.000
        l = libro(self.db, date(2026, 8, 1), date(2026, 8, 3))
        d2 = self.dia(l, "2026-08-02")
        self.assertEqual(d2["final"], 1_300_000)        # banco
        self.assertEqual(d2["mano_saldo"], 500_000)     # mano
        self.assertEqual(d2["total_final"], 1_800_000)  # banco + mano

    def test_la_mano_de_antes_del_rango_se_arrastra(self):
        """Un mes mirado suelto no arranca la mano en cero: trae lo recogido
        (menos lo pagado) de los meses anteriores."""
        self.ancla(1_000_000, date(2026, 8, 1))
        self.recogida(date(2026, 7, 20), 800_000)    # julio, antes del rango
        self.pago_efectivo(date(2026, 7, 25), 300_000)
        l = libro(self.db, date(2026, 8, 1), date(2026, 8, 2))
        d1 = self.dia(l, "2026-08-01")
        self.assertEqual(d1["mano_saldo"], 500_000)  # 800k − 300k, arrastrado

    def test_sin_cadena_del_banco_el_total_no_se_inventa(self):
        """La mano se conoce siempre, pero el TOTAL necesita el saldo del banco:
        antes del ancla, total_final va en null en vez de un número a medias."""
        self.ancla(1_000_000, date(2026, 8, 10))     # ancla a mitad de mes
        self.recogida(date(2026, 8, 3), 500_000)     # antes del ancla
        l = libro(self.db, date(2026, 8, 1), date(2026, 8, 12))
        d3 = self.dia(l, "2026-08-03")
        self.assertFalse(d3["cadena"])               # banco sin saldo ese día
        self.assertEqual(d3["mano_saldo"], 500_000)  # pero la mano sí se sabe
        self.assertIsNone(d3["total_final"])         # el total no se inventa

    def test_el_banco_no_cambia_por_la_mano(self):
        """La invariante que protege la aceptación de julio: agregar recogidas y
        pagos en efectivo NO mueve ni un peso los totales del banco."""
        self.ancla(1_000_000, date(2026, 8, 1))
        registrar(self.db, date(2026, 8, 2), self.occ.id, "salida", 100_000, "x",
                  usuario_id=self.admin.id)
        antes = libro(self.db, date(2026, 8, 1), date(2026, 8, 5))["totales"]
        self.recogida(date(2026, 8, 3), 500_000)
        self.pago_efectivo(date(2026, 8, 4), 200_000)
        desp = libro(self.db, date(2026, 8, 1), date(2026, 8, 5))["totales"]
        self.assertEqual(antes["entradas"], desp["entradas"])
        self.assertEqual(antes["salidas"], desp["salidas"])
        self.assertEqual(antes["final"], desp["final"])
        # La mano sí cambió, y el total la refleja.
        self.assertEqual(desp["mano_final"], 300_000)
        self.assertEqual(desp["total_final"], desp["final"] + 300_000)


if __name__ == "__main__":
    unittest.main()
