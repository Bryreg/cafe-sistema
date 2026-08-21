"""LOS DESECHABLES ADENTRO DEL COSTO DE LA BEBIDA.

Era uno de los CUATRO SESGOS que el piso de venta declaraba de sí mismo: «los
desechables no están dentro del costo de la bebida». El vaso, la tapa, la
servilleta y el azúcar de cada bebida para llevar quedaban afuera del costo
SIEMPRE —no por un dato que faltara, sino por cómo estaba armado el cálculo— y
como todos los sesgos de este piso, empujaba para el lado tranquilizador: menos
costo, más margen, piso más bajo.

Lo que fija este archivo:

1. LA DIRECCIÓN, ANTES QUE NADA. Sumar los desechables SUBE el costo, BAJA el
   margen y SUBE el piso. Si al meterlos el piso bajara, algo se restó donde
   había que sumar — y sería el mismo error tranquilizador, ahora con un test
   verde encima.
2. EL VASO NO SE CUENTA DOS VECES. El P&L sigue publicando `cogs_teorico` SIN
   desechables porque su término de fuga (medida por conteo físico) ya se lleva
   esos vasos: el desechable no descuenta inventario al vender. El piso, que no
   tiene término de fuga, usa `cogs_con_desechables`. Los dos salen de la MISMA
   medición y viajan juntos.
3. EL SESGO SE APAGA POR COBERTURA, NO POR DECRETO. Con el 12% de la venta con
   empaque cargado, el costo del vaso sigue casi todo afuera: el sesgo sigue
   vivo y lo dice. Solo se apaga cuando toda la venta medida tiene sus
   desechables cargados.
4. LA COBERTURA DE SEDES PUEDE DAR CERO, Y CERO ES EL PEOR CASO. La sede que
   cierra el conteo no siempre es la que vendió. Cuando la intersección da 0 de
   1, el residuo no lleva adentro un solo vaso de los que se sirvieron — y es
   justo el estado en el que una pantalla que pide «más de cero» se calla.
"""
import unittest
from datetime import timedelta

from app.models.models import (CajaTurno, CategoriaProductoEnum,
                               EstadoTurnoEnum, FacturaCompra,
                               FacturaCompraItem, Inventario, InventarioMensual,
                               InventarioMensualItem, MovimientoInventario,
                               Producto, ProductoDesechable, ProductoInsumo,
                               Ticket, TicketItem, Tienda, TipoMovInvEnum,
                               TipoPagoEnum)
from app.services import costos as costos_svc
from app.services.rentabilidad import get_rentabilidad
from tests.test_piso_venta import PisoBase, mediodia


class DesechablesBase(PisoBase):
    """Un latte con receta de leche y, cuando el test lo pide, su vaso.

    Números elegidos para poder verificar el piso a mano:
      leche  $2,50/ml × 100 ml = $250 de receta por latte
      vaso   $200 la unidad × 1 = $200 de empaque por latte
      10 lattes a $10.000 = $100.000 de venta en el mes
    """
    COSTO_LECHE = 2.5
    ML_POR_LATTE = 100.0
    COSTO_VASO = 200.0
    PRECIO_LATTE = 10_000.0
    UNIDADES = 10
    ARRIENDO = 9_000_000.0

    def insumo(self, nombre, unidad, costo):
        """Insumo con costo cargado por factura (no oficial: es el camino real)."""
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, precio_venta=0)
        self.db.add(p)
        self.db.flush()
        f = FacturaCompra(tienda_id=self.tienda.id, proveedor="Proveedor X",
                          valor_total=100 * costo, valor_pagado=0,
                          tipo_pago=TipoPagoEnum.credito, usuario_id=self.admin.id,
                          fecha_recibido=mediodia(self.hoy))
        self.db.add(f)
        self.db.flush()
        self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=p.id,
                                      cantidad=100, precio_unitario=costo))
        self.db.commit()
        return p

    def escenario(self):
        self.leche = self.insumo("Leche entera", "ml", self.COSTO_LECHE)
        self.vaso = self.insumo("Vaso 12 oz", "unidad", self.COSTO_VASO)
        self.latte = self.producto("Latte", precio=self.PRECIO_LATTE)
        self.db.add(ProductoInsumo(producto_id=self.latte.id, insumo_id=self.leche.id,
                                   cantidad=self.ML_POR_LATTE))
        self.db.commit()
        self.obligacion(self.ARRIENDO, self.fin_mes)
        self.historia_de_ventas()
        for _ in range(self.UNIDADES):
            self.venta(self.hoy, self.PRECIO_LATTE, producto=self.latte)

    def cargar_el_vaso(self, producto=None, cantidad=1.0):
        self.db.add(ProductoDesechable(producto_id=(producto or self.latte).id,
                                       insumo_id=self.vaso.id, cantidad=cantidad))
        self.db.commit()

    def sesgo(self, clave, piso=None):
        piso = piso or self.piso()
        return next(s for s in piso["sesgos"] if s["clave"] == clave)


class ElVasoEntraAlCostoTest(DesechablesBase):

    def test_meter_los_desechables_sube_el_piso_no_lo_baja(self):
        """LA DIRECCIÓN, medida sobre el mismo mes con y sin el vaso cargado.

        Sin vaso: mercadería = $2.500 sobre $100.000 = 2,5% de cada peso.
        Con vaso: $2.500 + $2.000 = $4.500 = 4,5%. El margen baja dos puntos y el
        piso —que es costos fijos DIVIDIDO ese margen— sube.
        """
        self.escenario()
        sin_vaso = self.piso()
        self.cargar_el_vaso()
        con_vaso = self.piso()

        self.assertGreater(con_vaso["razones"]["cogs"], sin_vaso["razones"]["cogs"])
        self.assertLess(con_vaso["margen_contribucion"], sin_vaso["margen_contribucion"])
        self.assertGreater(con_vaso["piso_mes"], sin_vaso["piso_mes"])
        self.assertGreater(con_vaso["piso_hoy"], sin_vaso["piso_hoy"])

    def test_el_costo_del_vaso_es_el_que_se_cargo_y_no_otro(self):
        """No alcanza con que suba: tiene que subir EXACTAMENTE lo que cuesta el
        empaque de lo que se vendió."""
        self.escenario()
        self.cargar_el_vaso()
        r = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]
        esperado = self.UNIDADES * self.COSTO_VASO           # 10 vasos × $200
        self.assertAlmostEqual(r["cogs_desechables"], esperado, places=2)
        self.assertAlmostEqual(r["cogs_teorico"],
                               self.UNIDADES * self.ML_POR_LATTE * self.COSTO_LECHE,
                               places=2)
        self.assertAlmostEqual(r["cogs_con_desechables"],
                               r["cogs_teorico"] + r["cogs_desechables"], places=2)

        piso = self.piso()
        ventas = piso["razones"]["ventas_medidas"]
        self.assertAlmostEqual(piso["razones"]["cogs_desechables"],
                               esperado / ventas, places=6)
        # ADITIVO: el renglón abierto suma exactamente el renglón entero.
        self.assertAlmostEqual(piso["razones"]["cogs"],
                               piso["razones"]["cogs_sin_desechables"]
                               + piso["razones"]["cogs_desechables"], places=6)

    def test_el_pl_no_se_come_el_vaso_dos_veces(self):
        """`cogs_teorico` y `margen_bruto_real` NO cambian al cargar el vaso: de
        ese lado la fuga por conteo ya lo estaba contando (el desechable no
        descuenta inventario al vender). Sumarlo también ahí contaría la misma
        plata dos veces en `margen_bruto_real_con_fuga`."""
        self.escenario()
        antes = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]
        self.cargar_el_vaso()
        despues = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]

        self.assertEqual(antes["cogs_teorico"], despues["cogs_teorico"])
        self.assertEqual(antes["margen_bruto_real"], despues["margen_bruto_real"])
        # Y lo que sí cambia es el término declarado aparte.
        self.assertEqual(antes["cogs_desechables"], 0)
        self.assertGreater(despues["cogs_desechables"], 0)

    def test_un_desechable_sin_costo_cargado_no_inventa_un_numero(self):
        """Un vaso sin ninguna factura leída no tiene costo. Ponerle $0 sería
        decir que el empaque es gratis; se queda afuera y la cobertura lo
        delata."""
        self.escenario()
        sin_costo = Producto(nombre="Tapa", categoria=CategoriaProductoEnum.insumo,
                             unidad_medida="unidad", precio_venta=0)
        self.db.add(sin_costo)
        self.db.flush()
        self.db.add(ProductoDesechable(producto_id=self.latte.id,
                                       insumo_id=sin_costo.id, cantidad=1))
        self.db.commit()
        r = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]
        self.assertEqual(r["cogs_desechables"], 0)


class ElSesgoSeApagaTest(DesechablesBase):

    def test_sin_desechables_cargados_el_sesgo_sigue_vivo(self):
        self.escenario()
        s = self.sesgo("desechables_fuera_del_costo")
        self.assertTrue(s["activo"])
        self.assertEqual(s["detalle"]["pct_venta_con_desechables"], 0)
        self.assertEqual(s["detalle"]["productos_con_desechables"], 0)

    def test_con_toda_la_venta_cubierta_el_sesgo_se_apaga(self):
        """Es lo que pedía el rediseño: meter los desechables APAGA el sesgo. Pero
        solo cuando de verdad están adentro de toda la venta medida."""
        self.escenario()
        self.cargar_el_vaso()
        s = self.sesgo("desechables_fuera_del_costo")
        self.assertFalse(s["activo"])
        self.assertEqual(s["detalle"]["pct_venta_con_desechables"], 100.0)
        self.assertGreater(s["detalle"]["cogs_desechables"], 0)

    def test_con_un_desechable_sin_costo_el_producto_no_cuenta_como_cubierto(self):
        """La versión fina del mismo error. El latte tiene vaso costeado y
        servilleta sin costear: los $200 del vaso SÍ se suman —esa plata salió—
        pero el empaque de ese producto no está entero adentro, así que el sesgo
        sigue vivo. Contarlo como cubierto sería declarar apagado un sesgo que
        todavía empuja el piso para abajo.

        Y ESTOS DOS NÚMEROS JUNTOS SON LOS QUE LA PANTALLA TIENE QUE PODER LEER.
        `cogs_desechables` $2.000 con `pct_venta_con_desechables` 0,0 es un estado
        REAL y frecuente —aparece apenas el dueño carga un renglón de empaque más
        del que tiene facturado— así que el 0% NO significa «no hay empaque
        cargado»: significa «ninguno lo tiene COMPLETO». El aviso de
        `ResultadoView` no puede negar el empaque que sí está adentro cuando
        `cogs_desechables > 0`; cambiar acá el 0 por un 100 «porque igual hay
        plata adentro» sería apagar el sesgo que este test mantiene vivo."""
        self.escenario()
        self.cargar_el_vaso()
        servilleta = Producto(nombre="Servilleta", categoria=CategoriaProductoEnum.insumo,
                              unidad_medida="unidad", precio_venta=0)
        self.db.add(servilleta)
        self.db.flush()
        self.db.add(ProductoDesechable(producto_id=self.latte.id,
                                       insumo_id=servilleta.id, cantidad=1))
        self.db.commit()

        r = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]
        self.assertAlmostEqual(r["cogs_desechables"],
                               self.UNIDADES * self.COSTO_VASO, places=2)
        self.assertEqual(r["pct_venta_con_desechables"], 0)
        self.assertTrue(self.sesgo("desechables_fuera_del_costo")["activo"])

    def test_con_media_venta_cubierta_el_sesgo_no_se_apaga(self):
        """La trampa tranquilizadora: cargarle el vaso a UN producto y creer que
        el costo del empaque ya está adentro. La cobertura lo dice."""
        self.escenario()
        self.cargar_el_vaso()
        torta = self.producto("Torta", precio=self.PRECIO_LATTE)
        for _ in range(self.UNIDADES):
            self.venta(self.hoy, self.PRECIO_LATTE, producto=torta)

        s = self.sesgo("desechables_fuera_del_costo")
        self.assertTrue(s["activo"])
        self.assertAlmostEqual(s["detalle"]["pct_venta_con_desechables"], 50.0)

    # ── EL TEXTO SALE DEL MISMO PREDICADO QUE `activo` ──────────────────────
    # El texto se elegía con `not cobertura`, que es otra pregunta que `activo`:
    # con la cobertura en 100 el sesgo quedaba APAGADO y el string que viajaba al
    # lado seguía diciendo «solo una parte de la venta tiene sus desechables
    # cargados». La pantalla filtra por `activo`, así que hoy no se ve — pero es
    # un campo afirmando lo contrario del campo con el que viaja, y el día que
    # alguien muestre el texto sin mirar la bandera publica la contradicción.

    def test_EL_BLOQUEANTE_con_todo_cubierto_el_texto_no_dice_que_falta(self):
        self.escenario()
        self.cargar_el_vaso()
        s = self.sesgo("desechables_fuera_del_costo")
        self.assertFalse(s["activo"])
        self.assertEqual(s["detalle"]["pct_venta_con_desechables"], 100.0)
        self.assertNotIn("solo una parte", s["texto"])
        self.assertIn("toda la venta", s["texto"])

    def test_con_media_venta_cubierta_el_texto_dice_media(self):
        self.escenario()
        self.cargar_el_vaso()
        torta = self.producto("Torta", precio=self.PRECIO_LATTE)
        for _ in range(self.UNIDADES):
            self.venta(self.hoy, self.PRECIO_LATTE, producto=torta)
        s = self.sesgo("desechables_fuera_del_costo")
        self.assertTrue(s["activo"])
        self.assertIn("solo una parte", s["texto"])

    def test_sin_nada_cubierto_el_texto_dice_que_no_estan(self):
        self.escenario()
        s = self.sesgo("desechables_fuera_del_costo")
        self.assertTrue(s["activo"])
        self.assertEqual(s["detalle"]["pct_venta_con_desechables"], 0)
        self.assertIn("no están dentro", s["texto"])

    def test_sin_poder_medir_la_cobertura_no_se_afirma_que_no_estan(self):
        """`None` no es 0. «Los desechables no están dentro del costo» es una
        afirmación sobre el mundo, y sin medición no se puede hacer: el sesgo
        sigue vivo —que es lo prudente— pero el texto dice que no se pudo medir.
        `not None` y `not 0.0` daban lo mismo, y por eso los dos casos caían en
        la misma frase."""
        razones = {"pct_venta_costeada": 100.0, "ventas": 100_000.0,
                   "pct_venta_con_desechables": None, "cogs_desechables": 0.0,
                   "comision_sin_cargar": False, "pct_tarjeta": 0.0,
                   "tasa_comision": 0.0}
        s = self.sesgo("desechables_fuera_del_costo",
                       piso={"sesgos": costos_svc._sesgos_del_piso(razones, 0)})
        self.assertTrue(s["activo"])
        self.assertIn("no se pudo medir", s["texto"])

    def test_los_otros_tres_sesgos_siguen_estando(self):
        """El bloque de la pantalla los nombra uno por uno: si desapareciera una
        clave, ese renglón se caería en silencio."""
        self.escenario()
        claves = [s["clave"] for s in self.piso()["sesgos"]]
        self.assertEqual(claves, ["productos_sin_costo", "costeo_parcial",
                                  "desechables_fuera_del_costo",
                                  "comision_datafono_sin_cargar",
                                  "retenciones_fuera_del_gasto"])


# ═══════════════════════════════════════════════════════════════════════════════
# 4. EL MARGEN QUE SE PUBLICA NO PUEDE OMITIR EL EMPAQUE
#
# El argumento que dejó el vaso afuera de `cogs_teorico` —«la fuga medida por
# conteo ya lo cuenta, sumarlo también sería doble conteo»— cubre EXACTAMENTE un
# número: `margen_bruto_real_con_fuga`. No cubre `margen_bruto_real` ni
# `pct_margen_bruto_real`, que no tienen término de fuga y se publican igual. Y
# la tarjeta que los dibuja no está detrás de `tiene_fuga_medida`: se dibuja
# SIEMPRE, también en el mes en curso, donde no hay ningún cierre.
#
# Con $100.000 vendidos, $2.500 de receta y $2.000 de vaso, la pantalla afirmaba
# «margen bruto real $97.500 (97,5%)» y el empaque no estaba en ninguna parte.
# ═══════════════════════════════════════════════════════════════════════════════

class ElMargenPublicadoTest(DesechablesBase):

    def test_el_margen_que_la_pantalla_muestra_lleva_el_empaque_adentro(self):
        """El número protagonista de la tarjeta descuenta receta Y empaque."""
        self.escenario()
        self.cargar_el_vaso()
        r = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]

        ventas = self.UNIDADES * self.PRECIO_LATTE          # $100.000
        receta = self.UNIDADES * self.ML_POR_LATTE * self.COSTO_LECHE   # $2.500
        empaque = self.UNIDADES * self.COSTO_VASO           # $2.000

        self.assertAlmostEqual(r["margen_bruto_real_con_desechables"],
                               ventas - receta - empaque, places=2)
        self.assertAlmostEqual(r["pct_margen_bruto_real_con_desechables"],
                               round((ventas - receta - empaque) / ventas * 100, 1),
                               places=1)
        # Y es EXACTAMENTE el complemento del costo completo que ya se publicaba.
        self.assertAlmostEqual(r["margen_bruto_real_con_desechables"],
                               r["ventas"] - r["cogs_con_desechables"], places=2)

    def test_el_de_receta_sola_sigue_existiendo_y_sigue_siendo_el_de_la_fuga(self):
        """No se le cambia el valor a `margen_bruto_real`: es la base de CONSUMO
        a la que se le resta el residuo del conteo, y meterle el vaso adentro
        contaría el mismo vaso dos veces en `margen_bruto_real_con_fuga`. Los dos
        márgenes conviven; lo que cambia es cuál manda en pantalla."""
        self.escenario()
        self.cargar_el_vaso()
        r = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]

        self.assertAlmostEqual(r["margen_bruto_real"],
                               r["ventas"] - r["cogs_teorico"], places=2)
        # La distancia entre los dos ES el empaque, ni un peso más.
        self.assertAlmostEqual(r["margen_bruto_real"] - r["margen_bruto_real_con_desechables"],
                               r["cogs_desechables"], places=2)

    def test_en_el_mes_en_curso_sin_un_solo_cierre_el_empaque_igual_esta(self):
        """EL CASO NORMAL, que es donde el agujero mordía. Sin ningún mes cerrado
        adentro del rango no hay término de fuga —`tiene_fuga_medida` en False y
        la banda que lo declaraba ni se dibuja—, y aun así el margen que se
        publica tiene el vaso descontado."""
        self.escenario()
        self.cargar_el_vaso()
        r = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]

        self.assertFalse(r["tiene_fuga_medida"])
        self.assertIsNone(r["margen_bruto_real_con_fuga"])
        self.assertGreater(r["cogs_desechables"], 0)
        self.assertLess(r["margen_bruto_real_con_desechables"], r["margen_bruto_real"])

    def test_cargar_el_vaso_BAJA_el_margen_publicado(self):
        """LA DIRECCIÓN, sobre el número nuevo. Si al cargar el empaque el margen
        de pantalla subiera, algo se restó donde había que sumar."""
        self.escenario()
        antes = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]
        self.cargar_el_vaso()
        despues = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]

        self.assertLess(despues["margen_bruto_real_con_desechables"],
                        antes["margen_bruto_real_con_desechables"])
        self.assertLess(despues["pct_margen_bruto_real_con_desechables"],
                        antes["pct_margen_bruto_real_con_desechables"])
        # Sin empaque cargado los dos márgenes son el MISMO número: el nuevo no
        # inventa una rebaja donde no hay nada que descontar.
        self.assertEqual(antes["margen_bruto_real_con_desechables"],
                         antes["margen_bruto_real"])

    def test_sin_ventas_el_porcentaje_es_None_y_no_cero(self):
        """Cero por ciento de margen es un veredicto; «no hay base para
        calcularlo» es otra cosa. La misma disciplina que `pct_margen_bruto`."""
        r = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]
        self.assertEqual(r["ventas"], 0)
        self.assertIsNone(r["pct_margen_bruto_real_con_desechables"])


# ═══════════════════════════════════════════════════════════════════════════════
# 5. «EL VASO YA ESTÁ ADENTRO DE LA FUGA» ES UNA CONDICIÓN, NO UN HECHO
#
# Todo el diseño de la capa se apoya en esa frase, y era una afirmación sobre lo
# que hizo el BARISTA: se cumple solo si contó ese renglón en el cierre.
# `cerrar()` rellena `cantidad_real` con el sistema para todo lo NO contado, así
# que un empaque que nadie miró da residuo 0 y se cae del término de fuga sin una
# sola señal — con `tiene_fuga_medida` en True y la banda diciendo «Residuo».
#
# Medido sobre el mismo mes cerrado, cambiando UNA sola cosa:
#   fue_contado=True  → fuga −$2.000 · margen con fuga $95.500  (se cumple)
#   fue_contado=False → fuga      $0 · margen con fuga $97.500  (y el empaque
#                       no está en ese término, mientras la banda igual se pinta)
# ═══════════════════════════════════════════════════════════════════════════════

class LaFugaCubreElEmpaqueTest(DesechablesBase):
    """El mismo latte, pero sobre un mes que YA pasó por un cierre de conteo.

    El mes tiene que estar COMPLETO adentro del rango para que `fuga_medida` lo
    mire, así que se usa el mes pasado y no el en curso.
    """

    def setUp(self):
        super().setUp()
        self.fin_pasado = self.dia1 - timedelta(days=1)
        self.ini_pasado = self.fin_pasado.replace(day=1)
        self.dia_venta = self.ini_pasado + timedelta(days=10)

    def insumo_con_stock(self, nombre, unidad, costo, stock):
        p = self.insumo(nombre, unidad, costo)
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.tienda.id,
                               stock_actual=stock))
        self.db.commit()
        return p

    def mov(self, prod, tipo, cant, dia):
        self.db.add(MovimientoInventario(producto_id=prod.id, tienda_id=self.tienda.id,
                                         tipo=tipo, cantidad=cant, fecha=mediodia(dia),
                                         usuario_id=self.admin.id, motivo="x"))
        self.db.commit()

    def venta_pasada(self, producto):
        t = Ticket(tienda_id=self.tienda.id, caja_turno_id=self.turno.id,
                   usuario_id=self.admin.id, fecha=mediodia(self.dia_venta),
                   total=self.PRECIO_LATTE, estado="completado", metodo_pago="efectivo",
                   monto_efectivo=self.PRECIO_LATTE, monto_tarjeta=0)
        self.db.add(t)
        self.db.flush()
        self.db.add(TicketItem(ticket_id=t.id, producto_id=producto.id,
                               nombre_producto=producto.nombre, cantidad=1,
                               precio_unitario=self.PRECIO_LATTE, subtotal=self.PRECIO_LATTE))
        self.db.commit()

    def escenario_cerrado(self, vaso_contado: bool, cargar_vaso: bool = True,
                          vaso_con_costo: bool = True, relleno: bool = False):
        """El latte del mes pasado, con su cierre de conteo ya hecho.

        La leche se descuenta por receta y el conteo la encuentra exacta: no
        aporta residuo. El VASO en cambio entra por compra y NADA lo descuenta al
        vender —el desechable no mueve inventario—, así que los 10 que se usaron
        para servir aparecen como faltante del conteo. Ese es, literalmente, el
        mecanismo por el que «la fuga ya se lleva el vaso».
        """
        self.leche = self.insumo_con_stock("Leche entera", "ml", self.COSTO_LECHE, 9_000)
        if vaso_con_costo:
            self.vaso = self.insumo_con_stock("Vaso 12 oz", "unidad", self.COSTO_VASO, 100)
        else:
            # Sin una sola factura leída no tiene costo: no aporta a
            # `cogs_desechables` y por lo tanto no es de lo que habla la frase.
            self.vaso = Producto(nombre="Vaso 12 oz", categoria=CategoriaProductoEnum.insumo,
                                 unidad_medida="unidad", precio_venta=0)
            self.db.add(self.vaso)
            self.db.flush()
            self.db.add(Inventario(producto_id=self.vaso.id, tienda_id=self.tienda.id,
                                   stock_actual=100))
            self.db.commit()

        self.latte = self.producto("Latte", precio=self.PRECIO_LATTE)
        self.latte.controla_stock = False
        self.db.add(ProductoInsumo(producto_id=self.latte.id, insumo_id=self.leche.id,
                                   cantidad=self.ML_POR_LATTE))
        if cargar_vaso:
            self.db.add(ProductoDesechable(producto_id=self.latte.id,
                                           insumo_id=self.vaso.id, cantidad=1.0))
        self.db.commit()

        self.mov(self.leche, TipoMovInvEnum.entrada, 10_000, self.ini_pasado)
        self.mov(self.vaso, TipoMovInvEnum.entrada, 100, self.ini_pasado)
        for _ in range(self.UNIDADES):
            self.venta_pasada(self.latte)
        self.mov(self.leche, TipoMovInvEnum.salida,
                 self.UNIDADES * self.ML_POR_LATTE, self.dia_venta)

        inv = InventarioMensual(tienda_id=self.tienda.id, anio=self.ini_pasado.year,
                                mes=self.ini_pasado.month, estado="cerrado",
                                usuario_id=self.admin.id,
                                fecha_cierre=mediodia(self.fin_pasado),
                                fecha_primer_cierre=mediodia(self.fin_pasado))
        self.db.add(inv)
        self.db.flush()
        self.db.add(InventarioMensualItem(inventario_id=inv.id, producto_id=self.leche.id,
                                          cantidad_sistema=9_000, cantidad_real=9_000,
                                          fue_contado=True))
        # `relleno` es el caso REAL de un renglón no contado: `cerrar()` no deja
        # `cantidad_real` en None, la iguala al sistema para que la diferencia dé
        # 0 y no ensucie el total. Sin mirar `fue_contado`, ese renglón se lee
        # idéntico a uno «contado y dio exacto».
        self.db.add(InventarioMensualItem(inventario_id=inv.id, producto_id=self.vaso.id,
                                          cantidad_sistema=100,
                                          cantidad_real=(90 if vaso_contado
                                                         else (100 if relleno else None)),
                                          fue_contado=vaso_contado))
        self.db.commit()
        return get_rentabilidad(self.db, self.ini_pasado, self.fin_pasado)["resumen"]

    def test_con_el_vaso_contado_el_argumento_se_cumple_Y_SE_DICE(self):
        """La mitad buena del mundo: el conteo miró el renglón, el residuo se
        lleva los $2.000 de empaque y ahí sí sumarlo al costo sería doble conteo.
        Lo nuevo es que la pantalla puede AFIRMARLO con un número."""
        r = self.escenario_cerrado(vaso_contado=True)

        self.assertAlmostEqual(r["fuga_inventario"],
                               -self.UNIDADES * self.COSTO_VASO, places=2)
        self.assertAlmostEqual(r["margen_bruto_real_con_fuga"], 95_500.0, places=2)
        self.assertEqual(r["desechables_con_costo"], 1)
        self.assertEqual(r["desechables_producto_mes"], 1)
        self.assertEqual(r["desechables_en_la_fuga"], 1)

    def test_con_el_vaso_SIN_contar_la_fuga_se_lo_pierde_y_el_contador_lo_delata(self):
        """LA MITAD QUE NADIE VERIFICABA. Cambia UNA cosa —`fue_contado`— y el
        residuo se va a $0 mientras `tiene_fuga_medida` sigue en True: sin este
        contador, la banda seguía diciendo «Residuo» sobre un conteo que jamás
        miró el empaque."""
        r = self.escenario_cerrado(vaso_contado=False)

        self.assertEqual(r["fuga_inventario"], 0.0)
        self.assertTrue(r["tiene_fuga_medida"])          # el flag viejo no avisa
        self.assertAlmostEqual(r["margen_bruto_real_con_fuga"], 97_500.0, places=2)
        # El contador nuevo SÍ avisa: 0 de 1.
        self.assertEqual(r["desechables_producto_mes"], 1)
        self.assertEqual(r["desechables_en_la_fuga"], 0)

    def test_el_empaque_no_desaparece_de_la_pantalla_aunque_el_conteo_lo_ignore(self):
        """La razón por la que las dos mitades van juntas: con el vaso sin
        contar, esos $2.000 no están en el residuo — pero SÍ están en el margen
        que la tarjeta de costo publica. Ya no hay ningún mundo en el que el
        empaque no esté en ningún número."""
        r = self.escenario_cerrado(vaso_contado=False)

        self.assertAlmostEqual(r["cogs_desechables"],
                               self.UNIDADES * self.COSTO_VASO, places=2)
        self.assertAlmostEqual(r["margen_bruto_real_con_desechables"], 95_500.0, places=2)
        # El de receta sola —el que la banda de fuga usa— sigue sin el empaque, a
        # propósito y declarado en su rótulo.
        self.assertAlmostEqual(r["margen_bruto_real"], 97_500.0, places=2)

    def test_el_renglon_RELLENADO_por_cerrar_no_cuenta_como_contado(self):
        """La versión fina del mismo error, y la que de verdad ocurre en el local.

        `cerrar()` iguala `cantidad_real` al sistema para todo lo que nadie tocó.
        Un contador que leyera esa columna vería el vaso «contado y exacto» y
        diría que el residuo cubre el empaque, con el residuo en $0 y el empaque
        en ninguna parte. Se mira `fue_contado`, que es la única marca de que
        alguien de verdad fue al estante."""
        r = self.escenario_cerrado(vaso_contado=False, relleno=True)

        self.assertEqual(r["fuga_inventario"], 0.0)
        self.assertEqual(r["desechables_producto_mes"], 1)
        self.assertEqual(r["desechables_en_la_fuga"], 0)

    def test_sin_desechables_cargados_no_se_inventa_cobertura(self):
        """Cero renglones de empaque no es «el conteo cubrió todo el empaque».
        El denominador queda en 0 y la pantalla no puede sacar un veredicto."""
        r = self.escenario_cerrado(vaso_contado=True, cargar_vaso=False)

        self.assertEqual(r["cogs_desechables"], 0)
        self.assertEqual(r["desechables_con_costo"], 0)
        self.assertEqual(r["desechables_producto_mes"], 0)
        self.assertEqual(r["desechables_en_la_fuga"], 0)

    def test_un_desechable_SIN_COSTO_no_entra_al_denominador(self):
        """Un vaso sin factura leída aporta $0 a `cogs_desechables`: no es de lo
        que habla la frase del doble conteo. Meterlo en el denominador diría que
        el conteo cubre menos empaque del que cubre, y aunque ese sesgo va para
        el lado incómodo, sigue siendo un número que no mide lo que dice."""
        r = self.escenario_cerrado(vaso_contado=True, vaso_con_costo=False)

        self.assertEqual(r["cogs_desechables"], 0)
        self.assertEqual(r["desechables_con_costo"], 0)
        self.assertEqual(r["desechables_producto_mes"], 0)

    def test_sin_ningun_cierre_los_contadores_no_afirman_nada(self):
        """`fuga_medida` devuelve `None` y no 0 cuando nadie cerró un conteo; los
        contadores del empaque tienen que acompañar esa nada, no rellenarla."""
        self.escenario_cerrado(vaso_contado=True)
        # El mes EN CURSO: la venta y el cierre son del pasado, así que este
        # rango no tiene ningún mes cerrado completo adentro.
        r = get_rentabilidad(self.db, self.dia1, self.hoy)["resumen"]

        self.assertFalse(r["tiene_fuga_medida"])
        self.assertEqual(r["desechables_producto_mes"], 0)
        self.assertEqual(r["desechables_en_la_fuga"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LA COBERTURA DEL EMPAQUE ES UNA FRACCIÓN CON DENOMINADOR MÓVIL
#
# `desechables_producto_mes` suma los renglones de empaque UNA VEZ POR CIERRE.
# La sede que no cierra no aporta numerador NI denominador: se cae de la fracción
# entera en vez de bajarla, y el par sale «todo contado» con la mitad del empaque
# afuera de todo término.
#
# Medido con dos sedes que venden lo mismo y una sola que cierra:
#   desechables 1 de 1  → la fracción dice «cubierto»
#   fuga_sedes 1 de 2   → y el tramo dice que habla de la mitad
#   residuo −$2.000 sobre $4.000 de empaque servido → la otra mitad no está ni en
#   el residuo ni en `margen_bruto_real`
#
# La fracción no está mal: es correcta ADENTRO del tramo medido y no dice nada de
# lo que quedó afuera. Por eso el verde de la pantalla se condiciona al tramo —el
# payload ya trae los dos ejes— en vez de leerse como una afirmación sobre todo
# el empaque servido en el período.
# ═══════════════════════════════════════════════════════════════════════════════

class DosSedesBase(DesechablesBase):
    """FIXTURE, sin tests propios: Vida y Centro, con el mismo latte a la venta.

    Vive aparte de los dos casos que la usan porque son dos mundos distintos
    armados sobre el mismo local —las dos venden y una cierra; una vende y la
    otra cierra— y colgar el segundo del primero le hacía correr sus tests de
    nuevo con otro nombre.
    """

    PRECIO = 5_000.0
    UNIDADES = 20
    COSTO_VASO = 100.0

    def setUp(self):
        super().setUp()
        self.fin_pasado = self.dia1 - timedelta(days=1)
        self.ini_pasado = self.fin_pasado.replace(day=1)
        self.dia_venta = self.ini_pasado + timedelta(days=10)
        self.centro = Tienda(nombre="Centro", direccion="y")
        self.db.add(self.centro)
        self.db.flush()
        self.turno_centro = CajaTurno(tienda_id=self.centro.id,
                                      usuario_apertura_id=self.admin.id,
                                      base_real=0.0, estado=EstadoTurnoEnum.cerrado,
                                      fecha_cierre=mediodia(self.hoy),
                                      efectivo_final_real=0.0)
        self.db.add(self.turno_centro)
        self.db.commit()

    def _stock(self, prod, tienda, cantidad):
        self.db.add(Inventario(producto_id=prod.id, tienda_id=tienda.id,
                               stock_actual=cantidad))
        self.db.commit()

    def _mov(self, prod, tipo, cant, dia, tienda):
        self.db.add(MovimientoInventario(producto_id=prod.id, tienda_id=tienda.id,
                                         tipo=tipo, cantidad=cant, fecha=mediodia(dia),
                                         usuario_id=self.admin.id, motivo="x"))
        self.db.commit()

    def _venta(self, tienda, turno, producto):
        t = Ticket(tienda_id=tienda.id, caja_turno_id=turno.id,
                   usuario_id=self.admin.id, fecha=mediodia(self.dia_venta),
                   total=self.PRECIO, estado="completado", metodo_pago="efectivo",
                   monto_efectivo=self.PRECIO, monto_tarjeta=0)
        self.db.add(t)
        self.db.flush()
        self.db.add(TicketItem(ticket_id=t.id, producto_id=producto.id,
                               nombre_producto=producto.nombre, cantidad=1,
                               precio_unitario=self.PRECIO, subtotal=self.PRECIO))
        self.db.commit()


class LaCoberturaDelEmpaqueEsPorCierreTest(DosSedesBase):
    """Las dos sedes venden el mismo latte; solo Vida cierra el conteo."""

    def escenario_dos_sedes(self):
        """Las dos venden 20 lattes; el vaso entra por compra y nada lo descuenta
        al vender, así que en la sede que CIERRA aparece como faltante y en la que
        no cierra no aparece en ningún lado."""
        leche = self.insumo("Leche entera", "ml", self.COSTO_LECHE)
        vaso = self.insumo("Vaso 12 oz", "unidad", self.COSTO_VASO)
        for tienda in (self.tienda, self.centro):
            self._stock(leche, tienda, 18_000)
            self._stock(vaso, tienda, 200)

        latte = self.producto("Latte", precio=self.PRECIO)
        latte.controla_stock = False
        self.db.add(ProductoInsumo(producto_id=latte.id, insumo_id=leche.id,
                                   cantidad=self.ML_POR_LATTE))
        self.db.add(ProductoDesechable(producto_id=latte.id, insumo_id=vaso.id,
                                       cantidad=1.0))
        self.db.commit()

        for tienda in (self.tienda, self.centro):
            self._mov(leche, TipoMovInvEnum.entrada, 20_000, self.ini_pasado, tienda)
            self._mov(vaso, TipoMovInvEnum.entrada, 200, self.ini_pasado, tienda)
        for _ in range(self.UNIDADES):
            self._venta(self.tienda, self.turno, latte)
            self._venta(self.centro, self.turno_centro, latte)
        for tienda in (self.tienda, self.centro):
            self._mov(leche, TipoMovInvEnum.salida,
                      self.UNIDADES * self.ML_POR_LATTE, self.dia_venta, tienda)

        # SOLO VIDA CIERRA, y cuenta el vaso: es la mitad buena del mundo.
        inv = InventarioMensual(tienda_id=self.tienda.id, anio=self.ini_pasado.year,
                                mes=self.ini_pasado.month, estado="cerrado",
                                usuario_id=self.admin.id,
                                fecha_cierre=mediodia(self.fin_pasado),
                                fecha_primer_cierre=mediodia(self.fin_pasado))
        self.db.add(inv)
        self.db.flush()
        self.db.add(InventarioMensualItem(inventario_id=inv.id, producto_id=leche.id,
                                          cantidad_sistema=18_000, cantidad_real=18_000,
                                          fue_contado=True))
        self.db.add(InventarioMensualItem(inventario_id=inv.id, producto_id=vaso.id,
                                          cantidad_sistema=200, cantidad_real=180,
                                          fue_contado=True))
        self.db.commit()
        return get_rentabilidad(self.db, self.ini_pasado, self.fin_pasado)["resumen"]

    def test_EL_BLOQUEANTE_la_fraccion_da_completa_con_media_sede_sin_contar(self):
        """El agujero, en un solo test. El par del empaque da 1 de 1 —lo que la
        pantalla leía como «ya está adentro»— y la sede que no cerró aportó cero
        a los DOS lados de la fracción en vez de bajarla."""
        r = self.escenario_dos_sedes()

        self.assertEqual(r["desechables_producto_mes"], 1)
        self.assertEqual(r["desechables_en_la_fuga"], 1)
        # …y sin embargo el tramo dice que esto habla de la mitad de las sedes.
        self.assertEqual(r["fuga_sedes"], 1)
        self.assertEqual(r["fuga_sedes_rango"], 2)

    def test_la_mitad_del_empaque_no_esta_en_NINGUN_termino(self):
        """Por qué el verde era falso y no solo optimista. Se sirvieron 40 vasos
        ($4.000 de empaque); el residuo se lleva los 20 de Vida ($2.000) y los 20
        de Centro no están ahí ni en el margen de receta de la misma banda."""
        r = self.escenario_dos_sedes()

        servido = 2 * self.UNIDADES * self.COSTO_VASO          # $4.000
        self.assertAlmostEqual(r["ventas"], 2 * self.UNIDADES * self.PRECIO, places=2)
        self.assertAlmostEqual(r["cogs_desechables"], servido, places=2)
        # El residuo cubre EXACTAMENTE la mitad: los vasos de la sede que contó.
        self.assertAlmostEqual(r["fuga_inventario"], -servido / 2, places=2)
        # Y el margen de la banda —el de receta sola— no tiene empaque adentro.
        self.assertAlmostEqual(
            r["margen_bruto_real"],
            r["ventas"] - 2 * self.UNIDADES * self.ML_POR_LATTE * self.COSTO_LECHE,
            places=2)
        # La cuenta que la pantalla ya no puede afirmar: «todo el empaque servido
        # está adentro del residuo» pediría que el residuo fuera −$4.000.
        self.assertNotAlmostEqual(r["fuga_inventario"], -servido, places=2)

    def test_el_payload_trae_los_dos_ejes_para_poder_condicionar_el_verde(self):
        """El arreglo es de pantalla, así que lo que el backend tiene que
        garantizar es que el tramo VIAJE junto al par del empaque: sin
        `fuga_sedes` / `fuga_sedes_rango` en la misma respuesta, la pantalla no
        tiene con qué apagar la afirmación."""
        r = self.escenario_dos_sedes()

        for k in ("desechables_en_la_fuga", "desechables_producto_mes",
                  "desechables_con_costo", "fuga_cierres",
                  "fuga_meses", "fuga_meses_rango",
                  "fuga_sedes", "fuga_sedes_rango"):
            self.assertIsNotNone(r.get(k), f"falta {k} en el resumen")
        # El tramo es parcial por SEDES y completo por MESES: el aviso de la
        # pantalla tiene que nombrar solo el eje que de verdad falta.
        self.assertLess(r["fuga_sedes"], r["fuga_sedes_rango"])
        self.assertEqual(r["fuga_meses"], r["fuga_meses_rango"])

    def test_con_las_DOS_sedes_cerrando_la_afirmacion_si_se_cumple(self):
        """La otra mitad del eje: cuando no queda tramo afuera, el residuo sí se
        lleva todo el empaque servido y el verde vuelve a ser verdad. Sin este
        test, condicionar el verde podría estar apagándolo para siempre."""
        self.escenario_dos_sedes()
        vaso = self.db.query(Producto).filter_by(nombre="Vaso 12 oz").one()
        leche = self.db.query(Producto).filter_by(nombre="Leche entera").one()
        inv = InventarioMensual(tienda_id=self.centro.id, anio=self.ini_pasado.year,
                                mes=self.ini_pasado.month, estado="cerrado",
                                usuario_id=self.admin.id,
                                fecha_cierre=mediodia(self.fin_pasado),
                                fecha_primer_cierre=mediodia(self.fin_pasado))
        self.db.add(inv)
        self.db.flush()
        self.db.add(InventarioMensualItem(inventario_id=inv.id, producto_id=leche.id,
                                          cantidad_sistema=18_000, cantidad_real=18_000,
                                          fue_contado=True))
        self.db.add(InventarioMensualItem(inventario_id=inv.id, producto_id=vaso.id,
                                          cantidad_sistema=200, cantidad_real=180,
                                          fue_contado=True))
        self.db.commit()
        r = get_rentabilidad(self.db, self.ini_pasado, self.fin_pasado)["resumen"]

        servido = 2 * self.UNIDADES * self.COSTO_VASO
        self.assertEqual(r["fuga_sedes"], r["fuga_sedes_rango"])
        self.assertEqual(r["desechables_en_la_fuga"], r["desechables_producto_mes"])
        self.assertAlmostEqual(r["fuga_inventario"], -servido, places=2)


# ══════════════════════════════════════════════════════════════════════════════
# 7. EL CASO CRUZADO: LA COBERTURA DE SEDES PUEDE DAR CERO, Y CERO ES EL PEOR CASO
#
# `fuga_sedes` es la INTERSECCIÓN —sedes que vendieron Y midieron— justamente para
# que este caso no pase inadvertido: la sede que cierra el conteo no vendió un peso
# y la que vende nunca cierra. El numerador da 0 y el denominador 1.
#
# `ResultadoView` decidía «¿falta tramo?» con `fuga_sedes > 0 && fuga_sedes < rango`,
# así que el aviso se apagaba JUSTO acá y la pantalla publicaba el renglón verde
# —«el vaso que se sirvió ya está adentro de este residuo»— sobre un residuo de $0
# que no lleva adentro un solo vaso de los que se sirvieron.
#
# Este archivo fija el HECHO del backend del que depende ese arreglo. Si alguien
# vuelve a comparar cardinalidades en `get_rentabilidad`, acá se pone rojo antes
# de que la pantalla vuelva a callarse sola.
# ══════════════════════════════════════════════════════════════════════════════

class LaSedeQueCerroNoEsLaQueVendioTest(DosSedesBase):
    """Vida cierra el conteo y no vende; Centro vende 20 lattes y no cierra."""

    def escenario_cruzado(self):
        leche = self.insumo("Leche entera", "ml", self.COSTO_LECHE)
        vaso = self.insumo("Vaso 12 oz", "unidad", self.COSTO_VASO)
        # Vida no tiene NADA: no vende, no recibe y no le falta. Su cierre es real
        # pero no puede aportar un peso de residuo — es el caso límite exacto.
        self._stock(leche, self.tienda, 0)
        self._stock(vaso, self.tienda, 0)
        self._stock(leche, self.centro, 18_000)
        self._stock(vaso, self.centro, 200)

        latte = self.producto("Latte", precio=self.PRECIO)
        latte.controla_stock = False
        self.db.add(ProductoInsumo(producto_id=latte.id, insumo_id=leche.id,
                                   cantidad=self.ML_POR_LATTE))
        self.db.add(ProductoDesechable(producto_id=latte.id, insumo_id=vaso.id,
                                       cantidad=1.0))
        self.db.commit()

        self._mov(leche, TipoMovInvEnum.entrada, 20_000, self.ini_pasado, self.centro)
        self._mov(vaso, TipoMovInvEnum.entrada, 200, self.ini_pasado, self.centro)
        for _ in range(self.UNIDADES):
            self._venta(self.centro, self.turno_centro, latte)
        self._mov(leche, TipoMovInvEnum.salida,
                  self.UNIDADES * self.ML_POR_LATTE, self.dia_venta, self.centro)

        inv = InventarioMensual(tienda_id=self.tienda.id, anio=self.ini_pasado.year,
                                mes=self.ini_pasado.month, estado="cerrado",
                                usuario_id=self.admin.id,
                                fecha_cierre=mediodia(self.fin_pasado),
                                fecha_primer_cierre=mediodia(self.fin_pasado))
        self.db.add(inv)
        self.db.flush()
        self.db.add(InventarioMensualItem(inventario_id=inv.id, producto_id=leche.id,
                                          cantidad_sistema=0, cantidad_real=0,
                                          fue_contado=True))
        self.db.add(InventarioMensualItem(inventario_id=inv.id, producto_id=vaso.id,
                                          cantidad_sistema=0, cantidad_real=0,
                                          fue_contado=True))
        self.db.commit()
        return get_rentabilidad(self.db, self.ini_pasado, self.fin_pasado)["resumen"]

    def test_EL_BLOQUEANTE_la_cobertura_de_sedes_da_CERO_de_una(self):
        """Cero medido de una: es la cobertura más chica que existe, y con el
        `> 0` de la pantalla era la única que no encendía ningún aviso."""
        r = self.escenario_cruzado()

        self.assertEqual(r["fuga_sedes"], 0)
        self.assertEqual(r["fuga_sedes_rango"], 1)
        # El eje de MESES está completo: el aviso que falta es el de sedes, solo.
        self.assertEqual(r["fuga_meses"], r["fuga_meses_rango"])

    def test_el_par_del_empaque_sigue_diciendo_cubierto_y_por_eso_manda_el_tramo(self):
        """La fracción del empaque no está mal: es correcta ADENTRO del tramo que
        el conteo miró. Lo que no puede es hablar sola — acá da «1 de 1» sobre un
        cierre de una sede que no vendió un solo latte."""
        r = self.escenario_cruzado()

        self.assertEqual(r["desechables_en_la_fuga"], r["desechables_producto_mes"])
        self.assertGreater(r["desechables_producto_mes"], 0)

    def test_el_residuo_es_CERO_y_el_empaque_servido_no_esta_en_ningun_termino(self):
        """La medición en pesos, que es lo que hace grave al aviso apagado: se
        sirvieron 20 vasos y el residuo del que la pantalla decía «ya los lleva
        adentro» vale $0,00."""
        r = self.escenario_cruzado()

        self.assertAlmostEqual(r["ventas"], self.UNIDADES * self.PRECIO, places=2)
        self.assertAlmostEqual(r["cogs_desechables"],
                               self.UNIDADES * self.COSTO_VASO, places=2)
        self.assertAlmostEqual(r["fuga_inventario"], 0.0, places=2)
        # Y la banda igual se dibuja: la puerta es `tiene_fuga_medida`, que sigue
        # en True porque el cierre de Vida existe.
        self.assertTrue(r["tiene_fuga_medida"])


if __name__ == "__main__":
    unittest.main()
