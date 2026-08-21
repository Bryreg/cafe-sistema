"""Los cuatro `if turno_activo:` sin else, cerrados.

El agujero medido: pagar una factura en efectivo SIN turno abierto actualizaba
`valor_pagado` pero la salida física de la plata no quedaba en NINGUNA parte —
ni cajón ni mano—. Le pasa justamente al admin, que está exento de turno: la
plata salía en la vida real y el sistema no se enteraba.

La regla que cierra las cuatro ramas:

- PAGAR sin turno abierto se registra en la MANO del dueño (`Pago` con método
  "efectivo", la fila que `_efectivo_en_mano` ya resta). Es el único origen
  físico posible: el cajón cerrado ya se contó, y si él lo toca igual, el cuadre
  de apertura siguiente lo detecta como faltante — ese candado ya existe.
- REVERTIR o CORREGIR algo que necesita mover el cajón, sin turno abierto,
  REBOTA con 400 legible: esas operaciones pueden esperar a que haya turno, y
  dejarlas pasar a medias corría el cuadre en silencio.
- La forma queda dicha en la factura («efectivo (de tu mano)») y ese valor está
  FUERA de ("efectivo", "contado") a propósito: la reconciliación de caja de
  `editar_factura` compara contra ese par, y un pago que nunca tocó el cajón no
  puede generarle reembolsos fantasma.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col, inicio_dia_col_utc
from app.database import Base
from app.models.models import (CajaTurno, CategoriaProductoEnum, EstadoTurnoEnum,
                               MovimientoCaja, Pago, Producto, RecogidaEfectivo,
                               RolEnum, Tienda, Usuario)
from app.services import costos as costos_svc
from app.services import facturas as fac
from app.services.costos import fijar_desde_recogidas
from app.services.facturas import FORMA_EFECTIVO_MANO


class FacturasSinTurnoBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.vida)
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.prod = Producto(nombre="Leche entera", categoria=CategoriaProductoEnum.bebida,
                             unidad_medida="unidad", controla_stock=True)
        self.db.add(self.prod)
        self.db.commit()
        self.hoy = hoy_col()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def turno_abierto(self) -> CajaTurno:
        t = CajaTurno(tienda_id=self.vida.id, usuario_apertura_id=self.admin.id,
                      base_real=0, estado=EstadoTurnoEnum.abierto)
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)
        return t

    def cerrar(self, t: CajaTurno):
        t.estado = EstadoTurnoEnum.cerrado
        t.fecha_cierre = inicio_dia_col_utc(self.hoy) + timedelta(hours=18)
        self.db.commit()

    def factura(self, tipo_pago="contado", valor=100000):
        data = SimpleNamespace(
            tipo_pago=tipo_pago,
            items=[SimpleNamespace(producto_id=self.prod.id, cantidad=10,
                                   precio_unitario=valor / 10, numero_lote=None,
                                   fecha_vencimiento=None)],
            valor_total=valor, tienda_id=self.vida.id, proveedor="Lácteos Andina",
            numero_factura="F-1", numero_lote=None, fecha_recibido=date.today(),
        )
        return fac.crear_factura(self.db, data, None, self.admin.id)

    def regimen_de_recogidas(self, monto=1_000_000):
        """La mano existe: hay régimen y una pasada registrada."""
        r = RecogidaEfectivo(tienda_id=self.vida.id, fecha=self.hoy, monto=monto,
                             usuario_id=self.admin.id)
        self.db.add(r)
        fijar_desde_recogidas(self.db, self.hoy)
        self.db.commit()

    def movimientos_caja(self):
        return self.db.query(MovimientoCaja).all()

    def pagos(self):
        return self.db.query(Pago).all()


class PagarSinTurnoTest(FacturasSinTurnoBase):

    def test_contado_sin_turno_sale_de_la_mano_no_del_silencio(self):
        """El caso del agujero, por el camino del alta."""
        f = self.factura(tipo_pago="contado", valor=400000)

        # La factura queda pagada, como siempre (contado se paga al recibir)...
        self.assertEqual(float(f.valor_pagado), 400000)
        # ...pero ahora la salida FÍSICA quedó registrada: un pago desde la mano.
        pagos = self.pagos()
        self.assertEqual(len(pagos), 1)
        self.assertEqual(pagos[0].factura_id, f.id)
        self.assertEqual(pagos[0].metodo, "efectivo")
        self.assertEqual(pagos[0].fecha_pago, self.hoy)
        self.assertIsNone(pagos[0].movimiento_caja_id)
        # Y ningún egreso de un cajón que no existía.
        self.assertEqual(self.movimientos_caja(), [])
        self.assertEqual(f.forma_pago_real, FORMA_EFECTIVO_MANO)

    def test_el_pago_desde_la_mano_baja_la_mano(self):
        """La cadena completa contra la fórmula real de la tercera bolsa."""
        self.regimen_de_recogidas(1_000_000)
        self.factura(tipo_pago="contado", valor=400000)

        mano = costos_svc._efectivo_en_mano(self.db)
        self.assertEqual(mano["monto"], 600000)

    def test_contado_con_turno_sigue_saliendo_del_cajon(self):
        """La rama vieja no cambia: con turno abierto el egreso va al cajón y
        NO se duplica en la mano."""
        self.turno_abierto()
        f = self.factura(tipo_pago="contado", valor=400000)

        movs = self.movimientos_caja()
        self.assertEqual(len(movs), 1)
        self.assertEqual(movs[0].tipo, "egreso")
        self.assertEqual(float(movs[0].valor), 400000)
        self.assertEqual(self.pagos(), [])
        self.assertEqual(f.forma_pago_real, "contado")

    def test_pago_explicito_en_efectivo_sin_turno_tambien_va_a_la_mano(self):
        """El mismo agujero por el otro camino: PATCH /facturas/{id}/pago."""
        f = self.factura(tipo_pago="credito", valor=500000)
        self.assertEqual(float(f.valor_pagado or 0), 0)

        fac.registrar_pago(self.db, f.id, 200000, "efectivo", None, self.admin.id)

        pagos = self.pagos()
        self.assertEqual(len(pagos), 1)
        self.assertEqual(float(pagos[0].monto), 200000)
        self.assertEqual(self.movimientos_caja(), [])
        self.db.refresh(f)
        self.assertEqual(float(f.valor_pagado), 200000)
        self.assertEqual(f.forma_pago_real, FORMA_EFECTIVO_MANO)

    def test_pago_por_transferencia_sin_turno_no_inventa_nada(self):
        """Una transferencia nunca tocó el cajón ni la mano: sin turno o con
        turno da igual, no se fabrica ninguna salida de efectivo."""
        f = self.factura(tipo_pago="credito", valor=500000)
        fac.registrar_pago(self.db, f.id, 200000, "transferencia", None, self.admin.id)
        self.assertEqual(self.pagos(), [])
        self.assertEqual(self.movimientos_caja(), [])


class RevertirYCorregirSinTurnoTest(FacturasSinTurnoBase):

    def _factura_pagada_en_turno_cerrado(self):
        t = self.turno_abierto()
        f = self.factura(tipo_pago="contado", valor=300000)
        self.cerrar(t)
        return f

    def test_eliminar_sin_turno_rebota_y_no_deja_nada_a_medias(self):
        f = self._factura_pagada_en_turno_cerrado()
        stock_antes = 10.0

        with self.assertRaises(HTTPException) as ctx:
            fac.eliminar_factura(self.db, f.id, self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIsInstance(ctx.exception.detail, str)
        self.assertIn("turno abierto", ctx.exception.detail)

        # Nada quedó a medias: la factura sigue viva y el inventario intacto.
        self.db.rollback()
        from app.models.models import FacturaCompra, Inventario
        self.assertIsNotNone(self.db.get(FacturaCompra, f.id))
        inv = self.db.query(Inventario).filter_by(
            producto_id=self.prod.id, tienda_id=self.vida.id).first()
        self.assertEqual(float(inv.stock_actual), stock_antes)

    def test_eliminar_con_turno_abierto_compensa_como_siempre(self):
        f = self._factura_pagada_en_turno_cerrado()
        self.turno_abierto()   # hay a dónde devolver la plata

        r = fac.eliminar_factura(self.db, f.id, self.admin.id)
        self.assertEqual(r["egresos_revertidos"], 300000)
        ingresos = [m for m in self.movimientos_caja() if m.tipo == "ingreso"]
        self.assertEqual(len(ingresos), 1)
        self.assertEqual(float(ingresos[0].valor), 300000)

    def test_eliminar_anula_los_pagos_y_la_mano_se_recompone(self):
        """Compra pagada de la mano que resultó no existir: borrarla tiene que
        devolverle la plata a la mano — anulando el pago, no borrándolo."""
        self.regimen_de_recogidas(1_000_000)
        f = self.factura(tipo_pago="contado", valor=400000)
        self.assertEqual(costos_svc._efectivo_en_mano(self.db)["monto"], 600000)

        r = fac.eliminar_factura(self.db, f.id, self.admin.id)

        self.assertEqual(r["pagos_anulados"], 1)
        self.assertTrue(all(p.anulado for p in self.pagos()))
        self.assertEqual(costos_svc._efectivo_en_mano(self.db)["monto"], 1_000_000)

    def test_corregir_el_pago_sin_turno_rebota_legible(self):
        """contado→transferencia devuelve plata al cajón; sin turno no hay cajón
        y la corrección entera espera."""
        f = self._factura_pagada_en_turno_cerrado()

        with self.assertRaises(HTTPException) as ctx:
            fac.editar_factura(self.db, f.id, self.admin.id, tipo_pago="transferencia")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("300,000", ctx.exception.detail)
        self.assertIn("turno abierto", ctx.exception.detail)

        self.db.rollback()
        from app.models.models import FacturaCompra
        self.assertEqual(self.db.get(FacturaCompra, f.id).tipo_pago.value,
                         "contado")

    def test_corregir_un_pago_de_la_mano_no_toca_el_cajon_y_recompone_la_mano(self):
        """La factura pagada de la mano se corrige a transferencia: el cajón no
        se compensa (nunca puso un peso) y el pago de la mano se anula — la
        plata vuelve a la bolsa de la que se afirmó que salió."""
        self.regimen_de_recogidas(1_000_000)
        f = self.factura(tipo_pago="contado", valor=400000)
        self.assertEqual(costos_svc._efectivo_en_mano(self.db)["monto"], 600000)

        # Sin turno abierto — y aun así la corrección pasa: no hay delta de cajón.
        fac.editar_factura(self.db, f.id, self.admin.id, tipo_pago="transferencia")

        self.assertEqual(self.movimientos_caja(), [])
        self.assertTrue(all(p.anulado for p in self.pagos()))
        self.assertEqual(costos_svc._efectivo_en_mano(self.db)["monto"], 1_000_000)


if __name__ == "__main__":
    unittest.main()
