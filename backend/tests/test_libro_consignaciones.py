"""Las consignaciones entran SOLAS al libro del banco, cada una en su día.

La excepción medida a la regla «el libro no deduce»: una consignación ES un
hecho bancario — el comprobante es la boleta del depósito, sin rezago ni
comisión que adivinar (Bold sigue tecleado, su regla no cambia). Es la columna
OCCIDENTE de la hoja del dueño, que hoy se teclea dos veces: una cuando la
barista registra la consignación y otra cuando él la copia al libro.

Las reglas que este archivo fija:

- SIN el corte activado, nada cambia: el libro es 100% tecleado, como siempre.
- El corte se fija UNA VEZ (como el ancla de las recogidas): moverlo hacia
  atrás duplicaría contra lo tecleado, hacia adelante haría desaparecer plata.
- La proyección entra a la CADENA (`_neto_hasta`), así que el libro, la serie
  y cualquier saldo derivado dicen lo mismo — sumar solo en la vista era la
  receta para dos números distintos de la misma pregunta.
- El día es el día COLOMBIA de la consignación (las 19:30 de Cali son las
  00:30 UTC del día siguiente; ubicarla por UTC la corría de día).
- Una consignación sin fecha NO se ubica en un día inventado: se cuenta y se
  dice en `consignaciones_sin_fecha`.
- La activación tiene vista previa con las DOS mitades medidas: lo que entra
  solo y lo ya tecleado que quedaría doble. Nunca un interruptor a ciegas.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base
from app.models.models import (Consignacion, EstadoConsignacionEnum, RolEnum,
                               Tienda, Usuario)
from app.services import banco as banco_svc
from app.services.banco import (activar_consignaciones, libro,
                                preview_consignaciones, registrar,
                                saldo_al_cierre, sembrar_cuentas, serie_mensual)


class LibroConsignacionesBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.vida)
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()
        sembrar_cuentas(self.db)
        self.occidente = self.db.query(banco_svc.CuentaBancaria).filter_by(
            nombre="Occidente").first()
        self.bold = self.db.query(banco_svc.CuentaBancaria).filter_by(
            nombre="Bold").first()

        self.hoy = hoy_col()
        self.d1 = self.hoy - timedelta(days=6)   # el «día 1» del escenario

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def dia(self, delta):
        return self.d1 + timedelta(days=delta)

    def consignar(self, valor, dia, *, hora_col=12, estado=None, fecha_null=False):
        c = Consignacion(
            tienda_id=self.vida.id, caja_turno_id=None, valor=valor,
            usuario_id=self.admin.id,
            estado=estado or EstadoConsignacionEnum.realizada,
            fecha=inicio_dia_col_utc(dia) + timedelta(hours=hora_col),
        )
        self.db.add(c)
        self.db.commit()
        if fecha_null:
            # El default del modelo pisa un None en el INSERT: la fila legacy
            # sin fecha se fabrica con un UPDATE, que es como existen en la
            # base real.
            c.fecha = None
            self.db.commit()
        return c

    def ancla(self, saldo, fecha):
        from app.services.costos import guardar_saldo_banco
        guardar_saldo_banco(self.db, saldo, fecha, self.admin.id)

    def activar(self, desde=None):
        return activar_consignaciones(self.db, desde or self.d1)

    def fila(self, dia):
        l = libro(self.db, dia, dia)
        return l["dias"][0]


class SinActivarNadaCambiaTest(LibroConsignacionesBase):

    def test_sin_corte_el_libro_no_proyecta_nada(self):
        self.consignar(790700, self.dia(0))
        f = self.fila(self.dia(0))
        self.assertEqual(f["total_entradas"], 0)
        self.assertEqual(f["consignaciones"], [])
        l = libro(self.db, self.dia(0), self.dia(0))
        self.assertIsNone(l["consignaciones_desde"])


class ProyeccionTest(LibroConsignacionesBase):

    def test_cada_consignacion_entra_en_su_dia_como_occidente(self):
        """El día 1 de julio del dueño: seis consignaciones, una columna."""
        self.activar()
        for v in (790700, 442100, 190300, 849500, 658150, 770500):
            self.consignar(v, self.dia(0))

        f = self.fila(self.dia(0))
        self.assertEqual(f["entradas"], {"Occidente": 3_701_250})
        self.assertEqual(f["total_entradas"], 3_701_250)
        self.assertEqual(len(f["consignaciones"]), 6)
        # Y no están mezcladas con lo tecleado: son otra lista, sin botón de
        # borrar del libro.
        self.assertEqual(f["movimientos"], [])

    def test_la_proyeccion_entra_a_la_cadena_del_saldo(self):
        """Con ancla el día 1 y una consignación el día 2, el cierre del día 3
        la trae — por `_neto_hasta`, no por una suma de la vista."""
        self.ancla(2_025_023, self.d1)
        self.activar()
        self.consignar(500_000, self.dia(1))

        cierre, cadena = saldo_al_cierre(self.db, self.dia(2))
        self.assertTrue(cadena)
        self.assertEqual(cierre, 2_525_023)
        # Y el libro dice lo mismo (misma cadena, no otra cuenta).
        self.assertEqual(self.fila(self.dia(2))["final"], 2_525_023)

    def test_conviven_con_lo_tecleado_del_mismo_dia(self):
        """Bold sigue tecleado: el día suma las dos fuentes, cada una en su
        columna — como la hoja."""
        self.activar()
        self.consignar(2_202_100, self.dia(1))
        registrar(self.db, self.dia(1), self.bold.id, "entrada", 1_410_000,
                  "Liquidación Bold", usuario_id=self.admin.id)

        f = self.fila(self.dia(1))
        self.assertEqual(f["entradas"],
                         {"Occidente": 2_202_100, "Bold": 1_410_000})
        self.assertEqual(len(f["movimientos"]), 1)
        self.assertEqual(len(f["consignaciones"]), 1)

    def test_anterior_al_corte_no_entra(self):
        """Lo de antes del corte ya está tecleado (o no está): proyectarlo lo
        contaría dos veces."""
        self.activar(desde=self.dia(2))
        self.consignar(999_999, self.dia(1))
        self.assertEqual(self.fila(self.dia(1))["total_entradas"], 0)

    def test_la_frontera_del_dia_es_colombia_no_utc(self):
        """19:30 de Cali = 00:30 UTC del día siguiente. La consignación de la
        noche pertenece al día en que se hizo, no al de Greenwich."""
        self.activar()
        self.consignar(300_000, self.dia(1), hora_col=19.5)
        self.assertEqual(self.fila(self.dia(1))["total_entradas"], 300_000)
        self.assertEqual(self.fila(self.dia(2))["total_entradas"], 0)

    def test_pendiente_y_realizada_entran_por_igual(self):
        """La pendiente es un depósito afirmado con comprobante que el admin no
        confirmó: su plata YA está en el banco. El estado viaja en la fila."""
        self.activar()
        self.consignar(100_000, self.dia(0),
                       estado=EstadoConsignacionEnum.pendiente)
        f = self.fila(self.dia(0))
        self.assertEqual(f["total_entradas"], 100_000)
        self.assertEqual(f["consignaciones"][0]["estado"], "pendiente")

    def test_sin_fecha_no_se_ubica_en_un_dia_inventado(self):
        self.activar()
        self.consignar(555_000, self.dia(0), fecha_null=True)
        l = libro(self.db, self.d1, self.dia(3))
        self.assertTrue(all(f["total_entradas"] == 0 for f in l["dias"]))
        self.assertEqual(l["consignaciones_sin_fecha"],
                         {"n": 1, "total": 555_000})

    def test_la_serie_mensual_dice_lo_mismo_que_el_libro(self):
        self.activar()
        self.consignar(500_000, self.dia(0))
        serie = serie_mensual(self.db, self.dia(0).year)
        mes = next(m for m in serie["meses"] if m["mes"] == self.dia(0).month)
        self.assertGreaterEqual(mes["entradas"], 500_000)


class ActivacionTest(LibroConsignacionesBase):

    def test_la_vista_previa_mide_las_dos_mitades(self):
        self.consignar(790_700, self.dia(0))
        self.consignar(442_100, self.dia(1))
        # Lo que él ya tecleó en ese rango: quedaría contado dos veces.
        registrar(self.db, self.dia(0), self.occidente.id, "entrada", 790_700,
                  "Consignación", usuario_id=self.admin.id)

        p = preview_consignaciones(self.db, self.d1)
        self.assertEqual(p["consignaciones"], {"n": 2, "total": 1_232_800})
        self.assertEqual(p["tecleadas_en_rango"]["n"], 1)
        self.assertEqual(p["tecleadas_en_rango"]["total"], 790_700)
        self.assertIsNone(p["ya_activado_desde"])

    def test_el_corte_se_fija_una_vez_y_no_se_mueve(self):
        self.activar()
        with self.assertRaises(ValueError) as ctx:
            self.activar(desde=self.dia(3))
        self.assertIn("no se mueve", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
