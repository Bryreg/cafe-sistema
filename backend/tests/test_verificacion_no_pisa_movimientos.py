"""La verificación de conteo no puede borrar lo que pasó mientras tanto.

Es el mismo defecto que `test_aplicar_conteo` ya fijó para el conteo completo,
en el único camino que se había quedado sin la regla: la aprobación de una
verificación puntual.

QUÉ PASÓ DE VERDAD (1-sep-2026, medido en producción). El circuito de
verificación fue pensado para responder «¿cuánto hay?» y que esa respuesta sea
el stock. Bien pensado cuando se aprueba enseguida. Pero la pantalla de conteo
tiene un botón «Coincide» que copia el conteo anterior, con una premisa que es
cierta ALLÁ y falsa ACÁ: «copiar no puede esconder faltantes, si el producto se
movió el sistema ya lo descontó y la diferencia aparece sola». En la pantalla de
conteo sí —`registrar_conteo` solo registra y compara—. En la verificación no:
esa copia SE ESCRIBE como stock.

Vida, 1-sep: conteo de apertura 6:26 am; a las 8:12 se prepararon 3 tandas de
mezcla de granizado que se llevaron 900 gr de leche en polvo; a las 8:53 la
barista respondió la verificación con 1.664 —el mismo número de las 6:26— y a
las 8:55 el admin aprobó. El stock quedó en 1.664 cuando había 764. Palmetto, el
mismo día: 12 almojabanas contadas a las 8:37, una vendida a las 8:55, respuesta
de 12 a las 9:03 y aprobación a las 9:06.

LO QUE FIJAN ESTOS TESTS

- REPETIR EL CONTEO CUANDO HUBO MOVIMIENTO SE FRENA. No se prohíbe —el saldo
  puede haber vuelto al mismo número— pero deja de ser un tap: hay que afirmarlo
  con `confirmar_igual`.
- SIN MOVIMIENTO, REPETIR ES LEGÍTIMO. Es la premisa del botón «Coincide», y
  sigue valiendo cuando de verdad no pasó nada.
- LO VENDIDO ENTRE LA RESPUESTA Y LA APROBACIÓN SOBREVIVE.
- UN AJUSTE POSTERIOR MANDA: no se pisa un anclaje más nuevo.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CajaTurno, CategoriaProductoEnum, ConteoFisico,
                               ConteoFisicoItem, ConteoVerificacion, EstadoTurnoEnum,
                               Inventario, MovimientoInventario, Producto, RolEnum,
                               Tienda, TipoConteoEnum, TipoMovInvEnum, Usuario)
from app.services import conteos as svc


class VerificacionBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.tienda = Tienda(nombre="Vida")
        self.db.add(self.tienda)
        self.admin = Usuario(nombre="Admin", email="a@a.com", password_hash="x",
                             rol=RolEnum.admin)
        self.db.add(self.admin)
        self.db.flush()

        self.prod = Producto(nombre="LECHE EN POLVO", categoria=CategoriaProductoEnum.insumo,
                             unidad_medida="gr", controla_stock=True)
        self.db.add(self.prod)
        self.db.flush()

        self.inv = Inventario(producto_id=self.prod.id, tienda_id=self.tienda.id,
                              stock_actual=1250.0, stock_minimo=0.0)
        self.db.add(self.inv)

        self.turno = CajaTurno(tienda_id=self.tienda.id, usuario_apertura_id=self.admin.id,
                               estado=EstadoTurnoEnum.abierto, base_real=0)
        self.db.add(self.turno)
        self.db.flush()

        self.conteo_en = datetime(2026, 9, 1, 11, 26)   # 6:26 am Colombia
        self.conteo = ConteoFisico(tienda_id=self.tienda.id, turno_id=self.turno.id,
                                   tipo=TipoConteoEnum.apertura,
                                   usuario_id=self.admin.id, fecha_registro=self.conteo_en)
        self.db.add(self.conteo)
        self.db.flush()
        self.db.add(ConteoFisicoItem(conteo_id=self.conteo.id, producto_id=self.prod.id,
                                     cantidad_sistema=1250.0, cantidad_real=1664.0,
                                     diferencia=414.0))
        self.verif = ConteoVerificacion(
            tienda_id=self.tienda.id, conteo_id=self.conteo.id, producto_id=self.prod.id,
            estado="solicitada", cantidad_sistema=1250.0, cantidad_conteo=1664.0,
            solicitada_por_id=self.admin.id,
            fecha_solicitud=self.conteo_en + timedelta(hours=2, minutes=22))
        self.db.add(self.verif)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        os.unlink(self.db_path)

    def mover(self, tipo: str, cantidad: float, cuando: datetime):
        self.db.add(MovimientoInventario(
            producto_id=self.prod.id, tienda_id=self.tienda.id,
            tipo=TipoMovInvEnum(tipo), cantidad=cantidad, fecha=cuando,
            usuario_id=self.admin.id, motivo="test"))
        if tipo == "entrada":
            self.inv.stock_actual = float(self.inv.stock_actual) + cantidad
        elif tipo == "salida":
            self.inv.stock_actual = float(self.inv.stock_actual) - cantidad
        else:
            self.inv.stock_actual = cantidad
        self.db.commit()


class RepetirElConteo(VerificacionBase):
    def test_repetir_el_conteo_con_movimiento_en_el_medio_se_frena(self):
        """El caso de Vida: se preparó granizado y la respuesta copia las 6:26."""
        self.mover("salida", 900.0, self.conteo_en + timedelta(hours=1, minutes=46))

        with self.assertRaises(HTTPException) as ctx:
            svc.responder_verificacion(self.db, self.verif.id, 1664.0, None, self.admin.id)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("900", str(ctx.exception.detail))
        self.db.refresh(self.verif)
        self.assertEqual(self.verif.estado, "solicitada")

    def test_confirmando_se_acepta(self):
        """No se prohíbe: se exige afirmarlo. La barista puede tener razón."""
        self.mover("salida", 900.0, self.conteo_en + timedelta(hours=1, minutes=46))
        svc.responder_verificacion(self.db, self.verif.id, 1664.0, None, self.admin.id,
                                   confirmar_igual=True)
        self.db.refresh(self.verif)
        self.assertEqual(self.verif.estado, "respondida")
        self.assertEqual(self.verif.cantidad_verificada, 1664.0)

    def test_sin_movimiento_repetir_es_legitimo(self):
        """La premisa del botón «Coincide» sigue valiendo donde es cierta."""
        svc.responder_verificacion(self.db, self.verif.id, 1664.0, None, self.admin.id)
        self.db.refresh(self.verif)
        self.assertEqual(self.verif.estado, "respondida")

    def test_un_numero_distinto_nunca_se_frena(self):
        """Recontar de verdad y dar otro número es el camino normal."""
        self.mover("salida", 900.0, self.conteo_en + timedelta(hours=1, minutes=46))
        svc.responder_verificacion(self.db, self.verif.id, 764.0, None, self.admin.id)
        self.db.refresh(self.verif)
        self.assertEqual(self.verif.cantidad_verificada, 764.0)


class AprobarNoPisaLoDelMedio(VerificacionBase):
    def responder(self, cantidad: float, cuando: datetime):
        svc.responder_verificacion(self.db, self.verif.id, cantidad, None, self.admin.id,
                                   confirmar_igual=True)
        self.verif.fecha_respuesta = cuando
        self.db.commit()

    def test_lo_vendido_entre_respuesta_y_aprobacion_sobrevive(self):
        """El caso de Palmetto, en gramos: 764 recontados, 30 vendidos, aprobar
        no puede devolver el saldo a 764."""
        respondio_en = self.conteo_en + timedelta(hours=2, minutes=27)
        self.responder(764.0, respondio_en)
        self.mover("salida", 30.0, respondio_en + timedelta(minutes=2))

        svc.resolver_verificacion(self.db, self.verif.id, True, self.admin.id)
        self.db.refresh(self.inv)
        self.assertEqual(self.inv.stock_actual, 734.0)

    def test_sin_hueco_el_resultado_es_el_de_siempre(self):
        """Aprobar enseguida sigue escribiendo exactamente el recuento."""
        self.responder(764.0, self.conteo_en + timedelta(hours=2, minutes=27))
        svc.resolver_verificacion(self.db, self.verif.id, True, self.admin.id)
        self.db.refresh(self.inv)
        self.assertEqual(self.inv.stock_actual, 764.0)

    def test_un_ajuste_posterior_manda(self):
        """Alguien ya volvió a anclar el producto al físico: es más nuevo."""
        respondio_en = self.conteo_en + timedelta(hours=2, minutes=27)
        self.responder(764.0, respondio_en)
        self.mover("ajuste", 500.0, respondio_en + timedelta(minutes=5))

        svc.resolver_verificacion(self.db, self.verif.id, True, self.admin.id)
        self.db.refresh(self.inv)
        self.assertEqual(self.inv.stock_actual, 500.0)

    def test_rechazar_no_toca_el_stock(self):
        self.responder(764.0, self.conteo_en + timedelta(hours=2, minutes=27))
        antes = float(self.inv.stock_actual)
        svc.resolver_verificacion(self.db, self.verif.id, False, self.admin.id)
        self.db.refresh(self.inv)
        self.assertEqual(self.inv.stock_actual, antes)


if __name__ == "__main__":
    unittest.main()
