"""LA PLATA DEL DÍA ANTERIOR PEDIDA DOS VECES.

Al abrir, la barista marca de qué días es la plata que hay en el cajón — el
`saldos_incluidos` que diseñó el dueño. Si se olvida de marcar el día anterior,
el sistema espera $0, ve esa plata y la anota como SOBRANTE del día nuevo. Y esa
misma plata queda pedida dos veces: una en su día, que sigue pendiente, y otra
adentro del día siguiente.

Palmetto, martes 18 de agosto: pedía consignar $416.800 cuando la venta en
efectivo del día fue $260.115. Los otros $156.685 eran del domingo 16, que en la
misma pantalla seguía mostrando $156.700 por consignar. Consignando los dos se
mandaban al banco $573.500 con $416.800 en el cajón.

Corregirlo es REHACER LA SELECCIÓN, no inventar otra cuenta. Y `base_real` se
queda en lo que de verdad se contó: esa plata SÍ estaba en el cajón, así que
ponerla en cero daría el número correcto mintiendo sobre lo que había.
"""
import unittest

from tests.base_cuadre import CuadreCajaBase
from app.services import caja as svc


class LaPlataDelDiaAnteriorTest(CuadreCajaBase):

    def _domingo_y_martes(self):
        """El domingo deja $156.685 sin consignar; el martes abre con esa plata
        en el cajón y la barista NO la marca."""
        domingo, martes = self.dia(-3), self.dia(-1)

        dom = self.abrir(base_real=0, momento=self.momento(domingo, 8))
        self.vender_efectivo(dom, 156_685)
        self.cerrar(dom, contado=156_685, momento=self.momento(domingo, 19))

        # Abre sin marcar el domingo: el sistema espera $0 y ve $156.685.
        mar = self.abrir(base_real=156_685, momento=self.momento(martes, 8))
        mar.base_sistema = 0
        mar.diferencia_apertura = 156_685
        mar.sobrante_consignable = 156_685
        self.db.commit()
        self.vender_efectivo(mar, 260_115)
        self.cerrar(mar, contado=156_685 + 260_115, momento=self.momento(martes, 19))
        return dom, mar

    def test_la_misma_plata_queda_pedida_dos_veces(self):
        """El estado de HOY, para que se vea que el test mide el caso real."""
        dom, mar = self._domingo_y_martes()
        self.assertEqual(self.consignable(dom), 156_685)
        self.assertEqual(self.consignable(mar), 416_800)
        # $573.485 pedidos con $416.800 en el cajón.
        self.assertEqual(self.consignable(dom) + self.consignable(mar), 573_485)

    def test_rehacer_la_seleccion_deja_el_martes_en_su_venta(self):
        """EL NÚMERO que pidió el dueño: el martes vale su venta y nada más."""
        dom, mar = self._domingo_y_martes()
        svc.ajustar_apertura(self.db, mar.id, base_real=156_685, caja_fuerte=None,
                             usuario_id=self.admin.id,
                             motivo="La plata del cajón era del domingo",
                             saldos_incluidos=[dom.id])
        self.db.refresh(mar)
        self.assertEqual(mar.sobrante_consignable, 0)
        self.assertEqual(self.consignable(mar), 260_115)

    def test_y_el_domingo_conserva_la_suya(self):
        """La otra mitad: corregir el martes no le puede sacar la plata al domingo."""
        dom, mar = self._domingo_y_martes()
        svc.ajustar_apertura(self.db, mar.id, base_real=156_685, caja_fuerte=None,
                             usuario_id=self.admin.id, motivo="era del domingo",
                             saldos_incluidos=[dom.id])
        self.assertEqual(self.consignable(dom), 156_685)

    def test_la_base_real_no_se_falsea(self):
        """Esa plata estaba en el cajón. `base_real` tiene que seguir diciendolo:
        el arreglo es la SELECCION, no borrar el conteo."""
        dom, mar = self._domingo_y_martes()
        svc.ajustar_apertura(self.db, mar.id, base_real=156_685, caja_fuerte=None,
                             usuario_id=self.admin.id, motivo="era del domingo",
                             saldos_incluidos=[dom.id])
        self.db.refresh(mar)
        self.assertEqual(mar.base_real, 156_685)
        self.assertEqual(mar.base_sistema, 156_685)

    def test_sin_pasar_seleccion_no_se_toca(self):
        """`None` deja la selección como está: una corrección de la caja fuerte
        no puede rehacer de qué días era la plata sin que nadie lo pida."""
        dom, mar = self._domingo_y_martes()
        svc.ajustar_apertura(self.db, mar.id, base_real=156_685, caja_fuerte=None,
                             usuario_id=self.admin.id, motivo="otra cosa")
        self.db.refresh(mar)
        self.assertEqual(mar.base_sistema, 0)


if __name__ == "__main__":
    unittest.main()
