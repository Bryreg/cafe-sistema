"""El motor de pedidos no le sugiere COMPRAR lo que se PREPARA en la barra.

La mezcla de granizado no la vende nadie: se arma con una receta. El motor la
veía como un insumo más y le decía al dueño «PEDIR 24.062 gr» a un proveedor que
no existe. La necesidad es real —la mezcla se está acabando—; lo que estaba mal
era el VERBO. Estos tests fijan el verbo, no la cantidad: la matemática de los
productos normales no se mueve ni un decimal.
"""
import math
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    CategoriaProductoEnum, FacturaCompra, FacturaCompraItem, Inventario,
    MovimientoInventario, Producto, ProductoInsumo, RolEnum, Tienda,
    TipoMovInvEnum, TipoPagoEnum, Usuario,
)
from app.services import pedidos as svc


class PedidosPreparablesTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t)
        self.db.flush()
        self.user = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                            rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.user)
        self.db.flush()

        # Insumo de la receta de la mezcla.
        self.azucar = self._producto("Azúcar a Granel", unidad="gr")
        # PREPARABLE con rendimiento cargado: controla stock, no se vende,
        # tiene receta propia. contenido_por_unidad = gr que produce UNA tanda.
        self.mezcla = self._producto("MEZCLA GRANIZADO", unidad="gr",
                                     contenido_por_unidad=2820)
        self.db.add(ProductoInsumo(producto_id=self.mezcla.id,
                                   insumo_id=self.azucar.id, cantidad=360))
        # PREPARABLE sin rendimiento cargado: mismo caso, contenido_por_unidad NULL.
        self.almibar = self._producto("Almíbar", unidad="ml")
        self.db.add(ProductoInsumo(producto_id=self.almibar.id,
                                   insumo_id=self.azucar.id, cantidad=200))
        # Producto NORMAL de reventa: se compra, se vende, sin receta propia.
        self.torta = self._producto("Torta Red Velvet", unidad="und",
                                    precio_venta=12900, proveedor="María María",
                                    categoria=CategoriaProductoEnum.pasteleria)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Fixtures ────────────────────────────────────────────────────────────
    def _producto(self, nombre, unidad="und", precio_venta=0, proveedor=None,
                  contenido_por_unidad=None,
                  categoria=CategoriaProductoEnum.insumo):
        p = Producto(nombre=nombre, categoria=categoria, unidad_medida=unidad,
                     controla_stock=True, incluir_en_conteo=True,
                     precio_venta=precio_venta, proveedor=proveedor,
                     lead_time_dias=2, contenido_por_unidad=contenido_por_unidad)
        self.db.add(p)
        self.db.flush()
        return p

    def _inv(self, producto, stock, minimo=0.0):
        self.db.add(Inventario(producto_id=producto.id, tienda_id=self.t.id,
                               stock_actual=stock, stock_minimo=minimo))
        self.db.commit()

    def _salidas(self, producto, total):
        """Reparte `total` en una salida dentro de la ventana de análisis."""
        self.db.add(MovimientoInventario(
            producto_id=producto.id, tienda_id=self.t.id,
            tipo=TipoMovInvEnum.salida, cantidad=total,
            fecha=datetime.utcnow() - timedelta(days=1),
            usuario_id=self.user.id, motivo="Venta POS",
        ))
        self.db.commit()

    def _items(self, data):
        out = {}
        for g in data["grupos_fijos"]:
            for p in g["productos"]:
                out[p["nombre"]] = p
        for p in data["insumos_generales"]:
            out[p["nombre"]] = p
        return out

    # ── Tests ───────────────────────────────────────────────────────────────
    def test_preparable_con_consumo_dice_preparar_y_no_comprar(self):
        """La mezcla se está acabando: la necesidad es real, el verbo es PREPARAR."""
        self._inv(self.mezcla, 3000)
        self._salidas(self.mezcla, 84000)          # 6.000 gr/día en 14 días
        item = self._items(svc.sugerencia_pedido(self.db, self.t.id))["MEZCLA GRANIZADO"]

        self.assertEqual(item["accion"], "preparar")
        # consumo 6000/día × (lead 2 + colchón 7) = 54.000 − 3.000 de stock
        self.assertEqual(item["cantidad_sugerida"], 51000)

    def test_preparable_con_rendimiento_cargado_dice_cuantas_tandas(self):
        self._inv(self.mezcla, 3000)
        self._salidas(self.mezcla, 84000)
        item = self._items(svc.sugerencia_pedido(self.db, self.t.id))["MEZCLA GRANIZADO"]

        self.assertEqual(item["rendimiento_tanda"], 2820)
        self.assertEqual(item["tandas_sugeridas"], math.ceil(51000 / 2820))   # 19

    def test_preparable_sin_rendimiento_no_inventa_tandas(self):
        """Sin `contenido_por_unidad` no hay factor de conversión: los gramos ya
        son honestos, una tanda inventada no lo sería."""
        self._inv(self.almibar, 100)
        self._salidas(self.almibar, 1400)          # 100 ml/día
        item = self._items(svc.sugerencia_pedido(self.db, self.t.id))["Almíbar"]

        self.assertEqual(item["accion"], "preparar")
        self.assertEqual(item["cantidad_sugerida"], 800)   # 100×9 − 100
        self.assertIsNone(item["tandas_sugeridas"])
        self.assertIsNone(item["rendimiento_tanda"])

    def test_producto_normal_sigue_diciendo_comprar_con_la_misma_cantidad(self):
        """Esto es un cambio de CLASIFICACIÓN, no de fórmula."""
        self._inv(self.torta, 10)
        self._salidas(self.torta, 140)             # 10 und/día
        item = self._items(svc.sugerencia_pedido(self.db, self.t.id))["Torta Red Velvet"]

        self.assertEqual(item["accion"], "comprar")
        self.assertEqual(item["cantidad_sugerida"], 80)    # 10×9 − 10
        self.assertIsNone(item["tandas_sugeridas"])

    def test_preparable_nunca_entra_en_un_grupo_de_proveedor(self):
        """Aunque alguien le haya escrito un proveedor a mano: nadie vende la
        mezcla hecha, y un grupo de proveedor es una lista de compra."""
        self.mezcla.proveedor = "Proveedor Cargado a Mano"
        self.db.commit()
        self._inv(self.mezcla, 0)
        self._salidas(self.mezcla, 14000)
        data = svc.sugerencia_pedido(self.db, self.t.id)

        agrupados = [p["nombre"] for g in data["grupos_fijos"] for p in g["productos"]]
        self.assertNotIn("MEZCLA GRANIZADO", agrupados)
        self.assertIn("MEZCLA GRANIZADO", [p["nombre"] for p in data["insumos_generales"]])

    def test_preparable_facturado_por_error_tampoco_entra_en_un_grupo(self):
        """El proveedor también puede entrar por el historial de compras
        (`_proveedores_por_compras`): una factura vieja que incluyó la mezcla."""
        f = FacturaCompra(tienda_id=self.t.id, proveedor="Distribuidora X",
                          numero_factura="FV-1", fecha_recibido=datetime.utcnow(),
                          usuario_id=self.user.id, valor_total=1000,
                          tipo_pago=TipoPagoEnum.contado)
        self.db.add(f)
        self.db.flush()
        self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=self.mezcla.id,
                                      cantidad=1, precio_unitario=1000))
        self.db.commit()
        self._inv(self.mezcla, 0)
        self._salidas(self.mezcla, 14000)
        data = svc.sugerencia_pedido(self.db, self.t.id)

        agrupados = [p["nombre"] for g in data["grupos_fijos"] for p in g["productos"]]
        self.assertNotIn("MEZCLA GRANIZADO", agrupados)

    def test_alertas_de_stock_tambien_dicen_el_verbo(self):
        """`get_alertas` es de donde el kiosko saca «+ pedir»: la barista tiene
        que poder marcar que falta mezcla sin que eso se lea como una compra."""
        from app.services import inventario as inv_svc
        self._inv(self.mezcla, 0, minimo=500)
        self._inv(self.torta, 0, minimo=2)
        filas = {f["producto"]: f for f in inv_svc.get_alertas(self.db, self.t.id)}

        self.assertEqual(filas["MEZCLA GRANIZADO"]["accion"], "preparar")
        self.assertEqual(filas["Torta Red Velvet"]["accion"], "comprar")
        # La cantidad no se mueve: sigue siendo el doble del mínimo menos el stock.
        self.assertEqual(filas["Torta Red Velvet"]["cantidad_sugerida"], 4)

    def test_la_solicitud_de_la_barista_llega_al_admin_con_el_verbo(self):
        """La barista pide mezcla (bien: le falta). El admin la ve en Solicitudes
        y de ahí sale un texto de WhatsApp AGRUPADO POR PROVEEDOR. Sin marcar el
        verbo, la mezcla terminaba dentro de un pedido a un proveedor."""
        from app.services import solicitudes as sol_svc
        sol_svc.crear_pedido(self.db, self.t.id, None, [
            {"producto_id": self.mezcla.id, "cantidad_solicitada": 2820},
            {"producto_id": self.torta.id, "cantidad_solicitada": 3},
        ], self.user.id)

        pedido = sol_svc.get_pedidos_todas(self.db)[0]
        por_nombre = {i.nombre: i for i in pedido.items}
        self.assertEqual(por_nombre["MEZCLA GRANIZADO"].accion, "preparar")
        self.assertEqual(por_nombre["Torta Red Velvet"].accion, "comprar")

    def test_producto_normal_con_proveedor_sigue_agrupado(self):
        """Guarda contra el arreglo de más: la torta SÍ se compra."""
        self._inv(self.torta, 1)
        self._salidas(self.torta, 140)
        data = svc.sugerencia_pedido(self.db, self.t.id)

        agrupados = {g["proveedor"]: [p["nombre"] for p in g["productos"]]
                     for g in data["grupos_fijos"]}
        self.assertIn("María María", agrupados)
        self.assertIn("Torta Red Velvet", agrupados["María María"])


if __name__ == "__main__":
    unittest.main()
