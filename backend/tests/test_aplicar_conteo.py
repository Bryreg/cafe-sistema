"""Aplicar un conteo no puede borrar lo que se vendió mientras tanto.

El conteo dice la verdad DEL INSTANTE en que se contó. Entre ese instante y el
clic de «Aplicar» el local no se detiene. La versión vieja escribía
`stock = lo contado` a secas, y con eso el saldo volvía a antes de las ventas del
medio: los movimientos seguían en el libro pero el stock los ignoraba.

Pasó de verdad y está medido. Conteo #348 de Palmetto, 18 de agosto: contado a
las 13:07, aplicado a las 15:42. En esas 2 h 35 se vendió un Granizado Caramelo
16oz —145 gr de mezcla y 30 gr de salsa— y tres baristas se sirvieron café.
Aplicar el conteo devolvió el stock al valor de las 13:07 y esos consumos
desaparecieron del saldo. El inventario quedó ALTO, y en el conteo siguiente esa
misma cantidad reapareció como FALTANTE: el sistema acusando de robo algo que se
vendió, se anotó y se cobró.

La cuenta correcta suma las dos fuentes en vez de dejar que una pise a la otra:

    stock = lo contado + (lo que entró − lo que salió DESDE el conteo)

Lo que fijan estos tests:

- LO DEL MEDIO SOBREVIVE. Es el caso que motivó el arreglo.
- UN AJUSTE POSTERIOR MANDA. Si alguien ya volvió a anclar el producto al físico
  después del conteo, ese dato es más nuevo: pisarlo con el conteo viejo sería
  deshacer una corrección buena. Se salta, y se DICE cuál.
- APLICAR DOS VECES NO REBOBINA. Sin candado, la segunda pasada se llevaba puesto
  todo lo vendido desde la primera, sin romper nada visible.
- SIN HUECO, EL RESULTADO ES EL DE SIEMPRE. El arreglo no puede cambiar el caso
  normal (contar y aplicar en el momento), que es el 5 de los 7 conteos reales.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CategoriaProductoEnum, CajaTurno, ConteoFisico,
                               ConteoFisicoItem, EstadoTurnoEnum, Inventario,
                               MovimientoInventario, Producto, RolEnum,
                               Tienda, TipoConteoEnum, TipoMovInvEnum, Usuario)
from app.services import conteos as svc


class AplicarConteoBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t = Tienda(nombre="Palmetto", direccion="x", activa=True)
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.turno = CajaTurno(tienda_id=self.t.id, usuario_apertura_id=self.admin.id,
                               estado=EstadoTurnoEnum.abierto, base_real=0)
        self.db.add(self.turno)
        self.db.commit()
        self.ahora = datetime.utcnow()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── fixtures ─────────────────────────────────────────────────────────────
    def producto(self, nombre, stock, unidad="gr"):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=True, precio_venta=0.0)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.t.id,
                               stock_actual=stock, stock_minimo=0))
        self.db.commit()
        return p

    def conteo(self, items, hace_horas=2.6):
        """Un conteo registrado hace `hace_horas`. items: [(producto, contado)]."""
        c = ConteoFisico(tienda_id=self.t.id, turno_id=self.turno.id,
                         tipo=TipoConteoEnum.apertura, usuario_id=self.admin.id,
                         fecha_registro=self.ahora - timedelta(hours=hace_horas))
        self.db.add(c)
        self.db.flush()
        for p, real in items:
            inv = self.db.query(Inventario).filter_by(
                producto_id=p.id, tienda_id=self.t.id).first()
            self.db.add(ConteoFisicoItem(
                conteo_id=c.id, producto_id=p.id,
                cantidad_sistema=inv.stock_actual, cantidad_real=real,
                diferencia=real - inv.stock_actual))
        self.db.commit()
        return c

    def mov(self, producto, tipo, cantidad, motivo, hace_horas):
        """Un movimiento REAL: mueve el stock igual que el flujo que lo genera."""
        inv = self.db.query(Inventario).filter_by(
            producto_id=producto.id, tienda_id=self.t.id).first()
        if tipo == "entrada":
            inv.stock_actual += cantidad
        elif tipo == "salida":
            inv.stock_actual -= cantidad
        else:
            inv.stock_actual = cantidad
        self.db.add(MovimientoInventario(
            producto_id=producto.id, tienda_id=self.t.id, tipo=tipo,
            cantidad=cantidad, motivo=motivo, usuario_id=self.admin.id,
            fecha=self.ahora - timedelta(hours=hace_horas)))
        self.db.commit()

    def stock(self, producto):
        return self.db.query(Inventario).filter_by(
            producto_id=producto.id, tienda_id=self.t.id).first().stock_actual


class LoDelMedioSobreviveTest(AplicarConteoBase):

    def test_la_venta_entre_el_conteo_y_su_aplicacion_no_se_borra(self):
        # El caso real: mezcla contada en 4.730 a las 13:07; a las 14:51 se vende
        # un granizado que consume 145 gr; se aplica a las 15:42.
        mezcla = self.producto("MEZCLA GRANIZADO (preparada)", stock=680)
        c = self.conteo([(mezcla, 4730)], hace_horas=2.6)
        self.mov(mezcla, "salida", 145,
                 "Venta POS — insumo de Granizado Caramelo 16oz", hace_horas=0.9)

        out = svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)

        # 4.730 contados menos los 145 que salieron después: NO 4.730.
        self.assertEqual(self.stock(mezcla), 4585)
        self.assertEqual(out["ajustados"], 1)

    def test_varias_salidas_y_una_entrada_se_netean(self):
        cafe = self.producto("Cafe Alta Tostion x2500", stock=10080)
        c = self.conteo([(cafe, 10660)], hace_horas=3)
        self.mov(cafe, "salida", 10, "Consumo (Ana)", hace_horas=2)
        self.mov(cafe, "salida", 10, "Consumo (Brayan)", hace_horas=1.5)
        self.mov(cafe, "entrada", 2500, "Factura #77 — Cafexcoop", hace_horas=1)

        svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.assertEqual(self.stock(cafe), 10660 - 20 + 2500)

    def test_lo_anterior_al_conteo_no_se_cuenta_dos_veces(self):
        # La barista ya vio ese movimiento cuando contó: sumarlo sería duplicarlo.
        cafe = self.producto("CAFE", stock=1000)
        self.mov(cafe, "salida", 200, "Venta POS", hace_horas=5)
        c = self.conteo([(cafe, 800)], hace_horas=3)

        svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.assertEqual(self.stock(cafe), 800)

    def test_el_saldo_no_queda_negativo(self):
        # Si lo movido se lleva más de lo contado, el piso es cero: un stock
        # negativo no es una corrección, es otro número falso.
        pulpa = self.producto("PULPA DE MORA", stock=10, unidad="und")
        c = self.conteo([(pulpa, 2)], hace_horas=2)
        self.mov(pulpa, "salida", 5, "Venta POS", hace_horas=1)

        svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.assertEqual(self.stock(pulpa), 0)


class UnAjustePosteriorMandaTest(AplicarConteoBase):

    def test_un_producto_ya_ajustado_despues_del_conteo_no_se_toca(self):
        # Alguien ya volvió a anclar el producto al físico DESPUÉS del conteo.
        # Ese dato es más nuevo: pisarlo con el conteo viejo desharía una
        # corrección buena.
        cafe = self.producto("CAFE", stock=1000)
        c = self.conteo([(cafe, 5000)], hace_horas=4)
        self.mov(cafe, "ajuste", 3200, "Verificación de conteo aprobada (conteo #9)",
                 hace_horas=1)

        out = svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)

        self.assertEqual(self.stock(cafe), 3200)
        self.assertEqual(out["ajustados"], 0)
        # Y se DICE cuál se saltó: un silencio acá deja al dueño creyendo que su
        # conteo entró entero.
        self.assertEqual(out["protegidos"], ["CAFE"])

    def test_los_demas_productos_del_conteo_si_se_aplican(self):
        cafe = self.producto("CAFE", stock=1000)
        leche = self.producto("LECHE", stock=500, unidad="ml")
        c = self.conteo([(cafe, 5000), (leche, 900)], hace_horas=4)
        self.mov(cafe, "ajuste", 3200, "Inventario mensual 08/2026 aplicado", hace_horas=1)

        out = svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)

        self.assertEqual(self.stock(cafe), 3200)     # protegido
        self.assertEqual(self.stock(leche), 900)     # aplicado
        self.assertEqual(out["protegidos"], ["CAFE"])
        self.assertEqual(out["ajustados"], 1)

    def test_un_ajuste_ANTERIOR_al_conteo_no_protege_nada(self):
        # Solo lo posterior al conteo es más nuevo que el conteo.
        cafe = self.producto("CAFE", stock=1000)
        self.mov(cafe, "ajuste", 1000, "Conteo #3 aplicado al inventario", hace_horas=6)
        c = self.conteo([(cafe, 800)], hace_horas=3)

        out = svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.assertEqual(self.stock(cafe), 800)
        self.assertEqual(out["protegidos"], [])


class AplicarDosVecesTest(AplicarConteoBase):

    def test_el_segundo_intento_se_rechaza(self):
        cafe = self.producto("CAFE", stock=1000)
        c = self.conteo([(cafe, 800)], hace_horas=1)
        svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)

        with self.assertRaises(HTTPException) as cm:
            svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("ya se aplicó", cm.exception.detail)

    def test_lo_vendido_despues_de_la_primera_pasada_no_se_rebobina(self):
        # Sin candado, la segunda pasada se llevaba puesto todo lo vendido desde
        # la primera. Nada se rompía, y ese era el problema.
        cafe = self.producto("CAFE", stock=1000)
        c = self.conteo([(cafe, 800)], hace_horas=2)
        svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.mov(cafe, "salida", 300, "Venta POS", hace_horas=0)
        self.assertEqual(self.stock(cafe), 500)

        with self.assertRaises(HTTPException):
            svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.assertEqual(self.stock(cafe), 500)

    def test_queda_marcado_con_la_fecha(self):
        cafe = self.producto("CAFE", stock=1000)
        c = self.conteo([(cafe, 800)], hace_horas=1)
        self.assertIsNone(c.fecha_aplicado)
        svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.db.refresh(c)
        self.assertIsNotNone(c.fecha_aplicado)


class ElCasoNormalNoCambiaTest(AplicarConteoBase):
    """5 de los 7 conteos reales se aplicaron en minutos. Ese camino es el común
    y el arreglo no puede moverlo."""

    def test_sin_movimientos_en_el_medio_el_stock_queda_en_lo_contado(self):
        cafe = self.producto("CAFE", stock=1000)
        leche = self.producto("LECHE", stock=500, unidad="ml")
        c = self.conteo([(cafe, 820), (leche, 480)], hace_horas=0.1)

        out = svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.assertEqual(self.stock(cafe), 820)
        self.assertEqual(self.stock(leche), 480)
        self.assertEqual(out["ajustados"], 2)
        self.assertEqual(out["protegidos"], [])

    def test_un_producto_que_ya_coincide_no_genera_movimiento(self):
        cafe = self.producto("CAFE", stock=1000)
        c = self.conteo([(cafe, 1000)], hace_horas=0.1)

        out = svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)
        self.assertEqual(out["ajustados"], 0)
        self.assertEqual(out["sin_cambio"], 1)
        self.assertEqual(
            self.db.query(MovimientoInventario).filter(
                MovimientoInventario.tipo == TipoMovInvEnum.ajuste).count(), 0)

    def test_el_motivo_sigue_siendo_el_que_la_escalera_reconoce(self):
        # `conciliacion._bucket` clasifica por el prefijo «Conteo #». Si cambiara,
        # estos ajustes caerían al cajón de sastre y la pantalla los mostraría
        # como movimiento sin causa.
        from app.services.conciliacion import _bucket
        cafe = self.producto("CAFE", stock=1000)
        c = self.conteo([(cafe, 800)], hace_horas=0.1)
        svc.aplicar_conteo_inventario(self.db, c.id, self.admin.id)

        m = self.db.query(MovimientoInventario).filter(
            MovimientoInventario.tipo == TipoMovInvEnum.ajuste).one()
        self.assertEqual(_bucket("ajuste", m.motivo), "ajustes_conteo")


if __name__ == "__main__":
    unittest.main()
