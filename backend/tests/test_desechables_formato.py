"""El formato de desechables: que salga solo, y que sea el MISMO en las dos sedes.

Dos problemas del piso, no de diseño.

EL FORMATO NO SALÍA. Dependía de que el admin se acordara de apretar «Pedir
conteo de desechables». Los vasos y las tapas están fuera del conteo diario
(`grupo_conteo='desechables'`), así que si nadie lo pide no se cuentan nunca y
el faltante aparece cuando se acaba algo en plena venta.

EL FORMATO PODÍA DIVERGIR ENTRE SEDES. Los items salen de cruzar los productos
del grupo con la tabla de inventario de CADA sede: un desechable sin fila en una
sede no aparece en su formato, y las dos pantallas se ven bien por separado, así
que nadie lo nota. Hoy en producción las dos sedes tienen los mismos 39 items
—verificado— pero nada lo impedía.
"""
import contextlib
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.tz import COL_OFFSET
from app.database import Base
from app.models.models import (CategoriaProductoEnum, Configuracion, Inventario,
                               Producto, RolEnum, SolicitudConteoDesechables,
                               Tienda, Usuario)
from app.services import conteos as svc


class FormatoDesechablesTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.palmetto = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.vaso = self._desechable("Vaso 12oz", sedes=[self.vida, self.palmetto])
        self.db.commit()

    def _producto(self, nombre, grupo=None):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida="und", controla_stock=True, precio_venta=0,
                     grupo_conteo=grupo, proveedor="Plásticos SA")
        self.db.add(p)
        self.db.flush()
        return p

    def _desechable(self, nombre, sedes):
        p = self._producto(nombre, grupo="desechables")
        for t in sedes:
            self.db.add(Inventario(producto_id=p.id, tienda_id=t.id, stock_actual=0))
        self.db.flush()
        return p

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Días programados ──────────────────────────────────────────────────────
    def test_por_defecto_lunes_y_viernes(self):
        self.assertEqual(svc.dias_programados(self.db), [0, 4])

    def test_se_pueden_cambiar_los_dias(self):
        r = svc.set_dias_programados(self.db, [1, 3], self.admin.id)
        self.assertEqual(r["dias"], [1, 3])
        self.assertEqual(r["nombres"], ["martes", "jueves"])
        self.assertEqual(svc.dias_programados(self.db), [1, 3])

    def test_lista_vacia_apaga_la_programacion(self):
        """Apagar es distinto de no haber configurado nunca: si se borrara la
        fila, `dias_programados` volvería al default y el formato seguiría
        saliendo los lunes."""
        svc.set_dias_programados(self.db, [], self.admin.id)
        self.assertEqual(svc.dias_programados(self.db), [])
        row = self.db.query(Configuracion).filter_by(
            clave=svc.CLAVE_DIAS_DESECHABLES).first()
        self.assertIsNotNone(row)

    def test_dia_fuera_de_rango_se_rechaza(self):
        with self.assertRaises(HTTPException):
            svc.set_dias_programados(self.db, [0, 9], self.admin.id)

    def test_config_corrupta_cae_al_default_sin_romper(self):
        self.db.add(Configuracion(clave=svc.CLAVE_DIAS_DESECHABLES, valor="lunes,viernes"))
        self.db.commit()
        self.assertEqual(svc.dias_programados(self.db), [0, 4])

    # ── Materialización ───────────────────────────────────────────────────────
    @contextlib.contextmanager
    def _en_dia(self, y, m, d, hora_col=12):
        """Congela el reloj en las `hora_col` del día Colombia y/m/d.

        Alcanza con `core.tz` porque el servicio saca de ahí las dos cosas: qué
        día es hoy y el instante que guarda en `fecha_solicitud`. Cuando la
        fecha la ponía el default de la columna hacía falta congelar también
        `models`, y ese desacople era un bug de verdad, no del test: la guarda
        de «ya salió hoy» comparaba contra un instante de otro reloj.

        Es una subclase de datetime, no un Mock: `tz.py` también usa
        `datetime.combine` y `datetime.min`, que un Mock deja inservibles.
        """
        congelado = datetime(y, m, d, hora_col, 0) + COL_OFFSET   # reloj de pared → UTC

        class RelojFijo(datetime):
            @classmethod
            def utcnow(cls):
                return congelado

        with patch("app.core.tz.datetime", RelojFijo):
            yield

    def test_el_lunes_sale_solo(self):
        # 2026-09-14 es lunes
        with self._en_dia(2026, 9, 14):
            creada = svc.asegurar_solicitud_programada(self.db, self.palmetto.id)
        self.assertTrue(creada)
        s = self.db.query(SolicitudConteoDesechables).filter_by(
            tienda_id=self.palmetto.id).first()
        self.assertEqual(s.estado, "pendiente")
        self.assertTrue(s.automatica)

    def test_el_viernes_tambien(self):
        with self._en_dia(2026, 9, 18):   # viernes
            self.assertTrue(svc.asegurar_solicitud_programada(self.db, self.vida.id))

    def test_el_miercoles_no(self):
        with self._en_dia(2026, 9, 16):   # miércoles
            self.assertFalse(svc.asegurar_solicitud_programada(self.db, self.vida.id))
        self.assertEqual(self.db.query(SolicitudConteoDesechables).count(), 0)

    def test_no_se_duplica_en_el_mismo_dia(self):
        """El kiosko pregunta cada pocos segundos: sin esta guarda el lunes se
        llenaría de solicitudes."""
        with self._en_dia(2026, 9, 14):
            self.assertTrue(svc.asegurar_solicitud_programada(self.db, self.vida.id))
            for _ in range(5):
                self.assertFalse(svc.asegurar_solicitud_programada(self.db, self.vida.id))
        self.assertEqual(self.db.query(SolicitudConteoDesechables).count(), 1)

    def test_no_reaparece_despues_de_responderla(self):
        """Mirar solo las PENDIENTES traería el formato de vuelta el mismo lunes
        en cuanto la barista lo responde."""
        with self._en_dia(2026, 9, 14):
            svc.asegurar_solicitud_programada(self.db, self.vida.id)
            s = self.db.query(SolicitudConteoDesechables).first()
            s.estado = "respondida"
            self.db.commit()
            self.assertFalse(svc.asegurar_solicitud_programada(self.db, self.vida.id))
        self.assertEqual(self.db.query(SolicitudConteoDesechables).count(), 1)

    def test_de_noche_sigue_siendo_el_mismo_dia_colombia(self):
        """A las 20:00 de Colombia el UTC ya está en el día siguiente. Con la
        fecha UTC, el formato del viernes volvería a salir el viernes a las
        19:01 — y el domingo a las 19:01 saldría el del lunes."""
        with self._en_dia(2026, 9, 14, hora_col=8):
            svc.asegurar_solicitud_programada(self.db, self.vida.id)
        with self._en_dia(2026, 9, 14, hora_col=20):
            self.assertFalse(svc.asegurar_solicitud_programada(self.db, self.vida.id))
        self.assertEqual(self.db.query(SolicitudConteoDesechables).count(), 1)

    def test_el_domingo_de_noche_no_adelanta_el_lunes(self):
        with self._en_dia(2026, 9, 13, hora_col=20):   # domingo 20:00 Colombia
            self.assertFalse(svc.asegurar_solicitud_programada(self.db, self.vida.id))

    def test_no_apila_sobre_un_pendiente_viejo(self):
        """Caso real: Palmetto tenía un formato pedido a mano el lunes y sin
        responder. Un segundo pendiente encima rompe el módulo entero — la
        barista llena el formato, se cierra uno y el otro queda vivo, así que el
        formato reaparece y no se va más."""
        with self._en_dia(2026, 9, 14):   # lunes: se pide a mano
            svc.solicitar_conteo_desechables(self.db, self.vida.id, self.admin.id)
        with self._en_dia(2026, 9, 18):   # viernes, y el del lunes sigue abierto
            self.assertFalse(svc.asegurar_solicitud_programada(self.db, self.vida.id))
        pendientes = self.db.query(SolicitudConteoDesechables).filter_by(
            tienda_id=self.vida.id, estado="pendiente").count()
        self.assertEqual(pendientes, 1)

    def test_si_el_viejo_ya_se_respondio_el_viernes_si_sale(self):
        """La guarda es «hay uno abierto», no «hubo alguno»: un formato ya
        respondido no puede bloquear el siguiente."""
        with self._en_dia(2026, 9, 14):
            svc.asegurar_solicitud_programada(self.db, self.vida.id)
            s = self.db.query(SolicitudConteoDesechables).first()
            s.estado = "respondida"
            self.db.commit()
        with self._en_dia(2026, 9, 18):   # viernes
            self.assertTrue(svc.asegurar_solicitud_programada(self.db, self.vida.id))

    def test_cada_sede_tiene_la_suya(self):
        with self._en_dia(2026, 9, 14):
            svc.asegurar_solicitud_programada(self.db, self.vida.id)
            svc.asegurar_solicitud_programada(self.db, self.palmetto.id)
        sedes = {s.tienda_id for s in self.db.query(SolicitudConteoDesechables).all()}
        self.assertEqual(sedes, {self.vida.id, self.palmetto.id})

    def test_sin_admin_activo_no_revienta_el_kiosko(self):
        """Lo llama el poll del kiosko: un problema de la programación no puede
        dejar la pantalla de la barista sin respuesta."""
        self.admin.activo = False
        self.db.commit()
        with self._en_dia(2026, 9, 14):
            self.assertFalse(svc.asegurar_solicitud_programada(self.db, self.vida.id))

    def test_el_poll_del_kiosko_la_materializa(self):
        with self._en_dia(2026, 9, 14):
            r = svc.get_solicitud_desechables(self.db, self.palmetto.id)
        self.assertTrue(r["pendiente"])
        self.assertTrue(r["automatica"])

    def test_apagada_no_sale_ni_el_lunes(self):
        svc.set_dias_programados(self.db, [], self.admin.id)
        with self._en_dia(2026, 9, 14):
            self.assertFalse(svc.asegurar_solicitud_programada(self.db, self.vida.id))

    # ── Items del formato, iguales en las dos sedes ───────────────────────────
    def test_el_formato_reporta_cobertura_por_sede(self):
        f = svc.formato(self.db)
        self.assertEqual(len(f["items"]), 1)
        self.assertTrue(f["items"][0]["en_todas"])
        self.assertEqual(f["items"][0]["tienda_ids"], [self.vida.id, self.palmetto.id])

    def test_un_item_que_le_falta_a_una_sede_se_delata(self):
        """Esta es la divergencia que no se ve desde ninguna de las dos
        pantallas del kiosko."""
        self._desechable("Tapa 12oz", sedes=[self.vida])   # Palmetto NO
        self.db.commit()
        f = svc.formato(self.db)
        cojo = next(i for i in f["items"] if i["nombre"] == "Tapa 12oz")
        self.assertFalse(cojo["en_todas"])
        self.assertEqual(cojo["tienda_ids"], [self.vida.id])

    def test_agregar_item_crea_la_fila_en_TODAS_las_sedes(self):
        servilleta = self._producto("Servilleta")
        self.db.commit()
        f = svc.agregar_item(self.db, servilleta.id, self.admin.id)
        item = next(i for i in f["items"] if i["nombre"] == "Servilleta")
        self.assertTrue(item["en_todas"])
        self.assertEqual(item["tienda_ids"], [self.vida.id, self.palmetto.id])

    def test_agregar_item_lo_saca_del_conteo_diario(self):
        """Si quedara en los dos conteos se contaría dos veces."""
        servilleta = self._producto("Servilleta")
        self.db.commit()
        svc.agregar_item(self.db, servilleta.id, self.admin.id)
        self.db.refresh(servilleta)
        self.assertFalse(servilleta.incluir_en_conteo)

    def test_no_se_agrega_dos_veces(self):
        with self.assertRaises(HTTPException):
            svc.agregar_item(self.db, self.vaso.id, self.admin.id)

    def test_agregar_producto_inexistente_es_404(self):
        with self.assertRaises(HTTPException) as ctx:
            svc.agregar_item(self.db, 9999, self.admin.id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_quitar_item_no_borra_el_stock(self):
        """El producto sigue en la bodega: lo único que cambia es que deja de
        pedirse en este conteo."""
        inv = self.db.query(Inventario).filter_by(
            producto_id=self.vaso.id, tienda_id=self.vida.id).first()
        inv.stock_actual = 120
        self.db.commit()
        f = svc.quitar_item(self.db, self.vaso.id, self.admin.id)
        self.assertEqual(f["items"], [])
        inv = self.db.query(Inventario).filter_by(
            producto_id=self.vaso.id, tienda_id=self.vida.id).first()
        self.assertEqual(inv.stock_actual, 120)

    def test_quitar_algo_que_no_esta_se_rechaza(self):
        otro = self._producto("Azúcar")
        self.db.commit()
        with self.assertRaises(HTTPException):
            svc.quitar_item(self.db, otro.id, self.admin.id)

    def test_sincronizar_arregla_un_formato_ya_divergido(self):
        self._desechable("Tapa 12oz", sedes=[self.vida])
        self.db.commit()
        r = svc.sincronizar_sedes(self.db, self.admin.id)
        self.assertEqual(len(r["filas_creadas"]), 1)
        self.assertTrue(all(i["en_todas"] for i in r["items"]))

    def test_sincronizar_es_idempotente(self):
        svc.sincronizar_sedes(self.db, self.admin.id)
        r = svc.sincronizar_sedes(self.db, self.admin.id)
        self.assertEqual(r["filas_creadas"], [])


if __name__ == "__main__":
    unittest.main()
