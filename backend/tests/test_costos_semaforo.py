"""Módulo Costos — Fase 5: la cobertura de COSTOS FIJOS que hace honesto al semáforo.

Hasta la fase 3, el "margen operativo de caja" no restaba arriendo ni nómina, y la
pantalla lo confesaba con una muletilla. Desde la fase 3 SÍ los resta — pero solo
los que alguien cargó. Y ahí aparece el defecto que esta fase cierra:

    un margen neto sin costos fijos cargados y uno con todos cargados son
    NUMÉRICAMENTE indistinguibles desde el frente. El primero está inflado; el
    segundo es real. Un semáforo que no puede distinguirlos puede decir "Sano"
    mientras falta el arriendo entero del mes.

`get_rentabilidad` expone entonces un dato ADITIVO —`costos_fijos_devengados`,
`n_costos_fijos`, `tiene_costos_fijos`— que NO entra en ninguna fórmula: la plata ya
estaba dentro de `gastos` y de `margen_neto`. Lo único que agrega es la capacidad de
decir "falta el dato" en vez de vender tranquilidad con un verde.

Este archivo pina justamente eso: que el campo vale 0/False sin obligaciones fijas,
el monto exacto con ellas, y que NINGÚN total viejo se movió al agregarlo.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base
from app.models.models import (
    CajaTurno, CostoCategoria, EstadoTurnoEnum, MovimientoCaja, Obligacion,
    RolEnum, Ticket, Tienda, Usuario,
)
from app.services.rentabilidad import get_rentabilidad


class CoberturaCostosFijosTest(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t1 = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t1)
        self.db.flush()
        self.u = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                         rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.u)
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.t1.id, usuario_apertura_id=self.u.id,
                               base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add(self.turno)
        self.db.flush()

        # Catálogo real (main.py siembra estas mismas claves y grupos).
        self.cat_arriendo = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                           grupo="fijo", orden=0)
        self.cat_nomina = CostoCategoria(clave="nomina", nombre="Nómina",
                                         grupo="fijo", orden=1)
        self.cat_mantenimiento = CostoCategoria(clave="mantenimiento", nombre="Mantenimiento",
                                                grupo="variable", orden=2)
        self.db.add_all([self.cat_arriendo, self.cat_nomina, self.cat_mantenimiento])

        self.ahora = inicio_dia_col_utc(hoy_col()) + (
            datetime.min.replace(hour=12) - datetime.min)
        self.db.add(Ticket(tienda_id=self.t1.id, caja_turno_id=self.turno.id,
                           usuario_id=self.u.id, fecha=self.ahora, total=1000000,
                           estado="completado", metodo_pago="efectivo"))
        # Un egreso suelto de caja: es gasto, pero NO es un costo fijo cargado.
        self.db.add(MovimientoCaja(caja_turno_id=self.turno.id, tipo="egreso",
                                   concepto="Domicilios", valor=50000,
                                   usuario_id=self.u.id, fecha=self.ahora))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def pl(self, **kw):
        return get_rentabilidad(self.db, hoy_col(), hoy_col(), **kw)

    def obligacion(self, categoria, monto, *, devengo=None, tienda_id=None, anulada=False):
        o = Obligacion(tienda_id=tienda_id, categoria_id=categoria.id,
                       concepto=f"{categoria.nombre} de prueba", monto=monto,
                       fecha_devengo=devengo or hoy_col(), usuario_id=self.u.id,
                       anulada=anulada)
        self.db.add(o)
        self.db.commit()
        return o

    # ── 1. Sin costos fijos: 0 y False, nunca ausente ────────────────────────

    def test_sin_obligaciones_fijas_el_campo_existe_y_vale_cero(self):
        r = self.pl()["resumen"]
        # El campo SIEMPRE viaja: si faltara, el frente no podría distinguir
        # "no hay costos fijos" de "este backend todavía no los reporta".
        self.assertIn("costos_fijos_devengados", r)
        self.assertEqual(r["costos_fijos_devengados"], 0)
        self.assertEqual(r["n_costos_fijos"], 0)
        self.assertIs(r["tiene_costos_fijos"], False)
        # Y hay gasto igual: un egreso suelto NO es cobertura de costos fijos.
        self.assertEqual(r["gastos"], 50000)

    # ── 2. Con costos fijos: el monto exacto ─────────────────────────────────

    def test_con_obligaciones_fijas_reporta_el_monto_y_el_conteo_exactos(self):
        self.obligacion(self.cat_arriendo, 800000)
        self.obligacion(self.cat_nomina, 1200000, tienda_id=self.t1.id)

        r = self.pl()["resumen"]
        self.assertEqual(r["costos_fijos_devengados"], 2000000)
        self.assertEqual(r["n_costos_fijos"], 2)
        self.assertIs(r["tiene_costos_fijos"], True)
        # Y siguen contando como gasto: el campo declara, no suma aparte.
        self.assertEqual(r["gastos"], 2050000)

    # ── 3. Solo 'fijo': una categoría variable no da cobertura ───────────────

    def test_una_obligacion_variable_no_cuenta_como_costo_fijo(self):
        self.obligacion(self.cat_mantenimiento, 300000)

        r = self.pl()["resumen"]
        self.assertEqual(r["costos_fijos_devengados"], 0)
        self.assertEqual(r["n_costos_fijos"], 0)
        self.assertIs(r["tiene_costos_fijos"], False)
        # Pero sí es gasto del período: cobertura ≠ plata.
        self.assertEqual(r["gastos"], 350000)

    # ── 4. Lo que no está devengado en el período no da cobertura ────────────

    def test_una_obligacion_fija_de_otro_mes_no_da_cobertura_de_este(self):
        self.obligacion(self.cat_arriendo, 800000,
                        devengo=hoy_col() - timedelta(days=45))
        r = self.pl()["resumen"]
        self.assertIs(r["tiene_costos_fijos"], False)
        self.assertEqual(r["costos_fijos_devengados"], 0)
        self.assertEqual(r["gastos"], 50000)   # tampoco entró al gasto de hoy

    def test_una_obligacion_fija_anulada_no_da_cobertura(self):
        self.obligacion(self.cat_arriendo, 800000, anulada=True)
        r = self.pl()["resumen"]
        self.assertIs(r["tiene_costos_fijos"], False)
        self.assertEqual(r["costos_fijos_devengados"], 0)

    # ── 5. Coherente con el filtro de sede ───────────────────────────────────

    def test_filtrando_por_sede_la_corporativa_no_da_cobertura_a_esa_sede(self):
        # Mismo criterio que `gastos`: con sede filtrada, la corporativa no se cuela
        # ni se prorratea. Si diera cobertura, la vista de una sede afirmaría estar
        # mirando un arriendo que su propio margen no resta.
        self.obligacion(self.cat_arriendo, 800000)                      # corporativa
        self.obligacion(self.cat_nomina, 1200000, tienda_id=self.t1.id)  # de la sede

        global_ = self.pl()["resumen"]
        self.assertEqual(global_["costos_fijos_devengados"], 2000000)
        self.assertEqual(global_["n_costos_fijos"], 2)

        sede = self.pl(tienda_id=self.t1.id)["resumen"]
        self.assertEqual(sede["costos_fijos_devengados"], 1200000)
        self.assertEqual(sede["n_costos_fijos"], 1)
        self.assertIs(sede["tiene_costos_fijos"], True)

    # ── 6. El campo es ADITIVO: no movió un peso de lo viejo ─────────────────

    def test_el_campo_nuevo_no_cambia_ningun_total_existente(self):
        antes = self.pl()["resumen"]
        self.obligacion(self.cat_arriendo, 800000)
        despues = self.pl()["resumen"]

        # Lo que cambia es lo que TIENE que cambiar (hay un gasto nuevo)…
        # assertAlmostEqual y no assertEqual: el margen sale de una división
        # (la venta neta) y restarle 800000 en el test arrastra ruido de punto
        # flotante que el código ya redondeó. Comparar floats con == es pedirle
        # al test que falle por un decimal decimoquinto.
        self.assertAlmostEqual(despues["gastos"], antes["gastos"] + 800000, places=2)
        self.assertAlmostEqual(despues["margen_neto"], antes["margen_neto"] - 800000,
                               places=2)
        # …y nada más: ventas, compras y margen bruto no dependen de los fijos.
        self.assertAlmostEqual(despues["ventas"], antes["ventas"], places=2)
        self.assertAlmostEqual(despues["compras"], antes["compras"], places=2)
        self.assertAlmostEqual(despues["margen_bruto"], antes["margen_bruto"], places=2)
        # El % de margen neto sigue derivándose del margen neto, no del campo
        # nuevo. La base es la venta NETA (sin impoconsumo), que es la misma que
        # usa el margen: con bases distintas el % no describiría a su numerador.
        self.assertAlmostEqual(
            despues["pct_margen_neto"],
            round(despues["margen_neto"] / despues["venta_neta"] * 100, 1))


if __name__ == "__main__":
    unittest.main()
