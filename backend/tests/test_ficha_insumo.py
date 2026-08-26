"""La ficha de UN insumo: qué hacía falta, qué llegó, por dónde salió, qué queda.

Es el detalle detrás de una fila de la tabla de insumos, y la regla que ordena
todo el archivo es que los TOTALES SON LOS MISMOS: los arma `_fila_insumo`,
compartida por los dos endpoints. Si la ficha recalculara por su cuenta, el día
que se agregue un renglón las dos pantallas dirían cosas distintas del mismo
producto y nadie sabría cuál creer.

Lo demás que se fija acá sale de una decisión de diseño que costó discutir: la
columna «pedí» comparable contra «llegó» NO SE PUEDE construir sin mentir. El
pedido al proveedor sale por WhatsApp y el sistema nunca lo guarda; lo que la
barista pide desde el kiosko viene en unidades de texto libre que cambian semana
a semana para el mismo producto («2 bolsa», «2 unidad», «5000 gr»). Por eso:

  · `hacia_falta` da tres cifras que SÍ son ciertas (salió, se compró, hay que
    pedir), y la tercera sale del motor de pedidos, no de una fórmula nueva.
  · `pedido_escrito` es una BITÁCORA: la cantidad tal cual se tecleó, con su
    unidad textual. Nunca se suma ni se resta contra lo que llegó.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col
from app.database import Base, get_db
from app.models.models import (CategoriaProductoEnum, EstadoSolicitudEnum,
                               FacturaCompra, FacturaCompraItem, Inventario,
                               MovimientoInventario, Producto, RolEnum,
                               SolicitudPedido, SolicitudPedidoItem, Tienda,
                               TipoMovInvEnum, TipoPagoEnum, Usuario)
from app.routers import inventario as inventario_router


class FichaBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="x", activa=True)
        self.palmetto = Tienda(nombre="Palmetto", direccion="y", activa=True)
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.barista = Usuario(nombre="Cata", email="b@test.local", password_hash="h",
                               rol=RolEnum.barista, tienda_id=self.vida.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.db.commit()

        self.hoy = hoy_col()
        self.desde = self.hoy - timedelta(days=30)

        app = FastAPI(title="Test ficha insumo")
        app.include_router(inventario_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Fixtures ──────────────────────────────────────────────────────────────
    def producto(self, nombre="Café", unidad="gr", proveedor=None, cpe=None,
                 stock=0.0, minimo=0.0, tienda=None):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=True, precio_venta=0.0,
                     proveedor=proveedor, contenido_por_empaque=cpe,
                     incluir_en_conteo=True)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=(tienda or self.vida).id,
                               stock_actual=stock, stock_minimo=minimo))
        self.db.commit()
        return p

    def mov(self, producto, tipo, cantidad, motivo, *, dias=5, tienda=None, barista=None):
        self.db.add(MovimientoInventario(
            producto_id=producto.id, tienda_id=(tienda or self.vida).id,
            tipo=tipo, cantidad=cantidad, motivo=motivo,
            fecha=datetime.utcnow() - timedelta(days=dias),
            usuario_id=self.admin.id, barista_nombre=barista,
        ))
        self.db.commit()

    def factura(self, proveedor, producto, cantidad, *, dias=5, precio=100.0, nro=None):
        f = FacturaCompra(tienda_id=self.vida.id, proveedor=proveedor,
                          numero_factura=nro, valor_total=cantidad * precio,
                          tipo_pago=TipoPagoEnum.contado, usuario_id=self.admin.id,
                          fecha_recibido=datetime.utcnow() - timedelta(days=dias))
        self.db.add(f)
        self.db.flush()
        self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=producto.id,
                                      cantidad=cantidad, precio_unitario=precio))
        self.db.commit()
        return f

    def solicitud(self, producto, cantidad, unidad, estado, *, dias=5):
        s = SolicitudPedido(tienda_id=self.vida.id, usuario_id=self.barista.id,
                            estado=estado,
                            fecha_solicitud=datetime.utcnow() - timedelta(days=dias))
        self.db.add(s)
        self.db.flush()
        self.db.add(SolicitudPedidoItem(solicitud_id=s.id, producto_id=producto.id,
                                        cantidad_solicitada=cantidad,
                                        unidad_solicitada=unidad))
        self.db.commit()
        return s

    def ficha(self, producto, tienda=None):
        r = self.client.get(f"/api/v1/inventario/insumo/{producto.id}/ficha", params={
            "tienda_id": (tienda or self.vida).id,
            "desde": self.desde.isoformat(), "hasta": self.hoy.isoformat(),
        })
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class MismosNumerosQueLaTablaTest(FichaBase):
    """La regla que ordena todo: ficha y tabla no pueden contradecirse."""

    def test_el_resumen_es_identico_al_de_la_tabla(self):
        cafe = self.producto("Café", proveedor=None)
        self.factura("Cafexcoop", cafe, 10000)
        self.mov(cafe, TipoMovInvEnum.entrada, 10000, "Factura #1 — Cafexcoop")
        self.mov(cafe, TipoMovInvEnum.salida, 3000, "Venta POS")
        self.mov(cafe, TipoMovInvEnum.salida, 200, "Daño: se mojó")
        self.mov(cafe, TipoMovInvEnum.salida, 400, "se fue y nadie anotó")

        tabla = self.client.get("/api/v1/inventario/movimiento-insumos", params={
            "tienda_id": self.vida.id, "desde": self.desde.isoformat(),
            "hasta": self.hoy.isoformat()}).json()
        fila = next(f for f in tabla["insumos"] if f["producto_id"] == cafe.id)
        self.assertEqual(self.ficha(cafe)["resumen"], fila)


class HaciaFaltaTest(FichaBase):
    """El reemplazo honesto de la columna «pedí»."""

    def test_las_tres_cifras_son_las_del_periodo(self):
        cafe = self.producto("Café")
        self.factura("Cafexcoop", cafe, 8000)
        self.mov(cafe, TipoMovInvEnum.entrada, 8000, "Factura #1 — Cafexcoop")
        self.mov(cafe, TipoMovInvEnum.salida, 5000, "Venta POS")
        self.mov(cafe, TipoMovInvEnum.salida, 1000, "Preparación: Granizado")

        d = self.ficha(cafe)
        self.assertEqual(d["hacia_falta"]["para_reponer"], 6000)   # todo lo que salió
        self.assertEqual(d["hacia_falta"]["se_compro"], 8000)
        # Y no se contradice con el bloque de abajo: es el MISMO total.
        self.assertEqual(d["hacia_falta"]["para_reponer"], d["resumen"]["total_salio"])

    def test_cuanto_pedir_sale_del_motor_no_de_una_formula_nueva(self):
        cafe = self.producto("Café", stock=100.0, minimo=500.0)
        self.mov(cafe, TipoMovInvEnum.salida, 2800, "Venta POS", dias=3)
        d = self.ficha(cafe)
        self.assertIsNotNone(d["hacia_falta"]["hoy_hay_que_pedir"])
        self.assertGreater(d["hacia_falta"]["hoy_hay_que_pedir"], 0)
        self.assertIsNotNone(d["hacia_falta"]["consumo_diario"])

    def test_traduce_a_empaques_cuando_se_sabe_cuanto_trae_uno(self):
        # Sin `contenido_por_empaque` no hay forma honesta de hablar en bolsas.
        cafe = self.producto("Café", cpe=2500.0, stock=0.0, minimo=5000.0)
        self.mov(cafe, TipoMovInvEnum.salida, 2800, "Venta POS", dias=3)
        d = self.ficha(cafe)
        self.assertEqual(d["hacia_falta"]["contenido_por_empaque"], 2500.0)
        self.assertIsNotNone(d["hacia_falta"]["empaques_sugeridos"])

    def test_sin_empaque_configurado_no_inventa_bolsas(self):
        cafe = self.producto("Café", cpe=None, stock=0.0, minimo=5000.0)
        self.mov(cafe, TipoMovInvEnum.salida, 2800, "Venta POS", dias=3)
        self.assertIsNone(self.ficha(cafe)["hacia_falta"]["empaques_sugeridos"])


class LlegoTest(FichaBase):
    """Qué entró, con qué papel — y qué entró sin ninguno."""

    def test_lista_las_facturas_del_rango(self):
        cafe = self.producto("Café")
        self.factura("Cafexcoop", cafe, 10000, precio=80.0, nro="9144", dias=10)
        self.factura("Cafexcoop", cafe, 7500, precio=85.0, dias=3)
        self.mov(cafe, TipoMovInvEnum.entrada, 17500, "Factura #1 — Cafexcoop")

        llego = self.ficha(cafe)["llego"]
        self.assertEqual(len(llego["facturas"]), 2)
        self.assertEqual(llego["con_factura"], 17500)
        self.assertEqual(llego["facturas"][0]["numero_factura"], "9144")
        self.assertEqual(llego["facturas"][0]["total"], 10000 * 80.0)

    def test_lo_que_entro_sin_papel_se_declara(self):
        # Entró al libro más de lo que hay facturado: mercadería cargada a mano.
        # Es la puerta de atrás del inventario y tiene que verse.
        cafe = self.producto("Café")
        self.factura("Cafexcoop", cafe, 10000)
        self.mov(cafe, TipoMovInvEnum.entrada, 11000, "Factura #1 — Cafexcoop")
        self.assertEqual(self.ficha(cafe)["llego"]["sin_papel"], 1000)

    def test_lo_producido_y_lo_trasladado_van_aparte_de_lo_comprado(self):
        mezcla = self.producto("Mezcla Granizado")
        self.mov(mezcla, TipoMovInvEnum.entrada, 2500, "Preparación: Mezcla Granizado")
        self.mov(mezcla, TipoMovInvEnum.entrada, 300, "Recibo traslado desde Palmetto")
        llego = self.ficha(mezcla)["llego"]
        self.assertEqual(llego["con_factura"], 0)
        self.assertEqual(llego["se_produjo_aca"], 2500)
        self.assertEqual(llego["vino_de_la_otra_sede"], 300)


class PedidoEscritoTest(FichaBase):
    """Bitácora, jamás un total."""

    def test_devuelve_la_cantidad_tal_cual_se_tecleo_con_su_unidad(self):
        azucar = self.producto("Azúcar", unidad="gr")
        self.solicitud(azucar, 2, "bolsa", EstadoSolicitudEnum.aprobada, dias=10)
        self.solicitud(azucar, 5000, "gr", EstadoSolicitudEnum.rechazada, dias=3)

        pe = self.ficha(azucar)["pedido_escrito"]
        self.assertEqual(len(pe), 2)
        # El mismo producto pedido en dos unidades incomparables: por eso la
        # pantalla no puede sumar esta columna.
        self.assertEqual((pe[0]["cantidad"], pe[0]["unidad"]), (2, "bolsa"))
        self.assertEqual((pe[1]["cantidad"], pe[1]["unidad"]), (5000, "gr"))
        self.assertEqual(pe[1]["estado"], "rechazada")

    def test_sin_solicitudes_devuelve_lista_vacia_no_un_cero(self):
        # Vacío es «no se pidió por el kiosko», que no es lo mismo que «se pidió 0».
        cafe = self.producto("Café")
        self.assertEqual(self.ficha(cafe)["pedido_escrito"], [])

    def test_no_trae_solicitudes_de_la_otra_sede(self):
        cafe = self.producto("Café")
        otra = SolicitudPedido(tienda_id=self.palmetto.id, usuario_id=self.barista.id,
                               estado=EstadoSolicitudEnum.pendiente,
                               fecha_solicitud=datetime.utcnow() - timedelta(days=2))
        self.db.add(otra); self.db.flush()
        self.db.add(SolicitudPedidoItem(solicitud_id=otra.id, producto_id=cafe.id,
                                        cantidad_solicitada=9, unidad_solicitada="und"))
        self.db.commit()
        self.assertEqual(self.ficha(cafe)["pedido_escrito"], [])


class MovimientosTest(FichaBase):
    """El detalle, con la causa del MISMO clasificador que los totales."""

    def test_cada_movimiento_trae_su_causa(self):
        cafe = self.producto("Café")
        self.mov(cafe, TipoMovInvEnum.entrada, 5000, "Factura #1 — Cafexcoop")
        self.mov(cafe, TipoMovInvEnum.salida, 300, "Venta POS", barista="Cata")
        self.mov(cafe, TipoMovInvEnum.salida, 50, "Daño: se cayó")
        self.mov(cafe, TipoMovInvEnum.salida, 20, "cualquier cosa")

        causas = {m["motivo"]: m["causa"] for m in self.ficha(cafe)["movimientos"]}
        self.assertEqual(causas["Factura #1 — Cafexcoop"], "entradas")
        self.assertEqual(causas["Venta POS"], "ventas")
        self.assertEqual(causas["Daño: se cayó"], "mermas")
        self.assertEqual(causas["cualquier cosa"], "otras_salidas")

    def test_trae_el_barista_para_poder_preguntar(self):
        cafe = self.producto("Café")
        self.mov(cafe, TipoMovInvEnum.salida, 300, "Venta POS", barista="Cata")
        m = self.ficha(cafe)["movimientos"][0]
        self.assertEqual(m["barista"], "Cata")

    def test_del_mas_nuevo_al_mas_viejo(self):
        cafe = self.producto("Café")
        self.mov(cafe, TipoMovInvEnum.salida, 1, "viejo", dias=20)
        self.mov(cafe, TipoMovInvEnum.salida, 2, "nuevo", dias=1)
        self.assertEqual([m["motivo"] for m in self.ficha(cafe)["movimientos"]],
                         ["nuevo", "viejo"])

    def test_cuando_recorta_lo_dice(self):
        # Una lista incompleta que parece completa es peor que decir que se cortó.
        cafe = self.producto("Café")
        for i in range(inventario_router._MAX_MOVS_FICHA + 12):
            self.db.add(MovimientoInventario(
                producto_id=cafe.id, tienda_id=self.vida.id,
                tipo=TipoMovInvEnum.salida, cantidad=1, motivo="Venta POS",
                fecha=datetime.utcnow() - timedelta(days=2, seconds=i),
                usuario_id=self.admin.id))
        self.db.commit()

        d = self.ficha(cafe)
        self.assertEqual(len(d["movimientos"]), inventario_router._MAX_MOVS_FICHA)
        self.assertTrue(d["movimientos_truncados"])
        self.assertEqual(d["movimientos_total"], inventario_router._MAX_MOVS_FICHA + 12)


class CandadosTest(FichaBase):
    def test_producto_inexistente_es_404(self):
        r = self.client.get("/api/v1/inventario/insumo/999999/ficha", params={
            "tienda_id": self.vida.id, "desde": self.desde.isoformat(),
            "hasta": self.hoy.isoformat()})
        self.assertEqual(r.status_code, 404)

    def test_producto_sin_inventario_en_la_sede_responde_vacio_no_404(self):
        # «¿Qué pasó con esto acá?» tiene una respuesta legítima: nada.
        solo_palmetto = self.producto("Solo Palmetto", tienda=self.palmetto)
        d = self.ficha(solo_palmetto, tienda=self.vida)
        self.assertEqual(d["resumen"]["total_salio"], 0)
        self.assertEqual(d["resumen"]["entradas"], 0)
        self.assertEqual(d["movimientos"], [])

    def test_rango_al_reves_es_400(self):
        cafe = self.producto("Café")
        r = self.client.get(f"/api/v1/inventario/insumo/{cafe.id}/ficha", params={
            "tienda_id": self.vida.id, "desde": self.hoy.isoformat(),
            "hasta": self.desde.isoformat()})
        self.assertEqual(r.status_code, 400)

    def test_solo_admin(self):
        cafe = self.producto("Café")
        self.app.dependency_overrides[get_current_user] = lambda: self.barista
        r = self.client.get(f"/api/v1/inventario/insumo/{cafe.id}/ficha", params={
            "tienda_id": self.vida.id, "desde": self.desde.isoformat(),
            "hasta": self.hoy.isoformat()})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
