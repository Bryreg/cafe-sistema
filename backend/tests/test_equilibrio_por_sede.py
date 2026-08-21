"""El punto de equilibrio en TRES números: Vida, Palmetto, Corporativo.

La decisión que esto fija: POR SEDE SE EXPONE, NO SE PRORRATEA. Si cada sede
mirara solo lo suyo, las dos pasarían su piso y el negocio igual perdería plata
— el corporativo (nómina, planilla, contabilidad) pesa más que las dos sedes
juntas y no cuelga de ninguna. Repartirlo tampoco: cualquier reparto es
inventado. Es la misma decisión que `corporativas_fuera` en el P&L por sede.

Y la propiedad que hace confiable el desglose: con el MISMO divisor (el margen
del negocio entero), la suma de las tres ventas necesarias ES `piso_mes` — la
descomposición cierra por construcción y se puede verificar a ojo en pantalla.

También fija la banda del contador: retefuente y reteica están fuera del costo
del mes (la clasificación vigente del dueño) y el sesgo lo DICE con su monto y
cuánto subiría el piso — pendiente el contador, nunca elegido en silencio.
"""
import unittest

from app.models.models import Tienda
from app.services import costos as svc

from tests.test_piso_venta import PisoBase


class EquilibrioPorSedeTest(PisoBase):

    def setUp(self):
        super().setUp()
        # La segunda sede, y las cuentas de julio del dueño (redondeadas):
        # Vida y Palmetto con su arriendo, y el bloque corporativo que pesa
        # más que las dos juntas.
        self.palmetto = Tienda(nombre="Palmetto", direccion="y")
        self.db.add(self.palmetto)
        self.db.commit()

        self.ob_vida = self.obligacion(5_759_820, self.dia1)
        self.ob_vida.tienda_id = self.tienda.id
        self.ob_palmetto = self.obligacion(8_615_464, self.dia1)
        self.ob_palmetto.tienda_id = self.palmetto.id
        self.obligacion(19_374_980, self.dia1)   # corporativa (tienda_id None)
        self.db.commit()

    def por_sede(self, piso=None):
        return (piso or self.piso())["por_sede"]

    def test_los_tres_numeros_sin_prorratear(self):
        ps = self.por_sede()
        fijos = {s["nombre"]: s["costos_fijos"] for s in ps["sedes"]}
        self.assertEqual(fijos["Vida"], 5_759_820)
        self.assertEqual(fijos["Palmetto"], 8_615_464)
        self.assertEqual(ps["corporativo"]["costos_fijos"], 19_374_980)
        # El corporativo pesa más que las dos sedes juntas ($14,4M): el 57% de
        # la estructura no cuelga de ninguna sede. Por eso se expone.
        self.assertGreater(ps["corporativo"]["costos_fijos"],
                           fijos["Vida"] + fijos["Palmetto"])

    def test_la_suma_de_las_ventas_necesarias_es_el_piso(self):
        """La garantía de consistencia. Con margen (ventas + costeo cargados),
        X + Y + Z == piso_mes al centavo de redondeo."""
        prod = self.producto(precio=10_000, costo=3_000)
        self.venta(self.hoy, 200_000, producto=prod)
        self.historia_de_ventas()

        piso = self.piso()
        self.assertIsNotNone(piso["piso_mes"], piso["puerta"])
        ps = self.por_sede(piso)
        partes = ([s["venta_necesaria"] for s in ps["sedes"]]
                  + [ps["corporativo"]["venta_necesaria"]])
        self.assertTrue(all(p is not None for p in partes))
        self.assertAlmostEqual(sum(partes), piso["piso_mes"], delta=0.05)

    def test_sin_margen_los_fijos_viajan_y_la_venta_necesaria_no_se_inventa(self):
        piso = self.piso()
        self.assertIsNone(piso["piso_mes"])
        ps = self.por_sede(piso)
        self.assertEqual(ps["corporativo"]["costos_fijos"], 19_374_980)
        self.assertIsNone(ps["corporativo"]["venta_necesaria"])
        self.assertTrue(all(s["venta_necesaria"] is None for s in ps["sedes"]))

    def test_el_avance_es_por_sede_y_el_corporativo_no_tiene(self):
        prod = self.producto(precio=10_000, costo=3_000)
        self.venta(self.hoy, 500_000, producto=prod)   # venta de Vida
        self.historia_de_ventas()

        ps = self.por_sede()
        vida = next(s for s in ps["sedes"] if s["nombre"] == "Vida")
        palmetto = next(s for s in ps["sedes"] if s["nombre"] == "Palmetto")
        self.assertGreater(vida["ventas_mes"], 0)
        self.assertIsNotNone(vida["avance_pct"])
        # Palmetto no vendió: su avance es 0, medido — no ausente.
        self.assertEqual(palmetto["ventas_mes"], 0)
        self.assertEqual(palmetto["avance_pct"], 0.0)
        # El corporativo no vende: su avance NO EXISTE, no es cero.
        self.assertIsNone(ps["corporativo"]["ventas_mes"])
        self.assertIsNone(ps["corporativo"]["avance_pct"])


class BandaDelContadorTest(PisoBase):

    def sesgo(self, piso=None):
        p = piso or self.piso()
        return next(s for s in p["sesgos"]
                    if s["clave"] == "retenciones_fuera_del_gasto")

    def test_sin_retenciones_el_sesgo_existe_apagado(self):
        """La clave viaja siempre: una pantalla vieja la ignora, la nueva no
        tiene que adivinar si el backend la conoce."""
        s = self.sesgo()
        self.assertFalse(s["activo"])
        self.assertEqual(s["detalle"]["monto_mes"], 0)

    def test_con_retenciones_dice_el_monto_y_cuanto_subiria(self):
        svc.sembrar_categorias(self.db)
        cat_rf = next(c for c in self.db.query(svc.CostoCategoria).all()
                      if c.clave == "retefuente")
        cat_ri = next(c for c in self.db.query(svc.CostoCategoria).all()
                      if c.clave == "reteica")
        self.obligacion(625_000, self.dia1, categoria=cat_rf)
        self.obligacion(145_000, self.dia1, categoria=cat_ri)
        # Con margen, el sesgo puede decir cuánto subiría el piso.
        prod = self.producto(precio=10_000, costo=3_000)
        self.venta(self.hoy, 200_000, producto=prod)
        self.historia_de_ventas()

        piso = self.piso()
        s = self.sesgo(piso)
        self.assertTrue(s["activo"])
        self.assertEqual(s["detalle"]["monto_mes"], 770_000)
        # $770.000/mes de diferencia en el punto de equilibrio, dividida por el
        # mismo margen que el piso — la advertencia habla en la misma unidad.
        self.assertAlmostEqual(
            s["detalle"]["subiria_piso"],
            770_000 / piso["margen_contribucion"], delta=0.05)
        # Y el piso publicado NO las cuenta: la clasificación vigente manda.
        self.assertNotIn("retefuente",
                         [c["clave"] for c in piso["costos_fijos"]["por_categoria"]])


if __name__ == "__main__":
    unittest.main()
