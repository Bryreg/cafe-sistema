"""EL PISO: cuánto hay que vender este mes para no perder plata.

    piso del mes = costos fijos del MES COMPLETO / margen de contribución
    falta        = piso del mes − lo vendido en el mes a la fecha
    piso de hoy  = falta / los días que QUEDAN por abrir

Lo que fija este archivo, y por qué cada cosa importa:

1. LA VENTANA DEL NUMERADOR. Los costos fijos se piden por el mes ENTERO. El
   arriendo y la nómina se devengan a fin de mes y la pantalla pide el P&L con
   `hasta = hoy`: con esa ventana el numerador vuelve casi vacío a principios de
   mes y el piso sale ridículamente bajo justo cuando todavía se puede hacer
   algo. Es el bug más fácil de reintroducir de todo el cálculo.
2. EL PISO DEL DÍA NO ES EL DEL MES DIVIDIDO PLANO. Descuenta lo ya vendido y
   reparte el resto entre los días que faltan: si el mes viene atrasado, SUBE.
3. LAS CUATRO PUERTAS DE HONESTIDAD, una por una, incluido el veredicto de
   margen no positivo — que no es falta de datos, es una respuesta.
4. EL TITULAR Y EL PISO DEL DÍA SALEN DE LOS MISMOS DOS NÚMEROS. Dos cuentas
   distintas se contradicen en la misma pantalla.
5. EL PISO DE CAJA es la columna de repuesto y, cuando existen los dos, MANDA EL
   MÁS ALTO. Cubrir el más chico y creer que alcanza es el error tranquilizador.
6. NO SE SUMA EL IMPOCONSUMO DOS VECES. Como el impuesto ya está restado del
   margen, el piso queda en pesos COBRADOS y no se le vuelve a sumar.
7. LOS DÍAS QUE ABRE EL LOCAL SE DERIVAN, no se preguntan: una sede que cierra
   los domingos no cuenta los domingos.

Todo el archivo trabaja contra `hoy_col()` real, así que las expectativas se
derivan del mismo calendario en vez de quemar fechas: un test que solo pasa la
primera quincena no prueba nada el 28.
"""
import calendar
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base, get_db
from app.models.models import (CajaTurno, CategoriaProductoEnum, Configuracion,
                               CostoCategoria, EstadoTurnoEnum, FacturaCompra,
                               Obligacion, Producto, RolEnum, Ticket,
                               TicketItem, Tienda, TipoPagoEnum, Usuario)
from app.routers import costos as costos_router
from app.services import costos as svc
from app.services.rentabilidad import costos_fijos_del_mes, get_rentabilidad

# La tarifa sembrada (`parametros_tributarios.SIEMBRA`): 8% con el precio de la
# carta CON el impuesto adentro, o sea 7,41% de cada peso cobrado.
TASA_IMPO = 0.08
I_MEDIDO = 1 - 1 / (1 + TASA_IMPO)


def ultimo_dia(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def mediodia(d: date) -> datetime:
    """Instante UTC del mediodía Colombia de ese día — bien adentro del día."""
    return inicio_dia_col_utc(d) + timedelta(hours=12)


class PisoBase(unittest.TestCase):
    """sqlite temporal + router real de costos (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False,
                                         bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.hoy = hoy_col()
        self.dia1 = self.hoy.replace(day=1)
        self.fin_mes = ultimo_dia(self.hoy)

        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.tienda.id,
                               usuario_apertura_id=self.admin.id,
                               base_real=0.0, estado=EstadoTurnoEnum.cerrado,
                               fecha_cierre=mediodia(self.hoy),
                               efectivo_final_real=0.0)
        self.db.add(self.turno)
        self.cat_fijo = CostoCategoria(clave="arriendo", nombre="Arriendo",
                                       grupo="fijo", orden=0)
        self.cat_var = CostoCategoria(clave="insumos", nombre="Insumos",
                                      grupo="variable", orden=1)
        self.db.add_all([self.cat_fijo, self.cat_var])
        self.db.commit()

        app = FastAPI()
        app.include_router(costos_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Ayudantes de datos ───────────────────────────────────────────────────

    def producto(self, nombre="Americano", precio=5000, costo=None) -> Producto:
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.bebida,
                     unidad_medida="unidad", precio_venta=precio,
                     precio_costo=costo)
        self.db.add(p)
        self.db.commit()
        return p

    def venta(self, dia: date, total: float, producto=None, tarjeta=0.0) -> Ticket:
        """Un ticket cobrado ese día. Con `producto` lleva ítem y entra al COGS."""
        t = Ticket(tienda_id=self.tienda.id, caja_turno_id=self.turno.id,
                   usuario_id=self.admin.id, fecha=mediodia(dia), total=total,
                   estado="completado",
                   metodo_pago="tarjeta" if tarjeta >= total else "efectivo",
                   monto_efectivo=round(total - tarjeta, 2), monto_tarjeta=tarjeta)
        self.db.add(t)
        self.db.flush()
        if producto is not None:
            self.db.add(TicketItem(ticket_id=t.id, producto_id=producto.id,
                                   nombre_producto=producto.nombre, cantidad=1,
                                   precio_unitario=total, subtotal=total))
        self.db.commit()
        return t

    def obligacion(self, monto: float, devengo: date, categoria=None,
                   vencimiento=None) -> Obligacion:
        o = Obligacion(categoria_id=(categoria or self.cat_fijo).id,
                       tienda_id=None, concepto="Arriendo", monto=monto,
                       fecha_devengo=devengo, fecha_vencimiento=vencimiento,
                       usuario_id=self.admin.id, anulada=False)
        self.db.add(o)
        self.db.commit()
        return o

    def factura(self, total: float, vence: date):
        f = FacturaCompra(tienda_id=self.tienda.id, proveedor="Lácteos",
                          valor_total=total, valor_pagado=0,
                          tipo_pago=TipoPagoEnum.credito, usuario_id=self.admin.id,
                          fecha_recibido=mediodia(self.hoy),
                          fecha_vencimiento=mediodia(vence))
        self.db.add(f)
        self.db.commit()
        return f

    def historia_de_ventas(self, cerrado_los=(6,), monto=200000.0):
        """8 semanas de venta previas, saltando los días de semana de `cerrado_los`.

        Es lo que hace que `_venta_esperada_por_dia_semana` tenga muestras y que
        los días que abre el local se puedan DERIVAR. Arranca en hoy-1 porque hoy
        queda fuera de esa ventana a propósito.

        SE FRENA EN EL DÍA 1 DEL MES EN CURSO, y no es cosmético: la venta del
        mes es el otro término de la resta que arma el titular, y si la historia
        la ensuciara, cada test tendría que descontar un ruido que no eligió.
        Los días previos alcanzan igual para tener muestras de los siete días de
        la semana en cualquier fecha del mes.
        """
        for n in range(1, 57):
            d = self.hoy - timedelta(days=n)
            if d >= self.dia1 or d.weekday() in cerrado_los:
                continue
            self.venta(d, monto)

    def piso(self, anio=None, mes=None) -> dict:
        return svc.get_piso(self.db, anio or self.hoy.year, mes or self.hoy.month)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LA VENTANA DEL NUMERADOR
# ═══════════════════════════════════════════════════════════════════════════════

class VentanaDelNumeradorTest(PisoBase):

    def test_el_mismo_mes_con_hasta_hoy_y_con_hasta_fin_de_mes_da_costo_fijo_distinto(self):
        """El bug más fácil de reintroducir, medido sobre un mes YA CERRADO.

        Se usa un mes pasado a propósito: así la ventana recortada es una fecha
        fija y el test no depende de qué día del mes se corra.
        """
        fin_pasado = self.dia1 - timedelta(days=1)
        ini_pasado = fin_pasado.replace(day=1)
        mitad = ini_pasado + timedelta(days=14)
        self.obligacion(500_000, ini_pasado + timedelta(days=4))   # dentro de la mitad
        self.obligacion(9_000_000, fin_pasado)                     # el arriendo de fin de mes

        parcial = get_rentabilidad(self.db, ini_pasado, mitad)
        completo = costos_fijos_del_mes(self.db, ini_pasado.year, ini_pasado.month)

        self.assertEqual(parcial["resumen"]["costos_fijos_devengados"], 500_000)
        self.assertEqual(completo["costos_fijos_devengados"], 9_500_000)
        self.assertNotEqual(parcial["resumen"]["costos_fijos_devengados"],
                            completo["costos_fijos_devengados"])
        # 19 veces más chico: con la ventana recortada el piso saldría 19 veces
        # más bajo, y hacia el lado tranquilizador.
        self.assertLess(parcial["resumen"]["costos_fijos_devengados"],
                        completo["costos_fijos_devengados"])

    def test_el_piso_usa_la_ventana_del_mes_completo(self):
        """No alcanza con que la función exista: el piso tiene que USARLA."""
        self.obligacion(9_000_000, self.fin_mes)
        self.historia_de_ventas()
        self.venta(self.hoy, 100_000)

        data = self.piso()
        self.assertEqual(data["costos_fijos"]["desde"], self.dia1)
        self.assertEqual(data["costos_fijos"]["hasta"], self.fin_mes)
        self.assertEqual(data["costos_fijos"]["total"], 9_000_000)
        self.assertEqual(
            data["costos_fijos"]["total"],
            costos_fijos_del_mes(self.db, self.hoy.year,
                                 self.hoy.month)["costos_fijos_devengados"])

    def test_el_costo_variable_no_entra_al_numerador(self):
        """El piso lo arman los costos FIJOS. Un costo que sube con la venta no
        es una obligación mensual, es una tasa, y ya está adentro del margen."""
        self.obligacion(1_000_000, self.fin_mes)
        self.obligacion(4_000_000, self.fin_mes, categoria=self.cat_var)
        self.assertEqual(self.piso()["costos_fijos"]["total"], 1_000_000)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. EL PISO DEL DÍA NO ES EL DEL MES DIVIDIDO PLANO
# ═══════════════════════════════════════════════════════════════════════════════

class PisoDelDiaTest(PisoBase):

    def setUp(self):
        super().setUp()
        self.obligacion(6_000_000, self.fin_mes)
        self.historia_de_ventas()

    def test_el_piso_del_dia_sube_si_se_viene_atrasado(self):
        """MISMO piso mensual, MENOS vendido → más plata por día que queda.

        Un mensual repartido en partes iguales no depende de lo vendido y daría
        el mismo número en los dos casos: una cifra tranquilizadora y falsa.
        """
        self.venta(self.hoy, 400_000)
        atrasado = self.piso()

        self.venta(self.hoy, 1_600_000)          # ahora lleva 2.000.000 vendidos
        al_dia = self.piso()

        self.assertEqual(atrasado["piso_mes"], al_dia["piso_mes"])
        self.assertGreater(atrasado["piso_hoy"], al_dia["piso_hoy"])
        # La diferencia es exactamente la venta extra repartida entre los días
        # que quedan: no hay ningún otro término escondido.
        dias = al_dia["dias"]["quedan"]
        self.assertAlmostEqual(atrasado["piso_hoy"] - al_dia["piso_hoy"],
                               1_600_000 / dias, places=1)

    def test_el_piso_del_dia_cierra_la_cuenta_del_mes(self):
        """piso_hoy × días que quedan + lo ya vendido == piso del mes."""
        self.venta(self.hoy, 900_000)
        d = self.piso()
        dias = d["dias"]["quedan"]
        self.assertAlmostEqual(d["piso_hoy"] * dias + d["ventas_mes"],
                               d["piso_mes"], places=0)

    def test_no_es_el_piso_mensual_repartido_plano(self):
        """El reparto plano ignora lo vendido; este no."""
        self.venta(self.hoy, 900_000)
        d = self.piso()
        todo_el_mes = svc.dias_que_abre(self.db, self.dia1, self.fin_mes)["dias"]
        plano = round(d["piso_mes"] / todo_el_mes, 2)
        self.assertNotEqual(d["piso_hoy"], plano)

    def test_un_mes_ya_cerrado_no_tiene_piso_por_dia_pero_si_tiene_falta(self):
        """Sin días que queden no hay «por día». `falta` sigue siendo verdad."""
        fin_pasado = self.dia1 - timedelta(days=1)
        ini_pasado = fin_pasado.replace(day=1)
        self.obligacion(3_000_000, fin_pasado)
        self.venta(fin_pasado, 500_000)

        d = self.piso(ini_pasado.year, ini_pasado.month)
        self.assertEqual(d["dias"]["quedan"], 0)
        self.assertIsNone(d["piso_hoy"])
        self.assertIsNotNone(d["falta"])
        # Las razones de un mes cerrado son las SUYAS, no prestadas — y el rótulo
        # dice «mes_pedido» y no «mes_actual» justamente porque no es agosto.
        self.assertEqual(d["razones"]["de"], "mes_pedido")
        # La venta del mes cerrado es la SUYA (la historia de 8 semanas también
        # cae ahí), y se le resta al piso igual que en el mes en curso.
        self.assertGreaterEqual(d["ventas_mes"], 500_000)
        self.assertEqual(d["falta"], round(d["piso_mes"] - d["ventas_mes"], 2))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. LAS CUATRO PUERTAS DE HONESTIDAD
# ═══════════════════════════════════════════════════════════════════════════════

class PuertasTest(PisoBase):

    def test_puerta_1_sin_costos_fijos_no_hay_piso_de_resultado_pero_si_de_caja(self):
        """El hueco CON NOMBRE. Un $0 acá se leería como «ya está cubierto»."""
        self.historia_de_ventas()
        self.venta(self.hoy, 300_000)
        self.factura(2_000_000, vence=self.hoy + timedelta(days=1))

        d = self.piso()
        self.assertEqual(d["puerta"], svc.PUERTA_SIN_COSTOS_FIJOS)
        self.assertFalse(d["costos_fijos"]["hay"])
        self.assertEqual(d["costos_fijos"]["n"], 0)
        self.assertIsNone(d["piso_mes"])
        self.assertIsNone(d["piso_hoy"])
        # El repuesto sí contesta: no necesita costeo de producto ni margen.
        self.assertIsNotNone(d["piso_caja"]["por_dia"])
        self.assertEqual(d["manda"], "caja")

    def test_puerta_2_sin_venta_en_el_mes_usa_las_razones_del_mes_anterior_y_lo_rotula(self):
        """Sin venta no hay cociente. Se pide prestado y se DICE."""
        fin_pasado = self.dia1 - timedelta(days=1)
        p = self.producto(costo=1000)
        self.venta(fin_pasado, 4000, producto=p)
        self.obligacion(2_000_000, self.fin_mes)

        d = self.piso()
        self.assertEqual(d["puerta"], svc.PUERTA_RAZONES_DEL_MES_ANTERIOR)
        self.assertEqual(d["razones"]["de"], "mes_anterior")
        self.assertEqual(d["razones"]["hasta"], fin_pasado)
        self.assertIsNotNone(d["piso_mes"])
        # La venta del mes ANTERIOR no se le resta al piso de ESTE mes: las
        # razones se piden prestadas, la plata no.
        self.assertEqual(d["ventas_mes"], 0.0)
        self.assertEqual(d["falta"], d["piso_mes"])

    def test_puerta_2b_sin_venta_ni_este_mes_ni_el_anterior_solo_queda_el_piso_de_caja(self):
        self.obligacion(2_000_000, self.fin_mes)
        self.factura(500_000, vence=self.hoy + timedelta(days=2))

        d = self.piso()
        self.assertEqual(d["puerta"], svc.PUERTA_SIN_RAZONES)
        self.assertIsNone(d["razones"])
        self.assertIsNone(d["margen_contribucion"])
        self.assertIsNone(d["piso_mes"])
        self.assertEqual(d["sesgos"], [])
        self.assertIsNotNone(d["piso_caja"]["por_dia"])
        self.assertEqual(d["manda"], "caja")

    def test_puerta_3_margen_no_positivo_es_un_veredicto_no_un_dato_que_falta(self):
        """Costo por encima del precio: cada venta pierde plata. Se dice plano."""
        self.historia_de_ventas()
        p = self.producto(precio=5000, costo=5200)
        self.obligacion(2_000_000, self.fin_mes)
        self.venta(self.hoy, 5000, producto=p)

        d = self.piso()
        self.assertEqual(d["puerta"], svc.PUERTA_MARGEN_NO_POSITIVO)
        self.assertLessEqual(d["margen_contribucion"], 0)
        self.assertIsNone(d["piso_mes"])
        # El margen medido SÍ viaja: el veredicto tiene que poder explicarse.
        self.assertGreater(d["razones"]["cogs"], 1.0)

    def test_puerta_4_el_numero_se_publica_igual_con_el_costeo_a_medias(self):
        """NO hay portón en `pct_venta_costeada`: la columna vertebral de la
        pantalla no puede desaparecer porque el costeo esté al 50%."""
        self.historia_de_ventas()
        p = self.producto(precio=5000, costo=1000)
        # Sin costo cargado: su venta entra al denominador de la cobertura y su
        # costo al margen valiendo $0. Es el sesgo, no un caso de laboratorio.
        q = self.producto("Torta", precio=5000, costo=None)
        self.obligacion(2_000_000, self.fin_mes)
        self.venta(self.hoy, 5000, producto=p)   # costeada
        self.venta(self.hoy, 5000, producto=q)   # sin costo cargado

        d = self.piso()
        self.assertEqual(d["puerta"], svc.PUERTA_OK)
        self.assertIsNotNone(d["piso_mes"])
        self.assertIsNotNone(d["piso_hoy"])
        self.assertEqual(d["rotulo"], "al_menos")
        # El porcentaje decide las PALABRAS, nunca si el número existe.
        self.assertLess(d["razones"]["pct_venta_costeada"], 100)

    def test_los_cuatro_sesgos_viajan_y_todos_bajan_el_piso(self):
        self.historia_de_ventas()
        p = self.producto(precio=5000, costo=1000)
        q = self.producto("Torta", precio=5000, costo=None)
        self.obligacion(2_000_000, self.fin_mes)
        self.venta(self.hoy, 5000, producto=p)
        # Sin costo cargado Y cobrada con datáfono: los cuatro sesgos vivos.
        self.venta(self.hoy, 5000, producto=q, tarjeta=5000)

        d = self.piso()
        claves = {s["clave"] for s in d["sesgos"]}
        self.assertEqual(claves, {"productos_sin_costo", "costeo_parcial",
                                  "desechables_fuera_del_costo",
                                  "comision_datafono_sin_cargar"})
        self.assertTrue(all(s["activo"] for s in d["sesgos"]))
        # La comisión no cargada se puede nombrar con su tamaño: la mitad de la
        # venta entró por datáfono y esa comisión no está adentro del margen.
        comision = next(s for s in d["sesgos"]
                        if s["clave"] == "comision_datafono_sin_cargar")
        self.assertAlmostEqual(comision["detalle"]["pct_tarjeta"], 0.5, places=3)
        self.assertEqual(d["razones"]["comision"], 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. EL TITULAR Y EL PISO SALEN DE LOS MISMOS DOS NÚMEROS
# ═══════════════════════════════════════════════════════════════════════════════

class TitularTest(PisoBase):

    def test_el_titular_no_es_un_segundo_calculo(self):
        self.historia_de_ventas()
        self.obligacion(5_000_000, self.fin_mes)
        self.venta(self.hoy, 700_000)

        d = self.piso()
        self.assertEqual(d["titular"]["falta"], d["falta"])
        self.assertEqual(d["titular"]["por_dia"], d["piso_hoy"])
        self.assertEqual(d["falta"], round(d["piso_mes"] - d["ventas_mes"], 2))
        self.assertEqual(d["piso_hoy"],
                         round(d["falta"] / d["dias"]["quedan"], 2))

    def test_pasado_el_piso_falta_es_negativo_y_no_se_recorta_en_cero(self):
        """El dueño tiene derecho a ver por cuánto lo pasó."""
        self.historia_de_ventas()
        self.obligacion(100_000, self.fin_mes)
        self.venta(self.hoy, 5_000_000)

        d = self.piso()
        self.assertLess(d["falta"], 0)
        self.assertTrue(d["cubierto"])
        self.assertEqual(d["titular"]["falta"], d["falta"])


# ═══════════════════════════════════════════════════════════════════════════════
# 5. EL PISO DE CAJA Y QUIÉN MANDA
# ═══════════════════════════════════════════════════════════════════════════════

class PisoDeCajaTest(PisoBase):

    def test_el_piso_de_caja_no_necesita_costeo_de_producto(self):
        """Es el repuesto para cuando falta el costeo: sale de la agenda y de la
        plata que hay, sin margen ni recetas."""
        self.historia_de_ventas()
        self.factura(3_000_000, vence=self.hoy + timedelta(days=3))

        d = self.piso()
        dias = d["dias"]["quedan"]
        self.assertEqual(d["piso_caja"]["salidas_agendadas"], 3_000_000)
        self.assertEqual(d["piso_caja"]["del_mes"], 3_000_000)   # caja en 0, reserva en 0
        self.assertEqual(d["piso_caja"]["por_dia"], round(3_000_000 / dias, 2))

    def test_lo_vencido_entra_al_piso_de_caja(self):
        """Se debe AHORA: dejarlo afuera haría desaparecer la mora del piso."""
        self.historia_de_ventas()
        self.factura(1_000_000, vence=self.hoy - timedelta(days=10))
        d = self.piso()
        self.assertEqual(d["piso_caja"]["salidas_agendadas"], 1_000_000)
        self.assertEqual(d["piso_caja"]["vencido"], 1_000_000)

    def test_la_reserva_sube_el_piso_de_caja_y_el_default_se_declara(self):
        self.historia_de_ventas()
        self.factura(1_000_000, vence=self.hoy + timedelta(days=2))

        sin_reserva = self.piso()
        self.assertTrue(sin_reserva["piso_caja"]["reserva_es_default"])
        self.assertEqual(sin_reserva["piso_caja"]["reserva"], 0.0)

        svc.guardar_reserva_minima_caja(self.db, 2_000_000, self.admin.id)
        con_reserva = self.piso()
        self.assertFalse(con_reserva["piso_caja"]["reserva_es_default"])
        self.assertEqual(con_reserva["piso_caja"]["del_mes"], 3_000_000)
        self.assertGreater(con_reserva["piso_caja"]["por_dia"],
                           sin_reserva["piso_caja"]["por_dia"])

    def test_manda_el_mas_alto_y_el_de_abajo_se_nombra(self):
        """Con los dos vivos gana el más exigente."""
        self.historia_de_ventas()
        self.obligacion(300_000, self.fin_mes)       # piso de resultado chico
        self.factura(20_000_000, vence=self.hoy + timedelta(days=1))
        self.venta(self.hoy, 100_000)

        d = self.piso()
        self.assertIsNotNone(d["piso_hoy"])
        self.assertIsNotNone(d["piso_caja"]["por_dia"])
        self.assertGreater(d["piso_caja"]["por_dia"], d["piso_hoy"])
        self.assertEqual(d["manda"], "caja")
        self.assertEqual(d["el_otro"], "resultado")

    def test_manda_el_de_resultado_cuando_es_el_mas_alto(self):
        self.historia_de_ventas()
        self.obligacion(30_000_000, self.fin_mes)
        self.factura(100_000, vence=self.hoy + timedelta(days=1))
        self.venta(self.hoy, 100_000)

        d = self.piso()
        self.assertGreater(d["piso_hoy"], d["piso_caja"]["por_dia"])
        self.assertEqual(d["manda"], "resultado")
        self.assertEqual(d["el_otro"], "caja")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LA DOBLE CONVERSIÓN
# ═══════════════════════════════════════════════════════════════════════════════

class DobleConversionTest(PisoBase):

    def test_el_impoconsumo_no_se_suma_dos_veces(self):
        """El piso queda en pesos COBRADOS y ahí termina.

        Como el impuesto ya está RESTADO del margen de contribución, el resultado
        de la división ya es lo que el cliente tiene que pagar. Volvérselo a sumar
        —el error clásico de trabajar en cobrado y en neto a la vez— inflaría el
        piso un 8% en la dirección alarmista, pero seguiría siendo falso.
        """
        self.historia_de_ventas()
        self.obligacion(1_000_000, self.fin_mes)
        self.venta(self.hoy, 100_000)          # sin ítems: COGS 0, comisión 0

        d = self.piso()
        mc = d["margen_contribucion"]
        self.assertAlmostEqual(d["razones"]["impoconsumo"], I_MEDIDO, places=4)
        self.assertAlmostEqual(d["razones"]["cogs"], 0.0, places=6)
        self.assertAlmostEqual(mc, 1 - I_MEDIDO, places=4)

        correcto = round(1_000_000 / mc, 2)
        con_impuesto_de_nuevo = round(correcto * (1 + TASA_IMPO), 2)
        self.assertEqual(d["piso_mes"], correcto)
        self.assertNotEqual(d["piso_mes"], con_impuesto_de_nuevo)

        # La vuelta completa: vender exactamente el piso deja exactamente los
        # costos fijos. Si hubiera una conversión de más, esto no cerraría.
        self.assertAlmostEqual(d["piso_mes"] * mc, 1_000_000, places=0)

    def test_el_cociente_del_impoconsumo_se_mide_y_no_sale_de_la_tarifa(self):
        """0,0741 y no 0,08. El precio de la carta lleva el impuesto adentro, y
        `Tributos.separar` devuelve además CERO cuando el régimen no lo incluye:
        el cociente medido cubre los dos casos sin una rama que se pueda olvidar.
        """
        self.historia_de_ventas()
        self.obligacion(1_000_000, self.fin_mes)
        self.venta(self.hoy, 108_000)

        d = self.piso()
        self.assertAlmostEqual(d["razones"]["impoconsumo"], I_MEDIDO, places=5)
        self.assertNotAlmostEqual(d["razones"]["impoconsumo"], TASA_IMPO, places=3)

    def test_la_comision_del_datafono_entra_solo_por_la_parte_con_tarjeta(self):
        self.historia_de_ventas()
        self.obligacion(1_000_000, self.fin_mes)
        self.venta(self.hoy, 100_000, tarjeta=100_000)
        self.venta(self.hoy, 100_000)
        self.db.add(Configuracion(clave=svc.CLAVE_COMISION_DATAFONO, valor="0.03"))
        self.db.commit()

        d = self.piso()
        self.assertAlmostEqual(d["razones"]["pct_tarjeta"], 0.5, places=4)
        self.assertAlmostEqual(d["razones"]["comision"], 0.015, places=4)
        sesgo = next(s for s in d["sesgos"]
                     if s["clave"] == "comision_datafono_sin_cargar")
        self.assertFalse(sesgo["activo"])


# ═══════════════════════════════════════════════════════════════════════════════
# 7. LOS DÍAS QUE ABRE EL LOCAL SE DERIVAN
# ═══════════════════════════════════════════════════════════════════════════════

class DiasQueAbreTest(PisoBase):

    def test_una_sede_que_cierra_los_domingos_no_cuenta_los_domingos(self):
        self.historia_de_ventas(cerrado_los=(6,))
        self.obligacion(3_000_000, self.fin_mes)
        self.venta(self.hoy, 100_000)

        d = self.piso()
        self.assertTrue(d["dias"]["derivados"])
        self.assertNotIn(6, d["dias"]["dias_semana"])
        esperados = sum(1 for n in range((self.fin_mes - self.hoy).days + 1)
                        if (self.hoy + timedelta(days=n)).weekday() != 6)
        self.assertEqual(d["dias"]["quedan"], esperados)
        self.assertEqual(d["dias"]["calendario"],
                         (self.fin_mes - self.hoy).days + 1)

    def test_hoy_cuenta_como_dia_que_queda(self):
        """La venta «a la fecha» ya incluye lo de hoy: las horas que quedan de
        hoy son horas en las que todavía se puede vender el resto."""
        self.historia_de_ventas(cerrado_los=())
        d = svc.dias_que_abre(self.db, self.hoy, self.fin_mes)
        self.assertEqual(d["dias"], (self.fin_mes - self.hoy).days + 1)

    def test_sin_historia_de_ventas_no_se_deriva_nada_y_se_declara(self):
        """Es el único punto que empuja el piso hacia abajo, así que se dice."""
        self.obligacion(1_000_000, self.fin_mes)
        d = self.piso()
        self.assertFalse(d["dias"]["derivados"])
        self.assertEqual(d["dias"]["quedan"], d["dias"]["calendario"])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. EL ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

class EndpointPisoTest(PisoBase):

    def test_get_piso_contesta_200_con_el_contrato_completo(self):
        self.historia_de_ventas()
        self.obligacion(4_000_000, self.fin_mes)
        self.venta(self.hoy, 500_000)

        r = self.client.get("/api/v1/costos/piso",
                            params={"anio": self.hoy.year, "mes": self.hoy.month})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        for campo in ("puerta", "costos_fijos", "margen_contribucion", "razones",
                      "piso_mes", "piso_hoy", "falta", "titular", "dias",
                      "piso_caja", "manda", "sesgos", "rotulo"):
            self.assertIn(campo, d)
        self.assertEqual(d["titular"]["por_dia"], d["piso_hoy"])

    def test_las_puertas_no_son_errores_contestan_200(self):
        """Sin un solo dato cargado el endpoint sigue contestando: la pantalla
        necesita el hueco CON NOMBRE, no un 500 ni un 400."""
        r = self.client.get("/api/v1/costos/piso",
                            params={"anio": self.hoy.year, "mes": self.hoy.month})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["puerta"], svc.PUERTA_SIN_COSTOS_FIJOS)

    def test_un_mes_que_no_existe_es_un_parametro_invalido(self):
        r = self.client.get("/api/v1/costos/piso",
                            params={"anio": self.hoy.year, "mes": 13})
        self.assertEqual(r.status_code, 422)

    def test_la_reserva_se_valida_en_el_handler_con_un_texto(self):
        """El `detail` de un 422 es una LISTA y el cliente solo lee strings."""
        r = self.client.post("/api/v1/costos/reserva-minima", json={"reserva": -1})
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)

    def test_la_reserva_se_guarda_y_se_lee(self):
        r = self.client.post("/api/v1/costos/reserva-minima",
                             json={"reserva": 1_500_000})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["reserva_minima_caja"], 1_500_000)
        self.assertFalse(r.json()["reserva_es_default"])
        self.assertEqual(svc.leer_reserva_minima_caja(self.db), (1_500_000.0, False))

    def test_la_reserva_tolera_basura_guardada(self):
        """La fila es TEXTO: un valor podrido de otra versión no puede tumbar la
        pantalla del dueño. Ante la duda, 0 y marcado como default."""
        self.db.add(Configuracion(clave=svc.CLAVE_RESERVA_MINIMA_CAJA,
                                  valor="no-es-un-numero"))
        self.db.commit()
        self.assertEqual(svc.leer_reserva_minima_caja(self.db), (0.0, True))


# ═══════════════════════════════════════════════════════════════════════════════
# 9. EL HORIZONTE DEL FLUJO, ANCLADO A FIN DE MES
# ═══════════════════════════════════════════════════════════════════════════════

class HorizonteYColchonTest(PisoBase):

    def test_sin_dias_el_horizonte_llega_al_ultimo_dia_del_mes(self):
        d = svc.get_flujo_proyectado(self.db)
        self.assertEqual(d["dias"], svc.dias_hasta_fin_de_mes(self.hoy))
        self.assertTrue(d["horizonte_es_fin_de_mes"])
        esperado = max(self.fin_mes, self.hoy + timedelta(days=1))
        self.assertEqual(d["serie"][-1]["fecha"], esperado)

    def test_el_horizonte_sigue_siendo_parametrizable(self):
        d = svc.get_flujo_proyectado(self.db, dias=7)
        self.assertEqual(len(d["serie"]), 7)
        self.assertEqual(d["serie"][-1]["fecha"], self.hoy + timedelta(days=7))
        self.assertEqual(d["horizonte_es_fin_de_mes"],
                         svc.dias_hasta_fin_de_mes(self.hoy) == 7)

    def test_el_ultimo_dia_del_mes_el_horizonte_no_queda_vacio(self):
        """`dias` = 0 no es una respuesta: se recorta a 1."""
        ultimo = ultimo_dia(date(2026, 2, 1))
        self.assertEqual(svc.dias_hasta_fin_de_mes(ultimo), 1)
        self.assertEqual(svc.dias_hasta_fin_de_mes(date(2026, 2, 27)), 1)

    def test_el_colchon_es_el_peor_dia_menos_la_reserva(self):
        """Contra el MÍNIMO de la serie y no contra el saldo final: la plata
        tiene que alcanzar todos los días, no solo el último."""
        # Sin historia de ventas: la serie no tiene entradas esperadas y el
        # mínimo se puede leer sin ruido.
        self.factura(500_000, vence=self.hoy + timedelta(days=1))
        svc.guardar_reserva_minima_caja(self.db, 200_000, self.admin.id)

        d = svc.get_flujo_proyectado(self.db)
        self.assertEqual(d["reserva_minima_caja"], 200_000)
        self.assertFalse(d["reserva_es_default"])
        self.assertEqual(d["saldo_minimo"], min(p["saldo"] for p in d["serie"]))
        self.assertEqual(d["colchon"], round(d["saldo_minimo"] - 200_000, 2))

    def test_sin_reserva_el_colchon_es_el_de_siempre_y_se_dice_que_es_default(self):
        d = svc.get_flujo_proyectado(self.db)
        self.assertTrue(d["reserva_es_default"])
        self.assertEqual(d["reserva_minima_caja"], 0.0)
        self.assertEqual(d["colchon"], d["saldo_minimo"])


if __name__ == "__main__":
    unittest.main()


# ─── La comisión del datáfono: el único sesgo que se apaga escribiendo ──────

class ComisionDatafonoTest(PisoBase):
    """SIN ESTE DATO EL PISO SALE CORTO, y es el único de los cuatro sesgos que
    se arregla con un número.

    La comisión se cobra de cada venta con tarjeta y hoy no la descuenta nadie:
    con la mitad de la venta por datáfono y una tasa de 2,5%, el margen se infla
    1,25 puntos y el piso baja en proporción — hacia el lado que tranquiliza.

    Hasta acá el endpoint la declaraba como sesgo activo y no había forma de
    cargarla. Un sesgo que se declara y no se puede apagar es una advertencia
    que el dueño va a aprender a ignorar.
    """

    def declarar(self, porcentaje):
        return self.client.post("/api/v1/costos/comision-datafono",
                                json={"porcentaje": porcentaje})

    def test_se_recibe_en_porcentaje_y_se_guarda_como_fraccion(self):
        """2.5 quiere decir 2,5%. Se recibe como viene en el contrato del
        adquirente y se guarda como fracción, para que nadie tenga que acordarse
        de en qué unidad quedó."""
        r = self.declarar(2.5)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(r.json()["comision_datafono"], 0.025, places=6)
        self.assertFalse(r.json()["sin_cargar"])

    def test_declararla_baja_el_margen_y_sube_el_piso(self):
        """LA DIRECCIÓN, que es lo que importa: cargar la comisión NUNCA puede
        bajar el piso. Si lo bajara, estaríamos restando dos veces."""
        antes = self.piso()
        self.declarar(2.5)
        despues = self.piso()

        if antes.get("margen_contribucion") is None:
            self.skipTest("sin razones medidas en este escenario")
        self.assertLess(despues["margen_contribucion"], antes["margen_contribucion"])
        self.assertGreater(despues["piso_mes"], antes["piso_mes"])

    def test_el_sesgo_se_apaga_cuando_se_carga(self):
        """Los sesgos solo existen cuando hay razones medidas: sin venta en el
        mes no hay margen del que hablar y la lista viene vacía, que es correcto
        (la puerta `sin_razones` ya dijo lo suyo)."""
        antes = {s["clave"]: s["activo"] for s in self.piso()["sesgos"]}
        if "comision_datafono_sin_cargar" not in antes:
            self.skipTest("sin razones medidas: no hay sesgos que declarar")
        self.assertTrue(antes["comision_datafono_sin_cargar"])
        self.declarar(2.5)
        despues = {s["clave"]: s["activo"] for s in self.piso()["sesgos"]}
        self.assertFalse(despues["comision_datafono_sin_cargar"])

    def test_una_comision_absurda_se_rechaza_con_su_motivo(self):
        """25% no es una comisión: es un 0,25 tecleado como porcentaje o al
        revés. Guardarlo en silencio desfigura el piso."""
        r = self.declarar(25)
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)
        self.assertIn("porcentaje", r.json()["detail"])

    def test_una_comision_negativa_se_rechaza(self):
        r = self.declarar(-1)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIsInstance(r.json()["detail"], str)

    def test_infinito_se_rechaza_sin_reventar_la_respuesta(self):
        """`inf` no es JSON válido, así que se manda como CUERPO CRUDO: es como
        llegaría de un cliente que serializa con la extensión de Python.

        Y por eso la validación vive en el HANDLER y no en pydantic: un `inf`
        rechazado por el schema vuelve DENTRO del cuerpo del 422 y revienta al
        serializar la propia respuesta de error. El dueño veía un 500 en vez del
        motivo.
        """
        for crudo in ('{"porcentaje": Infinity}', '{"porcentaje": NaN}'):
            r = self.client.post("/api/v1/costos/comision-datafono",
                                 content=crudo,
                                 headers={"Content-Type": "application/json"})
            self.assertEqual(r.status_code, 400, f"{crudo}: {r.text}")
            self.assertIsInstance(r.json()["detail"], str)

    def test_cero_es_valido_y_no_es_lo_mismo_que_sin_cargar(self):
        """«No pago comisión» es una decisión; «nadie la cargó» es una ausencia.
        Es la misma distinción que el resto del módulo hace en todos lados."""
        r = self.declarar(0)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["comision_datafono"], 0)
        self.assertFalse(r.json()["sin_cargar"])
