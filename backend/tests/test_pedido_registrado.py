"""El pedido que el dueño manda queda escrito.

Hasta acá «Armar pedido» calculaba muy bien qué pedir, armaba el texto de
WhatsApp y ahí terminaba: el pedido se iba por el teléfono y el sistema no se
enteraba nunca de que había existido. La ficha del insumo lo decía con todas las
letras —«el pedido al proveedor se manda por WhatsApp y hoy el sistema no lo
guarda»— y por eso no había forma de contestar la única pregunta que importa
cuando llega la mercadería: ¿trajeron lo que pedí?

Lo que estos tests fijan:

- SE GUARDA LO QUE SE MANDA, con proveedor y en la unidad del producto. Sin la
  unidad, «pedí 4» no se puede restar contra una factura de 4.000 gr.
- EL DOBLE TOQUE NO DUPLICA. Esto corre en una tablet, con un dedo, sobre wifi
  de local. Un pedido duplicado no rompe nada visible —esa es la trampa—: infla
  «pedí» para siempre y hace creer que el proveedor entregó de menos.
- EL PEDIDO DEL DUEÑO NO ES UNA SOLICITUD DE BARISTA. Viven en la misma tabla y
  se separan por `origen`. Si se colaran, la bandeja del kiosko se llenaría de
  pedidos que nadie tiene que aprobar y el contador de pendientes del dashboard
  mentiría todos los días.
- LAS FILAS VIEJAS SIGUEN SIENDO DEL KIOSKO. Tienen `origen` NULL porque son
  anteriores a la columna. Un filtro `!= 'admin'` a secas las descartaría en
  silencio (en SQL, NULL != 'admin' no es verdadero) y haría desaparecer toda la
  historia de solicitudes.
- «PEDÍ» SOLO SUMA LO PEDIDO EN LA UNIDAD DEL PRODUCTO, y lo que quedó en otra
  unidad lo DICE en vez de tragárselo: un «pedí 0» al lado de una entrada grande
  manda a buscar un problema que no existe.
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
                               ORIGEN_ADMIN, ORIGEN_KIOSKO, Producto, RolEnum,
                               SolicitudPedido, SolicitudPedidoItem, Tienda,
                               TipoPagoEnum, Usuario)
from app.routers import inventario as inventario_router
from app.routers import pedidos as pedidos_router
from app.services import pedidos as ped_svc
from app.services import solicitudes as sol_svc


class PedidoRegistradoBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
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

        app = FastAPI(title="Test pedido registrado")
        app.include_router(pedidos_router.router, prefix="/api/v1")
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
    def producto(self, nombre, unidad="gr", proveedor=None, stock=0.0, tienda=None):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=True, precio_venta=0.0,
                     proveedor=proveedor)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=(tienda or self.vida).id,
                               stock_actual=stock, stock_minimo=0))
        self.db.commit()
        return p

    def factura(self, proveedor, producto, cantidad, *, dias_atras=1, tienda=None,
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

    def registrar(self, proveedor, items, tienda=None, nota=None, esperar=200):
        r = self.client.post("/api/v1/pedidos/registrar", json={
            "tienda_id": (tienda or self.vida).id,
            "proveedor": proveedor,
            "items": items,
            "nota": nota,
        })
        self.assertEqual(r.status_code, esperar, r.text)
        return r.json()

    def ficha(self, producto, tienda=None):
        r = self.client.get(f"/api/v1/inventario/insumo/{producto.id}/ficha", params={
            "tienda_id": (tienda or self.vida).id,
            "desde": self.desde.isoformat(), "hasta": self.hoy.isoformat()})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def tabla(self, tienda=None):
        r = self.client.get("/api/v1/inventario/movimiento-insumos", params={
            "tienda_id": (tienda or self.vida).id,
            "desde": self.desde.isoformat(), "hasta": self.hoy.isoformat()})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def fila(self, data, nombre):
        return next((f for f in data["insumos"] if f["producto"] == nombre), None)


class GuardarElPedidoTest(PedidoRegistradoBase):

    def test_lo_que_se_manda_queda_escrito_con_proveedor_y_unidad(self):
        cafe = self.producto("Café", unidad="gr")
        out = self.registrar("Cafexcoop", [
            {"producto_id": cafe.id, "cantidad": 4000, "unidad": "gr"}])

        self.assertEqual(out["proveedor"], "Cafexcoop")
        self.assertFalse(out["ya_estaba"])
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["cantidad"], 4000)
        self.assertEqual(out["items"][0]["unidad"], "gr")
        self.assertEqual(out["items"][0]["nombre"], "Café")

        fila = self.db.query(SolicitudPedido).filter(SolicitudPedido.id == out["id"]).one()
        self.assertEqual(fila.origen, ORIGEN_ADMIN)
        self.assertEqual(fila.proveedor, "Cafexcoop")
        # Nace resuelto: el dueño no se pide permiso a sí mismo. Si naciera
        # pendiente aparecería en la bandeja como algo por decidir.
        self.assertEqual(fila.estado, EstadoSolicitudEnum.aprobada)
        self.assertEqual(fila.usuario_aprobacion_id, self.admin.id)
        self.assertIsNotNone(fila.fecha_aprobacion)

    def test_sin_unidad_cae_a_la_del_producto(self):
        # La cantidad sin unidad no se puede restar contra nada. Antes de dejar
        # el campo vacío se usa la del producto, que es la de las dos cuentas.
        azucar = self.producto("Azúcar", unidad="gr")
        out = self.registrar("Makro", [{"producto_id": azucar.id, "cantidad": 5000}])
        self.assertEqual(out["items"][0]["unidad"], "gr")

    def test_las_lineas_en_cero_no_son_un_pedido(self):
        # El input vacío del card llega como 0. Es «no le pido esto», no «le pido
        # cero»: no puede ocupar una línea del pedido ni contarse en «pedí».
        cafe = self.producto("Café")
        leche = self.producto("Leche", unidad="ml")
        out = self.registrar("Cafexcoop", [
            {"producto_id": cafe.id, "cantidad": 4000},
            {"producto_id": leche.id, "cantidad": 0},
        ])
        self.assertEqual([i["producto_id"] for i in out["items"]], [cafe.id])

    def test_un_pedido_entero_en_cero_es_un_error_no_un_pedido_vacio(self):
        cafe = self.producto("Café")
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 0}],
                       esperar=400)

    def test_sin_proveedor_no_se_guarda(self):
        # Un pedido que no le fue a nadie no se puede cotejar contra ninguna
        # factura: sería un número suelto que ensucia «pedí» sin poder cerrarse.
        cafe = self.producto("Café")
        self.registrar("   ", [{"producto_id": cafe.id, "cantidad": 10}], esperar=400)

    def test_un_producto_borrado_no_se_puede_pedir(self):
        self.registrar("Cafexcoop", [{"producto_id": 9999, "cantidad": 10}], esperar=400)


class NoDuplicarTest(PedidoRegistradoBase):
    """El doble toque en la tablet no puede convertirse en dos pedidos."""

    def test_el_mismo_pedido_dos_veces_seguidas_es_uno_solo(self):
        cafe = self.producto("Café")
        a = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        b = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])

        self.assertEqual(a["id"], b["id"])
        self.assertFalse(a["ya_estaba"])
        # La pantalla necesita saber que no guardó nada nuevo, para no celebrar
        # un pedido que ya estaba.
        self.assertTrue(b["ya_estaba"])
        self.assertEqual(self.db.query(SolicitudPedido).count(), 1)

    def test_la_grafia_del_proveedor_no_abre_la_puerta_al_duplicado(self):
        # «CAFEXCOOP» y «Cafexcoop  » son el mismo teléfono. La guarda compara con
        # la MISMA normalización con la que la pantalla agrupa los proveedores.
        cafe = self.producto("Café")
        a = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        b = self.registrar("CAFEXCOOP  ", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.assertEqual(a["id"], b["id"])

    def test_cambiar_una_cantidad_SI_es_otro_pedido(self):
        # Acordarse del azúcar y volver a mandar la lista es un pedido nuevo, no
        # un duplicado. La guarda es contra el accidente, no contra la corrección.
        cafe = self.producto("Café")
        a = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        b = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 6000}])
        self.assertNotEqual(a["id"], b["id"])
        self.assertFalse(b["ya_estaba"])

    def test_agregar_un_producto_SI_es_otro_pedido(self):
        cafe = self.producto("Café")
        azucar = self.producto("Azúcar")
        a = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        b = self.registrar("Cafexcoop", [
            {"producto_id": cafe.id, "cantidad": 4000},
            {"producto_id": azucar.id, "cantidad": 5000}])
        self.assertNotEqual(a["id"], b["id"])

    def test_otro_proveedor_no_es_duplicado(self):
        cafe = self.producto("Café")
        a = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        b = self.registrar("Makro", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.assertNotEqual(a["id"], b["id"])

    def test_pasada_la_ventana_el_mismo_pedido_vuelve_a_valer(self):
        # Dos pedidos iguales al mismo proveedor el mismo día son legítimos con
        # horas de por medio: uno en la mañana y otro en la tarde.
        cafe = self.producto("Café")
        a = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        viejo = self.db.query(SolicitudPedido).filter(SolicitudPedido.id == a["id"]).one()
        viejo.fecha_solicitud = datetime.utcnow() - timedelta(hours=3)
        self.db.commit()

        b = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.assertNotEqual(a["id"], b["id"])

    def test_la_sede_separa_los_pedidos(self):
        # El mismo pedido a Cafexcoop para Vida y para Palmetto son dos pedidos.
        cafe = self.producto("Café")
        self.db.add(Inventario(producto_id=cafe.id, tienda_id=self.palmetto.id,
                               stock_actual=0, stock_minimo=0))
        self.db.commit()
        a = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        b = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}],
                           tienda=self.palmetto)
        self.assertNotEqual(a["id"], b["id"])


class NoEnsuciarLaBandejaTest(PedidoRegistradoBase):
    """El pedido del dueño y la solicitud de la barista comparten tabla, no destino."""

    def solicitud_kiosko(self, producto, cantidad=3, unidad="bolsa"):
        return sol_svc.crear_pedido(
            self.db, self.vida.id, None,
            [{"producto_id": producto.id, "cantidad_solicitada": cantidad,
              "unidad_solicitada": unidad}],
            self.admin.id)

    def test_el_pedido_del_dueno_no_aparece_en_la_bandeja_de_la_barista(self):
        cafe = self.producto("Café")
        self.solicitud_kiosko(cafe)
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])

        todas = sol_svc.get_pedidos_todas(self.db)
        self.assertEqual(len(todas), 1, "el pedido del dueño se coló en la bandeja")
        self.assertEqual(todas[0].origen, ORIGEN_KIOSKO)

        de_la_sede = sol_svc.get_pedidos_tienda(self.db, self.vida.id)
        self.assertEqual(len(de_la_sede), 1)

        bandeja = sol_svc.get_bandeja_pendientes(self.db, self.vida.id)
        self.assertEqual(len(bandeja["pedidos"]), 1)

    def test_las_solicitudes_viejas_sin_origen_siguen_siendo_del_kiosko(self):
        # Toda la historia anterior a la columna tiene `origen` NULL. Un filtro
        # `!= 'admin'` a secas las borraría de la pantalla sin que nada avise.
        cafe = self.producto("Café")
        s = self.solicitud_kiosko(cafe)
        self.db.query(SolicitudPedido).filter(SolicitudPedido.id == s.id).update(
            {"origen": None})
        self.db.commit()

        self.assertEqual(len(sol_svc.get_pedidos_todas(self.db)), 1)
        self.assertEqual(len(sol_svc.get_pedidos_tienda(self.db, self.vida.id)), 1)
        self.assertEqual(
            len(sol_svc.get_bandeja_pendientes(self.db, self.vida.id)["pedidos"]), 1)

    def test_el_pedido_del_dueno_no_se_lee_como_alerta_de_barista(self):
        # `barista_alerto` pinta el producto como «la barista avisó». Un pedido
        # del dueño no es un aviso de nadie.
        cafe = self.producto("Café", stock=100)
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        items, _ = ped_svc._items_base(self.db, self.vida.id)
        fila = next(i for i in items if i["producto_id"] == cafe.id)
        self.assertFalse(fila["barista_alerto"])

    def test_una_solicitud_del_kiosko_no_se_borra_por_la_puerta_del_dueno(self):
        # Tiene su propio camino —aprobar o rechazar— y ese deja rastro de quién
        # decidió. Borrarla por acá haría desaparecer el aviso de otra persona.
        cafe = self.producto("Café")
        s = self.solicitud_kiosko(cafe)
        r = self.client.delete(f"/api/v1/pedidos/registrado/{s.id}",
                               params={"tienda_id": self.vida.id})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIsNotNone(
            self.db.query(SolicitudPedido).filter(SolicitudPedido.id == s.id).first())


class DeshacerTest(PedidoRegistradoBase):

    def test_borrar_un_pedido_mal_registrado_se_lleva_sus_lineas(self):
        cafe = self.producto("Café")
        out = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        r = self.client.delete(f"/api/v1/pedidos/registrado/{out['id']}",
                               params={"tienda_id": self.vida.id})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.db.query(SolicitudPedido).count(), 0)
        self.assertEqual(self.db.query(SolicitudPedidoItem).count(), 0)

    def test_no_se_borra_el_pedido_de_otra_sede(self):
        cafe = self.producto("Café")
        out = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        r = self.client.delete(f"/api/v1/pedidos/registrado/{out['id']}",
                               params={"tienda_id": self.palmetto.id})
        self.assertEqual(r.status_code, 404, r.text)

    def test_borrar_algo_que_no_existe_avisa(self):
        r = self.client.delete("/api/v1/pedidos/registrado/9999",
                               params={"tienda_id": self.vida.id})
        self.assertEqual(r.status_code, 404)


class PediContraLlegoTest(PedidoRegistradoBase):
    """La pregunta que motivó todo esto: ¿trajeron lo que pedí?"""

    def test_la_ficha_compara_lo_pedido_con_lo_que_llego_con_factura(self):
        cafe = self.producto("Café", unidad="gr")
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.factura("Cafexcoop", cafe, 3000)

        d = self.ficha(cafe)["pedi_llego"]
        self.assertEqual(d["pedi"], 4000)
        self.assertEqual(d["llego_con_factura"], 3000)
        self.assertEqual(d["diferencia"], 1000)      # positivo = trajeron de menos
        self.assertEqual(d["n_pedidos"], 1)
        self.assertEqual(d["proveedores"], ["Cafexcoop"])

    def test_lo_cargado_a_mano_no_cierra_un_pedido(self):
        # Solo cuenta lo que entró CON FACTURA: la mercadería cargada a mano no
        # respalda un pedido, y contarla haría cuadrar entregas que nadie hizo.
        from app.models.models import MovimientoInventario, TipoMovInvEnum
        cafe = self.producto("Café", unidad="gr")
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.db.add(MovimientoInventario(
            producto_id=cafe.id, tienda_id=self.vida.id, tipo=TipoMovInvEnum.entrada,
            cantidad=4000, motivo="cargado a mano", usuario_id=self.admin.id,
            fecha=datetime.utcnow() - timedelta(days=1)))
        self.db.commit()

        d = self.ficha(cafe)["pedi_llego"]
        self.assertEqual(d["llego_con_factura"], 0)
        self.assertEqual(d["diferencia"], 4000)

    def test_dos_pedidos_al_mismo_insumo_se_suman(self):
        cafe = self.producto("Café", unidad="gr")
        a = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.db.query(SolicitudPedido).filter(SolicitudPedido.id == a["id"]).update(
            {"fecha_solicitud": datetime.utcnow() - timedelta(days=5)})
        self.db.commit()
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 2000}])

        d = self.ficha(cafe)["pedi_llego"]
        self.assertEqual(d["pedi"], 6000)
        self.assertEqual(d["n_pedidos"], 2)

    def test_lo_pedido_por_el_kiosko_no_se_suma_a_pedi(self):
        # La barista teclea la unidad libre: el azúcar aparece como «2 bolsa»,
        # «2 unidad» y «5000 gr» en la misma semana. Sumar eso da un número falso.
        cafe = self.producto("Café", unidad="gr")
        sol_svc.crear_pedido(self.db, self.vida.id, None,
                             [{"producto_id": cafe.id, "cantidad_solicitada": 2,
                               "unidad_solicitada": "bolsa"}], self.admin.id)
        d = self.ficha(cafe)["pedi_llego"]
        self.assertEqual(d["pedi"], 0)
        # Pero SÍ se ve en la bitácora, con su origen a la vista.
        origenes = [p["origen"] for p in self.ficha(cafe)["pedido_escrito"]]
        self.assertEqual(origenes, [ORIGEN_KIOSKO])

    def test_lo_pedido_en_otra_unidad_se_dice_no_se_traga(self):
        # Si el producto cambia de unidad después del pedido, «pedí 0» al lado de
        # una entrada grande mandaría a buscar un problema que no existe.
        cafe = self.producto("Café", unidad="gr")
        self.registrar("Cafexcoop", [
            {"producto_id": cafe.id, "cantidad": 4, "unidad": "bolsa"}])

        d = self.ficha(cafe)["pedi_llego"]
        self.assertEqual(d["pedi"], 0)
        self.assertEqual(d["en_otra_unidad"], {"bolsa": 4})

    def test_la_bitacora_muestra_las_dos_clases_con_su_origen_y_proveedor(self):
        cafe = self.producto("Café", unidad="gr")
        sol_svc.crear_pedido(self.db, self.vida.id, None,
                             [{"producto_id": cafe.id, "cantidad_solicitada": 2,
                               "unidad_solicitada": "bolsa"}], self.admin.id)
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])

        lineas = self.ficha(cafe)["pedido_escrito"]
        self.assertEqual(len(lineas), 2)
        delDueno = next(l for l in lineas if l["origen"] == ORIGEN_ADMIN)
        self.assertEqual(delDueno["proveedor"], "Cafexcoop")
        delKiosko = next(l for l in lineas if l["origen"] == ORIGEN_KIOSKO)
        self.assertIsNone(delKiosko["proveedor"])

    def test_la_tabla_trae_la_columna_pedi_para_cada_insumo(self):
        cafe = self.producto("Café", unidad="gr")
        azucar = self.producto("Azúcar", unidad="gr")
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])

        data = self.tabla()
        self.assertEqual(self.fila(data, "Café")["pedi"], 4000)
        # Un 0 acá significa «no le pedí nada a nadie», no «no se sabe».
        self.assertEqual(self.fila(data, "Azúcar")["pedi"], 0)
        self.assertEqual(data["resumen"]["n_con_pedido"], 1)

    def test_la_tabla_y_la_ficha_dicen_el_mismo_pedi(self):
        # Los dos números salen de `_fila_insumo`, compartida. Este test existe
        # para que sigan saliendo de ahí: el día que alguien recalcule «pedí» en
        # una de las dos pantallas, las dos empiezan a decir cosas distintas del
        # mismo insumo y nadie sabe cuál creer.
        cafe = self.producto("Café", unidad="gr")
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.assertEqual(self.fila(self.tabla(), "Café")["pedi"],
                         self.ficha(cafe)["pedi_llego"]["pedi"])

    def test_el_pedido_de_la_otra_sede_no_cuenta_acá(self):
        cafe = self.producto("Café", unidad="gr")
        self.db.add(Inventario(producto_id=cafe.id, tienda_id=self.palmetto.id,
                               stock_actual=0, stock_minimo=0))
        self.db.commit()
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}],
                       tienda=self.palmetto)
        self.assertEqual(self.ficha(cafe)["pedi_llego"]["pedi"], 0)
        self.assertEqual(self.ficha(cafe, tienda=self.palmetto)["pedi_llego"]["pedi"], 4000)

    def test_un_pedido_fuera_del_rango_no_entra(self):
        cafe = self.producto("Café", unidad="gr")
        out = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.db.query(SolicitudPedido).filter(SolicitudPedido.id == out["id"]).update(
            {"fecha_solicitud": datetime.utcnow() - timedelta(days=90)})
        self.db.commit()
        self.assertEqual(self.ficha(cafe)["pedi_llego"]["pedi"], 0)


class LaPantallaNoOlvidaTest(PedidoRegistradoBase):
    """Lo ya pedido hoy viaja con el catálogo: el estado no vive en la pestaña."""

    def test_el_catalogo_trae_lo_que_ya_se_le_pidio_hoy_a_cada_proveedor(self):
        cafe = self.producto("Café", unidad="gr", proveedor="Cafexcoop", stock=100)
        self.producto("Azúcar", unidad="gr", proveedor="Makro", stock=100)
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])

        cat = ped_svc.catalogo_proveedores(self.db, self.vida.id)
        grupos = {g["proveedor"]: g for g in cat["proveedores"]}
        self.assertEqual(len(grupos["Cafexcoop"]["pedidos_hoy"]), 1)
        self.assertEqual(grupos["Cafexcoop"]["pedidos_hoy"][0]["items"][0]["cantidad"], 4000)
        # Al que no se le pidió nada, la lista viene vacía: no hay estado que inventar.
        self.assertEqual(grupos["Makro"]["pedidos_hoy"], [])

    def test_el_pedido_de_ayer_no_se_muestra_como_pedido_hoy(self):
        # Si el de ayer contara, la pantalla diría «ya pediste» todas las mañanas
        # y el dueño se saltaría el pedido del día.
        cafe = self.producto("Café", unidad="gr", proveedor="Cafexcoop", stock=100)
        out = self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])
        self.db.query(SolicitudPedido).filter(SolicitudPedido.id == out["id"]).update(
            {"fecha_solicitud": datetime.utcnow() - timedelta(days=1)})
        self.db.commit()

        cat = ped_svc.catalogo_proveedores(self.db, self.vida.id)
        grupos = {g["proveedor"]: g for g in cat["proveedores"]}
        self.assertEqual(grupos["Cafexcoop"]["pedidos_hoy"], [])

    def test_el_listado_de_registrados_devuelve_lo_del_dueno_y_nada_mas(self):
        cafe = self.producto("Café", unidad="gr")
        sol_svc.crear_pedido(self.db, self.vida.id, None,
                             [{"producto_id": cafe.id, "cantidad_solicitada": 2,
                               "unidad_solicitada": "bolsa"}], self.admin.id)
        self.registrar("Cafexcoop", [{"producto_id": cafe.id, "cantidad": 4000}])

        r = self.client.get("/api/v1/pedidos/registrados",
                            params={"tienda_id": self.vida.id})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["proveedor"], "Cafexcoop")


if __name__ == "__main__":
    unittest.main()
