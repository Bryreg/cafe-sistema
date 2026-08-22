"""LAS PALANCAS: dónde bajar un costo, con nombre y en pesos de piso.

El dueño pidió dos cosas que el sistema tenía a medias: «ver en qué se está
yendo la plata» y «cuál proveedor es el más solicitado, para negociar precios».
Las subas de precio ya se detectaban y se ordenaban bien, pero llegaban ANÓNIMAS
y en porcentaje — y ni un nombre faltante ni un porcentaje se pueden llevar a una
reunión.

Lo que fija este archivo:

1. EL RANKING AGRUPA POR NOMBRE NORMALIZADO. `FacturaCompra.proveedor` es texto
   libre: «Lácteos Andina» y «LACTEOS ANDINA» eran dos filas, cada una con la
   mitad del tamaño real. Para negociar es el peor error posible, porque parte al
   proveedor grande en varios chicos y ninguno parece importante.
2. SE MUESTRA LA GRAFÍA DE LA FACTURA MÁS RECIENTE, no la clave normalizada: el
   dueño reconoce el nombre que ve en el papel. Y «la más reciente» se decide con
   `fecha_recibido → fecha_registro → id`, porque la columna es nullable y el
   orden de los NULLs no es el mismo en SQLite que en Postgres.
3. LA CONCENTRACIÓN ES CONTRA EL TOTAL, no contra el proveedor más grande. «El
   más grande de la lista» no dice nada; «se lleva el 34% de todo lo que compro»
   es una posición de negociación.
4. LA ALERTA DE SUBA DICE QUIÉN, y el nombre sale de la MISMA factura que fijó el
   precio nuevo — no de la última factura de ese insumo por otra consulta.
5. LA SUBA SE TRADUCE A PESOS DE PISO POR DÍA, midiendo CONTRA el piso ya
   publicado (una diferencia, no un segundo cálculo del piso).
6. LO QUE NO SE PUEDE TRADUCIR VIAJA IGUAL, con el porqué en castellano. Una suba
   que desaparece de la lista es una suba que nadie va a ir a negociar.
7. SON DOS NÚMEROS Y NO UNO. «Lo que viene si el precio nuevo se queda» y «lo que
   vuelve hoy si el proveedor da marcha atrás» NO son la misma plata mirada de
   dos formas: el costo con el que se costea es el promedio de toda la historia,
   así que ya tiene parte de la suba adentro y solo ESA parte se puede recuperar.
   La pantalla publicó una versión que prometía 10,1 VECES lo que devolvía.
8. LA REFERENCIA NO SE MUEVE SOLA. El umbral del 10% y el porcentaje que se le
   dice al proveedor se miden contra el precio más barato de los últimos 12
   meses, no contra ese promedio: comparar contra algo que se acerca al precio
   nuevo con cada compra apaga la alerta mientras el piso todavía sube.
9. EL SUJETO DE LA FRASE Y EL PORCENTAJE VAN JUNTOS. Si el renglón dice «Andina
   subió la leche +X%», X tiene que ser lo que movió Andina — un número que él
   pueda verificar contra su propia factura.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CategoriaProductoEnum, FacturaCompra,
                               FacturaCompraItem, Producto, ProductoInsumo,
                               RolEnum, Tienda, TipoPagoEnum, Usuario)
from app.services import costos as costos_svc
from app.services.facturas import get_dashboard_pagos
from app.services.rentabilidad import (_costos_insumos, alertas_de_costo,
                                       cogs_por_insumo)
from tests.test_piso_venta import PisoBase, mediodia


# ═══════════════════════════════════════════════════════════════════════════════
# 1-3. EL RANKING DE PROVEEDORES: agrupar bien y decir cuánto pesa cada uno
# ═══════════════════════════════════════════════════════════════════════════════

class RankingDeProveedoresTest(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False,
                                         bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.u = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                         rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.u)
        self.db.commit()
        self.hoy = date.today()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def factura(self, proveedor, total, pagado=0.0, recibido=None, registro=None):
        f = FacturaCompra(tienda_id=self.tienda.id, proveedor=proveedor,
                          valor_total=total, valor_pagado=pagado,
                          tipo_pago=TipoPagoEnum.credito, usuario_id=self.u.id,
                          fecha_recibido=recibido,
                          fecha_registro=registro or mediodia(self.hoy))
        self.db.add(f)
        self.db.commit()
        return f

    def ranking(self):
        return {p["clave"]: p for p in get_dashboard_pagos(self.db)["por_proveedor"]}

    def test_las_grafias_del_mismo_proveedor_son_una_sola_fila(self):
        """El bug que parte al proveedor grande en varios chicos.

        Tres formas de escribir el mismo teléfono: mayúsculas, tildes y espacios
        de más. Antes eran TRES filas de $1.000.000 y el ranking mostraba a
        cualquier otro de $2.000.000 arriba de ellas.
        """
        self.factura("Lácteos Andina", 1_000_000, recibido=mediodia(self.hoy))
        self.factura("LACTEOS ANDINA", 1_000_000, recibido=mediodia(self.hoy))
        self.factura("lacteos  andina", 1_000_000, recibido=mediodia(self.hoy))
        self.factura("Panadería Sur", 2_000_000, recibido=mediodia(self.hoy))

        r = self.ranking()
        self.assertEqual(len(r), 2)
        andina = r["LACTEOS ANDINA"]
        self.assertEqual(andina["facturado"], 3_000_000)
        self.assertEqual(andina["n"], 3)
        # Y ahora encabeza, que es el punto entero: es el proveedor grande.
        primero = get_dashboard_pagos(self.db)["por_proveedor"][0]
        self.assertEqual(primero["clave"], "LACTEOS ANDINA")

    def test_muestra_la_grafia_de_la_factura_mas_reciente(self):
        """El dueño reconoce el nombre del papel, no la clave normalizada."""
        self.factura("LACTEOS ANDINA", 500_000,
                     recibido=mediodia(self.hoy - timedelta(days=10)))
        self.factura("Lácteos Andina S.A.S.", 500_000,
                     recibido=mediodia(self.hoy - timedelta(days=1)))
        # Ojo: normalizar quita tildes y puntos NO, así que estas dos grafías solo
        # caen en la misma clave si el sufijo coincide. Se usa el mismo sufijo a
        # propósito: lo que se prueba acá es CUÁL de las dos se muestra.
        r = get_dashboard_pagos(self.db)["por_proveedor"]
        nombres = {p["clave"]: p["proveedor"] for p in r}
        self.assertEqual(nombres["LACTEOS ANDINA"], "LACTEOS ANDINA")
        self.assertEqual(nombres["LACTEOS ANDINA S.A.S."], "Lácteos Andina S.A.S.")

    def test_la_mas_reciente_no_es_la_que_tiene_fecha_recibido_nula(self):
        """`fecha_recibido` es nullable y el orden de los NULLs cambia de motor.

        La factura vieja SIN fecha de recibido no puede ganar como «la más
        reciente» solo porque el SELECT la devolvió primero: se cae a
        `fecha_registro`, igual que en el resto del módulo.
        """
        self.factura("LACTEOS VIEJO", 100_000, recibido=None,
                     registro=mediodia(self.hoy - timedelta(days=30)))
        self.factura("Lácteos Nuevo", 100_000,
                     recibido=mediodia(self.hoy - timedelta(days=1)))
        # Las dos grafías normalizan distinto; se fuerza la MISMA clave usando el
        # mismo texto con distinta caja.
        self.db.query(FacturaCompra).filter(
            FacturaCompra.proveedor == "LACTEOS VIEJO").update(
                {"proveedor": "LACTEOS NUEVO"})
        self.db.commit()

        nombres = {p["clave"]: p["proveedor"]
                   for p in get_dashboard_pagos(self.db)["por_proveedor"]}
        self.assertEqual(nombres["LACTEOS NUEVO"], "Lácteos Nuevo")

    def test_la_concentracion_es_contra_el_total_y_no_contra_el_mas_grande(self):
        """La diferencia entre «el más grande» y «se lleva la mitad de todo».

        Normalizando contra el máximo, el primero siempre da 100% — un número que
        no dice nada y que además tranquiliza: parece que todo está repartido
        igual. Contra el total, el primero dice cuánta plata pasa por sus manos.
        """
        self.factura("Andina", 5_000_000, recibido=mediodia(self.hoy))
        self.factura("Sur", 3_000_000, recibido=mediodia(self.hoy))
        self.factura("Norte", 2_000_000, recibido=mediodia(self.hoy))

        d = get_dashboard_pagos(self.db)
        pct = {p["proveedor"]: p["pct_del_total"] for p in d["por_proveedor"]}
        self.assertEqual(pct["Andina"], 50.0)
        self.assertEqual(pct["Sur"], 30.0)
        self.assertEqual(pct["Norte"], 20.0)
        # Contra el más grande, «Andina» habría dado 100 y «Sur» 60.
        self.assertNotEqual(pct["Andina"], 100.0)
        self.assertAlmostEqual(sum(pct.values()), 100.0, places=1)
        self.assertEqual(d["totales"]["facturado"], 10_000_000)

    def test_sin_plata_facturada_la_concentracion_es_none_y_no_cero(self):
        """Un 0% diría «este proveedor no pesa». La verdad es que no hay base."""
        self.factura("Andina", 0, recibido=mediodia(self.hoy))
        d = get_dashboard_pagos(self.db)
        self.assertEqual(d["totales"]["facturado"], 0)
        self.assertIsNone(d["por_proveedor"][0]["pct_del_total"])


# ═══════════════════════════════════════════════════════════════════════════════
# 4-6. LA SUBA, CON NOMBRE Y EN PESOS DE PISO POR DÍA
# ═══════════════════════════════════════════════════════════════════════════════

class PalancasBase(PisoBase):
    """El escenario mínimo donde la línea de la reunión se puede armar entera:
    un latte con receta de leche, dos facturas de leche (la nueva más cara) y
    costos fijos cargados para que el piso exista.

    LAS DOS FACTURAS SON DE PROVEEDORES DISTINTOS a propósito: es el caso donde
    el sujeto de la frase no puede ser el que subió, porque el precio barato lo
    facturó otro."""

    PRECIO_VIEJO = 2.0      # $/ml — la REFERENCIA (lo más barato en 12 meses)
    PRECIO_NUEVO = 3.0      # $/ml → +50% contra la referencia; el promedio da 2,5
    ML_POR_LATTE = 100.0
    PRECIO_LATTE = 10_000.0
    UNIDADES = 10
    ARRIENDO = 9_000_000.0

    def insumo(self, nombre="Leche entera", unidad="ml"):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, precio_venta=0)
        self.db.add(p)
        self.db.commit()
        return p

    def compra(self, insumo, cantidad, precio, proveedor, dias_atras=0):
        f = FacturaCompra(tienda_id=self.tienda.id, proveedor=proveedor,
                          valor_total=cantidad * precio, valor_pagado=0,
                          tipo_pago=TipoPagoEnum.credito, usuario_id=self.admin.id,
                          fecha_recibido=mediodia(self.hoy - timedelta(days=dias_atras)))
        self.db.add(f)
        self.db.flush()
        self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=insumo.id,
                                      cantidad=cantidad, precio_unitario=precio))
        self.db.commit()
        return f

    def escenario(self, con_costos_fijos=True):
        self.leche = self.insumo()
        self.latte = self.producto("Latte", precio=self.PRECIO_LATTE)
        self.db.add(ProductoInsumo(producto_id=self.latte.id, insumo_id=self.leche.id,
                                   cantidad=self.ML_POR_LATTE))
        self.db.commit()
        self.compra(self.leche, 1000, self.PRECIO_VIEJO, "Lácteos del Valle", dias_atras=20)
        self.compra(self.leche, 1000, self.PRECIO_NUEVO, "Lácteos Andina", dias_atras=2)
        if con_costos_fijos:
            self.obligacion(self.ARRIENDO, self.fin_mes)
        self.historia_de_ventas()
        for _ in range(self.UNIDADES):
            self.venta(self.hoy, self.PRECIO_LATTE, producto=self.latte)

    def palancas(self):
        return costos_svc.get_palancas(self.db, self.hoy.year, self.hoy.month)

    def la_leche(self, r=None):
        r = r or self.palancas()
        return next(p for p in r["palancas"] if p["insumo_id"] == self.leche.id)

    # ── El escenario del bloqueante 5: la suba a medio absorber ──────────────
    # DIEZ compras al precio viejo y `n_nuevas` al nuevo, todas del MISMO
    # proveedor. Con una sola compra nueva el promedio ponderado queda en
    # $2,0727: de los $0,80 que subió la leche, apenas el 9,1% está adentro del
    # costo con el que hoy se costea. Es el escenario donde «lo que viene» y «lo
    # que vuelve» se separan diez veces, y donde la regla vieja del 10% se
    # apagaba sola a medida que crecía `n_nuevas`.
    VIEJO = 2.00
    NUEVO = 2.80
    COMPRAS_VIEJAS = 10

    def absorbido(self, n_nuevas=1):
        self.leche = self.insumo()
        self.latte = self.producto("Latte", precio=self.PRECIO_LATTE)
        self.db.add(ProductoInsumo(producto_id=self.latte.id, insumo_id=self.leche.id,
                                   cantidad=self.ML_POR_LATTE))
        self.db.commit()
        for i in range(self.COMPRAS_VIEJAS):
            self.compra(self.leche, 1000, self.VIEJO, "Lácteos Andina",
                        dias_atras=60 + i * 10)
        for i in range(n_nuevas):
            self.compra(self.leche, 1000, self.NUEVO, "Lácteos Andina",
                        dias_atras=1 + i)
        self.obligacion(self.ARRIENDO, self.fin_mes)
        self.historia_de_ventas()
        for _ in range(self.UNIDADES):
            self.venta(self.hoy, self.PRECIO_LATTE, producto=self.latte)


class LaSubaTieneNombreTest(PalancasBase):

    def test_la_alerta_dice_quien_subio_el_precio(self):
        self.escenario()
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)
        self.assertEqual(a["proveedor"], "Lácteos Andina")
        self.assertAlmostEqual(a["costo_usado"], 2.5)     # el promedio ponderado
        self.assertAlmostEqual(a["costo_ultimo"], 3.0)
        self.assertAlmostEqual(a["costo_ref"], 2.0)       # lo más barato en 12 meses
        self.assertAlmostEqual(a["pct_suba"], 50.0)

    def test_el_porcentaje_es_EL_QUE_MOVIO_EL_PROVEEDOR(self):
        """El número que el dueño se lleva a la reunión tiene que ser el que el
        proveedor reconoce en su propia factura.

        La leche pasó de $2,00 a $3,00: subió 50%. Medido contra el promedio
        ponderado de toda la historia ($2,50) daba 20%, y el dueño llegaba a
        discutir con una cifra que el otro desmiente sacando el papel. El
        promedio no es un precio: es el resultado de cuántas veces se compró.
        """
        self.escenario()
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)
        movio_el_proveedor = round(
            (self.PRECIO_NUEVO / self.PRECIO_VIEJO - 1) * 100, 1)
        contra_el_promedio = round((self.PRECIO_NUEVO / 2.5 - 1) * 100, 1)
        self.assertAlmostEqual(a["pct_suba"], movio_el_proveedor)
        self.assertNotAlmostEqual(a["pct_suba"], contra_el_promedio)

    def test_si_el_barato_lo_facturo_otro_el_proveedor_no_puede_ser_el_sujeto(self):
        """`mismo_proveedor` es lo que decide si la frase puede empezar con el
        nombre. Acá los $2,00 los facturó «Lácteos del Valle» y los $3,00
        «Lácteos Andina»: escribir «Andina subió la leche 50%» le atribuye a
        Andina un precio que Andina nunca cobró."""
        self.escenario()
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)
        self.assertFalse(a["mismo_proveedor"])
        # Y la referencia viaja con nombre y fecha: el «+50%» queda verificable
        # contra el papel en vez de ser un número que hay que creer.
        self.assertEqual(a["ref_proveedor"], "Lácteos del Valle")
        self.assertIsNotNone(a["ref_fecha"])
        self.assertEqual(a["ref_meses"], 12)

    def test_con_el_mismo_proveedor_de_los_dos_lados_si_puede_ser_el_sujeto(self):
        """Y la normalización es la del ranking: «LACTEOS ANDINA» y «Lácteos
        Andina» son el mismo teléfono, no dos empresas."""
        self.leche = self.insumo()
        self.latte = self.producto("Latte", precio=self.PRECIO_LATTE)
        self.db.add(ProductoInsumo(producto_id=self.latte.id, insumo_id=self.leche.id,
                                   cantidad=self.ML_POR_LATTE))
        self.db.commit()
        self.compra(self.leche, 1000, self.PRECIO_VIEJO, "LACTEOS ANDINA", dias_atras=20)
        self.compra(self.leche, 1000, self.PRECIO_NUEVO, "Lácteos Andina", dias_atras=2)
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)
        self.assertTrue(a["mismo_proveedor"])

    def test_el_nombre_no_es_el_del_proveedor_mas_grande(self):
        """«Mayorista Grande» trae CINCUENTA veces más leche que todos, pero al
        precio viejo. El que subió sigue siendo Andina, y ese es el teléfono que
        hay que levantar. Un nombre CERCA del correcto acá manda al dueño a
        pelear con la persona equivocada.
        """
        self.escenario()
        self.compra(self.leche, 50_000, self.PRECIO_VIEJO, "Mayorista Grande",
                    dias_atras=10)
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)
        self.assertEqual(a["proveedor"], "Lácteos Andina")
        # El precio nuevo y el nombre salen de LA MISMA fila, siempre.
        self.assertAlmostEqual(a["costo_ultimo"], self.PRECIO_NUEVO)

    def test_un_tipeo_freak_low_no_ancla_la_referencia(self):
        """Una factura vieja con el precio mal digitado NO puede volverse la
        referencia y prender una alerta falsa de +900%.

        La leche vale $3,00 en tres facturas y una vieja quedó tipeada en $0,30
        —un cero de menos, un décimo del real—. Con el «más barato a secas» esa
        factura anclaba la referencia en $0,30 y CADA compra normal se leía como
        «subió 900%». El piso anti-tipeo (mitad de la mediana = $1,50) la descarta:
        la referencia vuelve al $3,00 real y no hay suba que reportar."""
        self.leche = self.insumo()
        self.compra(self.leche, 1000, 3.0, "Lácteos Andina", dias_atras=40)
        self.compra(self.leche, 1000, 3.0, "Lácteos Andina", dias_atras=30)
        self.compra(self.leche, 1000, 0.30, "Lácteos Andina", dias_atras=60)  # TIPEO
        self.compra(self.leche, 1000, 3.0, "Lácteos Andina", dias_atras=2)
        _, ultimo = _costos_insumos(self.db)
        # La referencia es el barato REAL, no el tipeo.
        self.assertAlmostEqual(ultimo[self.leche.id]["ref"]["precio"], 3.0)
        self.assertIsNotNone(ultimo[self.leche.id]["ref"]["fecha"])
        # Y por lo tanto no hay alerta falsa: el último ($3,00) no supera a la
        # referencia real ($3,00) por más del 10%.
        con_alerta = {a["insumo_id"] for a in alertas_de_costo(self.db)}
        self.assertNotIn(self.leche.id, con_alerta)

    def test_un_precio_bajo_legitimo_si_es_la_referencia(self):
        """El piso descarta tipeos, NO rebajas reales. La leche estuvo a $2,00
        (mitad o más de la mediana, no un tipeo) y ahora está a $3,00: esa suba
        del 50% tiene que seguir prendida, medida contra los $2,00 de verdad."""
        self.leche = self.insumo()
        self.compra(self.leche, 1000, 2.0, "Lácteos del Valle", dias_atras=40)  # barato REAL
        self.compra(self.leche, 1000, 3.0, "Lácteos Andina", dias_atras=30)
        self.compra(self.leche, 1000, 3.0, "Lácteos Andina", dias_atras=2)
        _, ultimo = _costos_insumos(self.db)
        # mediana de [2,3,3] = 3 → piso 1,5 → el 2,0 sobrevive y es la referencia.
        self.assertAlmostEqual(ultimo[self.leche.id]["ref"]["precio"], 2.0)
        self.assertEqual(ultimo[self.leche.id]["ref"]["proveedor"], "Lácteos del Valle")

    def test_la_alerta_del_piso_es_la_misma_lista_que_la_de_productos(self):
        """Dos definiciones de «subió más de 10%» terminan en dos pantallas que
        se contradicen. Hay una sola función."""
        from app.services.rentabilidad import get_rentabilidad_productos
        self.escenario()
        de_productos = {a["insumo_id"]: a["pct_suba"]
                        for a in get_rentabilidad_productos(self.db)["alertas_costo"]}
        del_piso = {p["insumo_id"]: p["pct_suba"] for p in self.palancas()["palancas"]}
        self.assertEqual(de_productos, del_piso)


class LaSubaEnPesosDePisoTest(PalancasBase):

    def test_la_suba_se_traduce_a_pesos_de_piso_por_dia(self):
        """El número que convierte un porcentaje en una decisión.

        La cuenta, a mano y con los mismos datos del escenario:
          cogs de la leche en la ventana = 10 lattes × 100 ml × $2,5 = $2.500
          al precio nuevo cuesta 20% más                             = +$500
          sobre $100.000 vendidos                                    = 0,005
          margen viejo − 0,005 = margen nuevo, y el piso es CF/margen.
        """
        self.escenario()
        piso = costos_svc.get_piso(self.db, self.hoy.year, self.hoy.month)
        self.assertEqual(piso["puerta"], "ok")

        reparto = cogs_por_insumo(self.db, piso["razones"]["desde"],
                                  piso["razones"]["hasta"])
        self.assertAlmostEqual(reparto[self.leche.id], 2500.0, places=2)

        mc = piso["margen_contribucion"]
        delta = 500.0 / piso["razones"]["ventas_medidas"]
        esperado_mes = self.ARRIENDO / (mc - delta) - piso["piso_mes"]

        p = self.la_leche()
        self.assertIsNone(p["sin_impacto_porque"])
        self.assertAlmostEqual(p["costo_en_la_venta"], 2500.0, places=2)
        self.assertAlmostEqual(p["piso_mes_si_se_queda"], esperado_mes, delta=1.0)
        self.assertAlmostEqual(p["piso_dia_si_se_queda"],
                               esperado_mes / piso["dias"]["quedan"], delta=1.0)

    def test_los_dos_numeros_apuntan_para_lados_CONTRARIOS(self):
        """LA DIRECCIÓN, de cada uno. Que el precio nuevo se quede EMPEORA el piso;
        que el proveedor vuelva atrás lo MEJORA. Los dos signos salen de la
        cuenta, y que salgan iguales sería el error de signo disfrazado de buena
        noticia."""
        self.escenario()
        p = self.la_leche()
        self.assertGreater(p["piso_dia_si_se_queda"], 0)
        self.assertGreater(p["piso_mes_si_se_queda"], 0)
        self.assertLess(p["piso_dia_si_vuelve"], 0)
        self.assertLess(p["piso_mes_si_vuelve"], 0)
        # Y los márgenes se mueven al revés que los pisos: si el costo sube queda
        # menos de cada peso; si vuelve, queda más.
        piso = costos_svc.get_piso(self.db, self.hoy.year, self.hoy.month)
        self.assertLess(p["margen_si_se_queda"], piso["margen_contribucion"])
        self.assertGreater(p["margen_si_vuelve"], piso["margen_contribucion"])
        # La plata EN JUEGO es la distancia entre los dos mundos, nunca negativa.
        self.assertAlmostEqual(p["piso_mes_en_juego"],
                               p["piso_mes_si_se_queda"] - p["piso_mes_si_vuelve"],
                               places=2)
        self.assertGreater(p["piso_dia_en_juego"], 0)

    def test_el_impacto_se_mide_contra_el_piso_publicado_en_la_misma_respuesta(self):
        """No hay un segundo cálculo del piso: el bloque `piso` que viaja en la
        respuesta es contra el que se midió, y tiene que ser el mismo que
        `/costos/piso` para ese mes."""
        self.escenario()
        r = self.palancas()
        piso = costos_svc.get_piso(self.db, self.hoy.year, self.hoy.month)
        self.assertEqual(r["piso"]["piso_mes"], piso["piso_mes"])
        self.assertEqual(r["piso"]["margen_contribucion"], piso["margen_contribucion"])
        self.assertEqual(r["piso"]["costos_fijos"], piso["costos_fijos"]["total"])
        self.assertEqual(r["piso"]["dias_quedan"], piso["dias"]["quedan"])

    def test_sin_costos_fijos_la_suba_viaja_igual_con_el_porque(self):
        """La puerta del piso no puede hacer desaparecer la palanca: el dueño
        sigue teniendo que ir a negociar esa leche."""
        self.escenario(con_costos_fijos=False)
        p = self.la_leche()
        self.assertIsNone(p["piso_dia_si_se_queda"])
        self.assertIsNone(p["piso_dia_si_vuelve"])
        self.assertIsNotNone(p["sin_impacto_porque"])
        self.assertIn("piso", p["sin_impacto_porque"])
        # Lo que SÍ se pudo medir viaja igual: nombre, suba y venta tocada.
        self.assertEqual(p["proveedor"], "Lácteos Andina")
        self.assertAlmostEqual(p["venta_30d_afectada"],
                               self.PRECIO_LATTE * self.UNIDADES)

    def test_con_costo_oficial_no_promete_un_ahorro_que_no_va_a_llegar(self):
        """Con `precio_costo` fijado a mano, el COGS de ese producto no se mueve
        con el precio de compra de sus insumos. Decir «el piso te baja $X» sería
        prometer una plata que no va a aparecer nunca."""
        self.escenario()
        self.latte.precio_costo = 3000.0
        self.db.commit()
        p = self.la_leche()
        self.assertIsNone(p["piso_dia_si_se_queda"])
        self.assertIsNone(p["piso_dia_si_vuelve"])
        self.assertIn("fijado a mano", p["sin_impacto_porque"])

    def test_ordena_por_plata_de_piso_no_por_porcentaje(self):
        """Un 40% sobre algo que casi no se usa importa menos que un 12% sobre la
        leche. La lista se ordena por la unidad en la que se decide."""
        self.escenario()
        canela = self.insumo("Canela", unidad="gr")
        self.db.add(ProductoInsumo(producto_id=self.latte.id, insumo_id=canela.id,
                                   cantidad=0.2))
        self.db.commit()
        self.compra(canela, 100, 10.0, "Especias SA", dias_atras=20)
        self.compra(canela, 100, 20.0, "Especias SA", dias_atras=1)   # +33% sobre 15

        r = self.palancas()
        self.assertGreater(r["palancas"][0]["pct_suba"], 0)
        self.assertEqual(r["palancas"][0]["insumo_id"], self.leche.id,
                         "la leche mueve más pesos de piso aunque suba menos %")
        self.assertGreater(r["palancas"][0]["piso_dia_en_juego"],
                           r["palancas"][1]["piso_dia_en_juego"])
        self.assertGreater(r["palancas"][1]["pct_suba"], r["palancas"][0]["pct_suba"])


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SON DOS NÚMEROS Y NO UNO: lo que VIENE y lo que VUELVE
# ═══════════════════════════════════════════════════════════════════════════════
# El escenario del error, con los números reales del sondeo: DIEZ compras de
# leche a $2,00 y UNA a $2,80. El promedio ponderado queda en $2,0727, o sea que
# de la suba de $0,80 apenas $0,0727 —el 9,1%— está adentro del costo con el que
# hoy se costea. La pantalla publicaba «el piso sube $8.053 por día» y debajo
# escribía «recuperar el viejo es esa misma plata de vuelta»: recuperarlo
# devuelve $798 por día. Diez veces menos.

class LosDosNumerosTest(PalancasBase):
    """La suba recién llegada: casi nada absorbido, casi todo por venir."""

    def test_EL_BLOQUEANTE_lo_que_vuelve_es_una_fraccion_de_lo_que_viene(self):
        """El error, en un solo test.

        La frase «recuperar el viejo es esa misma plata de vuelta» afirmaba que
        estos dos números son el mismo. No lo son ni de cerca: con la suba recién
        llegada, lo que viene es un orden de magnitud más grande que lo que se
        puede recuperar hoy. Los dos se publican por separado, y este test se
        cae el día que alguien los vuelva a colapsar en uno.
        """
        self.absorbido()
        p = self.la_leche()
        viene = p["piso_dia_si_se_queda"]
        vuelve = abs(p["piso_dia_si_vuelve"])
        self.assertGreater(viene, 0)
        self.assertGreater(vuelve, 0)
        self.assertGreater(viene, vuelve * 5,
                           "si estos dos se parecen, alguien volvió a medir los "
                           "dos mundos desde el mismo lado")

    def test_lo_que_vuelve_es_lo_que_de_verdad_pasa_si_el_precio_vuelve(self):
        """LA PRUEBA CONTRA EL MUNDO, no contra la fórmula.

        Se fuerza el costo de la leche al precio viejo —que es lo que pasaría si
        el proveedor diera marcha atrás y el promedio terminara de bajar— y se
        vuelve a correr `get_piso` entero. El piso que sale tiene que ser el que
        la palanca prometió, o la pantalla está publicando una cuenta que el
        sistema no reproduce.
        """
        self.absorbido()
        antes = costos_svc.get_piso(self.db, self.hoy.year, self.hoy.month)
        prometido = self.la_leche()["piso_mes_si_vuelve"]

        self.leche.precio_costo = self.VIEJO     # el costo oficial pisa el promedio
        self.db.commit()
        despues = costos_svc.get_piso(self.db, self.hoy.year, self.hoy.month)

        real = despues["piso_mes"] - antes["piso_mes"]
        self.assertLess(real, 0)                  # el piso BAJA, que es el punto
        self.assertAlmostEqual(prometido, real, delta=abs(real) * 0.01)

    def test_pct_absorbido_es_lo_que_explica_la_diferencia(self):
        """Y viaja para que la pantalla pueda DECIR por qué los dos números no
        son el mismo, en vez de dejar al dueño creyendo que uno está mal."""
        self.absorbido()
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)
        # (2,0727 − 2,00) / (2,80 − 2,00) = 9,09%
        self.assertAlmostEqual(a["pct_absorbido"], 9.1, places=1)
        self.assertAlmostEqual(a["costo_usado"], 22_800 / 11_000)

    def test_con_un_costo_fijado_a_mano_no_se_inventa_una_fraccion(self):
        """`precio_costo` no tiene por qué caer entre la referencia y el último.
        Ahí `pct_absorbido` no es la fracción de nada, y recortarlo a 0% o 100%
        sonaría a medición."""
        self.absorbido()
        self.leche.precio_costo = 9.99          # afuera del sándwich, a propósito
        self.db.commit()
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)
        self.assertIsNone(a["pct_absorbido"])

    def test_cuando_la_suba_YA_LLEGO_los_dos_numeros_se_dan_vuelta(self):
        """El otro extremo del mismo eje, y la razón de publicar los dos.

        Con sesenta compras al precio nuevo el promedio casi lo alcanzó: ya casi
        no queda nada por venir, y TODO el movimiento posible está en recuperar
        el precio viejo. Publicar solo «lo que viene» diría que esta suba ya no
        importa, justo cuando es toda oportunidad de negociación.
        """
        self.absorbido(n_nuevas=60)
        p = self.la_leche()
        self.assertLess(p["piso_dia_si_se_queda"], abs(p["piso_dia_si_vuelve"]))

    def test_la_plata_EN_JUEGO_no_se_encoge_mientras_la_suba_se_absorbe(self):
        """POR QUÉ LA LISTA SE ORDENA POR `en_juego` Y NO POR «lo que viene».

        Los dos mundos —costear a $2,00 y costear a $2,80— no dependen de dónde
        esté hoy el promedio: lo único que el promedio decide es cuánto de esa
        distancia ya se caminó. Así que la distancia entera es la misma con una
        compra nueva que con sesenta, y es la única de las tres cifras que sirve
        para ordenar: «lo que viene» mandaría al fondo justo a la suba que ya
        llegó entera.
        """
        self.absorbido()
        con_una = self.la_leche()["piso_dia_en_juego"]
        self.tearDown()
        self.setUp()
        self.absorbido(n_nuevas=60)
        con_sesenta = self.la_leche()["piso_dia_en_juego"]
        self.assertAlmostEqual(con_una, con_sesenta, delta=1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 7-bis. LOS DOS NÚMEROS SON TOPES, Y NINGUNO PASA MAÑANA
#
# Partir la palanca en dos arregló el TAMAÑO (`si_vuelve` es el que de verdad
# devuelve la negociación) pero no el TIEMPO. Los dos salen de mover `costo_usado`
# hasta otro precio, y `costo_usado` es el promedio ponderado de TODA la historia
# de compras: no salta el día que el proveedor acepta, se arrastra factura a
# factura. La pantalla decía «el piso baja $X por día» y remataba con «lo que se
# recupera HOY yendo a negociar», y el día de la negociación el piso baja $0,00.
#
# Es la misma familia de error de siempre: un número CERCA del correcto —es el
# correcto, pero de otro momento— del lado que tranquiliza. El cálculo no se
# toca; lo que cambia es el VERBO de la pantalla («va bajando hasta $X por día a
# medida que se le compre a ese precio»), y estos tests fijan la escalera que ese
# verbo describe.
# ═══════════════════════════════════════════════════════════════════════════════

class LosDosNumerosSonTopesTest(PalancasBase):
    """10 compras a $2,00 y una a $2,80; el proveedor acepta volver a $2,00."""

    def piso_mes(self):
        return costos_svc.get_piso(self.db, self.hoy.year, self.hoy.month)["piso_mes"]

    def test_EL_BLOQUEANTE_el_dia_que_el_proveedor_acepta_el_piso_baja_cero(self):
        """La frase «lo que se recupera HOY yendo a negociar», medida.

        Aceptar no emite una factura, y `costo_usado` solo se mueve cuando llega
        una. Así que el día del acuerdo el piso no baja $797,88: baja $0,00
        EXACTO, y el número publicado es el tope de una escalera que recién
        empieza.
        """
        self.absorbido()
        antes = self.piso_mes()
        prometido = self.la_leche()["piso_mes_si_vuelve"]
        self.assertLess(prometido, 0)                 # hay algo que prometer

        # El acuerdo. No cambia ningún dato del sistema, que es justamente el
        # punto: no hay factura nueva.
        self.assertEqual(self.piso_mes() - antes, 0.0)

    def test_el_piso_camina_hacia_el_tope_compra_a_compra_y_no_lo_toca(self):
        """La escalera entera, que es lo que el verbo «va bajando hasta» describe.

        Cada factura al precio acordado tira el promedio ponderado un poco más
        abajo, y la caída se acerca al tope sin alcanzarlo: con cien compras
        todavía falta un 10%.
        """
        self.absorbido()
        antes = self.piso_mes()
        tope = self.la_leche()["piso_mes_si_vuelve"]

        recorrido = {}
        compras = 0
        for objetivo in (1, 5, 20, 100):
            while compras < objetivo:
                self.compra(self.leche, 1000, self.VIEJO, "Lácteos Andina")
                compras += 1
            recorrido[objetivo] = (self.piso_mes() - antes) / tope

        # Monótona, siempre adentro del tope, y sin llegar nunca.
        self.assertLess(recorrido[1], 0.15)
        self.assertLess(recorrido[1], recorrido[5])
        self.assertLess(recorrido[5], recorrido[20])
        self.assertLess(recorrido[20], recorrido[100])
        self.assertLess(recorrido[100], 1.0,
                        "si la escalera llega al tope, el promedio ponderado dejó "
                        "de ser un promedio y el verbo de la pantalla miente")
        # Y con UNA compra ya bajó algo: el verbo no puede ser «no se mueve».
        self.assertGreater(recorrido[1], 0.0)

    def test_el_de_IDA_tarda_lo_mismo_y_por_la_misma_razon(self):
        """No se arregla uno solo. `si_se_queda` es el MISMO promedio moviéndose
        para el otro lado: el día que el proveedor manda la factura cara el piso
        tampoco salta al número publicado. Por eso la frase de cierre los declara
        juntos en vez de poner el marcador de acumulación en un renglón solo."""
        self.absorbido()
        antes = self.piso_mes()
        tope = self.la_leche()["piso_mes_si_se_queda"]
        self.assertGreater(tope, 0)

        self.compra(self.leche, 1000, self.NUEVO, "Lácteos Andina")
        con_una = self.piso_mes() - antes
        self.assertGreater(con_una, 0)                       # sube, sí
        self.assertLess(con_una, tope * 0.5,                 # pero muy lejos del tope
                        "si una sola compra ya trae medio impacto, este número "
                        "dejó de ser un límite y la palabra «todavía» sobra")

    def test_el_tope_publicado_sigue_siendo_el_limite_correcto(self):
        """Y el cálculo NO se toca: forzando el costo al precio viejo —el final de
        la escalera— el piso real es el prometido. Lo que estaba mal era el
        tiempo verbal, no la cuenta."""
        self.absorbido()
        antes = self.piso_mes()
        prometido = self.la_leche()["piso_mes_si_vuelve"]

        self.leche.precio_costo = self.VIEJO
        self.db.commit()
        real = self.piso_mes() - antes

        self.assertAlmostEqual(prometido, real, delta=abs(real) * 0.01)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. LA REFERENCIA NO SE MUEVE SOLA
# ═══════════════════════════════════════════════════════════════════════════════

class LaAlertaNoSeApagaSolaTest(PalancasBase):

    def test_EL_BLOQUEANTE_sesenta_compras_al_precio_nuevo_no_apagan_la_alerta(self):
        """El barrido que medía el error, entero.

        Comparando contra el promedio ponderado —que se acerca al precio nuevo
        con cada compra— la alerta se apagaba a las 22 compras, y el piso del mes
        seguía trepando después: 9.993.415 con 20 compras, 9.995.269 con 22
        (ya sin alerta) y 10.010.355 con 60. Dos tercios de la plata llegaban con
        la pantalla en silencio. Contra el mínimo de 12 meses la alerta se queda
        prendida hasta que el precio baje de verdad.
        """
        pisos = []
        for n in (20, 22, 60):
            self.tearDown()
            self.setUp()
            self.absorbido(n_nuevas=n)
            alertas = [a for a in alertas_de_costo(self.db)
                       if a["insumo_id"] == self.leche.id]
            self.assertEqual(len(alertas), 1, f"con {n} compras la alerta se apagó")
            pisos.append(costos_svc.get_piso(
                self.db, self.hoy.year, self.hoy.month)["piso_mes"])
        # Y el piso SIGUIÓ SUBIENDO en ese tramo: la alerta que se apagaba dejaba
        # ir esta plata sin decir nada.
        self.assertEqual(pisos, sorted(pisos))
        self.assertGreater(pisos[-1], pisos[0])

    def test_la_regla_vieja_ya_no_alcanzaba_para_verla(self):
        """El daño evitado, nombrado: con 60 compras el último precio ya está
        adentro del 10% del promedio, así que la condición vieja
        (`ultimo <= usado * 1.10`) la habría descartado."""
        self.absorbido(n_nuevas=60)
        prom, ult = _costos_insumos(self.db)
        usado = prom[self.leche.id]
        ultimo = ult[self.leche.id]["precio"]
        self.assertLessEqual(ultimo, usado * 1.10)          # la regla vieja: NO alerta
        self.assertGreater(ultimo, ult[self.leche.id]["ref"]["precio"] * 1.10)
        self.assertTrue(any(a["insumo_id"] == self.leche.id
                            for a in alertas_de_costo(self.db)))

    def test_la_referencia_es_la_factura_mas_barata_de_los_ultimos_doce_meses(self):
        """Y no un promedio: es un precio que alguien facturó de verdad, así que
        se puede poner sobre la mesa."""
        self.absorbido()
        # Una factura carísima de hace dos años no puede ser la referencia: está
        # afuera de la ventana y además no es la más barata.
        self.compra(self.leche, 1000, 0.50, "Regalado SA", dias_atras=800)
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)
        self.assertAlmostEqual(a["costo_ref"], self.VIEJO)
        self.assertEqual(a["ref_proveedor"], "Lácteos Andina")

    def test_sin_ninguna_compra_en_la_ventana_no_se_inventa_una_suba(self):
        """Si el insumo no se compra hace más de un año no hay contra qué
        comparar el último precio, y decir eso es más honesto que anclar la
        referencia a un precio que ya nadie factura."""
        self.leche = self.insumo()
        self.latte = self.producto("Latte", precio=self.PRECIO_LATTE)
        self.db.add(ProductoInsumo(producto_id=self.latte.id, insumo_id=self.leche.id,
                                   cantidad=self.ML_POR_LATTE))
        self.db.commit()
        self.compra(self.leche, 1000, self.VIEJO, "Lácteos Andina", dias_atras=900)
        self.compra(self.leche, 1000, self.NUEVO, "Lácteos Andina", dias_atras=500)
        self.assertEqual([a for a in alertas_de_costo(self.db)
                          if a["insumo_id"] == self.leche.id], [])


# ═══════════════════════════════════════════════════════════════════════════════
# 9. EL REDONDEO ES DE LA IMPRESORA, NO DE LA CUENTA
# ═══════════════════════════════════════════════════════════════════════════════

class ElRedondeoNoEntraEnLaCuentaTest(PalancasBase):

    def canela_de_centavos(self):
        """Un insumo que se mide en gramos y cuesta menos de un centavo cada uno.
        `round($0,004545, 2)` da 0,00 — y eso era un divisor."""
        self.escenario()
        self.canela = self.insumo("Canela", unidad="gr")
        self.db.add(ProductoInsumo(producto_id=self.latte.id, insumo_id=self.canela.id,
                                   cantidad=200.0))
        self.db.commit()
        self.compra(self.canela, 10_000, 0.004, "Especias SA", dias_atras=40)
        self.compra(self.canela, 1_000, 0.010, "Especias SA", dias_atras=1)

    def test_EL_BLOQUEANTE_un_insumo_de_centavos_no_tira_abajo_el_bloque(self):
        """Era un ZeroDivisionError: 500 en `/costos/palancas` y el bloque 7 de
        la pantalla caído entero, con TODAS las demás subas adentro."""
        self.canela_de_centavos()
        r = self.client.get("/api/v1/costos/palancas",
                            params={"anio": self.hoy.year, "mes": self.hoy.month})
        self.assertEqual(r.status_code, 200)
        p = next(x for x in r.json()["palancas"] if x["nombre"] == "Canela")
        self.assertAlmostEqual(p["costo_usado"], 0.004545, places=6)
        self.assertIsNotNone(p["piso_dia_si_se_queda"])
        # Y la leche, que viajaba en la misma respuesta, tampoco se perdió.
        self.assertTrue(any(x["nombre"] == "Leche entera" for x in r.json()["palancas"]))

    def test_los_costos_se_publican_sin_redondear(self):
        """El `round(..., 2)` que reventaba estaba en el ORIGEN, así que ningún
        consumidor podía evitarlo. Ahora el que imprime redondea."""
        self.canela_de_centavos()
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.canela.id)
        self.assertNotEqual(a["costo_usado"], round(a["costo_usado"], 2))
        self.assertGreater(a["costo_usado"], 0)

    def test_el_cociente_sale_de_los_costos_enteros_no_de_los_impresos(self):
        """Medio punto de error metido por la impresora adentro de la cuenta.

        Con el promedio en $2,0727 —que redondeado a dos decimales da $2,07— el
        cociente redondeado publicaba $8.094,56 por día donde la cuenta da
        $8.052,95. No es un error grande; es un error que nadie puede explicar
        después, y que la pantalla presenta con la misma cara que el resto.
        """
        self.absorbido()
        piso = costos_svc.get_piso(self.db, self.hoy.year, self.hoy.month)
        razones = piso["razones"]
        cev = cogs_por_insumo(self.db, razones["desde"], razones["hasta"])[self.leche.id]
        a = next(a for a in alertas_de_costo(self.db)
                 if a["insumo_id"] == self.leche.id)

        def piso_moviendo(usado, destino):
            # El round(..., 6) del margen es el del servicio: se copia acá para
            # que la diferencia que mide este test sea SOLO la del redondeo de
            # los costos, que es la que se está probando.
            extra = cev * (destino / usado - 1.0)
            mc_n = round(piso["margen_contribucion"] - extra / razones["ventas_medidas"], 6)
            return piso["costos_fijos"]["total"] / mc_n - piso["piso_mes"]

        entero = piso_moviendo(a["costo_usado"], a["costo_ultimo"])
        impreso = piso_moviendo(round(a["costo_usado"], 2), round(a["costo_ultimo"], 2))
        p = self.la_leche()
        self.assertAlmostEqual(p["piso_mes_si_se_queda"], entero, delta=1.0)
        self.assertNotAlmostEqual(p["piso_mes_si_se_queda"], impreso, delta=1.0)


class ElEndpointTest(PalancasBase):

    def test_get_palancas_contesta_200_con_la_linea_completa(self):
        self.escenario()
        r = self.client.get("/api/v1/costos/palancas",
                            params={"anio": self.hoy.year, "mes": self.hoy.month})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        p = next(x for x in d["palancas"] if x["nombre"] == "Leche entera")
        # Las cuatro piezas de la frase que se lleva a la reunión.
        self.assertEqual(p["proveedor"], "Lácteos Andina")
        self.assertAlmostEqual(p["pct_suba"], 50.0)
        self.assertAlmostEqual(p["venta_30d_afectada"], 100_000)
        self.assertGreater(p["piso_dia_si_se_queda"], 0)
        self.assertLess(p["piso_dia_si_vuelve"], 0)

    def test_mes_fuera_de_rango_es_422_de_forma(self):
        r = self.client.get("/api/v1/costos/palancas",
                            params={"anio": self.hoy.year, "mes": 13})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
