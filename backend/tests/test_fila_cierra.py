"""La fila de un insumo tiene que CERRAR con lo que muestra.

El dueño lo encontró mirando una fila cualquiera de la pantalla de Insumos:

    AGUA MEDIUM BOTELLA · entró 180 · vendió 167 · queda 70

180 − 167 son 13, no 70. Los 57 que faltaban eran lo que ya había en el estante
el 1 de agosto, y la fila no tenía columna que los nombrara. Un renglón que no
aparece no se lee como ausente: se lee como CERO. Quien hace la resta de cabeza
—que es lo que uno hace con una tabla de números— llega a otro número y concluye
que el sistema está mal.

La escalera de conciliación define la identidad sobre los 13 renglones de
`conciliacion.RENGLONES`:

    stock_inicial + Σ(signo × renglón) = stock_esperado

La fila mostraba nueve. Estos tests fijan que los lleve todos y que la propia
fila diga si cierra, sobre los casos que en producción rompen la resta:

  · ARRANQUE — el más común y el que lo destapó.
  · LO QUE ENTRÓ SIN COMPRARSE — un traslado recibido y una tanda preparada
    suben el saldo sin que «entró» se mueva. La mezcla de granizado vive así.
  · LAS ANULACIONES — una factura eliminada resta sin ser merma ni venta.
  · LOS AJUSTES DE CONTEO — no son una causa de salida, pero mueven el saldo.
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
from app.models.models import (CategoriaProductoEnum, Inventario,
                               MovimientoInventario, Producto, RolEnum, Tienda,
                               TipoMovInvEnum, Usuario)
from app.routers import inventario as inventario_router


class FilaCierraTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.t = Tienda(nombre="Vida", direccion="x", activa=True)
        self.otra = Tienda(nombre="Palmetto", direccion="y", activa=True)
        self.db.add_all([self.t, self.otra])
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()
        self.hoy = hoy_col()
        self.desde = self.hoy - timedelta(days=26)

        app = FastAPI(title="Test fila cierra")
        app.include_router(inventario_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app, self.client = app, TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── fixtures ─────────────────────────────────────────────────────────────
    def producto(self, nombre, stock=0.0, unidad="und"):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=True, precio_venta=0.0)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.t.id,
                               stock_actual=stock, stock_minimo=0))
        self.db.commit()
        return p

    def mov(self, producto, tipo, cantidad, motivo, dias=5):
        """Escribe el movimiento Y mueve el stock, como lo hace el flujo real."""
        inv = self.db.query(Inventario).filter_by(
            producto_id=producto.id, tienda_id=self.t.id).first()
        if tipo == TipoMovInvEnum.entrada: inv.stock_actual += cantidad
        elif tipo == TipoMovInvEnum.salida: inv.stock_actual -= cantidad
        else: inv.stock_actual = cantidad
        self.db.add(MovimientoInventario(
            producto_id=producto.id, tienda_id=self.t.id, tipo=tipo, cantidad=cantidad,
            motivo=motivo, usuario_id=self.admin.id,
            fecha=datetime.utcnow() - timedelta(days=dias)))
        self.db.commit()

    def fila(self, producto):
        r = self.client.get("/api/v1/inventario/movimiento-insumos", params={
            "tienda_id": self.t.id, "desde": self.desde.isoformat(),
            "hasta": self.hoy.isoformat()})
        self.assertEqual(r.status_code, 200, r.text)
        return next(f for f in r.json()["insumos"] if f["producto_id"] == producto.id)

    def verificar(self, f):
        """La resta que el dueño hace de cabeza, con lo que la fila muestra."""
        salio = (f["ventas"] + f["mermas"] + f["traslados"] + f["preparaciones"]
                 + f["otras_salidas"])
        calculado = f["arranco"] + f["entradas"] + f["otros"] - salio
        self.assertAlmostEqual(
            calculado, f["queda"], places=2,
            msg=(f'«{f["producto"]}» no cierra: {f["arranco"]} + {f["entradas"]} '
                 f'+ {f["otros"]} − {salio} = {calculado}, pero queda dice {f["queda"]}'))
        self.assertTrue(f["cuadra"], "la fila dice que NO cuadra")

    # ── los tests ────────────────────────────────────────────────────────────
    def test_el_caso_del_agua_la_fila_lleva_su_arranque(self):
        # La fila real que lo destapó: 180 entró, 167 vendió, 70 queda.
        agua = self.producto("AGUA MEDIUM BOTELLA", stock=57)
        self.mov(agua, TipoMovInvEnum.entrada, 180, "Factura #150 — Alamo", dias=20)
        self.mov(agua, TipoMovInvEnum.salida, 167, "Venta POS", dias=10)

        f = self.fila(agua)
        self.assertEqual(f["arranco"], 57)      # el número que faltaba
        self.assertEqual(f["entradas"], 180)
        self.assertEqual(f["ventas"], 167)
        self.assertEqual(f["queda"], 70)
        self.verificar(f)

    def test_lo_que_entro_sin_comprarse_no_desaparece_de_la_cuenta(self):
        # La mezcla de granizado sube sin que nadie la facture: se prepara acá y
        # llega de la otra sede. Sin estos términos, «entró 0» y el saldo sube.
        mezcla = self.producto("MEZCLA GRANIZADO (preparada)", stock=1000, unidad="gr")
        self.mov(mezcla, TipoMovInvEnum.entrada, 5000, "Preparación: MEZCLA GRANIZADO", dias=8)
        self.mov(mezcla, TipoMovInvEnum.entrada, 800, "Recibo traslado desde Palmetto", dias=6)
        self.mov(mezcla, TipoMovInvEnum.salida, 2400, "Venta POS — insumo de Granizado", dias=3)

        f = self.fila(mezcla)
        self.assertEqual(f["entradas"], 0)                    # nadie lo compró
        self.assertEqual(f["preparaciones_producidas"], 5000)
        self.assertEqual(f["traslados_recibidos"], 800)
        self.assertEqual(f["otros"], 5800)                    # y aun así suma
        self.verificar(f)

    def test_una_anulacion_resta_sin_ser_merma_ni_venta(self):
        pulpa = self.producto("PULPA DE MORA", stock=10)
        self.mov(pulpa, TipoMovInvEnum.entrada, 30, "Factura #220 — Wilenses", dias=12)
        self.mov(pulpa, TipoMovInvEnum.salida, 30, "Eliminación factura #220 — Wilenses", dias=11)
        self.mov(pulpa, TipoMovInvEnum.salida, 5, "Venta POS", dias=4)

        f = self.fila(pulpa)
        self.assertEqual(f["reversas_salida"], 30)
        self.assertEqual(f["otros"], -30)      # resta, y con su signo
        self.verificar(f)

    def test_un_conteo_aplicado_mueve_el_saldo_y_la_cuenta_lo_absorbe(self):
        # Un conteo aplicado FIJA el saldo, no lo suma: la cadena hacia atrás se
        # corta ahí y lo que había antes no se puede reconstruir desde el libro.
        # La escalera arranca en cero y lo DECLARA (`arranque_estimado`) en vez de
        # inventar un número — y la cuenta cierra igual, con el conteo absorbido
        # en «otros». Que cierre no depende de conocer el arranque; que sea CIERTO,
        # sí, y por eso la marca tiene que viajar.
        cafe = self.producto("CAFE", stock=1000, unidad="gr")
        self.mov(cafe, TipoMovInvEnum.salida, 300, "Venta POS", dias=9)
        self.mov(cafe, TipoMovInvEnum.ajuste, 900, "Conteo #12 aplicado al inventario", dias=5)

        f = self.fila(cafe)
        self.assertTrue(f["arranque_estimado"], "el arranque es un supuesto y no se dice")
        self.assertEqual(f["arranco"], 0)
        self.assertEqual(f["ajustes_conteo"], 1200)
        self.assertEqual(f["otros"], 1200)
        self.verificar(f)

    def test_una_reversa_de_venta_tambien_entra(self):
        pan = self.producto("Almojabanas", stock=20)
        self.mov(pan, TipoMovInvEnum.salida, 6, "Venta POS", dias=7)
        self.mov(pan, TipoMovInvEnum.entrada, 2, "Anulación de ticket #4821", dias=6)

        f = self.fila(pan)
        self.assertEqual(f["reversas"], 2)
        self.assertEqual(f["entradas"], 0)   # una anulación no es una compra
        self.verificar(f)

    def test_todas_las_filas_de_la_sede_cierran(self):
        # La garantía que importa: no una fila elegida a dedo, TODAS.
        a = self.producto("AGUA", stock=57)
        self.mov(a, TipoMovInvEnum.entrada, 180, "Factura #1 — Alamo", dias=20)
        self.mov(a, TipoMovInvEnum.salida, 167, "Venta POS", dias=10)
        b = self.producto("CAFE", stock=1000, unidad="gr")
        self.mov(b, TipoMovInvEnum.salida, 300, "Consumo (Ana): se lo tomó", dias=9)
        self.mov(b, TipoMovInvEnum.ajuste, 900, "Conteo #12 aplicado al inventario", dias=5)
        c = self.producto("LECHE", stock=5, unidad="ml")
        self.mov(c, TipoMovInvEnum.salida, 2, "se fue y nadie anotó", dias=4)
        self.producto("SIN MOVIMIENTO", stock=12)

        r = self.client.get("/api/v1/inventario/movimiento-insumos", params={
            "tienda_id": self.t.id, "desde": self.desde.isoformat(),
            "hasta": self.hoy.isoformat()}).json()
        self.assertEqual(len(r["insumos"]), 4)
        for f in r["insumos"]:
            with self.subTest(producto=f["producto"]):
                self.verificar(f)

    def test_la_ficha_dice_el_mismo_arranque_que_la_tabla(self):
        # Las dos salen de `_fila_insumo`. Si divergieran, el dueño tendría dos
        # arranques distintos del mismo insumo y ninguna forma de saber cuál vale.
        agua = self.producto("AGUA", stock=57)
        self.mov(agua, TipoMovInvEnum.entrada, 180, "Factura #1 — Alamo", dias=20)
        self.mov(agua, TipoMovInvEnum.salida, 167, "Venta POS", dias=10)

        ficha = self.client.get(f"/api/v1/inventario/insumo/{agua.id}/ficha", params={
            "tienda_id": self.t.id, "desde": self.desde.isoformat(),
            "hasta": self.hoy.isoformat()}).json()
        self.assertEqual(ficha["resumen"], self.fila(agua))


if __name__ == "__main__":
    unittest.main()
