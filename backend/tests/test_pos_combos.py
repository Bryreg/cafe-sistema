"""Tests de COMBOS del POS: catálogo por tienda, validación de selecciones,
precio fijado por servidor, descuento de inventario por componentes (incluidas
opciones compuestas y cantidades ×N), no duplicación de ingresos, conteo de
combos vendidos y seed idempotente (cargar_combos)."""
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col
from app.database import Base, get_db
from app.models.models import (
    CajaTurno,
    CategoriaProductoEnum,
    Combo,
    ComboGrupo,
    ComboOpcion,
    ComboOpcionProducto,
    ComboTienda,
    EstadoTurnoEnum,
    Inventario,
    MovimientoInventario,
    Producto,
    ProductoInsumo,
    RolEnum,
    Ticket,
    TicketItem,
    TicketItemComboSeleccion,
    Tienda,
    TipoMovInvEnum,
    Usuario,
)
from app.routers import pos as pos_router
from app.services import dashboard_ejecutivo as dash_svc
from app.services import pos as pos_svc
from app.services.rentabilidad import get_pulso, get_rentabilidad


def create_test_app():
    test_app = FastAPI(title="Sistema Cafe Test — Combos")
    test_app.include_router(pos_router.router, prefix="/api/v1")
    return test_app


class CombosTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.db = self.SessionLocal()
        self.app = create_test_app()
        self.client = TestClient(self.app)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_get_db

        self.tienda_1 = Tienda(nombre="Vida", direccion="Sede Vida")
        self.tienda_2 = Tienda(nombre="Palmetto", direccion="Sede Palmetto")
        self.db.add_all([self.tienda_1, self.tienda_2])
        self.db.flush()

        self.barista = Usuario(
            nombre="Barista Uno",
            email="barista1@test.local",
            password_hash="hash",
            rol=RolEnum.barista,
            tienda_id=self.tienda_1.id,
            activo=True,
        )
        self.admin = Usuario(
            nombre="Admin",
            email="admin@test.local",
            password_hash="hash",
            rol=RolEnum.admin,
            tienda_id=self.tienda_1.id,
            activo=True,
        )
        self.db.add_all([self.barista, self.admin])
        self.db.commit()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def set_current_user(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def crear_producto(self, nombre, precio=0.0, controla_stock=False,
                       categoria=CategoriaProductoEnum.bebida):
        p = Producto(nombre=nombre, categoria=categoria, unidad_medida="und",
                     controla_stock=controla_stock, precio_venta=precio)
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)
        return p

    def crear_inventario(self, producto, tienda_id=None, stock=20.0):
        inv = Inventario(producto_id=producto.id, tienda_id=tienda_id or self.tienda_1.id,
                         stock_actual=stock, stock_minimo=0.0)
        self.db.add(inv)
        self.db.commit()
        self.db.refresh(inv)
        return inv

    def crear_combo(self, nombre, precio, tienda_ids, grupos, activo=True, orden=0):
        """grupos: [(nombre_grupo, [(nombre_opcion, [(producto, cantidad), ...]), ...]), ...]"""
        sombra = Producto(nombre=nombre, categoria=CategoriaProductoEnum.bebida,
                          unidad_medida="und", controla_stock=False, precio_venta=0)
        self.db.add(sombra)
        self.db.flush()
        combo = Combo(nombre=nombre, precio_venta=precio, activo=activo, orden=orden,
                      producto_id=sombra.id)
        self.db.add(combo)
        self.db.flush()
        for gi, (gnombre, opciones) in enumerate(grupos):
            grupo = ComboGrupo(combo_id=combo.id, nombre=gnombre, orden=gi)
            self.db.add(grupo)
            self.db.flush()
            for oi, (onombre, prods) in enumerate(opciones):
                opcion = ComboOpcion(grupo_id=grupo.id, nombre=onombre, orden=oi)
                self.db.add(opcion)
                self.db.flush()
                for prod, cant in prods:
                    self.db.add(ComboOpcionProducto(
                        opcion_id=opcion.id, producto_id=prod.id, cantidad=cant))
        for tid in tienda_ids:
            self.db.add(ComboTienda(combo_id=combo.id, tienda_id=tid))
        self.db.commit()
        self.db.refresh(combo)
        return combo

    def crear_turno_operativo(self, tienda_id=None):
        turno = CajaTurno(
            tienda_id=tienda_id or self.tienda_1.id,
            usuario_apertura_id=self.barista.id,
            base_sistema=0.0,
            base_real=100000.0,
            tiene_conteo_apertura=True,
            tiene_cuadre_llegada=True,
            estado=EstadoTurnoEnum.abierto,
        )
        self.db.add(turno)
        self.db.commit()
        self.db.refresh(turno)
        return turno

    def combo_basico(self, tienda_ids=None):
        """Combo de 2 grupos con 2 opciones cada uno (estilo Combo 01)."""
        self.americano = self.crear_producto("Americano Medium", 6900, controla_stock=True)
        self.cafe_leche = self.crear_producto("Cafe con Leche", 8900, controla_stock=True)
        self.almojabana = self.crear_producto("Almojabanas", 3900, controla_stock=True,
                                              categoria=CategoriaProductoEnum.pasteleria)
        self.croissant = self.crear_producto("Croissant Mantequilla", 0, controla_stock=True,
                                             categoria=CategoriaProductoEnum.pasteleria)
        return self.crear_combo(
            "Combo 01", 9900, tienda_ids or [self.tienda_1.id],
            [
                ("Bebida", [
                    ("Americano Medium", [(self.americano, 1)]),
                    ("Cafe con Leche", [(self.cafe_leche, 1)]),
                ]),
                ("Acompañamiento", [
                    ("Almojabanas", [(self.almojabana, 1)]),
                    ("Croissant Mantequilla", [(self.croissant, 1)]),
                ]),
            ],
        )

    def seleccion(self, combo, indices):
        """[(indice_grupo, indice_opcion)] → payload de selecciones."""
        sel = []
        for gi, oi in indices:
            grupo = combo.grupos[gi]
            sel.append({"grupo_id": grupo.id, "opcion_id": grupo.opciones[oi].id})
        return sel

    def post_ticket(self, combos, items=None, tienda_id=None, metodo="tarjeta", **extra):
        body = {
            "tienda_id": tienda_id or self.tienda_1.id,
            "items": items or [],
            "combos": combos,
            "metodo_pago": metodo,
        }
        body.update(extra)
        return self.client.post("/api/v1/pos/ticket", json=body)

    # ── Catálogo (GET /pos/combos) ───────────────────────────────────────────

    def test_get_combos_solo_activos_y_de_la_tienda(self):
        combo = self.combo_basico()
        otro = self.crear_combo("Combo Palmetto", 5000, [self.tienda_2.id],
                                [("Bebida", [("Americano Medium", [(self.americano, 1)])])])
        inactivo = self.crear_combo("Combo Viejo", 5000, [self.tienda_1.id],
                                    [("Bebida", [("Americano Medium", [(self.americano, 1)])])],
                                    activo=False)
        self.set_current_user(self.barista)

        r = self.client.get("/api/v1/pos/combos", params={"tienda_id": self.tienda_1.id})

        self.assertEqual(r.status_code, 200)
        nombres = [c["nombre"] for c in r.json()]
        self.assertEqual(nombres, ["Combo 01"])
        data = r.json()[0]
        self.assertEqual(data["precio_venta"], 9900.0)
        self.assertEqual(len(data["grupos"]), 2)
        self.assertEqual(len(data["grupos"][0]["opciones"]), 2)
        self.assertEqual(data["grupos"][0]["opciones"][0]["productos"][0]["nombre"],
                         "Americano Medium")
        self.assertIsNotNone(combo.id)
        self.assertIsNotNone(otro.id)
        self.assertIsNotNone(inactivo.id)

    def test_barista_no_consulta_combos_de_otra_tienda(self):
        self.combo_basico()
        self.set_current_user(self.barista)

        r = self.client.get("/api/v1/pos/combos", params={"tienda_id": self.tienda_2.id})

        self.assertEqual(r.status_code, 403)

    # ── Venta de combo (POST /pos/ticket) ────────────────────────────────────

    def test_venta_combo_crea_linea_con_precio_del_servidor(self):
        combo = self.combo_basico()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(0, 1), (1, 1)]),  # Cafe con Leche + Croissant
        }])

        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["total"], 9900.0)
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(item["nombre_producto"], "Combo 01")
        self.assertEqual(item["precio_unitario"], 9900.0)
        self.assertEqual(item["subtotal"], 9900.0)
        # La combinación elegida queda registrada, vinculada a la línea del combo
        sels = item["combo_selecciones"]
        self.assertEqual(len(sels), 2)
        self.assertEqual(
            {(s["nombre_grupo"], s["nombre_opcion"]) for s in sels},
            {("Bebida", "Cafe con Leche"), ("Acompañamiento", "Croissant Mantequilla")},
        )

    def test_precio_lo_fija_el_servidor_aunque_el_cliente_mande_otro(self):
        combo = self.combo_basico()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        # El payload intenta colar un precio distinto — el schema lo ignora y el
        # precio SIEMPRE sale de la DB.
        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 2,
            "precio_venta": 100,
            "precio": 100,
            "selecciones": self.seleccion(combo, [(0, 0), (1, 0)]),
        }])

        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["total"], 19800.0)

    def test_grupo_sin_seleccion_da_error(self):
        combo = self.combo_basico()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(0, 0)]),  # falta Acompañamiento
        }])

        self.assertEqual(r.status_code, 400)
        self.assertIn("Falta elegir", r.json()["detail"])
        self.assertIn("Acompañamiento", r.json()["detail"])

    def test_opcion_de_otro_grupo_da_error(self):
        combo = self.combo_basico()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        grupo_bebida = combo.grupos[0]
        opcion_acomp = combo.grupos[1].opciones[0]
        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": [
                {"grupo_id": grupo_bebida.id, "opcion_id": opcion_acomp.id},
                {"grupo_id": combo.grupos[1].id, "opcion_id": opcion_acomp.id},
            ],
        }])

        self.assertEqual(r.status_code, 400)
        self.assertIn("no pertenece", r.json()["detail"])

    def test_combo_de_otra_tienda_da_error(self):
        combo = self.combo_basico(tienda_ids=[self.tienda_2.id])
        self.crear_turno_operativo(self.tienda_1.id)
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(0, 0), (1, 0)]),
        }])

        self.assertEqual(r.status_code, 400)
        self.assertIn("no está disponible", r.json()["detail"])

    def test_combo_inactivo_da_error(self):
        combo = self.combo_basico()
        combo.activo = False
        self.db.commit()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(0, 0), (1, 0)]),
        }])

        self.assertEqual(r.status_code, 400)
        self.assertIn("no está activo", r.json()["detail"])

    def test_ticket_sin_items_ni_combos_da_error(self):
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([])

        self.assertEqual(r.status_code, 400)
        self.assertIn("no tiene items", r.json()["detail"])

    # ── Inventario ───────────────────────────────────────────────────────────

    def test_combo_descuenta_inventario_de_componentes(self):
        combo = self.combo_basico()
        inv_cafe = self.crear_inventario(self.cafe_leche, stock=10)
        inv_croissant = self.crear_inventario(self.croissant, stock=10)
        inv_americano = self.crear_inventario(self.americano, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 2,
            "selecciones": self.seleccion(combo, [(0, 1), (1, 1)]),
        }])

        self.assertEqual(r.status_code, 201, r.text)
        self.db.refresh(inv_cafe)
        self.db.refresh(inv_croissant)
        self.db.refresh(inv_americano)
        self.assertEqual(inv_cafe.stock_actual, 8.0)        # 10 − 2
        self.assertEqual(inv_croissant.stock_actual, 8.0)   # 10 − 2
        self.assertEqual(inv_americano.stock_actual, 10.0)  # opción NO elegida

    def test_opcion_compuesta_descuenta_ambos_productos(self):
        # "Americano Grande" = Americano Medium + Bebida Agrandada (DOS productos)
        americano = self.crear_producto("Americano Medium", 6900, controla_stock=True)
        agrandada = self.crear_producto("Bebida Agrandada", 2000, controla_stock=True)
        latte = self.crear_producto("Cafe Latte", 10900, controla_stock=True)
        pastel = self.crear_producto("Pastel de Pollo", 9900, controla_stock=True,
                                     categoria=CategoriaProductoEnum.pasteleria)
        combo = self.crear_combo(
            "Combo 02", 15900, [self.tienda_1.id],
            [
                ("Bebida", [
                    ("Cafe Latte", [(latte, 1)]),
                    ("Americano Grande", [(americano, 1), (agrandada, 1)]),
                ]),
                ("Acompañamiento", [("Pastel de Pollo", [(pastel, 1)])]),
            ],
        )
        inv_americano = self.crear_inventario(americano, stock=10)
        inv_agrandada = self.crear_inventario(agrandada, stock=10)
        inv_latte = self.crear_inventario(latte, stock=10)
        inv_pastel = self.crear_inventario(pastel, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(0, 1), (1, 0)]),
        }])

        self.assertEqual(r.status_code, 201, r.text)
        self.db.refresh(inv_americano)
        self.db.refresh(inv_agrandada)
        self.db.refresh(inv_latte)
        self.db.refresh(inv_pastel)
        self.assertEqual(inv_americano.stock_actual, 9.0)
        self.assertEqual(inv_agrandada.stock_actual, 9.0)
        self.assertEqual(inv_latte.stock_actual, 10.0)
        self.assertEqual(inv_pastel.stock_actual, 9.0)

    def test_grupo_fijo_por_dos_descuenta_doble_y_se_autoselecciona(self):
        # Combo 03: grupo "Bebidas" con UNA sola opción (Cappuccino ×2) → fijo,
        # el cliente NO manda selección de ese grupo.
        cappuccino = self.crear_producto("Cappuccino Tradicional Medium", 10900,
                                         controla_stock=True)
        torta_n = self.crear_producto("Torta Naranja", 12900, controla_stock=True,
                                      categoria=CategoriaProductoEnum.pasteleria)
        torta_c = self.crear_producto("Torta Chocolate", 13900, controla_stock=True,
                                      categoria=CategoriaProductoEnum.pasteleria)
        combo = self.crear_combo(
            "Combo 03", 27900, [self.tienda_1.id],
            [
                ("Bebidas", [("Cappuccino Tradicional Medium x2", [(cappuccino, 2)])]),
                ("Torta", [
                    ("Torta Naranja", [(torta_n, 1)]),
                    ("Torta Chocolate", [(torta_c, 1)]),
                ]),
            ],
        )
        inv_capp = self.crear_inventario(cappuccino, stock=10)
        inv_torta = self.crear_inventario(torta_n, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(1, 0)]),  # solo la torta
        }])

        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["total"], 27900.0)
        self.db.refresh(inv_capp)
        self.db.refresh(inv_torta)
        self.assertEqual(inv_capp.stock_actual, 8.0)   # ×2
        self.assertEqual(inv_torta.stock_actual, 9.0)
        sels = r.json()["items"][0]["combo_selecciones"]
        self.assertIn(("Bebidas", "Cappuccino Tradicional Medium x2"),
                      {(s["nombre_grupo"], s["nombre_opcion"]) for s in sels})

    def test_componente_descuenta_receta_de_insumos(self):
        # El componente "Cafe con Leche" (sin stock propio) descuenta su receta
        # (ProductoInsumo) igual que en una venta normal.
        combo = self.combo_basico()
        self.cafe_leche.controla_stock = False
        leche = self.crear_producto("Leche Entera", 0, controla_stock=True,
                                    categoria=CategoriaProductoEnum.insumo)
        self.db.add(ProductoInsumo(producto_id=self.cafe_leche.id,
                                   insumo_id=leche.id, cantidad=0.2))
        self.db.commit()
        inv_leche = self.crear_inventario(leche, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 2,
            "selecciones": self.seleccion(combo, [(0, 1), (1, 0)]),
        }])

        self.assertEqual(r.status_code, 201, r.text)
        self.db.refresh(inv_leche)
        self.assertAlmostEqual(inv_leche.stock_actual, 9.6)  # 10 − 0.2×2

    # ── Ingresos y conteo ────────────────────────────────────────────────────

    def test_combo_no_duplica_ingresos(self):
        combo = self.combo_basico()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(0, 0), (1, 0)]),
        }])

        self.assertEqual(r.status_code, 201, r.text)
        ticket_id = r.json()["id"]
        db = self.SessionLocal()
        try:
            items = db.query(TicketItem).filter(TicketItem.ticket_id == ticket_id).all()
            # Una sola línea con precio — los componentes NO son líneas del ticket
            self.assertEqual(len(items), 1)
            self.assertEqual(sum(i.subtotal for i in items), 9900.0)
            ticket = db.query(Ticket).get(ticket_id)
            self.assertEqual(ticket.total, 9900.0)
            # Los componentes quedan en la tabla de selecciones, con la línea del combo
            sels = db.query(TicketItemComboSeleccion).filter(
                TicketItemComboSeleccion.ticket_item_id == items[0].id).all()
            self.assertEqual(len(sels), 2)
        finally:
            db.close()

    def test_conteo_de_combos_vendidos_sale_de_analytics(self):
        combo = self.combo_basico()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        self.post_ticket([{"combo_id": combo.id, "cantidad": 2,
                           "selecciones": self.seleccion(combo, [(0, 0), (1, 0)])}])
        self.post_ticket([{"combo_id": combo.id, "cantidad": 1,
                           "selecciones": self.seleccion(combo, [(0, 1), (1, 1)])}])

        db = self.SessionLocal()
        try:
            top = pos_svc.get_analytics_productos_top(db, tienda_id=self.tienda_1.id)
            fila = next(f for f in top if f["nombre_producto"] == "Combo 01")
            self.assertEqual(fila["unidades"], 3)
            self.assertEqual(fila["total"], 29700.0)
        finally:
            db.close()

    def test_ticket_mixto_de_items_y_combos_suma_bien(self):
        combo = self.combo_basico()
        brownie = self.crear_producto("Brownie", 5000, controla_stock=True,
                                      categoria=CategoriaProductoEnum.pasteleria)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket(
            [{"combo_id": combo.id, "cantidad": 1,
              "selecciones": self.seleccion(combo, [(0, 0), (1, 0)])}],
            items=[{"producto_id": brownie.id, "cantidad": 2}],
            metodo="efectivo",
            efectivo_recibido=20000,
        )

        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["total"], 19900.0)  # 9900 + 5000×2
        self.assertEqual(body["cambio"], 100.0)
        self.assertEqual(len(body["items"]), 2)

    def test_anular_ticket_repone_stock_de_componentes(self):
        combo = self.combo_basico()
        inv_cafe = self.crear_inventario(self.cafe_leche, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 2,
            "selecciones": self.seleccion(combo, [(0, 1), (1, 1)]),
        }])
        self.assertEqual(r.status_code, 201, r.text)
        self.db.refresh(inv_cafe)
        self.assertEqual(inv_cafe.stock_actual, 8.0)

        db = self.SessionLocal()
        try:
            pos_svc.anular_ticket(db, r.json()["id"], usuario_id=self.admin.id,
                                  motivo="prueba")
        finally:
            db.close()
        self.db.refresh(inv_cafe)
        self.assertEqual(inv_cafe.stock_actual, 10.0)

    # ── Seed idempotente (cargar_combos) ─────────────────────────────────────

    def _productos_reales(self):
        """Los productos que la definición de combos referencia, SACADOS de esa
        misma definición. Antes era una lista escrita a mano acá, y agregar un
        combo nuevo al script rompía este test con «Producto NO encontrado» —
        un fallo que no dice nada del combo agregado y manda a editar el test."""
        import cargar_combos
        nombres = {
            nombre
            for cdef in cargar_combos.COMBOS
            for gdef in cdef["grupos"]
            for odef in gdef["opciones"]
            for nombre, _ in odef["productos"]
        }
        for n in sorted(nombres):
            self.crear_producto(n, 1000)

    def test_seed_combos_es_idempotente(self):
        import cargar_combos
        self._productos_reales()

        cargar_combos.run(db=self.db)
        cargar_combos.run(db=self.db)  # segunda corrida: no duplica

        # Lo esperado se deriva de la definición: así el test sigue verificando
        # que el seed refleja el script, en vez de una foto de cómo era el script
        # el día que se escribió el test.
        esperado = {(c["nombre"], float(c["precio"])) for c in cargar_combos.COMBOS}
        n_grupos = sum(len(c["grupos"]) for c in cargar_combos.COMBOS)
        n_opciones = sum(len(g["opciones"]) for c in cargar_combos.COMBOS for g in c["grupos"])

        combos = self.db.query(Combo).all()
        self.assertEqual(len(combos), len(cargar_combos.COMBOS))
        self.assertEqual({(c.nombre, c.precio_venta) for c in combos}, esperado)
        self.assertEqual(self.db.query(ComboGrupo).count(), n_grupos)
        self.assertEqual(self.db.query(ComboOpcion).count(), n_opciones)

        # Cada combo queda en LAS SEDES QUE DECLARA, no todos en una sola: el
        # script tenía una constante global que forzaba Vida para todos, así que
        # un combo de Palmetto no se podía cargar sin mover los demás.
        por_nombre = {c.nombre: c for c in combos}
        ids_sede = {"Vida": self.tienda_1.id, "Palmetto": self.tienda_2.id}
        for cdef in cargar_combos.COMBOS:
            combo = por_nombre[cdef["nombre"]]
            declaradas = cdef.get("sedes") or cargar_combos.SEDES_POR_DEFECTO
            reales = {a.tienda_id for a in
                      self.db.query(ComboTienda).filter_by(combo_id=combo.id).all()}
            self.assertEqual(reales, {ids_sede[s] for s in declaradas}, cdef["nombre"])
        # Opción compuesta: "Americano Grande" del Combo 02 consume DOS productos
        combo2 = next(c for c in combos if c.nombre == "Combo 02")
        grupo_bebida = next(g for g in combo2.grupos if g.nombre == "Bebida")
        opcion_grande = next(o for o in grupo_bebida.opciones if o.nombre == "Americano Grande")
        self.assertEqual(len(opcion_grande.productos), 2)
        # Grupo fijo del Combo 03: una sola opción con cantidad 2
        combo3 = next(c for c in combos if c.nombre == "Combo 03")
        grupo_fijo = next(g for g in combo3.grupos if g.nombre == "Bebidas")
        self.assertEqual(len(grupo_fijo.opciones), 1)
        self.assertEqual(grupo_fijo.opciones[0].productos[0].cantidad, 2)

    def test_seed_aborta_si_una_sede_declarada_no_existe(self):
        """Una sede mal escrita tiene que frenar el script ANTES de crear nada.
        Si pasara, el combo quedaría creado y sin sede: no se vende en ninguna
        parte y nadie se entera, porque la pantalla de Combos lo muestra igual."""
        import cargar_combos
        self._productos_reales()
        self.db.delete(self.tienda_2)   # se va Palmetto, que algún combo declara
        self.db.flush()
        declara_palmetto = any(
            "Palmetto" in (c.get("sedes") or cargar_combos.SEDES_POR_DEFECTO)
            for c in cargar_combos.COMBOS)
        if not declara_palmetto:
            self.skipTest("ningún combo declara Palmetto")
        with self.assertRaises(ValueError) as ctx:
            cargar_combos.run(db=self.db)
        self.assertIn("Palmetto", str(ctx.exception))
        self.assertEqual(self.db.query(Combo).count(), 0)

    def test_seed_falla_claro_si_falta_un_producto(self):
        import cargar_combos
        # Sin productos cargados → debe reportar los faltantes, no inventarlos
        with self.assertRaises(ValueError) as ctx:
            cargar_combos.run(db=self.db)
        self.assertIn("Americano Medium", str(ctx.exception))

    def test_seed_aborta_si_producto_real_colisiona_con_nombre_de_combo(self):
        import cargar_combos
        self._productos_reales()
        # Producto REAL (precio>0 y stock) llamado como un combo → NO adoptarlo
        # como sombra silenciosamente: abortar con el conflicto listado.
        self.crear_producto("Combo 01", 5000, controla_stock=True)
        with self.assertRaises(ValueError) as ctx:
            cargar_combos.run(db=self.db)
        self.assertIn("Combo 01", str(ctx.exception))
        # No creó combos a medias
        self.assertEqual(self.db.query(Combo).count(), 0)

    def test_seed_combo_sin_grupos_definido_aborta(self):
        import cargar_combos
        self._productos_reales()
        combos_def = [dict(cargar_combos.COMBOS[0], grupos=[])]
        with patch.object(cargar_combos, "COMBOS", combos_def):
            with self.assertRaises(ValueError) as ctx:
                cargar_combos.run(db=self.db)
        self.assertIn("Combo 01", str(ctx.exception))
        self.assertEqual(self.db.query(Combo).count(), 0)

    # ── Correcciones de revisión ─────────────────────────────────────────────

    def _revertir(self, ticket_id: int, items: list, motivo: str = "prueba NC"):
        self.set_current_user(self.admin)
        return self.client.post(f"/api/v1/pos/ticket/{ticket_id}/revertir",
                                json={"motivo": motivo, "items": items})

    def test_nota_credito_combo_no_usado_repone_componentes_y_recetas(self):
        # C1: la línea de combo apunta al sombra (controla_stock=False) — al
        # marcar "no usado" deben reponerse los CONSUMOS reales: componentes con
        # stock propio y recetas (insumos) de componentes sin stock propio.
        combo = self.combo_basico()
        self.cafe_leche.controla_stock = False
        leche = self.crear_producto("Leche Entera", 0, controla_stock=True,
                                    categoria=CategoriaProductoEnum.insumo)
        self.db.add(ProductoInsumo(producto_id=self.cafe_leche.id,
                                   insumo_id=leche.id, cantidad=0.2))
        self.db.commit()
        inv_croissant = self.crear_inventario(self.croissant, stock=10)
        inv_leche = self.crear_inventario(leche, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 2,
            "selecciones": self.seleccion(combo, [(0, 1), (1, 1)]),  # Cafe con Leche + Croissant
        }])
        self.assertEqual(r.status_code, 201, r.text)
        self.db.refresh(inv_croissant)
        self.db.refresh(inv_leche)
        self.assertEqual(inv_croissant.stock_actual, 8.0)
        self.assertAlmostEqual(inv_leche.stock_actual, 9.6)

        item_id = r.json()["items"][0]["id"]
        rv = self._revertir(r.json()["id"], [{"item_id": item_id, "producto_usado": False}])
        self.assertEqual(rv.status_code, 201, rv.text)
        self.db.refresh(inv_croissant)
        self.db.refresh(inv_leche)
        self.assertEqual(inv_croissant.stock_actual, 10.0)    # componente repuesto
        self.assertAlmostEqual(inv_leche.stock_actual, 10.0)  # receta repuesta

    def test_nota_credito_combo_usado_no_repone(self):
        combo = self.combo_basico()
        inv_cafe = self.crear_inventario(self.cafe_leche, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(0, 1), (1, 0)]),
        }])
        self.assertEqual(r.status_code, 201, r.text)

        item_id = r.json()["items"][0]["id"]
        rv = self._revertir(r.json()["id"], [{"item_id": item_id, "producto_usado": True}])
        self.assertEqual(rv.status_code, 201, rv.text)
        self.db.refresh(inv_cafe)
        self.assertEqual(inv_cafe.stock_actual, 9.0)  # usado: sigue descontado

    def test_nota_credito_lineas_del_mismo_combo_independientes(self):
        # W1: dos líneas del mismo combo comparten producto_id (sombra) — el
        # marcado usado/no-usado debe ser POR LÍNEA (id del ticket_item).
        combo = self.combo_basico()
        inv_cafe = self.crear_inventario(self.cafe_leche, stock=10)
        inv_americano = self.crear_inventario(self.americano, stock=10)
        inv_almojabana = self.crear_inventario(self.almojabana, stock=10)
        inv_croissant = self.crear_inventario(self.croissant, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([
            {"combo_id": combo.id, "cantidad": 1,
             "selecciones": self.seleccion(combo, [(0, 1), (1, 1)])},  # cafe + croissant
            {"combo_id": combo.id, "cantidad": 1,
             "selecciones": self.seleccion(combo, [(0, 0), (1, 0)])},  # americano + almojabana
        ])
        self.assertEqual(r.status_code, 201, r.text)
        items = r.json()["items"]
        self.assertEqual(len(items), 2)

        def con_cafe(item):
            return any(s["nombre_opcion"] == "Cafe con Leche"
                       for s in item["combo_selecciones"])

        linea_cafe = next(i for i in items if con_cafe(i))
        linea_amer = next(i for i in items if not con_cafe(i))
        rv = self._revertir(r.json()["id"], [
            {"item_id": linea_cafe["id"], "producto_usado": False},
            {"item_id": linea_amer["id"], "producto_usado": True},
        ])
        self.assertEqual(rv.status_code, 201, rv.text)
        for inv in (inv_cafe, inv_americano, inv_almojabana, inv_croissant):
            self.db.refresh(inv)
        self.assertEqual(inv_cafe.stock_actual, 10.0)       # no usado → repuesto
        self.assertEqual(inv_croissant.stock_actual, 10.0)  # no usado → repuesto
        self.assertEqual(inv_americano.stock_actual, 9.0)   # usado → descontado
        self.assertEqual(inv_almojabana.stock_actual, 9.0)  # usado → descontado

    def test_ventas_por_categoria_reporta_combos_como_categoria_propia(self):
        # C2: el ingreso del combo NO infla la categoría del sombra (bebida) ni
        # esconde pastelería — sale como categoría propia "combos".
        combo = self.combo_basico()
        brownie = self.crear_producto("Brownie", 5000, controla_stock=True,
                                      categoria=CategoriaProductoEnum.pasteleria)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket(
            [{"combo_id": combo.id, "cantidad": 1,
              "selecciones": self.seleccion(combo, [(0, 0), (1, 0)])}],
            items=[{"producto_id": brownie.id, "cantidad": 1}],
        )
        self.assertEqual(r.status_code, 201, r.text)

        db = self.SessionLocal()
        try:
            por_cat = {c["categoria"]: c
                       for c in dash_svc.ventas_por_categoria(db, None, None)}
        finally:
            db.close()
        self.assertIn("combos", por_cat)
        self.assertEqual(por_cat["combos"]["total"], 9900.0)
        self.assertEqual(por_cat["combos"]["unidades"], 1)
        self.assertNotIn("bebida", por_cat)  # el sombra no infla bebida
        self.assertEqual(por_cat["pasteleria"]["total"], 5000.0)

    def test_rentabilidad_incluye_costo_de_componentes_de_combo(self):
        # C3: el ingreso del combo entra a ventas — su costo (componentes) debe
        # entrar a cogs_teorico para no inflar el margen.
        combo = self.combo_basico()
        self.cafe_leche.precio_costo = 3000
        self.croissant.precio_costo = 2000
        self.db.commit()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 2,
            "selecciones": self.seleccion(combo, [(0, 1), (1, 1)]),
        }])
        self.assertEqual(r.status_code, 201, r.text)

        db = self.SessionLocal()
        try:
            res = get_rentabilidad(db, hoy_col(), hoy_col())["resumen"]
        finally:
            db.close()
        self.assertEqual(res["ventas"], 19800.0)
        self.assertAlmostEqual(res["cogs_teorico"], 10000.0)  # 2 × (3000 + 2000)
        self.assertAlmostEqual(res["margen_bruto_real"], 9800.0)
        self.assertEqual(res["pct_venta_costeada"], 100.0)

    def test_pulso_ticket_solo_combo_cuenta_bebida_con_pasteleria(self):
        # C2 (attach): los combos incluyen bebida + acompañamiento/torta — un
        # ticket solo-combo cuenta como bebida CON pastelería.
        combo = self.combo_basico()
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{
            "combo_id": combo.id,
            "cantidad": 1,
            "selecciones": self.seleccion(combo, [(0, 0), (1, 0)]),
        }])
        self.assertEqual(r.status_code, 201, r.text)

        db = self.SessionLocal()
        try:
            attach = get_pulso(db)["attach"]
        finally:
            db.close()
        self.assertEqual(attach["tickets_con_bebida"], 1)
        self.assertEqual(attach["pct_bebida_con_pasteleria"], 100.0)

    def test_producto_suelto_mas_componente_combo_fusiona_movimiento(self):
        # W4: producto suelto + mismo producto como componente del combo en el
        # mismo ticket → UN solo MovimientoInventario con la cantidad sumada.
        combo = self.combo_basico()
        inv_americano = self.crear_inventario(self.americano, stock=10)
        self.crear_inventario(self.almojabana, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket(
            [{"combo_id": combo.id, "cantidad": 1,
              "selecciones": self.seleccion(combo, [(0, 0), (1, 0)])}],  # americano + almojabana
            items=[{"producto_id": self.americano.id, "cantidad": 1}],
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.db.refresh(inv_americano)
        self.assertEqual(inv_americano.stock_actual, 8.0)  # 10 − (1 suelto + 1 combo)
        movs = self.db.query(MovimientoInventario).filter(
            MovimientoInventario.producto_id == self.americano.id,
            MovimientoInventario.tipo == TipoMovInvEnum.salida,
        ).all()
        self.assertEqual(len(movs), 1)
        self.assertEqual(movs[0].cantidad, 2.0)

    def _ticket_mixto_americano(self):
        """Ticket con americano suelto + combo cuyo componente es el MISMO
        americano → la venta descuenta con UN solo movimiento de salida (2.0)."""
        combo = self.combo_basico()
        inv_americano = self.crear_inventario(self.americano, stock=10)
        self.crear_inventario(self.almojabana, stock=10)
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket(
            [{"combo_id": combo.id, "cantidad": 1,
              "selecciones": self.seleccion(combo, [(0, 0), (1, 0)])}],  # americano + almojabana
            items=[{"producto_id": self.americano.id, "cantidad": 1}],
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r, inv_americano

    def _movimientos_entrada_americano(self):
        return self.db.query(MovimientoInventario).filter(
            MovimientoInventario.producto_id == self.americano.id,
            MovimientoInventario.tipo == TipoMovInvEnum.entrada,
        ).all()

    def test_anulacion_fusiona_movimiento_de_entrada_por_producto(self):
        # Espejo de W4: la venta fusionó suelto + componente en UN movimiento de
        # salida — la anulación debe reponer con UN solo movimiento de entrada
        # con la cantidad sumada, no uno por línea.
        r, inv_americano = self._ticket_mixto_americano()

        db = self.SessionLocal()
        try:
            pos_svc.anular_ticket(db, r.json()["id"], usuario_id=self.admin.id,
                                  motivo="prueba")
        finally:
            db.close()

        self.db.refresh(inv_americano)
        self.assertEqual(inv_americano.stock_actual, 10.0)
        movs = self._movimientos_entrada_americano()
        self.assertEqual(len(movs), 1)
        self.assertEqual(movs[0].cantidad, 2.0)

    def test_nota_credito_no_usado_fusiona_movimiento_de_entrada(self):
        # Espejo de W4 para la Nota Crédito: todo marcado NO usado → el suelto y
        # el componente del combo reponen con UN solo movimiento de entrada.
        r, inv_americano = self._ticket_mixto_americano()

        rv = self._revertir(r.json()["id"], [
            {"item_id": it["id"], "producto_usado": False}
            for it in r.json()["items"]
        ])
        self.assertEqual(rv.status_code, 201, rv.text)

        self.db.refresh(inv_americano)
        self.assertEqual(inv_americano.stock_actual, 10.0)
        movs = self._movimientos_entrada_americano()
        self.assertEqual(len(movs), 1)
        self.assertEqual(movs[0].cantidad, 2.0)

    def test_combo_sin_grupos_no_es_vendible(self):
        # W3: un combo sin grupos configurados no puede venderse a precio
        # completo sin componentes — error claro.
        combo = self.crear_combo("Combo Vacio", 9900, [self.tienda_1.id], [])
        self.crear_turno_operativo()
        self.set_current_user(self.barista)

        r = self.post_ticket([{"combo_id": combo.id, "cantidad": 1, "selecciones": []}])

        self.assertEqual(r.status_code, 400)
        self.assertIn("no tiene grupos", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
