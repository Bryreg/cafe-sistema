"""La vida de cada insumo en una tabla: qué entró, por dónde salió, qué queda.

El dueño lo pidió así: «tener en un mismo sitio control de lo que se pidió,
comparar con lo que llegó, y ver también lo que salió, ya sea por merma o venta
o traslado». `GET /inventario/movimiento-insumos` es esa tabla, y NO recalcula
la clasificación: se apoya en la escalera de conciliación, que ya reparte cada
movimiento del libro en su causa.

Lo que estos tests fijan, y por qué cada uno importa:

- EL ORIGEN sale de las compras REALES del rango, no del campo `Producto.
  proveedor` (que se escribe una vez y queda viejo). Y separa proveedor de
  compra directa: contra Cafexcoop hay pedido y precio acordado; en Makro no hay
  pedido que incumplir y la misma resta es la lista de mercado.
- EL AJUSTE DE CONTEO VIAJA APARTE del total que salió. No es una causa: es
  faltante viejo que apareció al contar. Mezclarlo taparía todo lo demás.
- `no_se_mide` DICE lo que un cero callaría: el producto entró y el libro no
  registra una sola venta. Los vasos y el jabón se gastan todos los días; que la
  caja no los descuente es un agujero de configuración, no una buena noticia.
- LO PRODUCIDO NO ES LO COMPRADO: una tanda preparada entra al libro, y si se
  sumara a `entradas` el local aparecería recibiendo mercadería que nadie
  facturó.
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
from app.models.models import (CategoriaProductoEnum, FacturaCompra,
                               FacturaCompraItem, Inventario,
                               MovimientoInventario, Producto, RolEnum, Tienda,
                               TipoMovInvEnum, TipoPagoEnum, Usuario)
from app.routers import inventario as inventario_router


class MovimientoInsumosBase(unittest.TestCase):
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
        self.db.add(self.admin)
        self.db.commit()

        self.hoy = hoy_col()
        self.desde = self.hoy - timedelta(days=30)

        app = FastAPI(title="Test movimiento insumos")
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
    def producto(self, nombre, unidad="gr", proveedor=None,
                 categoria=CategoriaProductoEnum.insumo, stock=0.0, tienda=None):
        p = Producto(nombre=nombre, categoria=categoria, unidad_medida=unidad,
                     controla_stock=True, precio_venta=0.0, proveedor=proveedor)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=(tienda or self.vida).id,
                               stock_actual=stock, stock_minimo=0))
        self.db.commit()
        return p

    def mov(self, producto, tipo, cantidad, motivo, *, dias_atras=5, tienda=None):
        self.db.add(MovimientoInventario(
            producto_id=producto.id, tienda_id=(tienda or self.vida).id,
            tipo=tipo, cantidad=cantidad, motivo=motivo,
            fecha=datetime.utcnow() - timedelta(days=dias_atras),
            usuario_id=self.admin.id,
        ))
        self.db.commit()

    def factura(self, proveedor, producto, cantidad, *, dias_atras=5, tienda=None,
                precio=100.0):
        f = FacturaCompra(tienda_id=(tienda or self.vida).id, proveedor=proveedor,
                          valor_total=cantidad * precio, tipo_pago=TipoPagoEnum.contado,
                          usuario_id=self.admin.id,
                          fecha_recibido=datetime.utcnow() - timedelta(days=dias_atras))
        self.db.add(f)
        self.db.flush()
        self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=producto.id,
                                      cantidad=cantidad, precio_unitario=precio))
        self.db.commit()
        return f

    def get(self, tienda=None, desde=None, hasta=None):
        t = (tienda or self.vida).id
        r = self.client.get("/api/v1/inventario/movimiento-insumos", params={
            "tienda_id": t,
            "desde": (desde or self.desde).isoformat(),
            "hasta": (hasta or self.hoy).isoformat(),
        })
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def fila(self, data, nombre):
        for f in data["insumos"]:
            if f["producto"] == nombre:
                return f
        return None


class OrigenTest(MovimientoInsumosBase):
    """De dónde viene el insumo: proveedor con pedido, o compra de mostrador."""

    def test_proveedor_sale_de_las_compras_del_rango(self):
        cafe = self.producto("Café", proveedor=None)
        self.factura("Cafexcoop", cafe, 10000)
        f = self.fila(self.get(), "Café")
        self.assertEqual(f["proveedor"], "Cafexcoop")
        self.assertEqual(f["origen"], "proveedor")

    def test_autoservicio_es_compra_directa(self):
        leche = self.producto("Leche Condensada")
        self.factura("Makro", leche, 5000)
        f = self.fila(self.get(), "Leche Condensada")
        self.assertEqual(f["origen"], "directa")

    def test_gana_el_proveedor_de_mas_cantidad_no_el_del_producto(self):
        # `Producto.proveedor` se escribe una vez y queda viejo: la tabla tiene
        # que decir de dónde viene DE VERDAD hoy.
        azucar = self.producto("Azúcar", proveedor="Proveedor Viejo")
        self.factura("Makro", azucar, 12000)
        self.factura("Galerías", azucar, 500)
        f = self.fila(self.get(), "Azúcar")
        self.assertEqual(f["proveedor"], "Makro")
        self.assertEqual(f["origen"], "directa")

    def test_sin_compras_en_el_rango_cae_al_proveedor_del_producto(self):
        # Si no, un insumo que no se compró este mes quedaría sin origen.
        te = self.producto("Té", proveedor="Cafexcoop")
        self.mov(te, TipoMovInvEnum.salida, 100, "Venta POS")
        f = self.fila(self.get(), "Té")
        self.assertEqual(f["proveedor"], "Cafexcoop")
        self.assertEqual(f["origen"], "proveedor")

    def test_sin_proveedor_por_ningun_lado_se_declara(self):
        misterio = self.producto("Insumo Suelto")
        self.mov(misterio, TipoMovInvEnum.salida, 5, "Venta POS")
        f = self.fila(self.get(), "Insumo Suelto")
        self.assertIsNone(f["proveedor"])
        self.assertEqual(f["origen"], "sin_origen")


class SalidasTest(MovimientoInsumosBase):
    """Lo que salió, repartido por causa — y lo que NO es una salida."""

    def test_cada_causa_en_su_columna_y_el_total_las_suma(self):
        cafe = self.producto("Café")
        self.factura("Cafexcoop", cafe, 10000)
        self.mov(cafe, TipoMovInvEnum.entrada, 10000, "Factura #1 — Cafexcoop")
        self.mov(cafe, TipoMovInvEnum.salida, 3000, "Venta POS")
        self.mov(cafe, TipoMovInvEnum.salida, 200, "Daño: se mojó")
        self.mov(cafe, TipoMovInvEnum.salida, 100, "Consumo (Ana): se lo tomó")
        self.mov(cafe, TipoMovInvEnum.salida, 500, "Traslado a Palmetto: falta allá")
        self.mov(cafe, TipoMovInvEnum.salida, 1500, "Preparación: Granizado")

        f = self.fila(self.get(), "Café")
        self.assertEqual(f["ventas"], 3000)
        self.assertEqual(f["mermas"], 300)          # daño + consumo van juntos
        self.assertEqual(f["traslados"], 500)
        self.assertEqual(f["preparaciones"], 1500)
        self.assertEqual(f["total_salio"], 5300)

    def test_salida_sin_motivo_conocido_cae_en_sin_causa_y_se_valoriza(self):
        cafe = self.producto("Café")
        self.factura("Cafexcoop", cafe, 1000, precio=50.0)
        self.mov(cafe, TipoMovInvEnum.entrada, 1000, "Factura #1 — Cafexcoop")
        self.mov(cafe, TipoMovInvEnum.salida, 400, "se fue")   # sin prefijo conocido

        f = self.fila(self.get(), "Café")
        self.assertEqual(f["otras_salidas"], 400)
        self.assertGreater(f["valor_sin_causa"], 0)
        self.assertAlmostEqual(f["valor_sin_causa"], 400 * f["valor_unitario"], places=2)

    def test_el_ajuste_de_conteo_no_entra_al_total_que_salio(self):
        # Un ajuste NO es una causa de salida: es faltante viejo que apareció al
        # contar. Si entrara al total, taparía todas las demás causas.
        cafe = self.producto("Café", stock=0.0)
        self.mov(cafe, TipoMovInvEnum.entrada, 1000, "Factura #1 — Cafexcoop")
        self.mov(cafe, TipoMovInvEnum.salida, 200, "Venta POS")
        self.mov(cafe, TipoMovInvEnum.ajuste, 300, "Conteo #7 aplicado al inventario",
                 dias_atras=1)

        f = self.fila(self.get(), "Café")
        self.assertEqual(f["ventas"], 200)
        self.assertEqual(f["total_salio"], 200)
        self.assertNotEqual(f["ajustes_conteo"], 0)

    def test_lo_producido_no_se_cuenta_como_comprado(self):
        # Una tanda preparada ENTRA al libro. Sumarla a `entradas` haría parecer
        # que alguien facturó mercadería que en realidad se hizo en la casa.
        mezcla = self.producto("Mezcla Granizado")
        self.mov(mezcla, TipoMovInvEnum.entrada, 2500, "Preparación: Mezcla Granizado")
        f = self.fila(self.get(), "Mezcla Granizado")
        self.assertEqual(f["entradas"], 0)
        self.assertEqual(f["preparaciones_producidas"], 2500)


class NoSeMideTest(MovimientoInsumosBase):
    """Un cero que no significa lo que parece."""

    def test_entro_y_nunca_salio_por_venta_se_declara(self):
        vaso = self.producto("Vaso Cartón 12oz", unidad="und")
        self.factura("Makro", vaso, 1000)
        self.mov(vaso, TipoMovInvEnum.entrada, 1000, "Factura #1 — Makro")
        f = self.fila(self.get(), "Vaso Cartón 12oz")
        self.assertEqual(f["ventas"], 0)
        self.assertTrue(f["no_se_mide"])

    def test_un_producto_que_si_vende_no_se_marca(self):
        cafe = self.producto("Café")
        self.mov(cafe, TipoMovInvEnum.entrada, 1000, "Factura #1 — Cafexcoop")
        self.mov(cafe, TipoMovInvEnum.salida, 10, "Venta POS")
        self.assertFalse(self.fila(self.get(), "Café")["no_se_mide"])

    def test_insumo_que_solo_se_gasta_preparando_no_se_marca(self):
        # Vende cero y aun así está medido: se consume en la tanda de granizado.
        polvo = self.producto("Leche en Polvo")
        self.mov(polvo, TipoMovInvEnum.entrada, 20000, "Factura #1 — Makro")
        self.mov(polvo, TipoMovInvEnum.salida, 15600, "Preparación: Granizado")
        f = self.fila(self.get(), "Leche en Polvo")
        self.assertEqual(f["ventas"], 0)
        self.assertEqual(f["preparaciones"], 15600)
        self.assertFalse(f["no_se_mide"])

    def test_sin_entradas_no_se_marca(self):
        # Sin compras no hay nada que declarar: la bandera es para el que ENTRÓ
        # y no salió, no para el que no se movió.
        viejo = self.producto("Insumo Dormido")
        self.assertFalse(self.fila(self.get(), "Insumo Dormido")["no_se_mide"])


class TablaTest(MovimientoInsumosBase):
    """Orden, resumen y candados."""

    def test_ordena_por_plata_sin_explicar(self):
        chico = self.producto("Chico")
        grande = self.producto("Grande")
        for p, cant, precio in ((chico, 100, 10.0), (grande, 100, 900.0)):
            self.factura("Cafexcoop", p, cant, precio=precio)
            self.mov(p, TipoMovInvEnum.entrada, cant, "Factura #1 — Cafexcoop")
            self.mov(p, TipoMovInvEnum.salida, 50, "vaya uno a saber")
        nombres = [f["producto"] for f in self.get()["insumos"]]
        self.assertLess(nombres.index("Grande"), nombres.index("Chico"))

    def test_resumen_cuenta_lo_que_la_pantalla_titula(self):
        cafe = self.producto("Café")
        self.factura("Cafexcoop", cafe, 1000, precio=50.0)
        self.mov(cafe, TipoMovInvEnum.entrada, 1000, "Factura #1 — Cafexcoop")
        self.mov(cafe, TipoMovInvEnum.salida, 300, "Venta POS")
        self.mov(cafe, TipoMovInvEnum.salida, 100, "se fue")
        vaso = self.producto("Vaso", unidad="und")
        self.factura("Makro", vaso, 500)
        self.mov(vaso, TipoMovInvEnum.entrada, 500, "Factura #2 — Makro")

        r = self.get()["resumen"]
        self.assertEqual(r["n_sin_causa"], 1)
        self.assertGreater(r["valor_sin_causa"], 0)
        self.assertEqual(r["n_no_se_mide"], 1)
        self.assertEqual(r["n_compra_directa"], 1)

    def test_cada_sede_ve_lo_suyo(self):
        cafe = self.producto("Café")
        self.producto("Solo de Palmetto", tienda=self.palmetto)
        self.assertIsNotNone(self.fila(self.get(self.vida), "Café"))
        self.assertIsNone(self.fila(self.get(self.vida), "Solo de Palmetto"))

    def test_rango_al_reves_es_400(self):
        r = self.client.get("/api/v1/inventario/movimiento-insumos", params={
            "tienda_id": self.vida.id,
            "desde": self.hoy.isoformat(),
            "hasta": (self.hoy - timedelta(days=5)).isoformat(),
        })
        self.assertEqual(r.status_code, 400)

    def test_solo_admin(self):
        barista = Usuario(nombre="Cata", email="b@test.local", password_hash="h",
                          rol=RolEnum.barista, tienda_id=self.vida.id, activo=True)
        self.db.add(barista)
        self.db.commit()
        self.app.dependency_overrides[get_current_user] = lambda: barista
        r = self.client.get("/api/v1/inventario/movimiento-insumos", params={
            "tienda_id": self.vida.id, "desde": self.desde.isoformat(),
            "hasta": self.hoy.isoformat()})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
