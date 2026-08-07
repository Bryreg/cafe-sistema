"""Escalera de conciliación por producto: de UN número que no explica nada a una
descomposición donde cada renglón es una CAUSA CONOCIDA y lo que sobra al final
es lo único que merece investigarse.

Hoy el cierre entrega `físico − sistema` y ese número mezcla consumo normal,
merma no registrada, error de conteo, receta mal cargada y robo: todos producen
el mismo síntoma —un negativo— y ninguno se distingue del otro.

La escalera reconstruye el stock ESPERADO desde el LIBRO DE MOVIMIENTOS sobre un
rango de fechas arbitrario (no desde la foto congelada del cierre, que se saca en
el primer instante en que alguien abre la pantalla del kiosko y por eso mete el
consumo legítimo del mes adentro del faltante):

    stock inicial + entradas − ventas − mermas − traslados ± ajustes = ESPERADO
    físico contado − ESPERADO = DIFERENCIA INEXPLICADA   ← esto es la fuga

Y valoriza esa fuga con UNA sola fuente de costo, priorizada y con el ORIGEN
expuesto, para que el dueño sepa si el número es firme o estimado.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import inicio_dia_col_utc
from app.database import Base
from app.models.models import (CategoriaProductoEnum, FacturaCompra,
                               FacturaCompraItem, Inventario, InventarioMensual,
                               Merma, MovimientoInventario, Producto,
                               ProductoInsumo, RolEnum, Ticket, TicketItem,
                               Tienda, TipoPagoEnum, Usuario)
from app.services import conciliacion as esc
from app.services import inventario_mensual as inv_svc


class _Base(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.t = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _producto(self, nombre, stock=0.0, precio_venta=0.0, precio_costo=None,
                  controla_stock=True, unidad="gr"):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=controla_stock,
                     precio_venta=precio_venta, precio_costo=precio_costo)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.t.id,
                               stock_actual=stock, stock_minimo=0))
        self.db.commit()
        return p

    def _mov(self, producto, tipo, cantidad, motivo, dia: date):
        """Movimiento del LIBRO en un día concreto. Escribe el stock igual que lo
        haría el flujo real (entrada/salida suman o restan; ajuste FIJA el valor
        absoluto — por eso el libro no se puede leer como una suma de deltas)."""
        fila = self.db.query(Inventario).filter_by(
            producto_id=producto.id, tienda_id=self.t.id).first()
        if tipo == "entrada":
            fila.stock_actual = (fila.stock_actual or 0) + cantidad
        elif tipo == "salida":
            fila.stock_actual = (fila.stock_actual or 0) - cantidad
        else:
            fila.stock_actual = cantidad
        mov = MovimientoInventario(
            producto_id=producto.id, tienda_id=self.t.id, tipo=tipo,
            cantidad=cantidad, motivo=motivo, usuario_id=self.admin.id,
            fecha=inicio_dia_col_utc(dia) + timedelta(hours=3))
        self.db.add(mov)
        self.db.commit()
        return mov

    def _escalera(self, producto, desde, hasta, fisico=None):
        out = esc.escalera_rango(self.db, self.t.id, desde, hasta,
                                 fisicos={producto.id: fisico} if fisico is not None else None)
        return next(p for p in out["productos"] if p["producto_id"] == producto.id)


class EscaleraTest(_Base):
    """La escalera separa lo explicado de lo inexplicado."""

    def test_producto_con_solo_ventas_no_deja_residuo(self):
        # 100 gr al arrancar julio, se venden 20 (el POS los descontó del libro),
        # se cuentan 80. Todo el movimiento tiene causa: nada que investigar.
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        self._mov(cafe, "salida", 20, "Venta POS — insumo de Americano", date(2026, 7, 10))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=80)

        self.assertEqual(e["stock_inicial"], 100)
        self.assertEqual(e["ventas"], 20)
        self.assertEqual(e["stock_esperado"], 80)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_merma_registrada_es_causa_conocida_y_no_deja_residuo(self):
        # Se botaron 15 gr y ALGUIEN LOS REGISTRÓ. Faltan 15 contra el arranque,
        # pero la merma los explica enteros: residuo 0.
        leche = self._producto("LECHE", stock=0)
        self._mov(leche, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        self._mov(leche, "salida", 15, "Daño: se cortó", date(2026, 7, 5))

        e = self._escalera(leche, date(2026, 7, 1), date(2026, 7, 31), fisico=85)

        self.assertEqual(e["mermas"], 15)
        self.assertEqual(e["ventas"], 0)
        self.assertEqual(e["stock_esperado"], 85)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_robo_simulado_aparece_entero_en_el_residuo(self):
        # Mismo movimiento registrado que el caso anterior, pero en la estantería
        # hay 12 gr menos de los que el libro puede justificar. ESO es la fuga.
        leche = self._producto("LECHE", stock=0)
        self._mov(leche, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        self._mov(leche, "salida", 15, "Daño: se cortó", date(2026, 7, 5))

        e = self._escalera(leche, date(2026, 7, 1), date(2026, 7, 31), fisico=73)

        self.assertEqual(e["stock_esperado"], 85)
        self.assertEqual(e["diferencia_inexplicada"], -12)   # negativo = falta

    def test_traslado_a_otra_sede_es_causa_conocida(self):
        azucar = self._producto("AZUCAR", stock=0)
        self._mov(azucar, "entrada", 50, "Recepción #1", date(2026, 6, 20))
        self._mov(azucar, "salida", 10, "Traslado a Centro: faltante", date(2026, 7, 3))

        e = self._escalera(azucar, date(2026, 7, 1), date(2026, 7, 31), fisico=40)

        self.assertEqual(e["traslados"], 10)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_ajuste_manual_entra_como_delta_no_como_valor_absoluto(self):
        # `MovimientoInventario.cantidad` de un ajuste guarda el stock RESULTANTE,
        # no el delta. Sumarlo como si fuera un delta rompe la escalera entera.
        pan = self._producto("PAN", stock=0)
        self._mov(pan, "entrada", 30, "Recepción #1", date(2026, 6, 20))
        self._mov(pan, "ajuste", 25, "Corrección manual del admin", date(2026, 7, 8))

        e = self._escalera(pan, date(2026, 7, 1), date(2026, 7, 31), fisico=25)

        self.assertEqual(e["stock_inicial"], 30)
        self.assertEqual(e["ajustes"], -5)          # delta, NO 25
        self.assertEqual(e["stock_esperado"], 25)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_el_rango_no_tiene_que_ser_un_mes_calendario(self):
        # El dueño eligió parametrizar por fechas para poder pasar a semanal sin
        # reescribir nada: lo de afuera del rango va al stock inicial, no al medio.
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, 7, 2))
        self._mov(cafe, "salida", 30, "Venta POS", date(2026, 7, 5))     # antes del rango
        self._mov(cafe, "salida", 10, "Venta POS", date(2026, 7, 12))    # dentro
        self._mov(cafe, "salida", 25, "Venta POS", date(2026, 7, 25))    # después

        e = self._escalera(cafe, date(2026, 7, 10), date(2026, 7, 17), fisico=60)

        self.assertEqual(e["stock_inicial"], 70)     # 100 − 30, todo lo previo
        self.assertEqual(e["ventas"], 10)            # SOLO la venta de la semana
        self.assertEqual(e["stock_esperado"], 60)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_lo_no_clasificado_es_un_renglon_propio_no_parte_del_residuo(self):
        # Una salida con un motivo que la escalera no sabe nombrar SIGUE estando en
        # el libro: es una causa conocida a medias, no una fuga. Meterla en el
        # residuo mandaría al dueño a investigar algo que el sistema ya registró.
        vaso = self._producto("VASO", stock=0, unidad="und")
        self._mov(vaso, "entrada", 200, "Recepción #1", date(2026, 6, 20))
        self._mov(vaso, "salida", 7, "Unificación: VASO VIEJO (#9) → VASO (#1)",
                  date(2026, 7, 4))

        e = self._escalera(vaso, date(2026, 7, 1), date(2026, 7, 31), fisico=193)

        self.assertEqual(e["otras_salidas"], 7)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_la_escalera_ignora_la_foto_congelada_del_cierre(self):
        # El bug que la escalera esquiva: `cantidad_sistema` se congela cuando
        # alguien ABRE la pantalla del kiosko (día 1), así que el consumo legítimo
        # del mes aparece como faltante. La escalera reconstruye desde el libro.
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        foto = inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)   # congela 100
        self._mov(cafe, "salida", 40, "Venta POS", date(2026, 7, 15))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=60)

        item = next(i for i in foto["items"] if i["producto_id"] == cafe.id)
        self.assertEqual(item["cantidad_sistema"], 100)      # la foto vieja
        self.assertEqual(e["stock_esperado"], 60)            # el libro al 31
        self.assertEqual(e["diferencia_inexplicada"], 0)     # no hay fuga: se vendió

    def test_sin_fisico_contado_no_se_inventa_un_residuo(self):
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, 6, 20))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31))

        self.assertEqual(e["stock_esperado"], 100)
        self.assertIsNone(e["stock_fisico"])
        self.assertIsNone(e["diferencia_inexplicada"])


class MotivosRealesTest(_Base):
    """El renglón que el dueño LEE tiene que decir la causa REAL. La identidad
    cierra igual con una etiqueta equivocada — y por eso mismo un prefijo que no
    matchea no rompe nada y miente para siempre."""

    def test_la_preparacion_de_pasteleria_no_cae_en_otras_salidas(self):
        # pasteleria.py:100 escribe "Preparación pastelería", SIN dos puntos: el
        # prefijo "Preparación:" no lo matchea y la preparación se leía como una
        # salida sin causa nombrada.
        torta = self._producto("TORTA", stock=0, unidad="und")
        self._mov(torta, "entrada", 20, "Recepción #1", date(2026, 6, 20))
        self._mov(torta, "salida", 3, "Preparación pastelería", date(2026, 7, 4))

        e = self._escalera(torta, date(2026, 7, 1), date(2026, 7, 31), fisico=17)

        self.assertEqual(e["preparaciones"], 3)
        self.assertEqual(e["otras_salidas"], 0)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_la_anulacion_de_un_traslado_recibido_es_una_reversa_no_otra_salida(self):
        # mermas.py:265 revierte el RECIBO con una salida: es una reversa, no una
        # salida sin causa. Y entra restando, como toda salida.
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 100, "Recibo traslado desde Centro", date(2026, 7, 2))
        self._mov(cafe, "salida", 100, "Anulación traslado #7 (revertir recibo)",
                  date(2026, 7, 3))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=0)

        self.assertEqual(e["traslados_recibidos"], 100)   # no es una compra
        self.assertEqual(e["reversas_salida"], 100)
        self.assertEqual(e["otras_salidas"], 0)
        self.assertEqual(e["entradas"], 0)
        self.assertEqual(e["stock_esperado"], 0)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_la_reversa_de_una_factura_no_se_lee_como_una_salida_sin_causa(self):
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 50, "Factura #A1 — Prov", date(2026, 7, 2))
        self._mov(cafe, "salida", 50, "Eliminación factura #A1 — Prov", date(2026, 7, 6))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=0)

        self.assertEqual(e["entradas"], 50)
        self.assertEqual(e["reversas_salida"], 50)
        self.assertEqual(e["otras_salidas"], 0)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_la_nota_de_credito_es_una_reversa_no_una_compra(self):
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 12, "Nota crédito ticket #55", date(2026, 7, 9))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=12)

        self.assertEqual(e["reversas"], 12)
        self.assertEqual(e["entradas"], 0)

    def test_la_entrada_de_una_unificacion_no_se_lee_como_una_compra(self):
        # inventario.py:645 escribe el MISMO motivo en las dos patas de una
        # unificación. La salida cae en `otras_salidas`, que no afirma nada; la
        # entrada caía en el bucket rotulado "compras y recepciones" e inflaba la
        # mercadería que se cree que entró al local. Nadie compró ni recibió nada:
        # el mismo producto cambió de ficha.
        vaso = self._producto("VASO", stock=0, unidad="und")
        self._mov(vaso, "entrada", 7, "Unificación: VASO VIEJO (#9) → VASO (#1)",
                  date(2026, 7, 4))

        e = self._escalera(vaso, date(2026, 7, 1), date(2026, 7, 31), fisico=7)

        self.assertEqual(e["unificaciones"], 7)
        self.assertEqual(e["entradas"], 0)
        self.assertEqual(e["stock_esperado"], 7)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_las_dos_patas_de_una_unificacion_caen_en_renglones_distintos(self):
        # La salida se queda a propósito en `otras_salidas`: el renglón genérico
        # de salidas no afirma una causa, así que no miente. Lo que no podía
        # quedarse era la ENTRADA, porque su renglón sí dice "compras".
        motivo = "Unificación: VASO VIEJO (#9) → VASO (#1)"
        keeper = self._producto("VASO", stock=0, unidad="und")
        archivado = self._producto("VASO VIEJO", stock=0, unidad="und")
        self._mov(archivado, "entrada", 7, "Recepción #1", date(2026, 6, 20))
        self._mov(keeper, "entrada", 7, motivo, date(2026, 7, 4))
        self._mov(archivado, "salida", 7, motivo, date(2026, 7, 4))

        k = self._escalera(keeper, date(2026, 7, 1), date(2026, 7, 31), fisico=7)
        a = self._escalera(archivado, date(2026, 7, 1), date(2026, 7, 31), fisico=0)

        self.assertEqual(k["unificaciones"], 7)
        self.assertEqual(k["entradas"], 0)
        self.assertEqual(a["otras_salidas"], 7)
        self.assertEqual(k["diferencia_inexplicada"], 0)
        self.assertEqual(a["diferencia_inexplicada"], 0)

    def test_la_identidad_cierra_aunque_un_motivo_nuevo_no_matchee_ningun_prefijo(self):
        # La garantía estructural: un motivo desconocido se degrada de etiqueta,
        # nunca se cae de la escalera ni ensucia el residuo.
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 100, "Motivo que nadie escribió todavía",
                  date(2026, 7, 2))
        self._mov(cafe, "salida", 30, "Otro motivo inventado mañana", date(2026, 7, 3))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=70)

        self.assertEqual(e["entradas"], 100)
        self.assertEqual(e["otras_salidas"], 30)
        self.assertEqual(e["diferencia_inexplicada"], 0)


class AjustesDeConteoTest(_Base):
    """Aplicar un conteo escribe un `ajuste` con el stock contado. Ese renglón no
    es una CAUSA: es un residuo inexplicado ANTERIOR ya volcado al libro. Contarlo
    como causa conocida es un falso negativo estructural."""

    def test_el_ajuste_de_un_conteo_aplicado_no_se_mezcla_con_los_manuales(self):
        pan = self._producto("PAN", stock=0, precio_costo=100)
        self._mov(pan, "entrada", 30, "Recepción #1", date(2026, 6, 20))
        self._mov(pan, "ajuste", 25, "Inventario mensual 06/2026 aplicado (dif -5)",
                  date(2026, 7, 8))

        e = self._escalera(pan, date(2026, 7, 1), date(2026, 7, 31), fisico=25)

        self.assertEqual(e["ajustes_conteo"], -5)
        self.assertEqual(e["ajustes"], 0)            # no es una corrección manual
        self.assertEqual(e["stock_esperado"], 25)    # la identidad cierra igual
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_un_conteo_parcial_esconde_la_fuga_y_el_resumen_la_declara(self):
        # El caso que hacía el daño: la sede aplica un conteo a mitad de mes, el
        # ajuste se traga los 5 faltantes y al cierre el residuo da 0. Sin este
        # número la pantalla diría "nada queda sin explicar" y sería mentira.
        pan = self._producto("PAN", stock=0, precio_costo=100)
        self._mov(pan, "entrada", 30, "Recepción #1", date(2026, 6, 20))
        self._mov(pan, "ajuste", 25, "Conteo #12 aplicado al inventario",
                  date(2026, 7, 8))

        out = esc.escalera_rango(self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
                                 fisicos={pan.id: 25})
        e = next(p for p in out["productos"] if p["producto_id"] == pan.id)

        self.assertEqual(e["diferencia_inexplicada"], 0)          # el libro cuadra
        self.assertEqual(out["resumen"]["ajustes_conteo_productos"], 1)
        self.assertEqual(out["resumen"]["valor_ajustes_conteo"], -500)   # 5 × $100

    def test_los_conteos_de_compras_y_las_verificaciones_tambien_cuentan(self):
        for motivo in ("Ajuste por conteo de compras #3",
                       "Verificación de conteo aprobada (conteo #9)"):
            with self.subTest(motivo=motivo):
                p = self._producto(f"P {motivo[:8]}", stock=0)
                self._mov(p, "entrada", 10, "Recepción #1", date(2026, 6, 20))
                self._mov(p, "ajuste", 8, motivo, date(2026, 7, 5))

                e = self._escalera(p, date(2026, 7, 1), date(2026, 7, 31), fisico=8)

                self.assertEqual(e["ajustes_conteo"], -2)
                self.assertEqual(e["ajustes"], 0)


class ResiduoContraElConsumoTest(_Base):
    """Ordenar por plata absoluta pone arriba a los productos de más rotación —los
    que más varianza NORMAL acumulan—. El residuo como % del consumo distingue una
    varianza crónica de proceso de un evento puntual."""

    def test_el_residuo_se_mide_tambien_contra_el_consumo_del_periodo(self):
        cafe = self._producto("CAFE", stock=0, precio_costo=10)
        self._mov(cafe, "entrada", 1000, "Recepción #1", date(2026, 6, 20))
        self._mov(cafe, "salida", 200, "Venta POS", date(2026, 7, 5))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=794)

        self.assertEqual(e["consumo_periodo"], 200)
        self.assertEqual(e["diferencia_inexplicada"], -6)
        self.assertEqual(e["pct_inexplicado"], -3.0)     # 6 sobre 200
        self.assertEqual(e["patron"], "proceso")         # crónico y chico

    def test_un_salto_grande_contra_el_consumo_se_marca_como_evento(self):
        cafe = self._producto("CAFE", stock=0, precio_costo=10)
        self._mov(cafe, "entrada", 1000, "Recepción #1", date(2026, 6, 20))
        self._mov(cafe, "salida", 200, "Venta POS", date(2026, 7, 5))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=720)

        self.assertEqual(e["pct_inexplicado"], -40.0)
        self.assertEqual(e["patron"], "evento")

    def test_sin_consumo_en_el_periodo_no_se_inventa_un_porcentaje(self):
        # Dividir por cero no convierte la ausencia de consumo en un porcentaje.
        cafe = self._producto("CAFE", stock=0, precio_costo=10)
        self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, 6, 20))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=95)

        self.assertEqual(e["consumo_periodo"], 0)
        self.assertIsNone(e["pct_inexplicado"])
        self.assertIsNone(e["patron"])
        self.assertEqual(e["diferencia_inexplicada"], -5)   # el residuo sí existe


class ConsumoTeoricoTest(_Base):
    """El consumo teórico (receta × unidades vendidas) es el CONTRASTE contra lo
    que el libro descontó: si no coinciden, la receta está mal cargada."""

    def _ticket(self, producto, cantidad, dia: date):
        t = Ticket(tienda_id=self.t.id, caja_turno_id=1, usuario_id=self.admin.id,
                   fecha=inicio_dia_col_utc(dia) + timedelta(hours=3),
                   total=1000 * cantidad, metodo_pago="efectivo", estado="completado")
        self.db.add(t)
        self.db.flush()
        self.db.add(TicketItem(ticket_id=t.id, producto_id=producto.id,
                               nombre_producto=producto.nombre, cantidad=cantidad,
                               precio_unitario=1000, subtotal=1000 * cantidad))
        self.db.commit()
        return t

    def test_receta_por_unidades_vendidas_da_el_consumo_teorico(self):
        cafe = self._producto("CAFE", stock=0)
        americano = self._producto("AMERICANO", stock=0, precio_venta=4000,
                                   controla_stock=False, unidad="und")
        self.db.add(ProductoInsumo(producto_id=americano.id, insumo_id=cafe.id, cantidad=18))
        self.db.commit()
        self._mov(cafe, "entrada", 1000, "Recepción #1", date(2026, 6, 20))
        self._ticket(americano, 10, date(2026, 7, 9))
        self._mov(cafe, "salida", 180, "Venta POS — insumo de AMERICANO", date(2026, 7, 9))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=820)

        self.assertEqual(e["consumo_teorico"], 180)      # 10 × 18
        self.assertEqual(e["ventas"], 180)               # lo que el libro descontó
        self.assertEqual(e["descuadre_receta"], 0)
        self.assertEqual(e["diferencia_inexplicada"], 0)

    def test_receta_que_no_coincide_con_el_libro_se_reporta_aparte(self):
        # El libro descontó 150 pero la receta de hoy dice 180: la receta cambió,
        # o la cascada a sustituto sacó parte de otro producto. Es una causa DISTINTA
        # del robo y no puede quedar escondida en el residuo.
        cafe = self._producto("CAFE", stock=0)
        americano = self._producto("AMERICANO", stock=0, precio_venta=4000,
                                   controla_stock=False, unidad="und")
        self.db.add(ProductoInsumo(producto_id=americano.id, insumo_id=cafe.id, cantidad=18))
        self.db.commit()
        self._mov(cafe, "entrada", 1000, "Recepción #1", date(2026, 6, 20))
        self._ticket(americano, 10, date(2026, 7, 9))
        self._mov(cafe, "salida", 150, "Venta POS — insumo de AMERICANO", date(2026, 7, 9))

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=850)

        self.assertEqual(e["consumo_teorico"], 180)
        self.assertEqual(e["ventas"], 150)
        self.assertEqual(e["descuadre_receta"], -30)     # el libro descontó 30 de menos
        self.assertEqual(e["diferencia_inexplicada"], 0)  # el libro sí cuadra con el físico

    def test_producto_sin_receta_no_inventa_un_consumo_teorico(self):
        # Sin receta y sin venta directa no hay forma de saber cuánto DEBIÓ salir.
        # Poner 0 sería afirmar que no se consumió nada: se dice que no se sabe.
        servilleta = self._producto("SERVILLETA", stock=0, unidad="und")
        self._mov(servilleta, "entrada", 500, "Recepción #1", date(2026, 6, 20))

        e = self._escalera(servilleta, date(2026, 7, 1), date(2026, 7, 31), fisico=470)

        self.assertIsNone(e["consumo_teorico"])
        self.assertTrue(e["sin_receta"])
        self.assertEqual(e["diferencia_inexplicada"], -30)   # el libro igual mide la fuga


class ValorizacionTest(_Base):
    """Una sola fuente de costo unitario, priorizada y con el ORIGEN expuesto."""

    def _factura(self, producto, cantidad, precio, dia=date(2026, 6, 1)):
        f = FacturaCompra(proveedor="Prov", tienda_id=self.t.id, valor_total=cantidad * precio,
                          usuario_id=self.admin.id, tipo_pago=TipoPagoEnum.contado,
                          fecha_recibido=datetime.combine(dia, datetime.min.time()))
        self.db.add(f)
        self.db.flush()
        self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=producto.id,
                                      cantidad=cantidad, precio_unitario=precio))
        self.db.commit()

    def test_precio_costo_oficial_manda_sobre_las_facturas(self):
        p = self._producto("CAFE", precio_costo=1200)
        self._factura(p, 10, 900)

        costo, origen = esc.costo_unitario(self.db)[p.id]

        self.assertEqual(costo, 1200)
        self.assertEqual(origen, "oficial")

    def test_el_promedio_de_facturas_es_PONDERADO_por_cantidad(self):
        # El bug verificado: AVG(precio_unitario) sin ponderar daba 150 —el promedio
        # de los dos precios— cuando el 90% de las unidades entraron a 200.
        p = self._producto("LECHE")
        self._factura(p, 10, 100)
        self._factura(p, 90, 200)

        costo, origen = esc.costo_unitario(self.db)[p.id]

        self.assertEqual(round(costo, 2), 190.0)
        self.assertEqual(origen, "factura")

    def test_sin_costo_de_compra_el_precio_de_venta_queda_marcado_como_estimado(self):
        p = self._producto("GASEOSA", precio_venta=5000)

        costo, origen = esc.costo_unitario(self.db)[p.id]

        self.assertEqual(costo, 5000)
        self.assertEqual(origen, "estimado")   # firme vs estimado: el dueño lo tiene que ver

    def test_un_insumo_sin_ninguna_fuente_de_costo_se_declara_sin_costo(self):
        # Éste es el caso que hacía que una fuga real valiera $0 en el total, en el
        # ranking y en el CSV: precio_venta 0 porque es insumo, y ninguna factura.
        p = self._producto("CANELA")

        costo, origen = esc.costo_unitario(self.db)[p.id]

        self.assertEqual(costo, 0)
        self.assertEqual(origen, "sin_costo")

    def test_la_escalera_expone_el_origen_del_costo_de_cada_producto(self):
        p = self._producto("CANELA")
        self._mov(p, "entrada", 100, "Recepción #1", date(2026, 6, 20))

        e = self._escalera(p, date(2026, 7, 1), date(2026, 7, 31), fisico=90)

        self.assertEqual(e["valor_origen"], "sin_costo")
        self.assertEqual(e["valor_inexplicado"], 0)

    def test_el_resumen_cuenta_los_faltantes_que_no_se_pudieron_valorizar(self):
        # Un total en $0 no puede leerse como "no hay fuga": se declara cuántos
        # productos tienen faltante sin costo cargado.
        sin = self._producto("CANELA")
        con = self._producto("CAFE", precio_costo=10)
        self._mov(sin, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        self._mov(con, "entrada", 100, "Recepción #1", date(2026, 6, 20))

        out = esc.escalera_rango(self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
                                 fisicos={sin.id: 90, con.id: 95})

        self.assertEqual(out["resumen"]["sin_costo"], 1)
        self.assertEqual(out["resumen"]["valor_inexplicado"], -50)   # solo el costeado


class PreparableTest(_Base):
    """Un PREPARABLE se cuenta por unidad de INVENTARIO (gr de mezcla) pero su
    receta rinde una TANDA entera. Confundir las dos unidades multiplica el costo
    del residuo por el rendimiento y fabrica la fuga más grande de la pantalla —
    la negación exacta de lo que la escalera viene a hacer."""

    def _mezcla(self, rendimiento=2820, receta=360, costo_azucar=10):
        # Mismo fixture que test_preparacion_idempotente: una tanda consume 360 gr
        # de azúcar y produce 2820 gr de mezcla.
        azucar = self._producto("AZUCAR", precio_costo=costo_azucar)
        mezcla = Producto(nombre="Mezcla Granizado", categoria=CategoriaProductoEnum.insumo,
                          unidad_medida="gr", controla_stock=True, precio_venta=0,
                          contenido_por_unidad=rendimiento)
        self.db.add(mezcla)
        self.db.flush()
        self.db.add(Inventario(producto_id=mezcla.id, tienda_id=self.t.id,
                               stock_actual=0, stock_minimo=0))
        self.db.add(ProductoInsumo(producto_id=mezcla.id, insumo_id=azucar.id,
                                   cantidad=receta))
        self.db.commit()
        return azucar, mezcla

    def test_el_costo_de_un_preparable_es_por_unidad_de_inventario_no_por_tanda(self):
        # La receta cuesta 360 × $10 = $3.600 la TANDA, y esa tanda rinde 2.820 gr.
        # El gramo vale $1,2766 — no $3.600.
        _azucar, mezcla = self._mezcla()

        costo, origen = esc.costo_unitario(self.db)[mezcla.id]

        self.assertEqual(origen, "receta")
        self.assertAlmostEqual(costo, 3600 / 2820, places=4)

    def test_un_gramo_de_residuo_de_preparable_no_se_valoriza_como_una_tanda(self):
        # 1 gr inexplicado vale $1,28. Valorizarlo como una tanda entera lo pondría
        # en $3.600 y lo mandaría al tope del ranking con una fuga inventada.
        _azucar, mezcla = self._mezcla()
        self._mov(mezcla, "entrada", 2820, "Preparación: Mezcla Granizado", date(2026, 7, 2))

        e = self._escalera(mezcla, date(2026, 7, 1), date(2026, 7, 31), fisico=2819)

        self.assertEqual(e["diferencia_inexplicada"], -1)
        self.assertAlmostEqual(e["valor_inexplicado"], -1.28, places=2)

    def test_un_preparable_sin_rendimiento_cargado_se_declara_sin_costo(self):
        # Sin `contenido_por_unidad` no hay forma de pasar de costo/tanda a
        # costo/gr. Inventar el factor sería peor que decir que no se sabe.
        _azucar, mezcla = self._mezcla(rendimiento=None)

        costo, origen = esc.costo_unitario(self.db)[mezcla.id]

        self.assertEqual(origen, "sin_costo")
        self.assertEqual(costo, 0)

    def test_un_producto_que_SI_se_vende_por_unidad_conserva_el_costo_de_su_receta(self):
        # La corrección es SOLO para preparables (controlan stock y no se venden).
        # Un producto vendido por unidad se cuenta en la misma unidad en que se
        # vende, así que su costo por receta ya está en la unidad correcta.
        masa = self._producto("MASA", precio_costo=100)
        waffle = Producto(nombre="WAFFLE", categoria=CategoriaProductoEnum.pasteleria,
                          unidad_medida="und", controla_stock=True, precio_venta=8000,
                          contenido_por_unidad=None)
        self.db.add(waffle)
        self.db.flush()
        self.db.add(Inventario(producto_id=waffle.id, tienda_id=self.t.id,
                               stock_actual=0, stock_minimo=0))
        self.db.add(ProductoInsumo(producto_id=waffle.id, insumo_id=masa.id, cantidad=4))
        self.db.commit()

        costo, origen = esc.costo_unitario(self.db)[waffle.id]

        self.assertEqual(origen, "receta")
        self.assertEqual(costo, 400)


class RankingTest(_Base):
    """El ranking es del RESIDUO, no de la diferencia bruta: se investiga lo que
    NADA explica, no lo que ya tiene causa."""

    def test_el_ranking_ordena_por_residuo_y_deja_afuera_lo_explicado(self):
        explicado = self._producto("LECHE", precio_costo=100)
        fuga = self._producto("CAFE", precio_costo=100)
        self._mov(explicado, "entrada", 200, "Recepción #1", date(2026, 6, 20))
        self._mov(fuga, "entrada", 200, "Recepción #1", date(2026, 6, 20))
        # LECHE se movió muchísimo más, pero TODO está registrado.
        self._mov(explicado, "salida", 150, "Venta POS", date(2026, 7, 5))
        self._mov(fuga, "salida", 5, "Venta POS", date(2026, 7, 5))

        out = esc.escalera_rango(self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
                                 fisicos={explicado.id: 50, fuga.id: 185})

        nombres = [r["producto_nombre"] for r in out["ranking"]]
        self.assertEqual(nombres, ["CAFE"])
        self.assertEqual(out["ranking"][0]["diferencia_inexplicada"], -10)

    def test_el_evento_le_gana_al_proceso_aunque_pese_menos_plata(self):
        # El peor orden posible es por plata a secas: el tope se lo lleva SIEMPRE
        # el producto de más rotación, que es el que más varianza NORMAL acumula.
        # La leche con 3% de servida de más pesa 4× en pesos que el frasco de
        # jarabe que efectivamente desapareció, y lo tapaba en la pantalla.
        leche = self._producto("LECHE", precio_costo=100)
        jarabe = self._producto("JARABE", precio_costo=100)
        self._mov(leche, "entrada", 20000, "Recepción #1", date(2026, 6, 20))
        self._mov(jarabe, "entrada", 300, "Recepción #1", date(2026, 6, 20))
        self._mov(leche, "salida", 10000, "Venta POS", date(2026, 7, 5))
        self._mov(jarabe, "salida", 100, "Venta POS", date(2026, 7, 5))

        out = esc.escalera_rango(
            self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
            # LECHE: 300 de residuo sobre 10.000 de consumo = 3% (proceso, $30.000).
            # JARABE: 80 sobre 100 = 80% (evento, $8.000) — pesa 4× menos.
            fisicos={leche.id: 9700, jarabe.id: 120})

        e = {p["producto_nombre"]: p for p in out["ranking"]}
        self.assertEqual(e["LECHE"]["patron"], "proceso")
        self.assertEqual(e["JARABE"]["patron"], "evento")
        self.assertEqual([p["producto_nombre"] for p in out["ranking"]],
                         ["JARABE", "LECHE"])
        # Y la plata sigue mandando ADENTRO del grupo, que es donde comparar
        # pesos quiere decir algo.
        self.assertGreater(abs(e["LECHE"]["valor_inexplicado"]),
                           abs(e["JARABE"]["valor_inexplicado"]))

    def test_dentro_de_un_mismo_patron_manda_la_plata(self):
        chico = self._producto("CANELA", precio_costo=1)
        grande = self._producto("CAFE", precio_costo=1000)
        for p in (chico, grande):
            self._mov(p, "entrada", 1000, "Recepción #1", date(2026, 6, 20))
            self._mov(p, "salida", 100, "Venta POS", date(2026, 7, 5))

        out = esc.escalera_rango(self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
                                 fisicos={chico.id: 850, grande.id: 850})

        # Mismo residuo, mismo % (50% → evento en los dos): ordena la plata.
        self.assertEqual([p["producto_nombre"] for p in out["ranking"]],
                         ["CAFE", "CANELA"])

    def test_los_que_no_se_pueden_valorizar_no_se_hunden_al_fondo_del_ranking(self):
        # Valen $0 y en un orden por plata quedan últimos: con el corte del
        # ranking pueden no llegar nunca a la pantalla por más kilos que hayan
        # desaparecido. Van en su propia lista, ordenados por CANTIDAD.
        sin = self._producto("CANELA")            # sin costo ni precio de venta
        con = self._producto("CAFE", precio_costo=100)
        self._mov(sin, "entrada", 1000, "Recepción #1", date(2026, 6, 20))
        self._mov(con, "entrada", 1000, "Recepción #1", date(2026, 6, 20))

        out = esc.escalera_rango(self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
                                 fisicos={sin.id: 100, con.id: 999})

        self.assertEqual([p["producto_nombre"] for p in out["ranking"]], ["CAFE"])
        self.assertEqual([p["producto_nombre"] for p in out["ranking_sin_costo"]],
                         ["CANELA"])
        self.assertEqual(out["ranking_sin_costo"][0]["diferencia_inexplicada"], -900)

    def test_el_ranking_sin_costo_ordena_por_cantidad_y_el_patron_no_manda(self):
        """La CANTIDAD manda sola, incluso contra el patrón.

        Sin pesos que mostrar, agrupar por patrón esconde justo lo que esta lista
        vino a destapar: al clavo le faltan 10 unidades de 20 (−50%, evento) y a la
        nuez 100 de 3.000 (−3%, proceso). Ordenar por patrón pone al clavo arriba y
        con el corte en 10 el faltante grande puede ni llegar al payload.
        """
        poco = self._producto("CLAVO")            # evento: chico pero desviadísimo
        mucho = self._producto("NUEZ MOSCADA")    # proceso: 10× más faltante
        self._mov(poco, "entrada", 1000, "Recepción #1", date(2026, 6, 20))
        self._mov(mucho, "entrada", 5000, "Recepción #1", date(2026, 6, 20))
        self._mov(poco, "salida", 20, "Venta POS", date(2026, 7, 5))
        self._mov(mucho, "salida", 3000, "Venta POS", date(2026, 7, 5))

        out = esc.escalera_rango(self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
                                 fisicos={poco.id: 970, mucho.id: 1900})

        por_nombre = {p["producto_nombre"]: p for p in out["ranking_sin_costo"]}
        # Los patrones son DISTINTOS a propósito: si empataran, este test pasaría
        # con el orden por patrón y sin él, y no probaría nada.
        self.assertEqual(por_nombre["CLAVO"]["patron"], "evento")
        self.assertEqual(por_nombre["NUEZ MOSCADA"]["patron"], "proceso")
        self.assertEqual(por_nombre["CLAVO"]["diferencia_inexplicada"], -10)
        self.assertEqual(por_nombre["NUEZ MOSCADA"]["diferencia_inexplicada"], -100)
        self.assertEqual([p["producto_nombre"] for p in out["ranking_sin_costo"]],
                         ["NUEZ MOSCADA", "CLAVO"])

    def test_el_faltante_mas_grande_sin_costo_llega_a_la_pantalla(self):
        """El corte en 10 no puede dejar afuera al que más falta.

        Con once faltantes chicos clasificados «evento», ordenar por patrón manda
        los once arriba y el faltante grande —que por ser crónico cae en
        «proceso»— se cae del payload antes de que la pantalla pueda mostrarlo.
        """
        grande = self._producto("HARINA")
        self._mov(grande, "entrada", 40000, "Recepción #1", date(2026, 6, 20))
        self._mov(grande, "salida", 30000, "Venta POS", date(2026, 7, 5))
        fisicos = {grande.id: 9100}               # −900 sobre 30.000 = −3% (proceso)
        for n in range(11):
            chico = self._producto(f"CHICO{n:02d}")
            self._mov(chico, "entrada", 100, "Recepción #1", date(2026, 6, 20))
            self._mov(chico, "salida", 10, "Venta POS", date(2026, 7, 5))
            fisicos[chico.id] = 85                # −5 sobre 10 = −50% (evento)

        out = esc.escalera_rango(self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
                                 fisicos=fisicos)

        nombres = [p["producto_nombre"] for p in out["ranking_sin_costo"]]
        self.assertEqual(nombres[0], "HARINA")
        # Y la pantalla solo muestra los primeros 6: tiene que estar entre ellos.
        self.assertIn("HARINA", nombres[:6])


class CotaDelLibroTest(_Base):
    """Leer la historia COMPLETA de movimientos crece sin techo con la edad del
    local. La cota acota esa lectura al rango pedido SIN perder un saldo firme:
    `_saldos` reconstruye hacia ATRÁS desde el stock vivo, así que una cota
    ingenua le saca el ancla al tramo viejo y devuelve un stock inicial estimado
    desde un cero que nunca existió."""

    def _libro_largo(self):
        """Un producto con ajustes ANTES y DESPUÉS del arranque del rango (el que
        necesita ancla previa) y otro sin ningún ajuste (el que no la necesita).

        Se escribe en orden CRONOLÓGICO estricto porque `_mov` va moviendo el
        stock vivo a medida que inserta: sembrar fuera de orden dejaría un
        `stock_actual` que no es el saldo del libro y la pasada hacia atrás
        arrancaría de un ancla falsa."""
        cafe = self._producto("CAFE", stock=0, precio_costo=10)
        leche = self._producto("LECHE", stock=0, precio_costo=10)
        for mes in range(1, 8):
            self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, mes, 2))
            self._mov(leche, "entrada", 100, "Recepción #1", date(2026, mes, 3))
            self._mov(cafe, "salida", 60, "Venta POS", date(2026, mes, 20))
            self._mov(leche, "salida", 70, "Venta POS", date(2026, mes, 21))
            # Ancla previa al rango (mayo) y un ajuste DENTRO del rango (julio):
            # sin el de mayo la pasada hacia atrás se frena en el de julio y el
            # arranque se estimaría desde un cero que nunca existió.
            if mes in (5, 7):
                self._mov(cafe, "ajuste", 150 if mes == 5 else 320,
                          "Corrección manual del admin", date(2026, mes, 25))
        return cafe, leche

    def test_reusar_un_contexto_sobre_un_rango_mas_viejo_se_frena(self):
        """La trampa del contexto compartido, cerrada con un portazo.

        `_corte_libro` acota el libro con el horizonte del CONTEXTO, no con el
        `desde` de cada llamada. Pedirle a un contexto de julio la escalera de
        junio devolvía un `stock_inicial` equivocado —el saldo del corte, no el del
        arranque— y sin marcarlo estimado. Es un error de programa, no un dato:
        tiene que fallar, no informar."""
        cafe, _leche = self._libro_largo()
        ctx = esc._Ctx(self.db, horizonte=date(2026, 7, 1))
        esc.escalera_rango(self.db, self.t.id, date(2026, 7, 1), date(2026, 7, 31),
                           fisicos={cafe.id: 320}, ctx=ctx)      # su propio horizonte: OK

        with self.assertRaises(AssertionError):
            esc.escalera_rango(self.db, self.t.id, date(2026, 6, 1), date(2026, 6, 30),
                               fisicos={cafe.id: 100}, ctx=ctx)

    def _sin_cota(self, desde, hasta, fisicos):
        """El comportamiento viejo: contexto sin horizonte = libro entero."""
        ctx = esc._Ctx(self.db)
        out = esc.escalera_rango(self.db, self.t.id, desde, hasta,
                                 fisicos=fisicos, ctx=ctx)
        return out, ctx

    def test_la_cota_devuelve_exactamente_la_misma_escalera_que_el_libro_entero(self):
        cafe, leche = self._libro_largo()
        desde, hasta = date(2026, 7, 1), date(2026, 7, 31)
        fisicos = {cafe.id: 300, leche.id: 150}

        viejo, ctx_viejo = self._sin_cota(desde, hasta, fisicos)
        nuevo = esc.escalera_rango(self.db, self.t.id, desde, hasta, fisicos=fisicos)

        self.assertEqual(nuevo["productos"], viejo["productos"])
        # Y de verdad leyó menos libro (si no, la cota no sirve para nada).
        ctx_nuevo = esc._Ctx(self.db, horizonte=desde)
        _filas, movs = ctx_nuevo.sede(self.t.id)
        _f2, movs_viejo = ctx_viejo.sede(self.t.id)
        leidos = sum(len(v) for v in movs.values())
        leidos_viejo = sum(len(v) for v in movs_viejo.values())
        self.assertLess(leidos, leidos_viejo)

    def test_la_cota_conserva_el_ancla_previa_y_no_estima_el_arranque_desde_cero(self):
        # El bug que una cota ingenua introduciría: cortar en el 1 de julio deja
        # afuera el ajuste de mayo, la pasada hacia atrás se frena en el de julio
        # y el tramo viejo se estima asumiendo que el libro arranca en cero JUSTO
        # en el corte. El arranque saldría mal Y marcado como estimado.
        cafe, leche = self._libro_largo()
        desde = date(2026, 7, 1)

        e = self._escalera(cafe, desde, date(2026, 7, 31), fisico=300)

        self.assertFalse(e["stock_inicial_estimado"])
        # Ajuste de mayo a 150, junio suma 100 y resta 60 → 190 al arrancar julio.
        self.assertEqual(e["stock_inicial"], 190)

    def test_sin_ancla_previa_se_lee_el_libro_entero_en_vez_de_inventar_el_arranque(self):
        # Un producto con ajustes SOLO después del arranque del rango no tiene
        # ancla firme anterior: ahí la estimación desde el inicio real del libro
        # es inevitable y la lectura completa es el precio de no inventar nada.
        cafe, leche = self._libro_largo()
        nuevo = self._producto("PAN", stock=0)
        self._mov(nuevo, "entrada", 50, "Recepción #1", date(2026, 3, 4))
        self._mov(nuevo, "ajuste", 40, "Corrección manual del admin", date(2026, 7, 12))
        desde, hasta = date(2026, 7, 1), date(2026, 7, 31)
        fisicos = {cafe.id: 300, nuevo.id: 40}

        ctx = esc._Ctx(self.db, horizonte=desde)
        self.assertIsNone(
            ctx._corte_libro(self.t.id, [cafe.id, leche.id, nuevo.id]))

        viejo, ctx_viejo = self._sin_cota(desde, hasta, fisicos)
        nueva = esc.escalera_rango(self.db, self.t.id, desde, hasta, fisicos=fisicos)
        self.assertEqual(nueva["productos"], viejo["productos"])
        # Y se leyó el libro entero, que es el precio de no inventar el arranque.
        _f, movs = ctx.sede(self.t.id)
        _f2, movs_viejo = ctx_viejo.sede(self.t.id)
        self.assertEqual(sum(len(v) for v in movs.values()),
                         sum(len(v) for v in movs_viejo.values()))

    def test_sin_ningun_ajuste_la_cota_llega_hasta_el_arranque_del_rango(self):
        # La pasada hacia atrás desde el stock vivo reconstruye cualquier sufijo
        # del libro: sin ajustes de por medio no hace falta un solo movimiento
        # anterior al rango, ni siquiera para el saldo previo.
        leche = self._producto("LECHE", stock=0, precio_costo=10)
        for mes in range(1, 8):
            self._mov(leche, "entrada", 100, "Recepción #1", date(2026, mes, 3))
            self._mov(leche, "salida", 70, "Venta POS", date(2026, mes, 21))
        desde, hasta = date(2026, 7, 1), date(2026, 7, 31)

        viejo, _ = self._sin_cota(desde, hasta, {leche.id: 200})
        nueva = esc.escalera_rango(self.db, self.t.id, desde, hasta,
                                   fisicos={leche.id: 200})

        self.assertEqual(nueva["productos"], viejo["productos"])
        ctx = esc._Ctx(self.db, horizonte=desde)
        _filas, movs = ctx.sede(self.t.id)
        self.assertEqual(len(movs[leche.id]), 2)     # solo los de julio
        self.assertEqual(nueva["productos"][0]["stock_inicial"], 180)
        self.assertFalse(nueva["productos"][0]["stock_inicial_estimado"])


class PasteleriaSinStockTest(_Base):
    """La pastelería que se registra sin stock suficiente NO puede quedarse fuera
    del libro: ese consumo reaparece después como residuo puro, o sea como una
    fuga fantasma que ninguna causa registrada puede explicar."""

    def test_registrar_pasteleria_sin_stock_igual_escribe_el_movimiento(self):
        from app.services import pasteleria

        torta = self._producto("TORTA", stock=2, unidad="und")
        pasteleria.registrar(self.db, self.t.id, torta.id, 5,
                             datetime(2026, 7, 20), self.admin.id)

        movs = self.db.query(MovimientoInventario).filter_by(producto_id=torta.id).all()
        self.assertEqual(len(movs), 1)
        self.assertEqual(movs[0].cantidad, 5)
        self.assertEqual(movs[0].motivo, "Preparación pastelería")

    def test_el_consumo_de_pasteleria_no_reaparece_como_fuga_inexplicada(self):
        from app.services import pasteleria

        torta = self._producto("TORTA", stock=0, unidad="und")
        self._mov(torta, "entrada", 4, "Recepción #1", date(2026, 7, 2))
        # Se registran 6 en vitrina con 4 en stock: el libro tiene que verlo.
        pasteleria.registrar(self.db, self.t.id, torta.id, 6,
                             datetime(2026, 7, 20), self.admin.id)
        # `MovimientoInventario.fecha` se sella con el reloj del servidor; acá se
        # lleva al día del registro para poder mirarlo en el rango de julio.
        mov = self.db.query(MovimientoInventario).filter_by(
            producto_id=torta.id, motivo="Preparación pastelería").one()
        mov.fecha = inicio_dia_col_utc(date(2026, 7, 20)) + timedelta(hours=3)
        self.db.commit()

        e = self._escalera(torta, date(2026, 7, 1), date(2026, 7, 31), fisico=-2)

        self.assertEqual(e["preparaciones"], 6)
        self.assertEqual(e["diferencia_inexplicada"], 0)   # nada de fuga fantasma


class BridgeConLaDiferenciaBrutaTest(_Base):
    """El puente entre el número que el dueño YA conoce y el residuo nuevo:
    bruta = explicado por el movimiento + inexplicado. Sin este puente, dos
    números distintos sobre el mismo producto se leen como una contradicción."""

    def test_la_diferencia_bruta_se_parte_en_explicado_mas_inexplicado(self):
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)     # foto: 100
        self._mov(cafe, "salida", 38, "Venta POS", date(2026, 7, 15))

        # Se cuentan 58: contra la foto faltan 42; el movimiento explica 38.
        out = esc.get_escalera_mensual(self.db, self.t.id, 2026, 7, fisicos={cafe.id: 58})
        e = next(p for p in out["productos"] if p["producto_id"] == cafe.id)

        self.assertEqual(e["diferencia_bruta"], -42)
        self.assertEqual(e["explicado_por_movimiento"], -38)
        self.assertEqual(e["diferencia_inexplicada"], -4)
        self.assertEqual(e["diferencia_bruta"],
                         e["explicado_por_movimiento"] + e["diferencia_inexplicada"])

    def test_la_escalera_mensual_toma_el_fisico_del_conteo_contado(self):
        cafe = self._producto("CAFE", stock=0)
        nadie = self._producto("TE", stock=0)
        self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        self._mov(nadie, "entrada", 40, "Recepción #1", date(2026, 6, 20))
        foto = inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)
        item = next(i for i in foto["items"] if i["producto_id"] == cafe.id)
        inv_svc.guardar(self.db, foto["id"], [{"id": item["id"], "cantidad_real": 95}])
        inv_svc.cerrar(self.db, foto["id"], self.admin.id)

        out = esc.get_escalera_mensual(self.db, self.t.id, 2026, 7)
        by_id = {p["producto_id"]: p for p in out["productos"]}

        self.assertEqual(by_id[cafe.id]["stock_fisico"], 95)
        self.assertEqual(by_id[cafe.id]["diferencia_inexplicada"], -5)
        # `cerrar` rellena cantidad_real con el sistema para lo NO contado: tomar
        # ese número como físico inventaría un conteo que nadie hizo.
        self.assertIsNone(by_id[nadie.id]["stock_fisico"])
        self.assertIsNone(by_id[nadie.id]["diferencia_inexplicada"])


class CorteDelPeriodoTest(_Base):
    """Hasta dónde llega el rango de un cierre mensual."""

    def test_cerrar_julio_en_agosto_no_le_carga_a_julio_las_ventas_de_agosto(self):
        # Cerrar el mes días después de contarlo es lo normal. Si el rango se
        # estirara hasta `fecha_cierre`, julio cargaría con las ventas de agosto y
        # cada producto que rota mostraría un SOBRANTE inventado.
        cafe = self._producto("CAFE", stock=0)
        self._mov(cafe, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        foto = inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)
        item = next(i for i in foto["items"] if i["producto_id"] == cafe.id)
        inv_svc.guardar(self.db, foto["id"], [{"id": item["id"], "cantidad_real": 100}])
        inv_svc.cerrar(self.db, foto["id"], self.admin.id)
        # El cierre quedó sellado el 3 de agosto y agosto ya vendió.
        inv = self.db.query(InventarioMensual).filter_by(
            tienda_id=self.t.id, anio=2026, mes=7).first()
        inv.fecha_cierre = inicio_dia_col_utc(date(2026, 8, 3))
        self.db.commit()
        self._mov(cafe, "salida", 40, "Venta POS", date(2026, 8, 1))

        out = esc.get_escalera_mensual(self.db, self.t.id, 2026, 7)
        e = next(p for p in out["productos"] if p["producto_id"] == cafe.id)

        self.assertEqual(out["corte_por"], "fin_de_mes")
        self.assertEqual(e["stock_esperado"], 100)          # julio no vio agosto
        self.assertEqual(e["diferencia_inexplicada"], 0)


class MermaPorRecetaTest(_Base):
    """Una merma de una BEBIDA descuenta los insumos por receta: la fila Merma
    apunta a la bebida, pero quien perdió stock es el insumo."""

    def test_la_merma_de_una_bebida_se_explica_en_la_escalera_del_insumo(self):
        cafe = self._producto("CAFE", stock=0)
        americano = self._producto("AMERICANO", stock=0, precio_venta=4000,
                                   controla_stock=False, unidad="und")
        self.db.add(ProductoInsumo(producto_id=americano.id, insumo_id=cafe.id, cantidad=18))
        self.db.commit()
        self._mov(cafe, "entrada", 1000, "Recepción #1", date(2026, 6, 20))
        self._mov(cafe, "salida", 36, "Daño: mal preparado — insumo de AMERICANO",
                  date(2026, 7, 6))
        self.db.add(Merma(tienda_id=self.t.id, producto_id=americano.id, cantidad=2,
                          motivo="mal preparado", usuario_id=self.admin.id,
                          fecha_registro=inicio_dia_col_utc(date(2026, 7, 6))))
        self.db.commit()

        e = self._escalera(cafe, date(2026, 7, 1), date(2026, 7, 31), fisico=964)

        self.assertEqual(e["mermas"], 36)
        self.assertEqual(e["diferencia_inexplicada"], 0)


class PLConLaFugaTest(_Base):
    """La merma real que el conteo mide JAMÁS llegaba al estado de resultados:
    `InventarioMensual` no se importaba en ningún otro servicio. El margen que el
    dueño mira no incluía la fuga que su propio sistema midió."""

    def _cerrar_mes_con_fuga(self):
        cafe = self._producto("CAFE", stock=0, precio_costo=100)
        self._mov(cafe, "entrada", 200, "Recepción #1", date(2026, 6, 20))
        foto = inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)
        self._mov(cafe, "salida", 50, "Venta POS", date(2026, 7, 10))
        item = next(i for i in foto["items"] if i["producto_id"] == cafe.id)
        inv_svc.guardar(self.db, foto["id"], [{"id": item["id"], "cantidad_real": 140}])
        inv_svc.cerrar(self.db, foto["id"], self.admin.id)
        return cafe

    def test_el_pl_expone_la_fuga_medida_sin_cambiar_el_margen_conocido(self):
        from app.services import rentabilidad

        antes = rentabilidad.get_rentabilidad(self.db, date(2026, 7, 1), date(2026, 7, 31),
                                              tienda_id=self.t.id)["resumen"]["margen_neto"]
        self._cerrar_mes_con_fuga()
        r = rentabilidad.get_rentabilidad(self.db, date(2026, 7, 1), date(2026, 7, 31),
                                          tienda_id=self.t.id)["resumen"]

        # Esperado al 31 = 200 − 50 = 150; contado 140 → fuga de 10 × $100.
        self.assertEqual(r["fuga_inventario"], -1000)
        self.assertTrue(r["tiene_fuga_medida"])
        self.assertEqual(r["margen_neto"], antes)          # NO cambia en silencio

    def test_la_fuga_NO_se_resta_del_margen_neto_porque_ya_esta_adentro(self):
        # `compras` es base de RECEPCIÓN: la mercadería se gasta ENTERA al
        # recibirla, así que lo que se compró y se fugó ya está descontado dentro
        # de `margen_neto`. Restarlo otra vez subestimaría la utilidad exactamente
        # en el valor de la fuga, todos los meses.
        from app.services import rentabilidad

        cafe = self._cerrar_mes_con_fuga()
        self._factura_recibida(cafe, 200, 100, date(2026, 7, 2))   # $20.000 de compra
        r = rentabilidad.get_rentabilidad(self.db, date(2026, 7, 1), date(2026, 7, 31),
                                          tienda_id=self.t.id)["resumen"]

        # La compra entera ya está restada del margen neto: no hay ningún KPI que
        # vuelva a descontarle la fuga encima.
        self.assertEqual(r["compras"], 20000)
        self.assertEqual(r["margen_neto"], r["ventas"] - r["compras"] - r["gastos"])
        self.assertNotIn("margen_neto_con_fuga", r)
        # El término vive contra el margen bruto REAL (base de CONSUMO): ahí sí la
        # fuga es plata que ninguna venta explica y todavía no se descontó.
        self.assertEqual(r["margen_bruto_real"], r["ventas"] - r["cogs_teorico"])
        self.assertEqual(r["margen_bruto_real_con_fuga"],
                         r["margen_bruto_real"] + r["fuga_inventario"])

    def test_sin_cierre_en_el_rango_la_fuga_se_declara_NO_MEDIDA_no_cero(self):
        r = rentabilidad_resumen(self.db, self.t.id)

        self.assertIsNone(r["fuga_inventario"])
        self.assertFalse(r["tiene_fuga_medida"])
        self.assertEqual(r["periodos_con_fuga_medida"], [])
        self.assertIsNone(r["margen_bruto_real_con_fuga"])

    def test_si_la_conciliacion_falla_el_estado_de_resultados_igual_se_muestra(self):
        # La fuga es un dato ADITIVO. El P&L nunca dependió de
        # `movimientos_inventario` y no puede empezar a caerse entero por eso.
        from app.services import conciliacion, rentabilidad

        self._cerrar_mes_con_fuga()
        original = conciliacion.fuga_medida
        conciliacion.fuga_medida = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("inventario roto"))
        try:
            r = rentabilidad.get_rentabilidad(self.db, date(2026, 7, 1), date(2026, 7, 31),
                                              tienda_id=self.t.id)["resumen"]
        finally:
            conciliacion.fuga_medida = original

        self.assertIn("margen_neto", r)          # el P&L sigue entero
        self.assertIsNone(r["fuga_inventario"])  # y la fuga dice la verdad: no se midió
        self.assertFalse(r["tiene_fuga_medida"])

    def test_la_fuga_valorizada_con_precio_de_VENTA_llega_al_pl_declarada(self):
        # Un producto de reventa sin costo cargado se valoriza con su precio de
        # venta: la fuga queda inflada y hasta ahora entraba al P&L como si fuera
        # un número firme.
        gaseosa = self._producto("GASEOSA", stock=0, precio_venta=5000)
        self._mov(gaseosa, "entrada", 20, "Recepción #1", date(2026, 6, 20))
        foto = inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)
        item = next(i for i in foto["items"] if i["producto_id"] == gaseosa.id)
        inv_svc.guardar(self.db, foto["id"], [{"id": item["id"], "cantidad_real": 18}])
        inv_svc.cerrar(self.db, foto["id"], self.admin.id)

        r = rentabilidad_resumen(self.db, self.t.id)

        self.assertEqual(r["fuga_inventario"], -10000)   # 2 × $5.000 de VENTA
        self.assertEqual(r["fuga_estimados"], 1)         # y lo dice

    def test_la_cobertura_de_varios_meses_es_producto_mes_y_lo_dice(self):
        # Sumar la cobertura de cada cierre a lo largo del rango daba un número
        # que no existe en ninguna parte: 3 cierres de 2 productos se leían como
        # "cubre X de 6 productos" cuando el local tiene 2. El ratio está bien; el
        # absoluto solo se puede leer con la cantidad de cierres al lado.
        from app.services import rentabilidad

        cafe = self._producto("CAFE", stock=0, precio_costo=100)
        te = self._producto("TE", stock=0, precio_costo=100)
        self._mov(cafe, "entrada", 900, "Recepción #1", date(2025, 12, 20))
        self._mov(te, "entrada", 900, "Recepción #1", date(2025, 12, 20))
        for mes in (1, 2, 3):
            foto = inv_svc.iniciar(self.db, self.t.id, 2026, mes, self.admin.id)
            item = next(i for i in foto["items"] if i["producto_id"] == cafe.id)
            inv_svc.guardar(self.db, foto["id"],
                            [{"id": item["id"], "cantidad_real": 900 - mes}])
            inv_svc.cerrar(self.db, foto["id"], self.admin.id)

        r = rentabilidad.get_rentabilidad(self.db, date(2026, 1, 1), date(2026, 3, 31),
                                          tienda_id=self.t.id)["resumen"]

        self.assertEqual(r["fuga_cierres"], 3)
        # 1 producto contado por cierre × 3 cierres, sobre 2 productos × 3 cierres.
        self.assertEqual(r["fuga_cobertura_contados"], 3)
        self.assertEqual(r["fuga_cobertura_productos"], 6)
        self.assertEqual(r["fuga_meses"], 3)

    def test_los_productos_sin_costo_no_se_cuentan_una_vez_por_mes(self):
        # `fuga_sin_costo` es una instrucción de trabajo ("cargá el costo de
        # estos"): contarlo por producto-mes manda a buscar fichas que no existen.
        from app.services import rentabilidad

        sin = self._producto("CANELA", stock=0)
        self._mov(sin, "entrada", 900, "Recepción #1", date(2025, 12, 20))
        for mes in (1, 2, 3):
            foto = inv_svc.iniciar(self.db, self.t.id, 2026, mes, self.admin.id)
            item = next(i for i in foto["items"] if i["producto_id"] == sin.id)
            inv_svc.guardar(self.db, foto["id"],
                            [{"id": item["id"], "cantidad_real": 900 - mes * 10}])
            inv_svc.cerrar(self.db, foto["id"], self.admin.id)

        r = rentabilidad.get_rentabilidad(self.db, date(2026, 1, 1), date(2026, 3, 31),
                                          tienda_id=self.t.id)["resumen"]

        self.assertEqual(r["fuga_sin_costo"], 1)     # UN producto, no tres
        self.assertEqual(r["fuga_cierres"], 3)

    def test_el_pl_declara_que_el_margen_y_la_fuga_no_cubren_el_mismo_tramo(self):
        # `margen_bruto_real_con_fuga` mezcla un margen del rango COMPLETO con una
        # fuga medida solo sobre meses cerrados enteros. El sesgo es optimista
        # (subdeclara la fuga), así que el par de tramos tiene que viajar.
        from app.services import rentabilidad

        self._cerrar_mes_con_fuga()      # cierra julio

        r = rentabilidad.get_rentabilidad(self.db, date(2026, 1, 1), date(2026, 12, 31),
                                          tienda_id=self.t.id)["resumen"]

        self.assertEqual(r["fuga_meses"], 1)
        self.assertEqual(r["fuga_meses_rango"], 12)
        self.assertLess(r["fuga_meses"], r["fuga_meses_rango"])

    # ── El OTRO eje del mismo tramo: las SEDES ───────────────────────────────
    def _otra_sede_que_vende_y_no_cuenta(self):
        """Una segunda sede que vende y NUNCA cierra un conteo.

        Su venta entra al margen de "Todas las sedes" y su fuga no entra a la
        resta: declarar solo los meses dejaba pasar exactamente este caso."""
        otra = Tienda(nombre="Centro", direccion="y")
        self.db.add(otra)
        self.db.flush()
        self._venta(otra.id, date(2026, 7, 12))
        self.db.commit()
        return otra

    def _venta(self, tienda_id, dia: date, total=50000):
        t = Ticket(tienda_id=tienda_id, caja_turno_id=1, usuario_id=self.admin.id,
                   fecha=inicio_dia_col_utc(dia) + timedelta(hours=3),
                   total=total, metodo_pago="efectivo", estado="completado")
        self.db.add(t)
        self.db.commit()
        return t

    def test_el_pl_declara_que_la_fuga_no_cubre_todas_las_sedes(self):
        from app.services import rentabilidad

        self._cerrar_mes_con_fuga()                # solo la sede Vida cierra julio
        self._venta(self.t.id, date(2026, 7, 12))
        self._otra_sede_que_vende_y_no_cuenta()

        r = rentabilidad.get_rentabilidad(self.db, date(2026, 7, 1), date(2026, 7, 31))["resumen"]

        # Las dos sedes vendieron y el margen las suma a las dos…
        self.assertEqual(r["fuga_sedes_rango"], 2)
        # …pero la fuga sale de UNA sola, y ahora se puede decir.
        self.assertEqual(r["fuga_sedes"], 1)
        # El eje de los meses no ve nada raro: julio está cerrado y el rango es julio.
        self.assertEqual(r["fuga_meses"], r["fuga_meses_rango"])

    def test_filtrando_por_una_sede_la_cobertura_de_sedes_esta_completa(self):
        # Con una sede elegida no hay nada que declarar: el margen y la fuga hablan
        # de la misma. El aviso no puede salir por el solo hecho de que exista otro
        # local en el catálogo.
        from app.services import rentabilidad

        self._cerrar_mes_con_fuga()
        self._venta(self.t.id, date(2026, 7, 12))
        self._otra_sede_que_vende_y_no_cuenta()

        r = rentabilidad.get_rentabilidad(self.db, date(2026, 7, 1), date(2026, 7, 31),
                                          tienda_id=self.t.id)["resumen"]

        self.assertEqual(r["fuga_sedes"], 1)
        self.assertEqual(r["fuga_sedes_rango"], 1)

    def test_la_sede_que_midio_no_tapa_a_la_que_vendio(self):
        # EL CASO CRUZADO, que comparar CANTIDADES deja pasar: la sede Vida cierra
        # su conteo pero no vendió nada en el rango, y la sede Centro vendió y nunca
        # cerró. Contando, es "1 medida de 1 que vendió" y el aviso se queda callado
        # — cuando la realidad es que TODO el margen del rango viene de una sede de
        # la que no se midió un solo gramo. Hay que intersecar los conjuntos.
        from app.services import rentabilidad

        self._cerrar_mes_con_fuga()                 # Vida mide y NO vende
        self._otra_sede_que_vende_y_no_cuenta()     # Centro vende y NO mide

        r = rentabilidad.get_rentabilidad(self.db, date(2026, 7, 1), date(2026, 7, 31))["resumen"]

        self.assertEqual(r["fuga_sedes_rango"], 1)  # solo Centro vendió
        self.assertEqual(r["fuga_sedes"], 0)        # y de Centro no se midió nada
        self.assertLess(r["fuga_sedes"], r["fuga_sedes_rango"])   # el aviso sale

    def test_una_sede_que_no_vendio_no_dispara_el_aviso(self):
        # Una sede sin operación en el rango no aporta margen, así que no falta en
        # la comparación: contarla sería un aviso que no se puede apagar nunca.
        from app.services import rentabilidad

        self._cerrar_mes_con_fuga()
        self._venta(self.t.id, date(2026, 7, 12))
        self.db.add(Tienda(nombre="Bodega", direccion="z"))   # existe y no vende
        self.db.commit()

        r = rentabilidad.get_rentabilidad(self.db, date(2026, 7, 1), date(2026, 7, 31))["resumen"]

        self.assertEqual(r["fuga_sedes_rango"], 1)
        self.assertEqual(r["fuga_sedes"], 1)

    def _factura_recibida(self, producto, cantidad, precio, dia):
        f = FacturaCompra(proveedor="Prov", tienda_id=self.t.id,
                          valor_total=cantidad * precio, usuario_id=self.admin.id,
                          tipo_pago=TipoPagoEnum.contado,
                          fecha_recibido=inicio_dia_col_utc(dia) + timedelta(hours=3))
        self.db.add(f)
        self.db.flush()
        self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=producto.id,
                                      cantidad=cantidad, precio_unitario=precio))
        self.db.commit()


class CostoCongeladoTest(_Base):
    """`valor_unitario` se congela al iniciar el conteo y sobre un mes que YA pasó
    por un cierre no se re-sincroniza nunca más (reabrir():207). El origen del
    costo, en cambio, se recalcula con el catálogo vivo. Son dos relojes en la
    misma fila, y la pantalla prometía que cargar el costo volvía real el neto:
    lo único que pasaba era que el aviso desaparecía."""

    def _mes_cerrado_sin_costo(self):
        p = self._producto("CANELA", stock=0)      # sin costo de ninguna clase
        self._mov(p, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        foto = inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)
        item = next(i for i in foto["items"] if i["producto_id"] == p.id)
        inv_svc.guardar(self.db, foto["id"], [{"id": item["id"], "cantidad_real": 90}])
        inv_svc.cerrar(self.db, foto["id"], self.admin.id)
        return p

    def test_cargar_el_costo_sobre_un_mes_cerrado_no_cambia_el_neto(self):
        p = self._mes_cerrado_sin_costo()
        antes = inv_svc.get_conciliacion(self.db, self.t.id, 2026, 7)
        self.assertEqual(antes["resumen"]["valor_neto"], 0)
        self.assertEqual(antes["resumen"]["dif_sin_costo"], 1)

        p.precio_costo = 500       # el dueño carga el costo HOY
        self.db.commit()
        despues = inv_svc.get_conciliacion(self.db, self.t.id, 2026, 7)

        # El aviso viejo se apaga (mira el catálogo vivo)…
        self.assertEqual(despues["resumen"]["dif_sin_costo"], 0)
        # …pero el neto NO se movió: la foto del período está congelada.
        self.assertEqual(despues["resumen"]["valor_neto"], 0)
        # Y eso es exactamente lo que la pantalla ahora puede decir.
        self.assertEqual(despues["resumen"]["dif_costo_congelado"], 1)
        self.assertTrue(despues["resumen"]["foto_congelada"])
        it = next(i for i in despues["items"] if i["producto_id"] == p.id)
        self.assertEqual(it["valor_unitario"], 0)        # con el que se valorizó
        self.assertEqual(it["valor_unitario_vivo"], 500)  # el del catálogo de hoy
        self.assertTrue(it["costo_congelado"])

    def test_un_mes_sin_cerrar_todavia_se_puede_sincronizar(self):
        # Mientras no hay cierre no hay foto que proteger: `reabrir` refresca el
        # costo, así que ahí la pantalla SÍ puede mandar a cargarlo.
        p = self._producto("CANELA", stock=0)
        self._mov(p, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        foto = inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)
        item = next(i for i in foto["items"] if i["producto_id"] == p.id)
        inv_svc.guardar(self.db, foto["id"], [{"id": item["id"], "cantidad_real": 90}])

        p.precio_costo = 500
        self.db.commit()
        antes = inv_svc.get_conciliacion(self.db, self.t.id, 2026, 7)
        self.assertFalse(antes["resumen"]["foto_congelada"])
        # El aviso sale mientras el mes sigue ABIERTO, que es el único momento en
        # que cargar el costo todavía cambia el número: acá "Sincronizar catálogo"
        # sí lo pone al día. Contarlo sobre la diferencia ALMACENADA lo dejaba en 0
        # hasta el cierre — o sea, aparecía recién cuando ya no servía para nada.
        self.assertEqual(antes["estado"], "en_proceso")
        self.assertEqual(antes["resumen"]["dif_costo_congelado"], 1)

        inv_svc.reabrir(self.db, self.t.id, 2026, 7, self.admin.id)
        despues = inv_svc.get_conciliacion(self.db, self.t.id, 2026, 7)

        it = next(i for i in despues["items"] if i["producto_id"] == p.id)
        self.assertEqual(it["valor_unitario"], 500)
        self.assertFalse(it["costo_congelado"])
        # Sincronizado el catálogo, el aviso se apaga solo.
        self.assertEqual(despues["resumen"]["dif_costo_congelado"], 0)

    def test_sin_costo_nuevo_nada_queda_marcado_como_congelado(self):
        self._mes_cerrado_sin_costo()
        out = inv_svc.get_conciliacion(self.db, self.t.id, 2026, 7)

        self.assertEqual(out["resumen"]["dif_costo_congelado"], 0)
        self.assertTrue(all(not i["costo_congelado"] for i in out["items"]))


class AvisoDeCalidadEnMesAbiertoTest(_Base):
    """Los contadores de calidad del neto miran la diferencia VIVA.

    La almacenada (`InventarioMensualItem.diferencia`) solo la escriben `cerrar()`
    y `corregir_item()`, así que en un mes EN PROCESO vale 0 en todas las filas —
    mientras la tabla de al lado ya muestra los faltantes con el cálculo vivo. Con
    la almacenada, el consejo "cargá el costo" aparecía recién en el mes cerrado:
    exactamente cuando cargarlo ya no mueve el número."""

    def _mes_en_proceso_con_faltantes(self):
        a = self._producto("CANELA", stock=0)          # sin costo de ninguna clase
        b = self._producto("NUEZ MOSCADA", stock=0)
        for p in (a, b):
            self._mov(p, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        foto = inv_svc.iniciar(self.db, self.t.id, 2026, 7, self.admin.id)
        por_prod = {i["producto_id"]: i["id"] for i in foto["items"]}
        inv_svc.guardar(self.db, foto["id"], [
            {"id": por_prod[a.id], "cantidad_real": 70},
            {"id": por_prod[b.id], "cantidad_real": 70},
        ])
        return a, b

    def test_el_mes_abierto_ya_avisa_que_faltan_costos(self):
        self._mes_en_proceso_con_faltantes()

        out = inv_svc.get_conciliacion(self.db, self.t.id, 2026, 7)

        # La diferencia ALMACENADA sigue en 0 —nadie cerró todavía— y ese era el
        # dato con el que se contaba.
        self.assertTrue(all((i["diferencia"] or 0) == 0 for i in out["items"]))
        self.assertEqual(out["estado"], "en_proceso")
        # Pero los dos faltantes existen y no se pueden valorizar: se dice AHORA.
        self.assertEqual(out["resumen"]["dif_sin_costo"], 2)
        self.assertFalse(out["resumen"]["foto_congelada"])

    def test_lo_que_nadie_conto_no_cuenta_como_diferencia(self):
        # `cantidad_real` en None no es un faltante: es un renglón sin contar. Si
        # entrara al conteo, el aviso saldría por productos que nadie miró.
        a, _b = self._mes_en_proceso_con_faltantes()
        c = self._producto("PIMIENTA", stock=0)
        self._mov(c, "entrada", 100, "Recepción #1", date(2026, 6, 20))
        inv_svc.reabrir(self.db, self.t.id, 2026, 7, self.admin.id)   # suma PIMIENTA

        out = inv_svc.get_conciliacion(self.db, self.t.id, 2026, 7)

        sin_contar = next(i for i in out["items"] if i["producto_id"] == c.id)
        self.assertFalse(sin_contar["fue_contado"])
        self.assertIsNone(sin_contar["cantidad_real"])
        self.assertEqual(out["resumen"]["dif_sin_costo"], 2)          # no 3

    def test_lo_contado_exacto_tampoco_cuenta(self):
        a, b = self._mes_en_proceso_con_faltantes()
        foto = inv_svc.get_actual(self.db, self.t.id, 2026, 7)
        item_b = next(i for i in foto["items"] if i["producto_id"] == b.id)
        inv_svc.guardar(self.db, foto["id"],
                        [{"id": item_b["id"], "cantidad_real": 100}])   # dio exacto

        out = inv_svc.get_conciliacion(self.db, self.t.id, 2026, 7)

        self.assertEqual(out["resumen"]["dif_sin_costo"], 1)


def rentabilidad_resumen(db, tienda_id):
    from app.services import rentabilidad
    return rentabilidad.get_rentabilidad(
        db, date(2026, 7, 1), date(2026, 7, 31), tienda_id=tienda_id)["resumen"]


if __name__ == "__main__":
    unittest.main()
