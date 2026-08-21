"""El candado de la nómina parcial.

El bug medido: una obligación de nómina devengada en un mes apaga el cálculo del
mes ENTERO («si el mes tiene nómina cargada a mano, gana la mano»,
rentabilidad._nomina_del_periodo) sin mirar el monto. Cargar una «Nómina
quincena» de la mitad dejaba el costo laboral del mes en la mitad y el margen se
veía mejor de lo que está — el error mudo y tranquilizador de siempre.

La regla: un monto de nómina a mano por debajo de 3/5 del cálculo del mes rebota
con 400 legible. El corte no es caprichoso: una quincena es la MITAD exacta y la
liquidación real del contador difiere del cálculo por puntos (retención,
embargos, redondeo de PILA), no por mitades. Más alta entra siempre — la misma
asimetría que el quinto del impoconsumo.
"""
import unittest
from datetime import date

from fastapi import HTTPException

from app.schemas.costos import ObligacionCreate, ObligacionUpdate
from app.services import costos as svc
from app.services.costos import _nomina_calculada_del_mes

from tests.test_nomina_agendada import _Planilla, ANIO, MES, ULTIMO


def _crear(db, admin_id, cat_id, monto, devengo, concepto="Nómina quincena"):
    return svc.crear_obligacion(db, ObligacionCreate(
        categoria_id=cat_id, concepto=concepto, monto=monto,
        fecha_devengo=devengo), admin_id)


class NominaParcialTest(_Planilla):

    def setUp(self):
        super().setUp()
        self.calculada = _nomina_calculada_del_mes(self.db, ANIO, MES)
        # El guardián del escenario: sin cálculo > 0 estos tests no prueban nada.
        self.assertGreater(self.calculada, 0)

    def test_la_quincena_rebota_con_el_motivo_y_las_cifras(self):
        quincena = round(self.calculada / 2, 2)
        with self.assertRaises(HTTPException) as ctx:
            _crear(self.db, self.admin.id, self.cat_nomina.id, quincena, ULTIMO)
        self.assertEqual(ctx.exception.status_code, 400)
        detalle = ctx.exception.detail
        self.assertIsInstance(detalle, str)
        # Las dos cifras a la vista: lo escrito y lo calculado.
        self.assertIn(f"${quincena:,.0f}", detalle)
        self.assertIn(f"${self.calculada:,.0f}", detalle)
        # Y nada quedó creado.
        self.db.rollback()
        from app.models.models import Obligacion
        self.assertEqual(self.db.query(Obligacion).count(), 0)

    def test_la_liquidacion_completa_del_contador_entra(self):
        """Un poco más baja que el cálculo es lo normal (el cálculo es un
        estimado declarado): entra sin drama."""
        contador = round(self.calculada * 0.9, 2)
        r = _crear(self.db, self.admin.id, self.cat_nomina.id, contador, ULTIMO,
                   concepto=f"Nómina agosto {ANIO}")
        self.assertEqual(r["monto"], contador)

    def test_mas_alta_que_el_calculo_entra_siempre(self):
        r = _crear(self.db, self.admin.id, self.cat_nomina.id,
                   round(self.calculada * 1.3, 2), ULTIMO,
                   concepto=f"Nómina agosto {ANIO}")
        self.assertGreater(r["monto"], self.calculada)

    def test_otra_categoria_no_pasa_por_el_candado(self):
        """El arriendo puede valer lo que sea: el candado es de la nómina."""
        r = _crear(self.db, self.admin.id, self.cat_arriendo.id, 10_000, ULTIMO,
                   concepto="Arriendo bodega")
        self.assertEqual(r["monto"], 10_000)

    def test_un_mes_sin_calculo_deja_pasar_la_mano(self):
        """Sin contratos ni turnos no hay contra qué comparar: la mano es la
        única fuente y bloquearla dejaría el mes sin nómina posible."""
        # La proyección sale de los CONTRATOS, así que el caso «sin cálculo» se
        # arma sin ninguno: es el estado de una base recién montada, antes de
        # cargar sueldos.
        from app.models.models import ContratoBarista
        self.db.query(ContratoBarista).delete()
        self.db.commit()
        lejos = date(ANIO + 1, 3, 31)
        self.assertEqual(_nomina_calculada_del_mes(self.db, ANIO + 1, 3), 0)
        r = _crear(self.db, self.admin.id, self.cat_nomina.id, 500_000, lejos)
        self.assertEqual(r["monto"], 500_000)

    def test_editar_hacia_una_quincena_tambien_rebota(self):
        """El mismo agujero por la puerta de al lado: crear completa y después
        bajarle el monto a la mitad."""
        r = _crear(self.db, self.admin.id, self.cat_nomina.id,
                   self.calculada, ULTIMO, concepto=f"Nómina agosto {ANIO}")
        with self.assertRaises(HTTPException) as ctx:
            svc.editar_obligacion(self.db, r["id"], ObligacionUpdate(
                monto=round(self.calculada / 2, 2)), self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_editar_la_nota_no_liquida_el_mes_de_nuevo(self):
        """La edición inocente no paga el costo del candado: sin tocar monto,
        categoría ni devengo, no hay nada nuevo que validar."""
        r = _crear(self.db, self.admin.id, self.cat_nomina.id,
                   self.calculada, ULTIMO, concepto=f"Nómina agosto {ANIO}")
        out = svc.editar_obligacion(self.db, r["id"], ObligacionUpdate(
            nota="la liquidación llegó por correo"), self.admin.id)
        self.assertEqual(out["nota"], "la liquidación llegó por correo")

    def test_agendar_con_monto_de_quincena_rebota_igual(self):
        """El botón «Agendar la nómina» acepta un monto a mano; una quincena
        entra igual de callada por ahí y apaga el mismo mes."""
        with self.assertRaises(HTTPException) as ctx:
            svc.agendar_nomina(self.db, ANIO, MES, self.admin.id,
                               monto=round(self.calculada / 2, 2))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("quincena", ctx.exception.detail)

    def test_agendar_sin_monto_sigue_andando(self):
        r = svc.agendar_nomina(self.db, ANIO, MES, self.admin.id)
        self.assertEqual(r["monto"], self.calculada)


if __name__ == "__main__":
    unittest.main()
