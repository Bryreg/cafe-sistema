"""El libro del banco: una fila por día, con la fórmula de la hoja del dueño.

    final = inicial + entradas − salidas   y   inicial(d) = final(d−1)

Cada caso se verifica a mano con una calculadora. Si alguno se cae, el saldo que
la pantalla muestra dejó de cuadrar contra el extracto.
"""
import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Configuracion
from app.services import banco


class BancoBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        banco.sembrar_cuentas(self.db)
        self.occ, self.bold = banco.cuentas(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def anclar(self, saldo, fecha):
        self.db.add(Configuracion(clave=banco.CLAVE_SALDO, valor=str(saldo)))
        self.db.add(Configuracion(clave=banco.CLAVE_SALDO_FECHA,
                                  valor=fecha.isoformat()))
        self.db.commit()

    def entrada(self, fecha, monto, cuenta=None, concepto="Consignación"):
        return banco.registrar(self.db, fecha, (cuenta or self.occ).id,
                               banco.ENTRADA, monto, concepto)

    def salida(self, fecha, monto, cuenta=None, concepto="Pago proveedor"):
        return banco.registrar(self.db, fecha, (cuenta or self.occ).id,
                               banco.SALIDA, monto, concepto)

    def dia(self, libro, fecha):
        return [d for d in libro["dias"] if d["fecha"] == fecha.isoformat()][0]


class LaFormulaDeLaHojaTest(BancoBase):
    def test_final_es_inicial_mas_lo_que_entra_menos_lo_que_sale(self):
        """La invariante que sostiene todo el módulo, verificable a ojo."""
        self.anclar(1_000_000, date(2026, 8, 1))
        self.entrada(date(2026, 8, 2), 3_701_250)
        self.salida(date(2026, 8, 2), 8_210_385)
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 5))
        for d in lib["dias"]:
            esperado = round(d["inicial"] + d["total_entradas"] - d["total_salidas"], 2)
            self.assertAlmostEqual(d["final"], esperado, places=2,
                                   msg="la fórmula no cierra el " + d["fecha"])

    def test_el_saldo_se_encadena_de_un_dia_al_siguiente(self):
        self.anclar(2_025_023, date(2026, 8, 1))
        self.entrada(date(2026, 8, 2), 2_202_100)
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 3))
        d1, d2, d3 = lib["dias"]
        self.assertAlmostEqual(d1["final"], 2_025_023)
        self.assertAlmostEqual(d2["inicial"], d1["final"])
        self.assertAlmostEqual(d2["final"], 2_025_023 + 2_202_100)
        self.assertAlmostEqual(d3["inicial"], d2["final"])

    def test_los_dias_SIN_movimiento_tambien_van(self):
        """Son los que dejan ver que el saldo se quedó abajo cuatro días
        seguidos. Un libro de solo días con movimiento esconde justo eso."""
        self.anclar(500_000, date(2026, 8, 1))
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(len(lib["dias"]), 31)

    def test_reproduce_un_dia_real_de_su_hoja(self):
        """1-jul-2026 del Excel del dueño: arranca en 2.025.023, entran
        3.701.250 por Occidente y 3.189.000 por Bold, salen 8.210.385 por Bold,
        y cierra en 704.888."""
        self.anclar(2_025_023, date(2026, 6, 30))
        self.entrada(date(2026, 7, 1), 3_701_250, self.occ)
        self.entrada(date(2026, 7, 1), 3_189_000, self.bold)
        self.salida(date(2026, 7, 1), 8_210_385, self.bold)
        d = self.dia(banco.libro(self.db, date(2026, 7, 1), date(2026, 7, 1)),
                     date(2026, 7, 1))
        self.assertAlmostEqual(d["inicial"], 2_025_023)
        self.assertAlmostEqual(d["final"], 704_888)


class ElSaldoNoSeInventaTest(BancoBase):
    def test_sin_ancla_la_serie_declara_que_no_hay_cadena(self):
        """Un saldo de $0 inventado se lee como «no hay plata» y dispara una
        decisión equivocada. Se declara que falta el dato."""
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 5))
        self.assertFalse(lib["cadena_completa"])
        self.assertIsNone(lib["ancla"]["fecha"])

    def test_con_ancla_la_cadena_se_declara_completa(self):
        self.anclar(1_000_000, date(2026, 7, 31))
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 5))
        self.assertTrue(lib["cadena_completa"])

    def test_un_dia_anterior_al_ancla_no_afirma_un_saldo(self):
        self.anclar(1_000_000, date(2026, 8, 15))
        _saldo, hay = banco.saldo_al_cierre(self.db, date(2026, 8, 1))
        self.assertFalse(hay)


class ElAnclaEsUnaAPERTURATest(BancoBase):
    """Qué significa exactamente el saldo que el dueño carga a mano.

    Es «con cuánto arranco este día», no «con cuánto cerré». No es una
    convención elegida al azar: es la de su hoja, donde el primer día de agosto
    abre con el cierre de julio (`B4 = +JUNIO!I34`) y donde los dos ajustes que
    él cargó a mano —abril y agosto— son saldos de arranque. Leerla como un
    cierre haría desaparecer los movimientos del día del ancla.
    """

    def test_el_dia_del_ancla_ARRANCA_con_ella(self):
        self.anclar(1_000_000, date(2026, 8, 10))
        lib = banco.libro(self.db, date(2026, 8, 10), date(2026, 8, 10))
        self.assertAlmostEqual(self.dia(lib, date(2026, 8, 10))["inicial"], 1_000_000)

    def test_los_movimientos_de_ese_dia_se_suman_encima(self):
        self.anclar(1_000_000, date(2026, 8, 10))
        self.entrada(date(2026, 8, 10), 400_000)
        lib = banco.libro(self.db, date(2026, 8, 10), date(2026, 8, 10))
        self.assertAlmostEqual(self.dia(lib, date(2026, 8, 10))["final"], 1_400_000)

    def test_el_dia_siguiente_abre_con_el_cierre_del_anterior(self):
        self.anclar(1_000_000, date(2026, 8, 10))
        self.entrada(date(2026, 8, 10), 400_000)
        lib = banco.libro(self.db, date(2026, 8, 10), date(2026, 8, 11))
        self.assertAlmostEqual(self.dia(lib, date(2026, 8, 11))["inicial"], 1_400_000)

    def test_arrancar_el_libro_DESPUES_del_ancla_igual_encadena(self):
        """Mirar solo el 11 no puede dar distinto que mirar del 10 al 11."""
        self.anclar(1_000_000, date(2026, 8, 10))
        self.entrada(date(2026, 8, 10), 400_000)
        solo11 = banco.libro(self.db, date(2026, 8, 11), date(2026, 8, 11))
        self.assertAlmostEqual(self.dia(solo11, date(2026, 8, 11))["inicial"], 1_400_000)


class ElSignoLoPoneElTipoTest(BancoBase):
    def test_un_monto_negativo_se_rechaza(self):
        """Una salida de −$100.000 sumaría plata, y ese error no se ve hasta
        que el mes no cuadra contra el extracto."""
        with self.assertRaises(ValueError):
            self.salida(date(2026, 8, 1), -100_000)

    def test_un_monto_en_cero_se_rechaza(self):
        with self.assertRaises(ValueError):
            self.entrada(date(2026, 8, 1), 0)

    def test_un_movimiento_sin_concepto_se_rechaza(self):
        """Sin concepto no se puede conciliar después contra el extracto."""
        with self.assertRaises(ValueError):
            self.entrada(date(2026, 8, 1), 1000, concepto="   ")

    def test_un_tipo_inventado_se_rechaza(self):
        with self.assertRaises(ValueError):
            banco.registrar(self.db, date(2026, 8, 1), self.occ.id,
                            "transferencia", 1000, "x")

    def test_una_cuenta_que_no_existe_se_rechaza(self):
        with self.assertRaises(ValueError):
            banco.registrar(self.db, date(2026, 8, 1), 9999,
                            banco.ENTRADA, 1000, "x")


class CadaCuentaConSuColumnaTest(BancoBase):
    def test_las_entradas_se_abren_por_cuenta(self):
        self.anclar(0, date(2026, 8, 1))
        self.entrada(date(2026, 8, 2), 1_000_000, self.occ)
        self.entrada(date(2026, 8, 2), 500_000, self.bold)
        d = self.dia(banco.libro(self.db, date(2026, 8, 2), date(2026, 8, 2)),
                     date(2026, 8, 2))
        self.assertAlmostEqual(d["entradas"]["Occidente"], 1_000_000)
        self.assertAlmostEqual(d["entradas"]["Bold"], 500_000)
        self.assertAlmostEqual(d["total_entradas"], 1_500_000)

    def test_sembrar_dos_veces_no_duplica_cuentas(self):
        banco.sembrar_cuentas(self.db)
        self.assertEqual(len(banco.cuentas(self.db)), 2)


class LoQueElDuenoNecesitaVerTest(BancoBase):
    def test_marca_los_dias_que_cierran_en_rojo(self):
        """En julio real tuvo cuatro días seguidos en negativo."""
        self.anclar(100_000, date(2026, 8, 1))
        self.salida(date(2026, 8, 2), 500_000)
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 5))
        self.assertTrue(self.dia(lib, date(2026, 8, 2))["en_rojo"])
        self.assertEqual(lib["totales"]["dias_en_rojo"], 4)      # del 2 al 5

    def test_reporta_el_dia_mas_bajo_del_periodo(self):
        """El colchón se adelgaza antes de llegar a cero: hay que verlo venir."""
        self.anclar(1_000_000, date(2026, 8, 1))
        self.salida(date(2026, 8, 2), 900_000)
        self.entrada(date(2026, 8, 3), 2_000_000)
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 3))
        self.assertAlmostEqual(lib["totales"]["dia_mas_bajo"], 100_000)

    def test_la_serie_del_ano_muestra_los_doce_meses(self):
        self.anclar(0, date(2026, 1, 1))
        self.entrada(date(2026, 3, 10), 5_000_000)
        self.salida(date(2026, 3, 20), 2_000_000)
        s = banco.serie_mensual(self.db, 2026)
        self.assertEqual(len(s["meses"]), 12)
        marzo = s["meses"][2]
        self.assertAlmostEqual(marzo["entradas"], 5_000_000)
        self.assertAlmostEqual(marzo["salidas"], 2_000_000)
        self.assertAlmostEqual(marzo["neto"], 3_000_000)


class CorregirArreglaTodoAguasAbajoTest(BancoBase):
    def test_borrar_un_movimiento_viejo_recorre_la_cadena_solo(self):
        """El saldo se DERIVA, por eso no hay que reescribir nada."""
        self.anclar(1_000_000, date(2026, 8, 1))
        m = self.salida(date(2026, 8, 2), 300_000)
        self.entrada(date(2026, 8, 5), 500_000)
        antes = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 10))
        self.assertAlmostEqual(self.dia(antes, date(2026, 8, 10))["final"], 1_200_000)
        self.assertTrue(banco.borrar(self.db, m.id))
        despues = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 10))
        self.assertAlmostEqual(self.dia(despues, date(2026, 8, 10))["final"], 1_500_000)

    def test_borrar_algo_que_no_existe_no_revienta(self):
        self.assertFalse(banco.borrar(self.db, 9999))


if __name__ == "__main__":
    unittest.main()
