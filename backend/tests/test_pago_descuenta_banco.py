"""El pago que descuenta del banco en la MISMA transacción, y la puerta muerta.

Dos arreglos del mismo endpoint (POST /costos/pagos):

1. `factura_id` era una puerta que no llevaba a ninguna parte: creaba la fila
   Pago pero jamás tocaba `FacturaCompra.valor_pagado` — la factura seguía
   debiendo lo mismo en la agenda y en todas las pantallas, con el pago
   invisible. Ahora contesta 400 con el motivo y la salida nombrada.

2. «Y descontalo del banco» eran DOS escrituras del frontend (el pago y después
   el movimiento): si la segunda fallaba, el vencimiento quedaba tachado y el
   saldo del banco no bajaba. Ahora `descontar_banco` + `cuenta_id` crean el
   movimiento DENTRO de la transacción del pago: o entran los dos, o ninguno.
   La respuesta trae SIEMPRE `movimiento_banco_id` (número si lo creó, null si
   no se pidió): la clave ausente es la señal de servidor viejo para que el
   cliente caiga al camino de las dos escrituras.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import hoy_col
from app.database import Base
from app.models.models import (CostoCategoria, CuentaBancaria, MovimientoBanco,
                               Obligacion, Pago, RolEnum, Tienda, Usuario)
from app.schemas.costos import PagoCreate
from app.services import costos as svc


class PagoBancoBase(unittest.TestCase):
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
        self.occidente = CuentaBancaria(nombre="Occidente", orden=1, activa=True)
        self.db.add_all([self.admin, self.occidente])
        self.db.commit()

        svc.sembrar_categorias(self.db)
        self.cat = self.db.query(CostoCategoria).filter_by(clave="arriendo").first()
        self.hoy = hoy_col()

        self.obligacion = Obligacion(
            tienda_id=self.vida.id, categoria_id=self.cat.id,
            concepto="Arriendo Vida", monto=4_292_453,
            fecha_devengo=self.hoy.replace(day=1), usuario_id=self.admin.id)
        self.db.add(self.obligacion)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def pagar(self, **campos):
        base = dict(obligacion_id=self.obligacion.id, monto=4_292_453,
                    fecha_pago=self.hoy, metodo="transferencia")
        base.update(campos)
        return svc.registrar_pago(self.db, PagoCreate(**base), self.admin.id)


class DescuentoAtomicoTest(PagoBancoBase):

    def test_el_pago_y_la_salida_nacen_juntos_y_enlazados(self):
        r = self.pagar(descontar_banco=True, cuenta_id=self.occidente.id)

        movs = self.db.query(MovimientoBanco).all()
        self.assertEqual(len(movs), 1)
        m = movs[0]
        self.assertEqual(m.tipo, "salida")
        self.assertEqual(float(m.monto), 4_292_453)
        self.assertEqual(m.fecha, self.hoy)
        self.assertEqual(m.cuenta_id, self.occidente.id)
        # El enlace: la agenda usa obligacion_id para no contar la deuda dos
        # veces (cubierto_de combina pago y banco por MÁXIMO).
        self.assertEqual(m.obligacion_id, self.obligacion.id)
        self.assertEqual(m.concepto, "Arriendo Vida")
        # Y la respuesta lo dice, para que el cliente sepa que no hace falta la
        # segunda escritura.
        self.assertEqual(r["movimiento_banco_id"], m.id)

    def test_sin_descontar_la_clave_viaja_igual_con_null(self):
        """La CLAVE presente con null distingue «no lo pedí» de «el servidor no
        conoce el campo»: ausente no es vacío, y el cliente decide con eso."""
        r = self.pagar()
        self.assertIn("movimiento_banco_id", r)
        self.assertIsNone(r["movimiento_banco_id"])
        self.assertEqual(self.db.query(MovimientoBanco).count(), 0)

    def test_una_cuenta_inexistente_no_deja_el_pago_a_medias(self):
        """La atomicidad es el punto entero: si el movimiento no puede nacer,
        el pago tampoco — el estado de antes de las dos escrituras era
        exactamente el vencimiento tachado con el saldo sin bajar."""
        with self.assertRaises(HTTPException) as ctx:
            self.pagar(descontar_banco=True, cuenta_id=99999)
        self.assertEqual(ctx.exception.status_code, 400)

        self.db.rollback()
        self.assertEqual(self.db.query(Pago).count(), 0)
        self.assertEqual(self.db.query(MovimientoBanco).count(), 0)

    def test_descontar_con_efectivo_rebota(self):
        """El efectivo sale del cajón o de la mano: meterlo al libro escribiría
        una salida que el extracto nunca va a tener."""
        with self.assertRaises(HTTPException) as ctx:
            self.pagar(metodo="efectivo", descontar_banco=True,
                       cuenta_id=self.occidente.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("cajón", ctx.exception.detail)

    def test_descontar_con_fecha_futura_rebota(self):
        with self.assertRaises(HTTPException) as ctx:
            self.pagar(fecha_pago=self.hoy + timedelta(days=1),
                       descontar_banco=True, cuenta_id=self.occidente.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("futura", ctx.exception.detail)

    def test_descontar_sin_cuenta_rebota(self):
        with self.assertRaises(HTTPException) as ctx:
            self.pagar(descontar_banco=True)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("cuenta", ctx.exception.detail.lower())

    def test_el_pago_sin_descuento_sigue_intacto(self):
        """El camino de siempre no cambia: el pago tacha el vencimiento y el
        libro no se toca — ese es el default, dicho en el propio formulario."""
        r = self.pagar()
        self.assertEqual(r["monto"], 4_292_453)
        pagos = self.db.query(Pago).all()
        self.assertEqual(len(pagos), 1)
        self.assertFalse(pagos[0].anulado)


class PuertaMuertaDeFacturaTest(PagoBancoBase):

    def test_factura_id_contesta_400_con_la_salida_nombrada(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.registrar_pago(self.db, PagoCreate(
                factura_id=123, monto=50_000, fecha_pago=self.hoy,
                metodo="efectivo"), self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)
        detalle = ctx.exception.detail
        self.assertIsInstance(detalle, str)
        # El motivo (la tabla que el saldo no lee) y la salida (su propia fila).
        self.assertIn("no lee", detalle)
        self.assertIn("Lo que baja el margen", detalle)
        self.db.rollback()
        self.assertEqual(self.db.query(Pago).count(), 0)

    def test_sin_obligacion_ni_factura_tambien_rebota(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.registrar_pago(self.db, PagoCreate(
                monto=50_000, fecha_pago=self.hoy), self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
