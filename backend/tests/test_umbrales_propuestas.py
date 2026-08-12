"""Mínimos propuestos: el sistema PROPONE, el dueño ACEPTA.

55 de 56 productos tienen `stock_minimo = 0` —el default del esquema— y con el
mínimo en 0 el kiosko no marca nada nunca y el motor no avisa hasta llegar a
cero. Nadie va a inventar 55 números a mano. El sistema ya mide el consumo real
y conoce el lead time: puede proponerlos.

Lo que estos tests fijan, en orden de importancia:

  1. NADA se escribe sin confirmación. El GET es read-only ABSOLUTO (se cuenta
     el estado de la tabla antes y después) y el PATCH escribe SOLO lo que llega.
  2. NINGÚN número inventado. Consumo cero ⇒ no hay propuesta, va a `sin_dato`
     con su razón. Jamás un 0 propuesto: 0 es exactamente el default inerte que
     esto viene a arreglar.
  3. La propuesta es COHERENTE con el motor que después va a leer ese mínimo:
     misma ventana (`DIAS_ANALISIS`), mismo lead time, y siempre por DEBAJO de
     lo que el motor repone (`_dias_objetivo`).
  4. El antes/después es visible: cuántos productos pasan a estar en alerta HOY
     al aceptar.
"""
import math
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import (
    AuditLog, CategoriaProductoEnum, Inventario, MovimientoInventario, Producto,
    ProductoInsumo, RolEnum, Tienda, TipoMovInvEnum, Usuario,
)
from app.services import umbrales as svc
from app.services.pedidos import DIAS_ANALISIS, _dias_objetivo


class _Base(unittest.TestCase):
    """sqlite temporal + fixture de cafetería real (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t = Tienda(nombre="Vida", direccion="Sede Vida")
        self.otra = Tienda(nombre="Palmetto", direccion="Sede Palmetto")
        self.db.add_all([self.t, self.otra])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Fixtures ────────────────────────────────────────────────────────────
    def _producto(self, nombre, unidad="und", lead=2, precio_venta=0,
                  controla=True, en_conteo=True,
                  categoria=CategoriaProductoEnum.insumo):
        p = Producto(nombre=nombre, categoria=categoria, unidad_medida=unidad,
                     controla_stock=controla, incluir_en_conteo=en_conteo,
                     precio_venta=precio_venta, lead_time_dias=lead)
        self.db.add(p)
        self.db.flush()
        self.db.commit()
        return p

    def _inv(self, producto, stock, minimo=0.0, critico=0.0, ideal=0.0, tienda=None):
        self.db.add(Inventario(producto_id=producto.id,
                               tienda_id=(tienda or self.t).id,
                               stock_actual=stock, stock_minimo=minimo,
                               stock_critico=critico, stock_ideal=ideal))
        self.db.commit()

    def _salidas(self, producto, total, dias=1, tienda=None):
        """Reparte `total` en `dias` días DISTINTOS dentro de la ventana del motor.

        El offset es `i días + 1 hora`, no `i+1 días`: con `dias=DIAS_ANALISIS` el
        último movimiento caería JUSTO sobre el corte —que el servicio calcula
        unos microsegundos después que este fixture— y quedaría afuera. Los
        offsets siguen separados por 24 h exactas, así que las fechas de
        calendario siguen siendo todas distintas."""
        for i in range(dias):
            self.db.add(MovimientoInventario(
                producto_id=producto.id, tienda_id=(tienda or self.t).id,
                tipo=TipoMovInvEnum.salida, cantidad=total / dias,
                fecha=datetime.utcnow() - timedelta(days=i, hours=1),
                usuario_id=self.admin.id, motivo="Venta POS",
            ))
        self.db.commit()

    def _prop(self, data, nombre):
        for p in data["propuestas"]:
            if p["nombre"] == nombre:
                return p
        return None

    def _sin_dato(self, data, nombre):
        for p in data["sin_dato"]:
            if p["nombre"] == nombre:
                return p
        return None


class ProponerTest(_Base):
    """La propuesta: el número, su justificación y lo que NO se propone."""

    def test_la_propuesta_es_consumo_por_lead_time(self):
        """El mínimo significa «cuando llegues acá, pedí ya»: lo que se gasta
        mientras llega el pedido. Café: 3.360 gr en 14 días = 240 gr/día,
        lead 2 ⇒ 480 gr."""
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        self._inv(cafe, 1200)
        self._salidas(cafe, 3360, dias=7)

        p = self._prop(svc.proponer(self.db, self.t.id), "Café Excelso")
        self.assertIsNotNone(p)
        self.assertEqual(p["consumo_diario"], 240.0)
        self.assertEqual(p["minimo_propuesto"], 480)
        self.assertEqual(p["cubre_dias"], 2)

    def test_la_propuesta_usa_la_misma_ventana_que_el_motor(self):
        """Una salida FUERA de `DIAS_ANALISIS` no cuenta: si contara, la
        propuesta y el motor leerían dos consumos distintos del mismo producto."""
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        self._inv(cafe, 1200)
        self._salidas(cafe, 3360, dias=7)
        self.db.add(MovimientoInventario(
            producto_id=cafe.id, tienda_id=self.t.id, tipo=TipoMovInvEnum.salida,
            cantidad=99999, fecha=datetime.utcnow() - timedelta(days=DIAS_ANALISIS + 3),
            usuario_id=self.admin.id, motivo="Venta vieja",
        ))
        self.db.commit()

        p = self._prop(svc.proponer(self.db, self.t.id), "Café Excelso")
        self.assertEqual(p["consumo_diario"], 240.0)
        self.assertEqual(p["minimo_propuesto"], 480)

    def test_la_propuesta_nunca_llega_a_lo_que_el_motor_repone(self):
        """Invariante duro. Si el mínimo fuera el objetivo de reposición, el
        producto quedaría en alerta el día siguiente a cada entrega — para
        siempre. El mínimo DISPARA el pedido; `_dias_objetivo` dice hasta dónde
        se repone. Son dos números distintos y el primero va abajo."""
        for i, lead in enumerate((1, 2, 3, 5)):
            p = self._producto(f"Insumo lead {lead}", unidad="gr", lead=lead)
            self._inv(p, 10000)
            self._salidas(p, 1400, dias=5)          # 100 gr/día
        data = svc.proponer(self.db, self.t.id)

        self.assertEqual(len(data["propuestas"]), 4)
        for prop in data["propuestas"]:
            lead = prop["lead_time_dias"]
            self.assertLess(prop["minimo_propuesto"],
                            prop["consumo_diario"] * _dias_objetivo(lead),
                            f"lead {lead}: el mínimo alcanzó el objetivo del motor")
            self.assertEqual(prop["motor_repone_hasta"],
                             round(prop["consumo_diario"] * _dias_objetivo(lead), 2))

    def test_consumo_cero_no_propone_nada_y_dice_por_que(self):
        """El caso más importante: sin consumo medido no hay número honesto.
        Va a `sin_dato` con su razón — jamás un 0, que es el default inerte."""
        serv = self._producto("Servilletas", unidad="und", lead=2)
        self._inv(serv, 300)

        data = svc.proponer(self.db, self.t.id)
        self.assertIsNone(self._prop(data, "Servilletas"))
        sd = self._sin_dato(data, "Servilletas")
        self.assertIsNotNone(sd)
        self.assertIn("14", sd["razon"])
        self.assertNotIn("minimo_propuesto", sd)

    def test_ninguna_propuesta_puede_ser_cero(self):
        """Guarda global: un 0 propuesto sería indistinguible del default."""
        chico = self._producto("Vaso 12oz", unidad="und", lead=1)
        self._inv(chico, 200)
        self._salidas(chico, 7, dias=7)             # 0,5 und/día → 0,5 × 1 = 0,5
        micro = self._producto("Esencia de vainilla", unidad="lt", lead=2)
        self._inv(micro, 3)
        self._salidas(micro, 0.014, dias=2)         # 0,001 lt/día → 0,002

        data = svc.proponer(self.db, self.t.id)
        for prop in data["propuestas"]:
            self.assertGreater(prop["minimo_propuesto"], 0, prop["nombre"])
        # Unidad discreta: no existe medio vaso de umbral, redondea PARA ARRIBA.
        self.assertEqual(self._prop(data, "Vaso 12oz")["minimo_propuesto"], 1)
        # Unidad decimal: el paso más chico representable, no un 0 por redondeo.
        self.assertEqual(self._prop(data, "Esencia de vainilla")["minimo_propuesto"], 0.01)

    def test_el_redondeo_saca_el_ruido_decimal(self):
        """3,714 gr no es un umbral, es ruido de float: 4 gr."""
        canela = self._producto("Canela molida", unidad="gr", lead=2)
        self._inv(canela, 500)
        self._salidas(canela, 26, dias=4)           # 1,857 gr/día → 3,714

        p = self._prop(svc.proponer(self.db, self.t.id), "Canela molida")
        self.assertEqual(p["minimo_propuesto"], 4)

    def test_los_litros_conservan_dos_decimales(self):
        """En kg/lt el decimal SÍ decide: 0,05 lt no puede redondearse a 0."""
        v = self._producto("Vainilla", unidad="lt", lead=2)
        self._inv(v, 2)
        self._salidas(v, 0.35, dias=2)              # 0,025 lt/día → 0,05

        p = self._prop(svc.proponer(self.db, self.t.id), "Vainilla")
        self.assertEqual(p["minimo_propuesto"], 0.05)

    def test_la_propuesta_dice_sobre_cuantos_dias_se_midio(self):
        """El dato que la sostiene viaja con ella: 3.360 gr repartidos en 7 días
        con movimiento, dentro de una ventana de 14."""
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        self._inv(cafe, 1200)
        self._salidas(cafe, 3360, dias=7)

        p = self._prop(svc.proponer(self.db, self.t.id), "Café Excelso")
        self.assertEqual(p["dias_de_datos"], 7)
        self.assertEqual(p["ventana_dias"], DIAS_ANALISIS)

    def test_el_preparable_viaja_marcado_preparar(self):
        """El mínimo vale igual —dispara la alerta— pero el verbo es otro: nadie
        vende hecha la mezcla de granizado."""
        azucar = self._producto("Azúcar a Granel", unidad="gr")
        mezcla = self._producto("MEZCLA GRANIZADO", unidad="gr", lead=2)
        self.db.add(ProductoInsumo(producto_id=mezcla.id, insumo_id=azucar.id,
                                   cantidad=360))
        self.db.commit()
        self._inv(mezcla, 3000)
        self._salidas(mezcla, 84000, dias=14)       # 6.000 gr/día

        data = svc.proponer(self.db, self.t.id)
        p = self._prop(data, "MEZCLA GRANIZADO")
        self.assertEqual(p["accion"], "preparar")
        self.assertEqual(p["minimo_propuesto"], 12000)   # 6000 × lead 2

    def test_insumo_de_receta_sospechosa_lleva_advertencia_y_queda_fuera(self):
        """La receta del Latte descuenta 18 «lt» de leche por unidad vendida. Si
        eran gramos, el consumo medido está inflado 1000× y la propuesta
        heredaría el error. Viaja con advertencia y NO entra al aceptar-todo."""
        leche = self._producto("Leche entera", unidad="lt", lead=1)
        latte = self._producto("Latte", unidad="und", precio_venta=9000,
                               controla=False, categoria=CategoriaProductoEnum.bebida)
        self.db.add(ProductoInsumo(producto_id=latte.id, insumo_id=leche.id,
                                   cantidad=18))
        self.db.commit()
        self._inv(leche, 40)
        self._salidas(leche, 252, dias=14)          # 18 lt/día

        data = svc.proponer(self.db, self.t.id)
        p = self._prop(data, "Leche entera")
        self.assertIsNotNone(p["advertencia"])
        self.assertIn("18", p["advertencia"])
        self.assertFalse(p["en_aceptar_todo"])
        self.assertEqual(data["impacto"]["aceptar_todo"]["propuestas"], 0)

    def test_producto_sin_receta_sospechosa_entra_al_aceptar_todo(self):
        """Guarda contra el arreglo de más."""
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        self._inv(cafe, 1200)
        self._salidas(cafe, 3360, dias=7)

        p = self._prop(svc.proponer(self.db, self.t.id), "Café Excelso")
        self.assertIsNone(p["advertencia"])
        self.assertTrue(p["en_aceptar_todo"])

    def test_el_que_ya_tiene_minimo_cargado_no_se_toca(self):
        """Esto propone lo que FALTA. Un mínimo puesto a mano es una decisión."""
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        self._inv(cafe, 1200, minimo=800)
        self._salidas(cafe, 3360, dias=7)

        data = svc.proponer(self.db, self.t.id)
        self.assertIsNone(self._prop(data, "Café Excelso"))
        self.assertIsNone(self._sin_dato(data, "Café Excelso"))

    def test_solo_inventario_gestionado(self):
        """Misma regla que el motor: controla stock Y entra al conteo. Un
        archivado no necesita mínimo — su stock no es confiable."""
        fuera = self._producto("Bebida del POS", unidad="und", controla=False,
                               precio_venta=6000)
        nocuenta = self._producto("Helado a granel", unidad="gr", en_conteo=False)
        self._inv(fuera, 0)
        self._inv(nocuenta, 5000)
        self._salidas(fuera, 140, dias=7)
        self._salidas(nocuenta, 1400, dias=7)

        data = svc.proponer(self.db, self.t.id)
        nombres = [p["nombre"] for p in data["propuestas"] + data["sin_dato"]]
        self.assertNotIn("Bebida del POS", nombres)
        self.assertNotIn("Helado a granel", nombres)

    def test_el_consumo_es_de_la_sede_pedida(self):
        """Los mínimos son POR SEDE: el consumo de Vida no es el de Palmetto."""
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        self._inv(cafe, 1200, tienda=self.t)
        self._inv(cafe, 1200, tienda=self.otra)
        self._salidas(cafe, 3360, dias=7, tienda=self.t)        # 240 gr/día
        self._salidas(cafe, 1400, dias=7, tienda=self.otra)     # 100 gr/día

        self.assertEqual(self._prop(svc.proponer(self.db, self.t.id),
                                    "Café Excelso")["minimo_propuesto"], 480)
        self.assertEqual(self._prop(svc.proponer(self.db, self.otra.id),
                                    "Café Excelso")["minimo_propuesto"], 200)

    def test_conflicto_con_ideal_cargado_se_declara_y_queda_fuera_del_aceptar_todo(self):
        """El PATCH rechaza (con razón) un mínimo por encima del ideal, y el lote
        es atómico: UNA propuesta en conflicto tumbaría las 55. El conflicto se
        declara en la propuesta —donde el dueño puede decidir— en vez de
        descubrirse como un 400 después de marcar todo."""
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        # ideal cargado en 300, pero el consumo propone 480: choque seguro.
        self._inv(cafe, 1200, ideal=300)
        self._salidas(cafe, 3360, dias=7)                       # 240 gr/día × 2 = 480

        prop = self._prop(svc.proponer(self.db, self.t.id), "Café Excelso")
        self.assertEqual(prop["minimo_propuesto"], 480)         # la propuesta no se maquilla
        self.assertIsNotNone(prop["advertencia"])
        self.assertIn("ideal", prop["advertencia"])
        self.assertFalse(prop["en_aceptar_todo"])               # no entra al botón masivo

    def test_conflicto_con_critico_cargado_tambien_se_declara(self):
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        # crítico cargado en 900, propuesta 480: quedaría critico > minimo.
        self._inv(cafe, 1200, critico=900)
        self._salidas(cafe, 3360, dias=7)

        prop = self._prop(svc.proponer(self.db, self.t.id), "Café Excelso")
        self.assertIsNotNone(prop["advertencia"])
        self.assertIn("crítico", prop["advertencia"])
        self.assertFalse(prop["en_aceptar_todo"])


class ImpactoTest(_Base):
    """El antes/después. Un producto que amanece en alerta sin que nadie sepa
    por qué destruye la confianza en el sistema entero."""

    def test_dice_cuantos_pasan_a_alerta_hoy_mismo(self):
        # Torta: 3 und/día, lead 3 ⇒ mínimo 9, y hay 4 en stock → BAJO al aceptar.
        torta = self._producto("Torta Red Velvet", unidad="und", lead=3,
                               categoria=CategoriaProductoEnum.pasteleria)
        self._inv(torta, 4)
        self._salidas(torta, 42, dias=14)
        # Café: 240 gr/día, lead 2 ⇒ mínimo 480, y hay 1.200 → sigue normal.
        cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        self._inv(cafe, 1200)
        self._salidas(cafe, 3360, dias=7)

        data = svc.proponer(self.db, self.t.id)
        self.assertEqual(self._prop(data, "Torta Red Velvet")["quedaria_en"], "bajo")
        self.assertTrue(self._prop(data, "Torta Red Velvet")["cambia_a_alerta"])
        self.assertEqual(self._prop(data, "Café Excelso")["quedaria_en"], "normal")
        self.assertFalse(self._prop(data, "Café Excelso")["cambia_a_alerta"])

        self.assertEqual(data["impacto"]["propuestas"], 2)
        self.assertEqual(data["impacto"]["nuevos_en_alerta"], 1)

    def test_el_que_ya_esta_en_alerta_no_se_cuenta_como_nuevo(self):
        """Un producto en cero YA está en alerta hoy: el mínimo no lo cambia, y
        contarlo como consecuencia de aceptar sería inflar el susto."""
        torta = self._producto("Torta Red Velvet", unidad="und", lead=3,
                               categoria=CategoriaProductoEnum.pasteleria)
        self._inv(torta, 0)
        self._salidas(torta, 42, dias=14)

        data = svc.proponer(self.db, self.t.id)
        p = self._prop(data, "Torta Red Velvet")
        self.assertEqual(p["estado_hoy"], "agotado")
        self.assertEqual(p["quedaria_en"], "agotado")
        self.assertFalse(p["cambia_a_alerta"])
        self.assertEqual(data["impacto"]["nuevos_en_alerta"], 0)
        self.assertEqual(data["impacto"]["ya_en_alerta"], 1)


class EndpointsTest(_Base):
    """La forma HTTP: GET read-only absoluto y PATCH que escribe SOLO el mínimo."""

    def setUp(self):
        super().setUp()
        app = FastAPI(title="Test umbrales propuestos")
        from app.routers import inventario as inventario_router
        app.include_router(inventario_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app = app
        self.client = TestClient(app)

        self.cafe = self._producto("Café Excelso", unidad="gr", lead=2)
        self._inv(self.cafe, 1200, critico=0.0, ideal=0.0)
        self._salidas(self.cafe, 3360, dias=7)
        self.torta = self._producto("Torta Red Velvet", unidad="und", lead=3,
                                    categoria=CategoriaProductoEnum.pasteleria)
        self._inv(self.torta, 4)
        self._salidas(self.torta, 42, dias=14)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        super().tearDown()

    def _estado_tabla(self):
        filas = self.db.query(Inventario).order_by(Inventario.id).all()
        return [(f.id, f.stock_actual, f.stock_minimo, f.stock_critico, f.stock_ideal)
                for f in filas]

    def _aplicar(self, items, tienda_id=None):
        return self.client.patch("/api/v1/inventario/umbrales/aplicar", json={
            "tienda_id": tienda_id if tienda_id is not None else self.t.id,
            "items": items,
        })

    # ── GET ─────────────────────────────────────────────────────────────────
    def test_get_responde_la_forma_esperada(self):
        r = self.client.get("/api/v1/inventario/umbrales/propuestas",
                            params={"tienda_id": self.t.id})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for k in ("tienda_id", "propuestas", "sin_dato", "impacto", "ventana_dias"):
            self.assertIn(k, data)
        self.assertEqual(len(data["propuestas"]), 2)

    def test_el_get_no_escribe_absolutamente_nada(self):
        """Read-only ABSOLUTO: ni una fila, ni un umbral, ni un movimiento."""
        antes = self._estado_tabla()
        n_movs = self.db.query(MovimientoInventario).count()
        n_audit = self.db.query(AuditLog).count()

        r = self.client.get("/api/v1/inventario/umbrales/propuestas",
                            params={"tienda_id": self.t.id})
        self.assertEqual(r.status_code, 200)
        self.db.expire_all()

        self.assertEqual(self._estado_tabla(), antes)
        self.assertEqual(self.db.query(MovimientoInventario).count(), n_movs)
        self.assertEqual(self.db.query(AuditLog).count(), n_audit)

    # ── PATCH ───────────────────────────────────────────────────────────────
    def test_aplicar_escribe_solo_lo_que_llega(self):
        r = self._aplicar([{"producto_id": self.cafe.id, "stock_minimo": 480}])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["aplicados"], 1)
        self.db.expire_all()

        inv_cafe = self.db.query(Inventario).filter_by(producto_id=self.cafe.id,
                                                       tienda_id=self.t.id).one()
        inv_torta = self.db.query(Inventario).filter_by(producto_id=self.torta.id,
                                                        tienda_id=self.t.id).one()
        self.assertEqual(inv_cafe.stock_minimo, 480)
        self.assertEqual(inv_torta.stock_minimo, 0)      # NO llegó: NO se toca

    def test_aplicar_no_toca_critico_ni_ideal_ni_lead_time(self):
        self.db.query(Inventario).filter_by(producto_id=self.cafe.id,
                                            tienda_id=self.t.id).update(
            {"stock_critico": 100.0, "stock_ideal": 3000.0})
        self.db.commit()

        r = self._aplicar([{"producto_id": self.cafe.id, "stock_minimo": 480}])
        self.assertEqual(r.status_code, 200)
        self.db.expire_all()

        inv = self.db.query(Inventario).filter_by(producto_id=self.cafe.id,
                                                  tienda_id=self.t.id).one()
        self.assertEqual(inv.stock_critico, 100.0)
        self.assertEqual(inv.stock_ideal, 3000.0)
        self.assertEqual(
            self.db.query(Producto).filter_by(id=self.cafe.id).one().lead_time_dias, 2)

    def test_aplicar_escribe_solo_en_la_sede_pedida(self):
        self._inv(self.cafe, 900, tienda=self.otra)
        r = self._aplicar([{"producto_id": self.cafe.id, "stock_minimo": 480}])
        self.assertEqual(r.status_code, 200)
        self.db.expire_all()

        otra = self.db.query(Inventario).filter_by(producto_id=self.cafe.id,
                                                   tienda_id=self.otra.id).one()
        self.assertEqual(otra.stock_minimo, 0)

    def test_aplicar_deja_rastro_de_auditoria(self):
        antes = self.db.query(AuditLog).count()
        self._aplicar([{"producto_id": self.cafe.id, "stock_minimo": 480}])
        self.db.expire_all()
        self.assertGreater(self.db.query(AuditLog).count(), antes)
        log = self.db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        self.assertEqual(log.tabla_afectada, "inventario")
        self.assertIn("480", log.datos_despues or "")

    def test_infinito_da_400_limpio_y_no_escribe(self):
        """GOTCHA del repo: con `Field(ge=…, allow_inf_nan=False)` el 422 de
        pydantic incrusta el valor ofensor en el cuerpo, y `inf` no es
        serializable a JSON: la propia respuesta de error revienta. La
        validación va en el handler."""
        antes = self._estado_tabla()
        for crudo in ("Infinity", "-Infinity", "NaN"):
            r = self.client.patch(
                "/api/v1/inventario/umbrales/aplicar",
                content=('{"tienda_id": %d, "items": [{"producto_id": %d, '
                         '"stock_minimo": %s}]}' % (self.t.id, self.cafe.id, crudo)),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(r.status_code, 400, crudo)
            self.assertIsInstance(r.json()["detail"], str)
        self.db.expire_all()
        self.assertEqual(self._estado_tabla(), antes)

    def test_negativo_da_400_y_no_escribe(self):
        antes = self._estado_tabla()
        r = self._aplicar([{"producto_id": self.cafe.id, "stock_minimo": -1}])
        self.assertEqual(r.status_code, 400)
        self.db.expire_all()
        self.assertEqual(self._estado_tabla(), antes)

    def test_un_item_invalido_no_escribe_ninguno(self):
        """Atómico: «no se escribió nada, arreglá ese» es predecible; una
        escritura parcial silenciosa no."""
        antes = self._estado_tabla()
        r = self._aplicar([
            {"producto_id": self.cafe.id, "stock_minimo": 480},
            {"producto_id": self.torta.id, "stock_minimo": -5},
        ])
        self.assertEqual(r.status_code, 400)
        self.db.expire_all()
        self.assertEqual(self._estado_tabla(), antes)

    def test_lista_vacia_da_400(self):
        r = self._aplicar([])
        self.assertEqual(r.status_code, 400)

    def test_producto_sin_fila_en_la_sede_da_404(self):
        huerfano = self._producto("Sin inventario", unidad="und")
        r = self._aplicar([{"producto_id": huerfano.id, "stock_minimo": 3}])
        self.assertEqual(r.status_code, 404)

    def test_no_admin_no_puede(self):
        barista = Usuario(nombre="Barista", email="b@t.local", password_hash="h",
                          rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add(barista)
        self.db.commit()
        self.app.dependency_overrides[get_current_user] = lambda: barista

        self.assertEqual(self.client.get("/api/v1/inventario/umbrales/propuestas",
                                         params={"tienda_id": self.t.id}).status_code, 403)
        self.assertEqual(self._aplicar([{"producto_id": self.cafe.id,
                                         "stock_minimo": 480}]).status_code, 403)


if __name__ == "__main__":
    unittest.main()
