"""CORREGIR LA APERTURA TIENE QUE LLEGAR HASTA EL CONSIGNABLE.

El caso real: Palmetto, sábado 15 de agosto. Al abrir el turno la barista declaró
que tenía en el cajón la BASE MÁS la venta del día anterior, cuando solo tenía que
elegir la venta. La base nunca salió de la caja fuerte — fue un error de carga, no
un movimiento de plata.

Ese error dejó $500.000 de `sobrante_consignable` y el día pasó a pedir $697.900
en vez de $197.900. `ajustar_apertura` existe justamente para esto (su docstring
dice «corregir errores como meter la caja fuerte dentro de la base»), pero
recalculaba `diferencia_apertura` y NO `sobrante_consignable`, que es la columna
que lee la fórmula del consignable.

O sea: una corrección que parecía completa y no lo era. El admin arreglaba la
apertura, la pantalla del cuadre quedaba bien, y Consignaciones seguía pidiendo el
sobrante viejo. Es la familia de error de siempre —un número que quedó cerca del
correcto— por el camino más traicionero: el de la herramienta que existe PARA
corregir.
"""
import unittest

from tests.test_prestamo_caja_fuerte import CajaFuerteBase
from app.services import caja as svc


class AjustarAperturaLimpiaElSobranteTest(CajaFuerteBase):

    def _sabado_mal_declarado(self):
        """El sábado tal como quedó: $500.000 de sobrante por la apertura mal
        declarada, sin que ninguna plata se haya movido."""
        sabado = self.dia(-3)
        turno = self.abrir(base_real=0, momento=self.momento(sabado, 8))
        self.vender_efectivo(turno, 293_205)
        # Los dos pagos de contado de ese día: Calipulpas y Paola.
        self.egreso(turno, 45_400, self.momento(sabado, 9), concepto="Pago proveedor: Calipulpas")
        self.egreso(turno, 50_000, self.momento(sabado, 10), concepto="Pago proveedor: Paola")
        # La barista declaró que abría con la base MÁS la venta del día anterior.
        # El sistema lo lee como sobrante y lo manda a bancar.
        turno.sobrante_consignable = 500_000
        turno.diferencia_apertura = 500_000
        turno.base_real = 500_000
        self.db.commit()
        # Al cierre cuenta lo que el sistema espera con esa base adentro, así que
        # no hay diferencia de cierre: el error está SOLO en la apertura.
        # El cierre del TURNO cuenta la base adentro —`cerrar_caja` la incluye en
        # el esperado— y da los $95 de más que él tiene en pantalla. Los $197.900
        # de las 19:42 son la entrega de la barista DESPUÉS de sacar la base, que
        # es otro registro: no es este.
        self.cerrar(turno, contado=500_000 + 293_205 - 95_400 + 95,
                    momento=self.momento(sabado, 21),
                    justificacion="contó $95 de más")
        return turno

    def test_antes_de_corregir_pide_los_697900(self):
        turno = self._sabado_mal_declarado()
        self.assertEqual(self.consignable(turno), 697_900)

    def test_corregir_la_apertura_lo_deja_en_197900(self):
        """EL NÚMERO. Sin registrar ningún traslado: la base nunca se movió."""
        turno = self._sabado_mal_declarado()
        svc.ajustar_apertura(self.db, turno.id, base_real=0, caja_fuerte=None,
                             usuario_id=self.admin.id,
                             motivo="La base estaba contada dentro de la apertura")
        self.db.refresh(turno)
        self.assertEqual(turno.sobrante_consignable, 0)
        self.assertEqual(self.consignable(turno), 197_900)

    def test_un_turno_viejo_sin_sobrante_no_estrena_uno(self):
        """La columna nació nullable para no reclamar sobrantes de turnos
        anteriores al fix de jul-2026. Corregir su apertura no puede inventarle
        uno que nunca se le pidió."""
        sabado = self.dia(-3)
        turno = self.abrir(base_real=0, momento=self.momento(sabado, 8))
        self.vender_efectivo(turno, 200_000)
        turno.sobrante_consignable = None
        self.db.commit()
        self.cerrar(turno, contado=200_000, momento=self.momento(sabado, 21))

        svc.ajustar_apertura(self.db, turno.id, base_real=300_000, caja_fuerte=None,
                             usuario_id=self.admin.id, motivo="corrección")
        self.db.refresh(turno)
        self.assertIsNone(turno.sobrante_consignable)


if __name__ == "__main__":
    unittest.main()
