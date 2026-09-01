"""Qué puede entrar como CONTEO FÍSICO en el inventario mensual.

Sale de la casilla que aprendió a sumar. Enseñarle «6+8» —así se cuenta de
verdad: seis en la vitrina, ocho en la bodega— trajo gratis la resta, y con ella
un agujero que antes no se podía tocar: «8-10» da −2 y entraba como existencia
física. Al cerrar, el mes convierte esa cantidad en diferencia contra el sistema,
así que un signo mal tecleado se vuelve un faltante en pesos que nunca ocurrió y
que alguien va a salir a investigar.

Y del otro reporte del piso —«el botón no guarda lo que queda escrito»— queda la
regla del silencio: `guardar()` descartaba sin decir nada el renglón que no le
servía y contestaba 200 con el inventario entero, indistinguible de un guardado
bueno. Guardar de menos se arregla contando otra vez; un 200 que miente, no.
"""
import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CategoriaProductoEnum, Inventario, Producto,
                               RolEnum, Tienda, Usuario)
from app.services import inventario_mensual as svc


class ConteoValidoTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.tienda)
        self.db.flush()
        self.user = Usuario(nombre="Barista", email="b@t.local", password_hash="h",
                            rol=RolEnum.barista, tienda_id=self.tienda.id, activo=True)
        self.db.add(self.user)
        self.db.flush()
        self.leche = self._producto("LECHE ENTERA", 100)
        self.pan = self._producto("PAN", 40)
        self.db.commit()

        self.inv = svc.iniciar(self.db, self.tienda.id, 2026, 9, self.user.id,
                               self.user.id, self.user.nombre)
        porNombre = {it["producto_nombre"]: it["id"] for it in self.inv["items"]}
        self.item_leche = porNombre["LECHE ENTERA"]
        self.item_pan = porNombre["PAN"]

    def _producto(self, nombre: str, stock: float) -> Producto:
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida="und", controla_stock=True, precio_venta=5000)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.tienda.id, stock_actual=stock))
        return p

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _item(self, data: dict, item_id: int) -> dict:
        return next(it for it in data["items"] if it["id"] == item_id)

    # ── El conteo físico nunca es negativo ────────────────────────────────────
    def test_negativo_no_entra_como_conteo(self):
        """«8-10» da −2 y NO es una existencia física. Antes se guardaba, y el
        cierre lo convertía en un faltante en pesos que nunca ocurrió."""
        data = svc.guardar(self.db, self.inv["id"], [
            {"id": self.item_leche, "cantidad_real": -2},
            {"id": self.item_pan, "cantidad_real": 38},
        ])
        leche = self._item(data, self.item_leche)
        self.assertIsNone(leche["cantidad_real"])
        self.assertFalse(leche["fue_contado"])
        # El renglón bueno del mismo envío no se pierde por el malo
        self.assertEqual(self._item(data, self.item_pan)["cantidad_real"], 38)
        self.assertEqual([x["producto"] for x in data["no_guardados"]], ["LECHE ENTERA"])
        self.assertIn("negativ", data["no_guardados"][0]["motivo"])

    def test_negativo_no_llega_a_inventar_un_faltante_al_cerrar(self):
        """La consecuencia medida: con 100 de sistema, un −7 guardado cerraba el
        mes con −107 unidades de diferencia y −$535.000 de fuga inventada."""
        with self.assertRaises(HTTPException):
            svc.guardar(self.db, self.inv["id"], [{"id": self.item_leche, "cantidad_real": -7}])
        cerrado = svc.cerrar(self.db, self.inv["id"], self.user.id)
        leche = self._item(cerrado, self.item_leche)
        # No contado ⇒ se iguala al sistema y no ensucia el neto con nada
        self.assertEqual(leche["diferencia"], 0)
        self.assertEqual(cerrado["valor_diferencia_total"], 0)

    def test_cero_si_es_un_conteo(self):
        """Contar cero es contar: es el renglón que dice «se acabó»."""
        data = svc.guardar(self.db, self.inv["id"], [{"id": self.item_leche, "cantidad_real": 0}])
        leche = self._item(data, self.item_leche)
        self.assertEqual(leche["cantidad_real"], 0)
        self.assertTrue(leche["fue_contado"])
        self.assertEqual(data["no_guardados"], [])

    # ── Lo que no se guarda, se dice ──────────────────────────────────────────
    def test_lo_descartado_viaja_en_la_respuesta(self):
        """null, texto, infinito y un id ajeno: cuatro formas de no guardar que
        antes contestaban 200 sin una palabra."""
        data = svc.guardar(self.db, self.inv["id"], [
            {"id": self.item_pan, "cantidad_real": 12},
            {"id": self.item_leche, "cantidad_real": None},
            {"id": 999999, "cantidad_real": 5},
        ])
        self.assertEqual(self._item(data, self.item_pan)["cantidad_real"], 12)
        motivos = {x["id"]: x["motivo"] for x in data["no_guardados"]}
        self.assertEqual(set(motivos), {self.item_leche, 999999})

    def test_texto_no_revienta_el_endpoint(self):
        """`float("abc")` tiraba un ValueError: 500 en mitad de un conteo, con
        todos los renglones del envío sin guardar."""
        data = svc.guardar(self.db, self.inv["id"], [
            {"id": self.item_pan, "cantidad_real": 12},
            {"id": self.item_leche, "cantidad_real": "abc"},
        ])
        self.assertEqual(self._item(data, self.item_pan)["cantidad_real"], 12)
        self.assertEqual(len(data["no_guardados"]), 1)

    def test_infinito_no_entra(self):
        """Un NaN o un infinito guardado envenena todos los totales del mes."""
        data = svc.guardar(self.db, self.inv["id"], [
            {"id": self.item_leche, "cantidad_real": float("inf")},
            {"id": self.item_pan, "cantidad_real": 3},
        ])
        self.assertIsNone(self._item(data, self.item_leche)["cantidad_real"])
        self.assertEqual(len(data["no_guardados"]), 1)

    def test_si_no_se_guardo_nada_el_request_falla(self):
        """Sin trabajo parcial que perder, el envío falla de verdad: un bundle
        viejo que manda `null` ve «Error al guardar» y no un «Guardado» que
        miente. Ese era el reporte del piso, palabra por palabra."""
        with self.assertRaises(HTTPException) as ctx:
            svc.guardar(self.db, self.inv["id"], [
                {"id": self.item_leche, "cantidad_real": None},
                {"id": self.item_pan, "cantidad_real": None},
            ])
        self.assertEqual(ctx.exception.status_code, 400)

    def test_envio_vacio_no_es_un_error(self):
        """Guardar sin nada tecleado es un no-op, no un fallo."""
        data = svc.guardar(self.db, self.inv["id"], [])
        self.assertEqual(data["no_guardados"], [])
        self.assertEqual(data["contados"], 0)

    # ── La corrección del admin sigue la misma regla ──────────────────────────
    def test_corregir_item_rechaza_negativo(self):
        """Acá el dedazo cuesta más: es un mes CERRADO y a un clic de aplicarse
        al inventario."""
        svc.guardar(self.db, self.inv["id"], [{"id": self.item_leche, "cantidad_real": 90}])
        svc.cerrar(self.db, self.inv["id"], self.user.id)
        with self.assertRaises(HTTPException) as ctx:
            svc.corregir_item(self.db, self.item_leche, -5, self.user.id)
        self.assertEqual(ctx.exception.status_code, 400)
        actual = svc.get_actual(self.db, self.tienda.id, 2026, 9)
        self.assertEqual(self._item(actual, self.item_leche)["cantidad_real"], 90)


if __name__ == "__main__":
    unittest.main()
