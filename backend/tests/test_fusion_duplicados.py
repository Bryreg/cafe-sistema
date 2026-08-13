"""Fusión de duplicados archivados: re-apuntar la historia y borrar el cascarón.

Estos tests corren sobre la parte del sistema que más daño puede hacer: mueven
ventas reales de un producto a otro. Por eso cubren tanto lo que TIENE que pasar
(la historia se muda entera, el cascarón desaparece) como lo que JAMÁS puede
pasar (fusionar dos vivos, cambiar el total de un ticket, sumar stock en
silencio, romper un combo, borrar un archivado que tiene historia).
"""
import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import (
    CategoriaProductoEnum,
    Combo,
    ComboGrupo,
    ComboOpcion,
    ComboOpcionProducto,
    Inventario,
    MovimientoInventario,
    Producto,
    ProductoAlias,
    ProductoDesechable,
    ProductoInsumo,
    RolEnum,
    Ticket,
    TicketItem,
    Tienda,
    TipoMovInvEnum,
    Usuario,
)
from app.routers import inventario as inventario_router
from app.services import fusion_duplicados as svc


def create_test_app():
    test_app = FastAPI(title="Sistema Cafe Test — Fusión duplicados")
    test_app.include_router(inventario_router.router, prefix="/api/v1")
    return test_app


class FusionDuplicadosBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
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

        self.t1 = Tienda(nombre="Vida", direccion="Sede Vida")
        self.t2 = Tienda(nombre="Palmetto", direccion="Sede Palmetto")
        self.db.add_all([self.t1, self.t2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.barista = Usuario(nombre="Barista", email="b@test.local", password_hash="h",
                               rol=RolEnum.barista, tienda_id=self.t1.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.db.commit()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def vivo(self, nombre, precio=5000.0, categoria=CategoriaProductoEnum.pasteleria):
        p = Producto(nombre=nombre, categoria=categoria, unidad_medida="und",
                     controla_stock=True, incluir_en_conteo=True, precio_venta=precio)
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)
        return p

    def archivado(self, nombre, categoria=CategoriaProductoEnum.pasteleria):
        """La misma firma que usa el catálogo: fuera del POS, del conteo y del stock."""
        p = Producto(nombre=nombre, categoria=categoria, unidad_medida="und",
                     controla_stock=False, incluir_en_conteo=False, precio_venta=0)
        self.db.add(p)
        self.db.commit()
        self.db.refresh(p)
        return p

    def inv(self, producto, tienda, stock=0.0):
        r = Inventario(producto_id=producto.id, tienda_id=tienda.id,
                       stock_actual=stock, stock_minimo=0.0)
        self.db.add(r)
        self.db.commit()
        return r

    def movimiento(self, producto, tienda, cantidad=3.0):
        m = MovimientoInventario(producto_id=producto.id, tienda_id=tienda.id,
                                 tipo=TipoMovInvEnum.entrada, cantidad=cantidad,
                                 motivo="test", usuario_id=self.admin.id)
        self.db.add(m)
        self.db.commit()
        return m

    def ticket_con(self, lineas):
        """lineas: [(producto, cantidad, precio_unitario)]. Total = suma de subtotales."""
        total = sum(c * p for _, c, p in lineas)
        t = Ticket(tienda_id=self.t1.id, caja_turno_id=None, usuario_id=self.admin.id,
                   total=total, metodo_pago="efectivo", monto_efectivo=total)
        # caja_turno_id es NOT NULL en el esquema real; para el test basta un turno falso
        t.caja_turno_id = self._turno_id()
        self.db.add(t)
        self.db.flush()
        for prod, cant, precio in lineas:
            self.db.add(TicketItem(ticket_id=t.id, producto_id=prod.id,
                                   nombre_producto=prod.nombre, cantidad=cant,
                                   precio_unitario=precio, subtotal=cant * precio))
        self.db.commit()
        self.db.refresh(t)
        return t

    def _turno_id(self):
        from app.models.models import CajaTurno, EstadoTurnoEnum
        turno = self.db.query(CajaTurno).first()
        if turno is None:
            turno = CajaTurno(tienda_id=self.t1.id, usuario_apertura_id=self.admin.id,
                              base_real=0, estado=EstadoTurnoEnum.cerrado)
            self.db.add(turno)
            self.db.commit()
            self.db.refresh(turno)
        return turno.id

    def alias(self, producto, texto):
        a = ProductoAlias(alias_normalizado=texto.upper(), alias_original=texto,
                          producto_id=producto.id, origen="correccion", veces_visto=1)
        self.db.add(a)
        self.db.commit()
        return a

    def conteo_filas(self):
        """Filas de TODAS las tablas. La foto que prueba que un GET no escribió."""
        out = {}
        for tabla in Base.metadata.sorted_tables:
            out[tabla.name] = self.db.execute(
                select(func.count()).select_from(tabla)
            ).scalar()
        return out

    def existe(self, producto_id):
        return self.db.query(Producto).filter_by(id=producto_id).first() is not None

    def como_admin(self):
        self.app.dependency_overrides[get_current_user] = lambda: self.admin

    def como_barista(self):
        self.app.dependency_overrides[get_current_user] = lambda: self.barista


# ─────────────────────────────────────────────────────────────────────────────
# El caso feliz: la historia se muda entera y el cascarón desaparece
# ─────────────────────────────────────────────────────────────────────────────

class FusionSimpleTest(FusionDuplicadosBase):
    def test_mueve_toda_la_historia_y_borra_el_cascaron(self):
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.movimiento(muerto, self.t1, 4)
        self.movimiento(muerto, self.t2, 7)
        muerto_id = muerto.id

        out = svc.fusionar_par(self.db, muerto_id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["movidos"].get("movimientos_inventario.producto_id"), 2)
        self.db.expire_all()
        self.assertFalse(self.existe(muerto_id))                    # cascarón borrado
        movs = self.db.query(MovimientoInventario).all()
        self.assertEqual([m.producto_id for m in movs], [vivo.id, vivo.id])

    def test_sin_historia_solo_borra_el_cascaron(self):
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        muerto_id = muerto.id

        out = svc.fusionar_par(self.db, muerto_id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["movidos"], {})
        self.db.expire_all()
        self.assertFalse(self.existe(muerto_id))
        self.assertTrue(self.existe(vivo.id))

    def test_deja_rastro_en_auditoria(self):
        from app.models.models import AuditLog
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.movimiento(muerto, self.t1, 4)

        svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.db.expire_all()
        logs = self.db.query(AuditLog).filter_by(accion="fusionar_duplicado").all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].usuario_id, self.admin.id)


# ─────────────────────────────────────────────────────────────────────────────
# VENTAS: se re-apuntan, jamás se borran, y la plata no se mueve
# ─────────────────────────────────────────────────────────────────────────────

class VentasIntactasTest(FusionDuplicadosBase):
    def test_el_total_vendido_del_ticket_no_cambia(self):
        vivo = self.vivo("Pastel de Queso", precio=9000)
        muerto = self.archivado("Pastel Queso")
        ticket = self.ticket_con([(vivo, 2, 9000.0), (muerto, 1, 8000.0)])
        total_antes = float(ticket.total)
        items_antes = self.db.query(func.count(TicketItem.id)).scalar()

        svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.db.expire_all()
        t = self.db.query(Ticket).filter_by(id=ticket.id).first()
        self.assertEqual(float(t.total), total_antes)                    # la plata no se movió
        self.assertEqual(self.db.query(func.count(TicketItem.id)).scalar(), items_antes)
        suma = self.db.query(func.sum(TicketItem.subtotal)).filter_by(ticket_id=t.id).scalar()
        self.assertEqual(float(suma), total_antes)
        # y todas las líneas ahora cuelgan del vivo
        pids = {i.producto_id for i in self.db.query(TicketItem).filter_by(ticket_id=t.id)}
        self.assertEqual(pids, {vivo.id})

    def test_el_nombre_vendido_de_la_linea_no_se_reescribe(self):
        """El snapshot del ticket es lo que el cliente pagó ese día. Se conserva."""
        vivo = self.vivo("Pastel de Queso", precio=9000)
        muerto = self.archivado("Pastel Queso")
        ticket = self.ticket_con([(muerto, 1, 8000.0)])

        svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.db.expire_all()
        item = self.db.query(TicketItem).filter_by(ticket_id=ticket.id).first()
        self.assertEqual(item.nombre_producto, "Pastel Queso")
        self.assertEqual(float(item.precio_unitario), 8000.0)


# ─────────────────────────────────────────────────────────────────────────────
# INVENTARIO: el único (producto_id, tienda_id) choca SIEMPRE
# ─────────────────────────────────────────────────────────────────────────────

class ChoqueInventarioTest(FusionDuplicadosBase):
    def test_choque_con_stock_cero_se_resuelve_borrando_la_fila_del_muerto(self):
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.inv(vivo, self.t1, stock=12.0)
        self.inv(muerto, self.t1, stock=0.0)

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        filas = self.db.query(Inventario).all()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0].producto_id, vivo.id)
        self.assertEqual(filas[0].stock_actual, 12.0)      # el stock del vivo INTACTO

    def test_choque_con_stock_distinto_de_cero_aborta_el_par(self):
        """Sumar stock en silencio inventaría mercancía. Se aborta y se reporta."""
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.inv(vivo, self.t1, stock=12.0)
        self.inv(muerto, self.t1, stock=3.0)
        muerto_id = muerto.id

        out = svc.fusionar_par(self.db, muerto_id, vivo.id, self.admin.id)

        self.assertFalse(out["ok"])
        self.assertIn("stock", (out.get("error") or "").lower())
        self.db.expire_all()
        self.assertTrue(self.existe(muerto_id))                       # nada se tocó
        filas = {(r.producto_id, r.stock_actual) for r in self.db.query(Inventario)}
        self.assertEqual(filas, {(vivo.id, 12.0), (muerto_id, 3.0)})

    def test_sin_choque_la_fila_de_inventario_se_reapunta(self):
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.inv(vivo, self.t1, stock=12.0)
        self.inv(muerto, self.t2, stock=0.0)

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        por_tienda = {r.tienda_id: r.producto_id for r in self.db.query(Inventario)}
        self.assertEqual(por_tienda, {self.t1.id: vivo.id, self.t2.id: vivo.id})


# ─────────────────────────────────────────────────────────────────────────────
# ALIASES: alias_normalizado es único GLOBAL, no lo ve uniques_con_producto()
# ─────────────────────────────────────────────────────────────────────────────

class AliasesTest(FusionDuplicadosBase):
    def test_alias_repetido_se_borra_y_alias_distinto_se_reapunta(self):
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.alias(vivo, "PASTEL DE QUESO")
        self.alias(muerto, "PASTEL DE QUESO X12")   # se muda: el OCR aprende a ir al vivo
        # mismo alias en los dos es imposible por el único global; el choque real
        # es el alias del muerto que YA existe apuntando al vivo:
        self.alias(muerto, "TORTA QUESO PROV")

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        aliases = self.db.query(ProductoAlias).all()
        self.assertEqual({a.alias_normalizado for a in aliases},
                         {"PASTEL DE QUESO", "PASTEL DE QUESO X12", "TORTA QUESO PROV"})
        self.assertEqual({a.producto_id for a in aliases}, {vivo.id})

    def test_alias_identico_en_muerto_y_vivo_se_resuelve_borrando_el_del_muerto(self):
        """El único de alias_normalizado es un ÍNDICE aparte, no parte del CREATE
        TABLE: una base a la que nunca se le creó (o a la que se le cayó) admite
        el mismo alias en los dos productos. La fusión no delega en la base la
        resolución de ese choque — lo resuelve ella, y por eso se prueba sin él."""
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.db.execute(text("DROP INDEX ix_producto_aliases_alias_normalizado"))
        self.db.commit()
        self.alias(vivo, "PASTEL QUESO")
        self.alias(muerto, "PASTEL QUESO")
        self.alias(muerto, "TORTA QUESO PROV")

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        aliases = self.db.query(ProductoAlias).all()
        self.assertEqual(len(aliases), 2)
        self.assertEqual({a.alias_normalizado for a in aliases},
                         {"PASTEL QUESO", "TORTA QUESO PROV"})
        self.assertEqual({a.producto_id for a in aliases}, {vivo.id})


# ─────────────────────────────────────────────────────────────────────────────
# AUTO-REFERENCIAS: sustituto_id y las recetas con DOS columnas de producto
# ─────────────────────────────────────────────────────────────────────────────

class AutoReferenciasTest(FusionDuplicadosBase):
    def test_sustituto_id_se_reapunta_al_vivo(self):
        vivo = self.vivo("Leche Entera")
        muerto = self.archivado("Leche Entera 1L")
        otro = self.vivo("Leche Deslactosada")
        otro.sustituto_id = muerto.id
        self.db.commit()

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        self.assertEqual(self.db.query(Producto).filter_by(id=otro.id).first().sustituto_id,
                         vivo.id)

    def test_el_vivo_no_queda_como_sustituto_de_si_mismo(self):
        vivo = self.vivo("Leche Entera")
        muerto = self.archivado("Leche Entera 1L")
        vivo.sustituto_id = muerto.id       # el vivo se apoyaba en su propio duplicado
        self.db.commit()

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        self.assertIsNone(self.db.query(Producto).filter_by(id=vivo.id).first().sustituto_id)

    def test_receta_repetida_se_borra_y_la_distinta_se_reapunta(self):
        bebida = self.vivo("Latte")
        otra = self.vivo("Capuchino")
        vivo = self.vivo("Leche Entera")
        muerto = self.archivado("Leche Entera 1L")
        self.db.add_all([
            ProductoInsumo(producto_id=bebida.id, insumo_id=vivo.id, cantidad=200),
            ProductoInsumo(producto_id=bebida.id, insumo_id=muerto.id, cantidad=150),  # choca
            ProductoInsumo(producto_id=otra.id, insumo_id=muerto.id, cantidad=180),    # se muda
        ])
        self.db.commit()

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        recetas = {(r.producto_id, r.insumo_id, r.cantidad)
                   for r in self.db.query(ProductoInsumo)}
        self.assertEqual(recetas, {(bebida.id, vivo.id, 200), (otra.id, vivo.id, 180)})

    def test_no_queda_un_producto_consumiendose_a_si_mismo(self):
        """El vivo tenía al muerto en su propia receta. Re-apuntar a ciegas lo
        dejaría consumiéndose a sí mismo: esa línea se borra."""
        vivo = self.vivo("Leche Entera")
        muerto = self.archivado("Leche Entera 1L")
        self.db.add(ProductoInsumo(producto_id=vivo.id, insumo_id=muerto.id, cantidad=100))
        self.db.commit()

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        self.assertEqual(self.db.query(ProductoInsumo).count(), 0)

    def test_desechables_reapunta_las_dos_columnas(self):
        bebida = self.vivo("Latte")
        vivo = self.vivo("Vaso 12oz")
        muerto = self.archivado("Vaso 12 oz")
        self.db.add(ProductoDesechable(producto_id=bebida.id, insumo_id=muerto.id, cantidad=1))
        self.db.commit()

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        filas = [(d.producto_id, d.insumo_id) for d in self.db.query(ProductoDesechable)]
        self.assertEqual(filas, [(bebida.id, vivo.id)])


# ─────────────────────────────────────────────────────────────────────────────
# LO QUE JAMÁS PUEDE PASAR
# ─────────────────────────────────────────────────────────────────────────────

class GuardasTest(FusionDuplicadosBase):
    def test_jamas_fusiona_dos_productos_vivos(self):
        a = self.vivo("Pastel de Queso")
        b = self.vivo("Pastel Queso")

        out = svc.fusionar_par(self.db, b.id, a.id, self.admin.id)

        self.assertFalse(out["ok"])
        self.assertIn("archivado", (out.get("error") or "").lower())
        self.db.expire_all()
        self.assertTrue(self.existe(b.id))

    def test_el_endpoint_rechaza_un_muerto_vivo_antes_de_tocar_nada(self):
        self.como_admin()
        a = self.vivo("Pastel de Queso")
        b = self.vivo("Pastel Queso")
        c = self.archivado("Pastel  Queso")

        r = self.client.post("/api/v1/inventario/duplicados/fusionar", json={
            "pares": [{"muerto": c.id, "vivo": a.id}, {"muerto": b.id, "vivo": a.id}],
            "borrar_huerfanos_vacios": False,
        })

        self.assertEqual(r.status_code, 400)
        self.db.expire_all()
        self.assertTrue(self.existe(b.id))
        self.assertTrue(self.existe(c.id))     # ni siquiera el par válido se ejecutó

    def test_el_vivo_no_puede_ser_el_muerto(self):
        p = self.archivado("Pastel Queso")
        out = svc.fusionar_par(self.db, p.id, p.id, self.admin.id)
        self.assertFalse(out["ok"])

    def test_el_producto_sombra_de_un_combo_nunca_es_muerto(self):
        """Un combo tiene un producto sombra con precio 0, sin stock y fuera del
        conteo: la firma EXACTA de un archivado. Fusionarlo movería el combo a un
        producto real del POS. Se aborta."""
        vivo = self.vivo("Combo 03")
        sombra = self.archivado("Combo 03", categoria=CategoriaProductoEnum.bebida)
        combo = Combo(nombre="Combo 03", precio_venta=20000, activo=True,
                      orden=0, producto_id=sombra.id)
        self.db.add(combo)
        self.db.commit()
        sombra_id = sombra.id

        out = svc.fusionar_par(self.db, sombra_id, vivo.id, self.admin.id)

        self.assertFalse(out["ok"])
        self.assertIn("combo", (out.get("error") or "").lower())
        self.db.expire_all()
        self.assertTrue(self.existe(sombra_id))
        self.assertEqual(self.db.query(Combo).count(), 1)

    def test_un_par_que_falla_no_arrastra_a_los_otros(self):
        vivo_a = self.vivo("Pastel de Queso")
        malo = self.archivado("Pastel Queso")
        self.inv(vivo_a, self.t1, stock=12.0)
        self.inv(malo, self.t1, stock=3.0)          # choque con stock: aborta
        vivo_b = self.vivo("Torta de Chocolate")
        bueno = self.archivado("Torta Chocolate")
        self.movimiento(bueno, self.t1, 5)
        malo_id, bueno_id = malo.id, bueno.id

        out = svc.fusionar(self.db, [{"muerto": malo_id, "vivo": vivo_a.id},
                                     {"muerto": bueno_id, "vivo": vivo_b.id}],
                           borrar_huerfanos_vacios=False, usuario_id=self.admin.id)

        self.assertEqual(len(out["pares"]), 2)
        self.assertFalse(out["pares"][0]["ok"])
        self.assertTrue(out["pares"][1]["ok"], out["pares"][1].get("error"))
        self.db.expire_all()
        self.assertTrue(self.existe(malo_id))       # el que falló quedó como estaba
        self.assertFalse(self.existe(bueno_id))     # el otro se fusionó igual

    def test_correr_la_fusion_dos_veces_no_rompe_nada(self):
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.movimiento(muerto, self.t1, 4)
        muerto_id = muerto.id
        pares = [{"muerto": muerto_id, "vivo": vivo.id}]

        primera = svc.fusionar(self.db, pares, borrar_huerfanos_vacios=True,
                               usuario_id=self.admin.id)
        segunda = svc.fusionar(self.db, pares, borrar_huerfanos_vacios=True,
                               usuario_id=self.admin.id)

        self.assertTrue(primera["pares"][0]["ok"])
        self.assertFalse(segunda["pares"][0]["ok"])       # ya no hay nada que hacer
        self.db.expire_all()
        self.assertEqual(self.db.query(MovimientoInventario).count(), 1)
        self.assertTrue(self.existe(vivo.id))


# ─────────────────────────────────────────────────────────────────────────────
# HUÉRFANOS: archivados sin ningún vivo (el menú viejo)
# ─────────────────────────────────────────────────────────────────────────────

class HuerfanosTest(FusionDuplicadosBase):
    def test_el_plan_dice_cuales_tienen_historia(self):
        vacio = self.archivado("Muffin Mora")
        conhistoria = self.archivado("Cake Banano")
        self.movimiento(conhistoria, self.t1, 2)

        plan = svc.plan(self.db)

        por_id = {h["id"]: h for h in plan["huerfanos"]}
        self.assertFalse(por_id[vacio.id]["tiene_historia"])
        self.assertTrue(por_id[conhistoria.id]["tiene_historia"])
        self.assertEqual(por_id[conhistoria.id]["ancla"],
                         {"movimientos_inventario.producto_id": 1})

    def test_borra_solo_los_vacios_y_conserva_los_que_tienen_historia(self):
        vacio = self.archivado("Muffin Mora")
        conhistoria = self.archivado("Cake Banano")
        self.movimiento(conhistoria, self.t1, 2)
        vacio_id, conhistoria_id = vacio.id, conhistoria.id

        out = svc.fusionar(self.db, [], borrar_huerfanos_vacios=True,
                           usuario_id=self.admin.id)

        self.assertEqual([h["id"] for h in out["huerfanos_borrados"]], [vacio_id])
        self.assertEqual([h["id"] for h in out["huerfanos_conservados"]], [conhistoria_id])
        self.db.expire_all()
        self.assertFalse(self.existe(vacio_id))
        self.assertTrue(self.existe(conhistoria_id))

    def test_sin_la_bandera_no_borra_ningun_huerfano(self):
        vacio = self.archivado("Muffin Mora")
        vacio_id = vacio.id

        out = svc.fusionar(self.db, [], borrar_huerfanos_vacios=False,
                           usuario_id=self.admin.id)

        self.assertEqual(out["huerfanos_borrados"], [])
        self.db.expire_all()
        self.assertTrue(self.existe(vacio_id))

    def test_una_fila_de_inventario_en_cero_no_es_historia(self):
        """Al dar de alta un producto el sistema le crea un casillero por sede.
        Un casillero en 0 y sin umbrales no lo escribió nadie: si contara como
        historia, el catálogo diría «no puedo borrarlo, tiene historia» sobre un
        producto que no tiene absolutamente nada."""
        huerfano = self.archivado("Muffin Mora")
        self.inv(huerfano, self.t1, stock=0.0)
        self.inv(huerfano, self.t2, stock=0.0)
        huerfano_id = huerfano.id

        plan = svc.plan(self.db)
        self.assertFalse(plan["huerfanos"][0]["tiene_historia"])
        self.assertEqual(plan["huerfanos"][0]["ancla"], {})

        out = svc.fusionar(self.db, [], borrar_huerfanos_vacios=True,
                           usuario_id=self.admin.id)

        self.assertEqual([h["id"] for h in out["huerfanos_borrados"]], [huerfano_id])
        self.db.expire_all()
        self.assertFalse(self.existe(huerfano_id))
        self.assertEqual(self.db.query(Inventario).count(), 0)   # el casillero se fue con él

    def test_una_fila_de_inventario_con_stock_si_es_historia(self):
        huerfano = self.archivado("Muffin Mora")
        self.inv(huerfano, self.t1, stock=4.0)
        huerfano_id = huerfano.id

        out = svc.fusionar(self.db, [], borrar_huerfanos_vacios=True,
                           usuario_id=self.admin.id)

        self.assertEqual([h["id"] for h in out["huerfanos_conservados"]], [huerfano_id])
        self.db.expire_all()
        self.assertTrue(self.existe(huerfano_id))

    def test_un_umbral_configurado_a_mano_si_es_historia(self):
        """Un mínimo distinto de 0 lo escribió el admin: eso sí es un registro."""
        huerfano = self.archivado("Muffin Mora")
        fila = self.inv(huerfano, self.t1, stock=0.0)
        fila.stock_minimo = 5.0
        self.db.commit()
        huerfano_id = huerfano.id

        out = svc.fusionar(self.db, [], borrar_huerfanos_vacios=True,
                           usuario_id=self.admin.id)

        self.assertEqual([h["id"] for h in out["huerfanos_conservados"]], [huerfano_id])
        self.db.expire_all()
        self.assertTrue(self.existe(huerfano_id))

    def test_un_producto_sombra_de_combo_no_se_borra_como_huerfano(self):
        sombra = self.archivado("Combo 03", categoria=CategoriaProductoEnum.bebida)
        self.db.add(Combo(nombre="Combo 03", precio_venta=20000, activo=True,
                          orden=0, producto_id=sombra.id))
        self.db.commit()
        sombra_id = sombra.id

        svc.fusionar(self.db, [], borrar_huerfanos_vacios=True, usuario_id=self.admin.id)

        self.db.expire_all()
        self.assertTrue(self.existe(sombra_id))


# ─────────────────────────────────────────────────────────────────────────────
# EL PLAN (GET): read-only de verdad
# ─────────────────────────────────────────────────────────────────────────────

class PlanTest(FusionDuplicadosBase):
    def _escenario(self):
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.movimiento(muerto, self.t1, 4)
        self.inv(vivo, self.t1, stock=9.0)
        self.inv(muerto, self.t1, stock=0.0)
        self.archivado("Muffin Mora")
        a1 = self.vivo("Torta de Chocolate")
        a2 = self.vivo("Torta Chocolate")
        self.archivado("Torta  Chocolate")
        return vivo, muerto, a1, a2

    def test_el_plan_no_escribe_una_sola_fila(self):
        self._escenario()
        antes = self.conteo_filas()

        svc.plan(self.db)

        self.assertEqual(self.conteo_filas(), antes)

    def test_el_plan_clasifica_en_tres_desenlaces(self):
        vivo, muerto, _, _ = self._escenario()

        plan = svc.plan(self.db)

        self.assertEqual([f["muerto"]["id"] for f in plan["fusionables"]], [muerto.id])
        f = plan["fusionables"][0]
        self.assertEqual(f["vivo"]["id"], vivo.id)
        self.assertEqual(f["mueve"]["movimientos_inventario.producto_id"], 1)
        self.assertTrue(f["seguro"])
        self.assertTrue(f["choques"])                       # inventario choca, resuelto
        self.assertEqual(len(plan["ambiguos"]), 1)          # dos vivos "Torta Chocolate"
        self.assertEqual([h["nombre"] for h in plan["huerfanos"]], ["Muffin Mora"])
        self.assertEqual(plan["resumen"]["fusionables"], 1)

    def test_un_choque_de_stock_deja_el_par_como_no_seguro(self):
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.inv(vivo, self.t1, stock=9.0)
        self.inv(muerto, self.t1, stock=2.0)

        plan = svc.plan(self.db)

        f = plan["fusionables"][0]
        self.assertFalse(f["seguro"])
        self.assertTrue(f["bloqueos"])

    def test_el_endpoint_del_plan_es_solo_admin(self):
        self._escenario()
        self.como_barista()
        r = self.client.get("/api/v1/inventario/duplicados/plan")
        self.assertEqual(r.status_code, 403)

    def test_el_endpoint_del_plan_devuelve_el_reporte_y_no_escribe(self):
        self._escenario()
        self.como_admin()
        antes = self.conteo_filas()

        r = self.client.get("/api/v1/inventario/duplicados/plan")

        self.assertEqual(r.status_code, 200)
        cuerpo = r.json()
        self.assertIn("fusionables", cuerpo)
        self.assertIn("ambiguos", cuerpo)
        self.assertIn("huerfanos", cuerpo)
        self.assertEqual(cuerpo["resumen"]["fusionables"], 1)
        self.db.expire_all()
        self.assertEqual(self.conteo_filas(), antes)


# ─────────────────────────────────────────────────────────────────────────────
# EL ENDPOINT QUE ESCRIBE
# ─────────────────────────────────────────────────────────────────────────────

class EndpointFusionarTest(FusionDuplicadosBase):
    def test_solo_admin(self):
        self.como_barista()
        r = self.client.post("/api/v1/inventario/duplicados/fusionar",
                             json={"pares": [], "borrar_huerfanos_vacios": False})
        self.assertEqual(r.status_code, 403)

    def test_fusiona_y_reporta_par_por_par(self):
        self.como_admin()
        vivo = self.vivo("Pastel de Queso")
        muerto = self.archivado("Pastel Queso")
        self.movimiento(muerto, self.t1, 4)
        muerto_id = muerto.id

        r = self.client.post("/api/v1/inventario/duplicados/fusionar", json={
            "pares": [{"muerto": muerto_id, "vivo": vivo.id}],
            "borrar_huerfanos_vacios": False,
        })

        self.assertEqual(r.status_code, 200)
        cuerpo = r.json()
        self.assertTrue(cuerpo["pares"][0]["ok"])
        self.assertEqual(cuerpo["resumen"]["fusionados"], 1)
        self.db.expire_all()
        self.assertFalse(self.existe(muerto_id))

    def test_borra_huerfanos_vacios_cuando_se_pide(self):
        self.como_admin()
        vacio = self.archivado("Muffin Mora")
        vacio_id = vacio.id

        r = self.client.post("/api/v1/inventario/duplicados/fusionar", json={
            "pares": [], "borrar_huerfanos_vacios": True,
        })

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["resumen"]["huerfanos_borrados"], 1)
        self.db.expire_all()
        self.assertFalse(self.existe(vacio_id))


# ─────────────────────────────────────────────────────────────────────────────
# El descubrimiento del mapeo: la lista NO está tipeada a mano
# ─────────────────────────────────────────────────────────────────────────────

class DescubrimientoTest(FusionDuplicadosBase):
    def test_descubre_las_columnas_y_los_uniques_del_mapeo(self):
        refs = svc.referencias()
        nombres = {f"{c.__tablename__}.{col}" for c, col in refs}
        for esperada in ("ticket_items.producto_id", "notas_credito_items.producto_id",
                         "producto_insumos.insumo_id", "productos.sustituto_id",
                         "producto_aliases.producto_id"):
            self.assertIn(esperada, nombres)
        uniques = {c.__tablename__ for c, _ in svc.uniques_con_producto()}
        self.assertEqual(uniques, {"inventario", "producto_insumos", "producto_desechables",
                                   "combos", "combo_opcion_productos", "conteo_verificaciones"})

    def test_toda_tabla_con_unique_tiene_una_estrategia_decidida(self):
        """Si mañana alguien agrega un único nuevo con producto_id, este test cae:
        la estrategia se decide a mano, nunca por defecto."""
        for cls, _ in svc.uniques_con_producto():
            self.assertIn(cls.__tablename__, svc.ESTRATEGIA_CHOQUE,
                          f"{cls.__tablename__} no tiene estrategia de choque decidida")

    def test_el_script_del_dry_run_usa_el_mismo_servicio(self):
        import scripts.fusionar_duplicados_dryrun as script
        self.assertIs(script.referencias, svc.referencias)
        self.assertIs(script.uniques_con_producto, svc.uniques_con_producto)
        self.assertIs(script.norm, svc.norm)
        self.assertIs(script.es_archivado, svc.es_archivado)
        self.assertIs(script.parejas, svc.parejas)


class ComboOpcionesTest(FusionDuplicadosBase):
    def test_membresia_repetida_en_una_opcion_se_borra(self):
        vivo = self.vivo("Torta de Chocolate")
        muerto = self.archivado("Torta Chocolate")
        sombra = self.archivado("Combo 03", categoria=CategoriaProductoEnum.bebida)
        combo = Combo(nombre="Combo 03", precio_venta=20000, activo=True,
                      orden=0, producto_id=sombra.id)
        self.db.add(combo)
        self.db.flush()
        grupo = ComboGrupo(combo_id=combo.id, nombre="Torta", orden=0)
        self.db.add(grupo)
        self.db.flush()
        opcion = ComboOpcion(grupo_id=grupo.id, nombre="Chocolate", orden=0)
        self.db.add(opcion)
        self.db.flush()
        self.db.add_all([
            ComboOpcionProducto(opcion_id=opcion.id, producto_id=vivo.id, cantidad=1),
            ComboOpcionProducto(opcion_id=opcion.id, producto_id=muerto.id, cantidad=1),
        ])
        self.db.commit()

        out = svc.fusionar_par(self.db, muerto.id, vivo.id, self.admin.id)

        self.assertTrue(out["ok"], out.get("error"))
        self.db.expire_all()
        filas = self.db.query(ComboOpcionProducto).all()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0].producto_id, vivo.id)


if __name__ == "__main__":
    unittest.main()


class StockSinContarTest(FusionDuplicadosBase):
    """La guarda que el crítico encontró rota: era ASIMÉTRICA.

    Solo abortaba si el VIVO ya tenía casillero en esa sede. En el caso
    contrario —el vivo sin fila— la fila del archivado CON STOCK se re-apuntaba
    y el vivo heredaba mercancía que nadie contó, con el plan diciendo
    `seguro: true` y sin una palabra de stock. No era teórico: en la base real
    hay archivados con 6, 10, 15 y 17 unidades, y el destino no tenía fila.
    """

    def test_stock_del_archivado_bloquea_aunque_el_vivo_no_tenga_casillero(self):
        muerto = self.archivado("Muffin Naranja")
        vivo = self.vivo("Muffin de Naranja")
        # El archivado tiene 10 unidades; el vivo NO tiene fila en esa sede.
        self.inv(muerto, self.t1, stock=10)

        pl = svc.plan(self.db)
        par = next(f for f in pl["fusionables"] if f["muerto"]["id"] == muerto.id)
        self.assertFalse(par["seguro"], "un archivado con stock no puede ser «seguro»")
        self.assertTrue(any("stock 10" in b for b in par["bloqueos"]),
                        f"el bloqueo tiene que decir el stock: {par['bloqueos']}")

    def test_el_ejecutor_tambien_lo_frena_y_no_mueve_nada(self):
        """El plan y el ejecutor validan por separado: el stock pudo cambiar
        entre que el admin miró la pantalla y apretó el botón."""
        muerto = self.archivado("Alfajor viejo")
        vivo = self.vivo("Alfajor")
        self.inv(muerto, self.t1, stock=15)

        r = svc.fusionar(self.db, [{"muerto": muerto.id, "vivo": vivo.id}],
                         borrar_huerfanos_vacios=False, usuario_id=None)
        par = r["pares"][0]
        self.assertFalse(par["ok"])
        self.assertIn("stock 15", par["error"])
        # Y el archivado sigue existiendo, con su stock intacto.
        self.assertTrue(self.existe(muerto.id))
        inv = self.db.query(Inventario).filter_by(producto_id=muerto.id).first()
        self.assertEqual(15, inv.stock_actual)

    def test_con_stock_en_cero_si_fusiona(self):
        """El caso legítimo: casillero vacío, no es mercancía."""
        muerto = self.archivado("Brownie viejo")
        vivo = self.vivo("Brownie")
        self.inv(muerto, self.t1, stock=0)
        # El id se guarda ANTES: tras la fusión la instancia está borrada y
        # tocar muerto.id levanta ObjectDeletedError.
        muerto_id = muerto.id

        r = svc.fusionar(self.db, [{"muerto": muerto_id, "vivo": vivo.id}],
                         borrar_huerfanos_vacios=False, usuario_id=None)
        self.assertTrue(r["pares"][0]["ok"], r["pares"][0].get("error"))
        self.assertFalse(self.existe(muerto_id))
