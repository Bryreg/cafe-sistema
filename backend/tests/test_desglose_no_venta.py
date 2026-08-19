"""LOS CINCO TÉRMINOS DE LA FÓRMULA TIENEN QUE PODER VERSE, los cinco.

El consignable del dueño es

    ventas + ingresos de caja − egresos + diferencia de cierre + sobrante de apertura

y hasta acá `sobrante_consignable` no se exponía en NINGUNA parte: ni en la
respuesta del backend, ni en la pantalla, ni abriendo la fila. El dueño miraba un
martes que pedía $416.800 con $260.115 de venta y no tenía cómo averiguar de
dónde salían los $156.685 de diferencia.

Un número que no se puede auditar es un número al que no se le puede creer, y esa
es la familia de error que este módulo viene matando. Estos tests fijan que los
sumandos estén a la vista y que cuadren contra el total.
"""
import unittest

from tests.test_cascada_consignaciones import CascadaBase
from app.services import consignaciones as consig_svc


class DesgloseDeLoQueNoEsVentaTest(CascadaBase):

    def fila(self, turno):
        return next(f for f in consig_svc.get_resumen_admin(self.db, turno.tienda_id)
                    if f["turno_id"] == turno.id)

    def test_un_dia_limpio_no_tiene_nada_que_no_sea_venta(self):
        """El día normal: el desglose da cero y la pantalla no lo muestra."""
        t = self.jornada(self.dia(-1), en_caja=0, venta=300_000)
        f = self.fila(t)
        self.assertEqual(f["sobrante_apertura"], 0)
        self.assertEqual(f["en_cajon_no_es_venta"], 0)
        self.assertEqual(f["esperado_consignar"], 300_000)

    def test_el_sobrante_de_apertura_deja_de_ser_invisible(self):
        """EL TÉRMINO QUE NO SE VEÍA. Es el que explicaba el martes del dueño."""
        t = self.jornada(self.dia(-1), en_caja=0, venta=260_115)
        t.sobrante_consignable = 156_685
        self.db.commit()

        f = self.fila(t)
        self.assertEqual(f["sobrante_apertura"], 156_685)
        self.assertEqual(f["en_cajon_no_es_venta"], 156_685)
        # Y el total sigue siendo el de su fórmula: nada cambió de la cuenta.
        self.assertEqual(f["esperado_consignar"], 260_115 + 156_685)

    def test_los_sumandos_cuadran_contra_el_total(self):
        """La invariante que hace auditable la fila: si el desglose no cierra
        contra el esperado, alguno de los dos está mintiendo."""
        t = self.jornada(self.dia(-1), en_caja=0, venta=200_000, pagado=30_000)
        t.sobrante_consignable = 50_000
        t.diferencia_cierre = 10_000
        self.db.commit()

        f = self.fila(t)
        self.assertEqual(
            round(f["total_efectivo"] - f["total_egresos"] + f["en_cajon_no_es_venta"], 2),
            f["esperado_consignar"])


if __name__ == "__main__":
    unittest.main()
