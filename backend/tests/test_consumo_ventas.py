"""El consumo aprendido de las VENTAS reales — no solo de las salidas de 14 días.

Estos tests fijan el cambio: «alcanza X días» y la cantidad sugerida ahora salen
de lo que REALMENTE se vendió, sobre 8 semanas, con mediana por día de la semana,
repartido al inventario igual que la caja (stock propio, receta, combo). Pero
nunca por debajo de lo que físicamente salió del estante (el piso de salidas),
así no se subestima. Y cuando no hay ventas, todo queda como estaba.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.core.tz import hoy_col
from app.models.models import (
    CategoriaProductoEnum, Inventario, MovimientoInventario, Producto,
    ProductoInsumo, RolEnum, Ticket, TicketItem, TicketItemComboSeleccion,
    Tienda, TipoMovInvEnum, Usuario,
)
from app.services import consumo_ventas
from app.services import pedidos as pedidos_svc


class ConsumoVentasTest(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.hoy = hoy_col()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.vida)
        self.db.flush()
        self.user = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                            rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.user)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    # ─── andamio ──────────────────────────────────────────────────────────────

    def _producto(self, nombre, controla_stock=True, precio_venta=0, lead_time_dias=2):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida="und", controla_stock=controla_stock,
                     incluir_en_conteo=True, precio_venta=precio_venta,
                     lead_time_dias=lead_time_dias)
        self.db.add(p)
        self.db.flush()
        return p

    def _inv(self, producto, stock=0.0, minimo=0.0):
        inv = Inventario(producto_id=producto.id, tienda_id=self.vida.id,
                         stock_actual=stock, stock_minimo=minimo)
        self.db.add(inv)
        self.db.flush()
        return inv

    def _fecha_utc(self, dias_atras):
        """Instante UTC que cae en el día Colombia (hoy - dias_atras). Mediodía UTC
        = 7am Colombia, mismo día — lejos de cualquier frontera de medianoche."""
        d = self.hoy - timedelta(days=dias_atras)
        return datetime.combine(d, time(12, 0))

    def _ticket(self, lineas, dias_atras, estado="completado"):
        """lineas: [(producto, cantidad)] o [(producto, cantidad, [(componente, cant)])].
        El tercer campo, si viene, hace la línea un COMBO con sus selecciones."""
        total = sum((p.precio_venta or 0) * c for p, c, *_ in lineas)
        t = Ticket(tienda_id=self.vida.id, caja_turno_id=1, usuario_id=self.user.id,
                   fecha=self._fecha_utc(dias_atras), total=total, metodo_pago="efectivo",
                   estado=estado)
        self.db.add(t)
        self.db.flush()
        for linea in lineas:
            prod, cant = linea[0], linea[1]
            ti = TicketItem(ticket_id=t.id, producto_id=prod.id, nombre_producto=prod.nombre,
                            cantidad=cant, precio_unitario=(prod.precio_venta or 0),
                            subtotal=(prod.precio_venta or 0) * cant)
            self.db.add(ti)
            self.db.flush()
            if len(linea) == 3:
                for comp, ccant in linea[2]:
                    self.db.add(TicketItemComboSeleccion(
                        ticket_item_id=ti.id, combo_id=1, producto_id=comp.id,
                        nombre_grupo="g", nombre_opcion="o", cantidad=ccant))
        self.db.flush()
        return t

    def _tasa(self, producto):
        return consumo_ventas.tasa_diaria_por_producto(self.db, self.vida.id, self.hoy).get(producto.id)

    def _item_base(self, producto):
        items, _ = pedidos_svc._items_base(self.db, self.vida.id)
        return next((i for i in items if i["producto_id"] == producto.id), None)

    # ─── 1. lo que se vende parejo da su propia tasa ──────────────────────────

    def test_vende_parejo_da_esa_tasa(self):
        """Vendido 4 por día, todos los días de la ventana → la tasa es 4/día.
        (Sin salidas de inventario: manda la venta.)"""
        alfajor = self._producto("Alfajor")
        self._inv(alfajor, stock=40)
        for k in range(1, 57):                      # [hoy-56, hoy-1]
            self._ticket([(alfajor, 4)], dias_atras=k)
        self.assertAlmostEqual(self._tasa(alfajor), 4.0, places=3)

    # ─── 2. un pico de un solo día no mueve la mediana ────────────────────────

    def test_pico_de_un_dia_no_mueve_la_tasa(self):
        """Vendió 100 un día y 0 el resto. La mediana por día de semana lo ignora:
        es exactamente lo que se quiere (no salir corriendo por un evento)."""
        torta = self._producto("Torta")
        self._inv(torta, stock=5)
        otro = self._producto("Café")            # abre el local todos los días
        self._inv(otro, stock=999)
        for k in range(1, 57):
            self._ticket([(otro, 1)], dias_atras=k)
        self._ticket([(torta, 100)], dias_atras=10)   # el pico
        # 100 en 1 de 8 muestras de ese día de semana → mediana 0 → tasa 0 (no aparece).
        self.assertIsNone(self._tasa(torta))

    # ─── 3. lo que solo se vende los sábados se proyecta por semana ────────────

    def test_solo_sabados_da_tasa_por_dia_calendario(self):
        """Vende S los sábados y 0 el resto (local abierto todos los días). La tasa
        es la mediana del sábado ÷ 7: cuánto se consume por día calendario, para que
        «alcanza» proyecte hasta el próximo sábado."""
        pandebono = self._producto("Pan de bono")
        self._inv(pandebono, stock=14)
        otro = self._producto("Café")
        self._inv(otro, stock=999)
        S = 14
        for k in range(1, 57):
            d = self.hoy - timedelta(days=k)
            lineas = [(otro, 1)]
            if d.weekday() == 5:                  # sábado
                lineas.append((pandebono, S))
            self._ticket(lineas, dias_atras=k)
        self.assertAlmostEqual(self._tasa(pandebono), S / 7.0, places=3)

    # ─── 4. la venta de un compuesto descuenta sus insumos (receta) ───────────

    def test_receta_reparte_la_venta_a_los_insumos(self):
        """Un café con leche no lleva stock propio; descuenta leche por receta. La
        venta del café tiene que aparecer como consumo de LECHE, no del café."""
        leche = self._producto("Leche", controla_stock=True)
        self._inv(leche, stock=100)
        cafe = self._producto("Café con leche", controla_stock=False, precio_venta=6000)
        self.db.add(ProductoInsumo(producto_id=cafe.id, insumo_id=leche.id, cantidad=0.2))
        self.db.flush()
        for k in range(1, 57):
            self._ticket([(cafe, 10)], dias_atras=k)      # 10 cafés/día → 2 de leche/día
        self.assertAlmostEqual(self._tasa(leche), 2.0, places=3)
        self.assertIsNone(self._tasa(cafe), "el café no lleva stock propio: no es consumo de inventario")

    # ─── 5. un combo se abre en sus componentes reales ────────────────────────

    def test_combo_reparte_a_sus_componentes(self):
        """El combo entra al ticket como una línea sombra; su consumo real son los
        productos de la selección. Vender el combo consume el componente."""
        galleta = self._producto("Galleta", controla_stock=True)
        self._inv(galleta, stock=100)
        combo = self._producto("Combo desayuno", controla_stock=False, precio_venta=12000)
        for k in range(1, 57):
            self._ticket([(combo, 3, [(galleta, 2)])], dias_atras=k)   # 3 combos × 2 = 6/día
        self.assertAlmostEqual(self._tasa(galleta), 6.0, places=3)

    # ─── 6. lo anulado, lo de hoy y lo viejo no cuentan ───────────────────────

    def test_anulado_hoy_y_fuera_de_ventana_no_cuentan(self):
        prod = self._producto("Muffin")
        self._inv(prod, stock=10)
        self._ticket([(prod, 50)], dias_atras=10, estado="anulado")   # anulado
        self._ticket([(prod, 50)], dias_atras=0)                       # hoy (excluido)
        self._ticket([(prod, 50)], dias_atras=70)                      # fuera de 56 días
        self.assertIsNone(self._tasa(prod), "ninguna de esas ventas alimenta el consumo")

    # ─── 7. nunca por debajo de lo que salió del estante (piso de salidas) ─────

    def test_el_piso_de_salidas_manda_cuando_es_mayor(self):
        """Se vendió poco por POS (1/día) pero salió mucho del inventario (mermas
        10/día). El consumo no puede ser 1: se perdió stock real y hay que reponerlo."""
        prod = self._producto("Crema", lead_time_dias=2)
        self._inv(prod, stock=30)
        for k in range(1, 57):
            self._ticket([(prod, 1)], dias_atras=k)                    # ventas: 1/día
        for k in range(0, 14):                                         # salidas: 10/día
            self.db.add(MovimientoInventario(
                producto_id=prod.id, tienda_id=self.vida.id, tipo=TipoMovInvEnum.salida,
                cantidad=10, fecha=datetime.utcnow() - timedelta(days=k, hours=1),
                usuario_id=self.user.id))
        self.db.flush()
        it = self._item_base(prod)
        self.assertEqual(it["consumo_diario"], 10.0)     # max(1, 10)
        self.assertEqual(it["dias_restantes"], 3.0)      # 30 / 10

    # ─── 8. el caso almojábana: se vende sin merma y ahora SÍ avisa ────────────

    def test_venta_sin_salidas_da_consumo_y_alerta(self):
        """Un producto que se vende (y descuenta su propio stock) pero cuyas salidas
        de los últimos 14 días no alcanzan a contar bien: la venta histórica le da
        un consumo real, un «alcanza» y su estado. Antes, sin salidas, era consumo 0."""
        almojabana = self._producto("Almojábana", lead_time_dias=2)
        self._inv(almojabana, stock=30, minimo=0)
        for k in range(1, 57):
            self._ticket([(almojabana, 6)], dias_atras=k)     # 6/día, sin ninguna salida
        it = self._item_base(almojabana)
        self.assertEqual(it["consumo_diario"], 6.0)
        self.assertEqual(it["dias_restantes"], 5.0)           # 30 / 6
        self.assertEqual(it["estado"], "pronto")              # 5 > lead(2), ≤ lead*3(6)
        self.assertEqual(it["cantidad_sugerida"], 24)         # ceil(6*(2+7) − 30)


if __name__ == "__main__":
    unittest.main()
