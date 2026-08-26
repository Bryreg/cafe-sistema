"""La escalera de UN producto tiene que dar exactamente lo mismo que la de la sede.

La ficha de un insumo pedía la escalera COMPLETA de la sede para leer un solo
renglón. Medido en producción: abrir el insumo más movido costaba 1,9 s y abrir
uno SIN UN SOLO MOVIMIENTO costaba 1,7 s — la diferencia es ruido, porque el
trabajo nunca fue sobre el insumo sino sobre los 19.000 movimientos de la sede.
El mismo insumo sobre un rango de un día bajaba a 0,5 s: lo que manda es el
período, no el producto. Eso solo puede pasar si se está calculando todo.

`producto_ids` acota ese trabajo. El riesgo del cambio es UNO y es grave: que la
escalera recortada devuelva un número distinto al de la tabla. Ahí no se rompe
nada visible —las dos pantallas simplemente dicen cosas distintas del mismo
insumo y nadie sabe cuál creer—, que es el modo de falla más caro de este
sistema y el que ya nos costó una vez.

Estos tests comparan RENGLÓN POR RENGLÓN la escalera completa contra la acotada,
sobre un escenario con todo lo que puede introducir dependencias entre productos:

  · RECETAS — el consumo teórico de un insumo sale de las VENTAS de los productos
    terminados que lo usan. Si acotar dejara los tickets afuera, el insumo de una
    receta aparecería con consumo teórico 0 y su fuga saldría inventada.
  · AJUSTES — un ajuste guarda el stock ABSOLUTO, no el delta, y es el ancla
    desde la que se reconstruye el saldo hacia atrás. El corte del libro se
    calcula sobre el conjunto de productos pedidos: acotarlo no puede dejar un
    producto sin su ancla.
  · UN PRODUCTO SIN MOVIMIENTOS y otro con historia anterior al rango, que son
    los dos bordes de la reconstrucción del arranque.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import inicio_dia_col_utc
from app.database import Base
from app.models.models import (CategoriaProductoEnum, Inventario,
                               MovimientoInventario, Producto, ProductoInsumo,
                               RolEnum, Ticket, TicketItem, Tienda, Usuario)
from app.services import conciliacion as esc

DESDE, HASTA = date(2026, 7, 1), date(2026, 7, 31)


class EscaleraAcotadaTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.t = Tienda(nombre="Vida", direccion="x")
        self.otra = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.t, self.otra])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()
        self._escenario()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── fixtures ─────────────────────────────────────────────────────────────
    def _producto(self, nombre, stock=0.0, precio_venta=0.0, precio_costo=None,
                  unidad="gr", tienda=None):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=True,
                     precio_venta=precio_venta, precio_costo=precio_costo)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=(tienda or self.t).id,
                               stock_actual=stock, stock_minimo=0))
        self.db.commit()
        return p

    def _mov(self, producto, tipo, cantidad, motivo, dia: date, tienda=None):
        tid = (tienda or self.t).id
        fila = self.db.query(Inventario).filter_by(
            producto_id=producto.id, tienda_id=tid).first()
        if tipo == "entrada":
            fila.stock_actual = (fila.stock_actual or 0) + cantidad
        elif tipo == "salida":
            fila.stock_actual = (fila.stock_actual or 0) - cantidad
        else:
            fila.stock_actual = cantidad
        self.db.add(MovimientoInventario(
            producto_id=producto.id, tienda_id=tid, tipo=tipo, cantidad=cantidad,
            motivo=motivo, usuario_id=self.admin.id,
            fecha=inicio_dia_col_utc(dia) + timedelta(hours=3)))
        self.db.commit()

    def _venta(self, producto, cantidad, dia: date):
        tk = Ticket(tienda_id=self.t.id, caja_turno_id=1, usuario_id=self.admin.id,
                    fecha=inicio_dia_col_utc(dia) + timedelta(hours=5),
                    total=1000 * cantidad, metodo_pago="efectivo", estado="completado")
        self.db.add(tk)
        self.db.flush()
        self.db.add(TicketItem(ticket_id=tk.id, producto_id=producto.id,
                               nombre_producto=producto.nombre, cantidad=cantidad,
                               precio_unitario=1000, subtotal=1000 * cantidad))
        self.db.commit()

    def _escenario(self):
        # Un terminado que se vende y CONSUME dos insumos por receta: la única
        # dependencia real entre productos que tiene la escalera.
        self.americano = self._producto("AMERICANO", stock=0, precio_venta=5000)
        self.cafe = self._producto("CAFE", stock=0, precio_costo=40)
        self.leche = self._producto("LECHE", stock=0, unidad="ml", precio_costo=4)
        self.db.add_all([
            ProductoInsumo(producto_id=self.americano.id, insumo_id=self.cafe.id, cantidad=10),
            ProductoInsumo(producto_id=self.americano.id, insumo_id=self.leche.id, cantidad=100),
        ])
        self.db.commit()

        # CAFE: historia anterior al rango, ajuste adentro, ventas y merma.
        self._mov(self.cafe, "entrada", 5000, "Factura #1 — Cafexcoop", date(2026, 6, 10))
        self._mov(self.cafe, "ajuste", 4800, "Conteo #1 aplicado al inventario", date(2026, 6, 28))
        self._mov(self.cafe, "entrada", 2000, "Factura #2 — Cafexcoop", date(2026, 7, 5))
        self._mov(self.cafe, "salida", 300, "Venta POS — insumo de Americano", date(2026, 7, 8))
        self._mov(self.cafe, "salida", 50, "Daño: se cayó al piso", date(2026, 7, 9))
        self._mov(self.cafe, "salida", 200, "Traslado a Palmetto: falta allá", date(2026, 7, 12))
        self._mov(self.cafe, "ajuste", 6100, "Conteo #2 aplicado al inventario", date(2026, 7, 20))

        # LECHE: solo entradas y ventas, sin ancla de ajuste dentro del rango.
        self._mov(self.leche, "entrada", 20000, "Recepción #3", date(2026, 6, 15))
        self._mov(self.leche, "salida", 3000, "Venta POS — insumo de Americano", date(2026, 7, 8))

        # Las ventas que alimentan el consumo TEÓRICO de los dos insumos.
        self._venta(self.americano, 30, date(2026, 7, 8))
        self._venta(self.americano, 12, date(2026, 7, 18))

        # Un insumo SIN un solo movimiento: el borde barato, y el que en
        # producción tardaba lo mismo que el más movido.
        self.bolsa = self._producto("BOLSA ANTIGRASA", stock=232, unidad="und")

        # Ruido: otro insumo movido, y uno de la OTRA sede que no debe aparecer.
        self.azucar = self._producto("AZUCAR", stock=0, precio_costo=3)
        self._mov(self.azucar, "entrada", 8000, "Factura #4 — Makro", date(2026, 7, 2))
        self._mov(self.azucar, "salida", 1500, "Consumo (Cata): se lo tomó", date(2026, 7, 11))
        self.ajeno = self._producto("PULPA MORA", stock=50, tienda=self.otra)
        self._mov(self.ajeno, "entrada", 100, "Factura #9", date(2026, 7, 3), tienda=self.otra)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _completa(self, fisicos=None):
        out = esc.escalera_rango(self.db, self.t.id, DESDE, HASTA, fisicos=fisicos)
        return {p["producto_id"]: p for p in out["productos"]}

    def _acotada(self, ids, fisicos=None):
        out = esc.escalera_rango(self.db, self.t.id, DESDE, HASTA, fisicos=fisicos,
                                 producto_ids=ids)
        return {p["producto_id"]: p for p in out["productos"]}

    # ── los tests ────────────────────────────────────────────────────────────
    def test_cada_producto_solo_da_identico_a_la_sede_entera(self):
        completa = self._completa()
        for p in (self.cafe, self.leche, self.bolsa, self.azucar, self.americano):
            with self.subTest(producto=p.nombre):
                fila = self._acotada([p.id]).get(p.id)
                self.assertIsNotNone(fila, f"{p.nombre} desapareció al acotar")
                # Renglón por renglón, no un par de campos elegidos a dedo: lo que
                # se protege es que NINGUNA clave cambie de valor.
                self.assertEqual(fila, completa[p.id])

    def test_el_consumo_teorico_de_una_receta_sobrevive_al_filtro(self):
        # Es la única dependencia entre productos: sale de las VENTAS del
        # terminado, no del libro del insumo. 42 americanos × 10 gr = 420 gr.
        fila = self._acotada([self.cafe.id])[self.cafe.id]
        self.assertEqual(fila["consumo_teorico"], 420)
        self.assertEqual(fila["consumo_teorico"],
                         self._completa()[self.cafe.id]["consumo_teorico"])
        # Y el insumo sigue teniendo VÍA de consumo: acotar no lo convierte en un
        # producto del que «no se sabe cómo se consume». Se comprueba CON un
        # conteo físico: sin él el residuo es None a propósito —no hay contra qué
        # comparar la reconstrucción— y eso no dice nada sobre la vía.
        con_fisico = self._acotada([self.cafe.id], {self.cafe.id: 5900})[self.cafe.id]
        self.assertIsNotNone(con_fisico["diferencia_inexplicada"])
        self.assertEqual(con_fisico["consumo_teorico"], 420)

    def test_el_ajuste_sigue_anclando_el_arranque(self):
        # El ajuste guarda el stock ABSOLUTO y es el ancla desde la que se
        # reconstruye hacia atrás. El corte del libro se calcula sobre el
        # conjunto pedido: acotar no puede dejar al producto sin su ancla.
        fila = self._acotada([self.cafe.id])[self.cafe.id]
        completa = self._completa()[self.cafe.id]
        self.assertEqual(fila["stock_inicial"], completa["stock_inicial"])
        self.assertEqual(fila["stock_inicial_estimado"], completa["stock_inicial_estimado"])
        self.assertEqual(fila["ajustes_conteo"], completa["ajustes_conteo"])

    def test_el_fisico_contado_y_la_fuga_no_cambian(self):
        fisicos = {self.cafe.id: 5900}
        self.assertEqual(self._acotada([self.cafe.id], fisicos)[self.cafe.id],
                         self._completa(fisicos)[self.cafe.id])

    def test_acotar_a_varios_da_lo_mismo_que_acotar_a_cada_uno(self):
        ids = [self.cafe.id, self.leche.id, self.bolsa.id]
        juntos = self._acotada(ids)
        self.assertEqual(set(juntos), set(ids))
        for pid in ids:
            with self.subTest(producto_id=pid):
                self.assertEqual(juntos[pid], self._acotada([pid])[pid])

    def test_el_filtro_no_trae_a_los_demas(self):
        # Si devolviera la sede entera el ahorro sería cero y nadie lo notaría:
        # los números estarían bien y la pantalla seguiría lenta.
        solo = self._acotada([self.cafe.id])
        self.assertEqual(list(solo), [self.cafe.id])

    def test_un_producto_de_otra_sede_no_aparece_aunque_se_pida(self):
        # El filtro de producto no puede saltarse el de sede.
        self.assertEqual(self._acotada([self.ajeno.id]), {})

    def test_pedir_un_producto_inexistente_devuelve_vacio_sin_reventar(self):
        self.assertEqual(self._acotada([999999]), {})

    def test_sin_filtro_sigue_viniendo_la_sede_entera(self):
        # El camino viejo no cambia: la tabla y la pantalla de conciliación
        # siguen pidiendo todo.
        completa = self._completa()
        self.assertEqual(len(completa), 5)   # los 5 de Vida, no el de Palmetto
        self.assertNotIn(self.ajeno.id, completa)

    def test_un_contexto_prestado_igual_respeta_el_filtro(self):
        # El P&L pasa su propio `ctx`, que trae la sede entera. Sin el filtro
        # defensivo, `producto_ids` se ignoraría en silencio: los números
        # estarían bien y el parámetro significaría una cosa distinta según
        # quién lo llame, que es la clase de bug que nadie encuentra.
        ctx = esc._Ctx(self.db, horizonte=DESDE)
        out = esc.escalera_rango(self.db, self.t.id, DESDE, HASTA,
                                 ctx=ctx, producto_ids=[self.cafe.id])
        self.assertEqual([p["producto_id"] for p in out["productos"]], [self.cafe.id])

    def test_un_contexto_acotado_no_se_reusa_para_pedir_de_mas(self):
        # La memoización de `_Ctx` tiene una sola clave (la sede). Un contexto
        # acotado solo puede servir a sus productos: si alguien lo reusara para
        # pedir otro, tiene que salir vacío y no una fila calculada a medias
        # sobre un libro que se leyó recortado.
        ctx = esc._Ctx(self.db, horizonte=DESDE, solo_ids=[self.cafe.id])
        out = esc.escalera_rango(self.db, self.t.id, DESDE, HASTA, ctx=ctx)
        self.assertEqual([p["producto_id"] for p in out["productos"]], [self.cafe.id])


if __name__ == "__main__":
    unittest.main()
