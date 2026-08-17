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


class ElAnclaAMitadDeMesTest(BancoBase):
    """EL CASO NORMAL, y el que rompía el mes entero.

    El editor propone HOY como fecha del extracto y el sistema pide
    actualizarlo cada 7 días, así que el ancla cae a mitad de mes casi siempre.
    Con una sola bandera para todo el rango —calculada mirando el día 1— el mes
    en curso quedaba marcado «sin saldos» aunque del ancla en adelante el saldo
    sea exacto, y la pantalla le pedía al dueño cargar lo que acababa de
    cargar. La cadena se decide POR DÍA.
    """

    def test_los_dias_desde_el_ancla_SI_tienen_saldo(self):
        self.anclar(1_000_000, date(2026, 8, 16))
        self.entrada(date(2026, 8, 17), 500_000)
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 31))
        d16 = self.dia(lib, date(2026, 8, 16))
        d17 = self.dia(lib, date(2026, 8, 17))
        self.assertTrue(d16["cadena"])
        self.assertAlmostEqual(d16["inicial"], 1_000_000)
        self.assertTrue(d17["cadena"])
        self.assertAlmostEqual(d17["final"], 1_500_000)

    def test_los_dias_ANTES_del_ancla_van_en_null_y_no_se_inventan(self):
        self.anclar(1_000_000, date(2026, 8, 16))
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 31))
        d1 = self.dia(lib, date(2026, 8, 1))
        self.assertFalse(d1["cadena"])
        self.assertIsNone(d1["inicial"])
        self.assertIsNone(d1["final"])
        self.assertFalse(d1["en_rojo"])      # sin saldo no hay rojo posible

    def test_el_mes_dice_DESDE_CUANDO_hay_saldo_en_vez_de_apagarse(self):
        self.anclar(1_000_000, date(2026, 8, 16))
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 31))
        self.assertFalse(lib["cadena_completa"])          # el mes no está entero
        self.assertEqual(lib["dias_con_saldo"], 16)       # del 16 al 31
        self.assertEqual(lib["primer_dia_con_saldo"], "2026-08-16")

    def test_el_dia_mas_bajo_ignora_los_dias_sin_saldo(self):
        """Un mínimo sobre una lista con nulos no significa nada."""
        self.anclar(1_000_000, date(2026, 8, 16))
        self.salida(date(2026, 8, 20), 900_000)
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 31))
        self.assertAlmostEqual(lib["totales"]["dia_mas_bajo"], 100_000)
        self.assertEqual(lib["totales"]["fecha_dia_mas_bajo"], "2026-08-20")

    def test_mirar_solo_la_segunda_quincena_da_lo_mismo(self):
        """El saldo de un día no puede depender del rango que se pida."""
        self.anclar(1_000_000, date(2026, 8, 16))
        self.entrada(date(2026, 8, 17), 500_000)
        mes = self.dia(banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 31)),
                       date(2026, 8, 20))
        quincena = self.dia(banco.libro(self.db, date(2026, 8, 17), date(2026, 8, 31)),
                            date(2026, 8, 20))
        self.assertAlmostEqual(mes["final"], quincena["final"])
        self.assertTrue(quincena["cadena"])

    def test_con_el_ancla_el_dia_1_el_mes_entero_tiene_saldo(self):
        self.anclar(1_000_000, date(2026, 8, 1))
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 31))
        self.assertTrue(lib["cadena_completa"])
        self.assertEqual(lib["dias_con_saldo"], 31)


class ElAnclaSeSaneaTest(BancoBase):
    """`configuracion` es texto libre: un `inf` ahí adentro reventaba la pestaña.

    El valor viajaba dentro de los saldos del libro y FastAPI serializa con
    allow_nan=False, así que /banco/libro devolvía 500 y no cargaba nada. El
    flujo proyectado tenía su propia red; el libro no tenía ninguna.
    """

    def _anclar_crudo(self, valor):
        self.db.add(Configuracion(clave=banco.CLAVE_SALDO, valor=valor))
        self.db.add(Configuracion(clave=banco.CLAVE_SALDO_FECHA,
                                  valor="2026-08-01"))
        self.db.commit()

    def test_un_infinito_no_llega_al_libro(self):
        self._anclar_crudo("inf")
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 3))
        for d in lib["dias"]:
            self.assertTrue(d["inicial"] is None or abs(d["inicial"]) < 1e13)
            self.assertTrue(d["final"] is None or abs(d["final"]) < 1e13)

    def test_un_ancla_podrida_es_NO_TENER_ancla_no_un_ancla_de_cero(self):
        """Saneando solo el monto y conservando la fecha, la cadena arrancaba
        desde un cero inventado y el libro afirmaba «ese día tenías $0» sobre
        un dato que nadie cargó."""
        for basura in ("inf", "nan", "hola", "-999999", "999999999999999"):
            with self.subTest(basura=basura):
                self.db.query(Configuracion).delete()
                self.db.commit()
                self._anclar_crudo(basura)
                saldo, fecha = banco.ancla(self.db)
                self.assertEqual(saldo, 0.0)
                self.assertIsNone(fecha, f"«{basura}» dejó una fecha usable")

    def test_con_ancla_podrida_ningun_dia_tiene_saldo(self):
        self._anclar_crudo("inf")
        lib = banco.libro(self.db, date(2026, 8, 1), date(2026, 8, 3))
        self.assertEqual(lib["dias_con_saldo"], 0)
        self.assertFalse(any(d["cadena"] for d in lib["dias"]))

    def test_un_ancla_en_CERO_de_verdad_si_sirve(self):
        """Cero es un saldo posible; basura no. No se pueden confundir."""
        self._anclar_crudo("0")
        saldo, fecha = banco.ancla(self.db)
        self.assertEqual(saldo, 0.0)
        self.assertEqual(fecha, date(2026, 8, 1))


if __name__ == "__main__":
    unittest.main()