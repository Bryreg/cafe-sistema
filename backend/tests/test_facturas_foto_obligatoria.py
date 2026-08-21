"""La foto de la factura es OBLIGATORIA para registrar el ingreso (router HTTP).

Pedido del dueño: la barista no puede registrar mercancía recibida sin la foto
de la factura — es el comprobante de lo que entró. La regla vive en el router
(POST /facturas/), que es el único camino por el que se crea una recepción; el
servicio `crear_factura` sigue aceptando `imagen_url=None` para sus usos
internos y sus tests, así que esta prueba va contra el HTTP real (TestClient).

Se monta SOLO el router de facturas con las dependencias de auth/DB sobreescritas
—no se importa app.main, que siembra y migra contra la base de verdad—.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import (get_current_user, require_barista_en_turno)
from app.database import Base, get_db
from app.models.models import RolEnum, Tienda, Usuario
from app.routers import facturas as router_facturas


class FotoObligatoriaTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.t = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t); self.db.flush()
        self.barista = Usuario(nombre="Catherin", email="cath@t.local",
                               password_hash="h", rol=RolEnum.barista,
                               tienda_id=self.t.id, activo=True)
        self.db.add(self.barista); self.db.commit()

        app = FastAPI()
        app.include_router(router_facturas.router, prefix="/api/v1")

        def _db():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        bid, bnom, tid = self.barista.id, self.barista.nombre, self.t.id
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: self.db.get(Usuario, bid)
        # La barista está en su turno: acá se da por hecho, la regla del turno tiene
        # sus propios tests (test_facturas_sin_turno). Lo que se prueba es la foto.
        app.dependency_overrides[require_barista_en_turno] = lambda: (bid, bnom)
        self.tid = tid
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close(); self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _payload(self):
        """Un payload que PARSEA como FacturaCreate y pasa el chequeo de sede: así
        la request llega hasta el candado de la foto y no rebota antes por otra cosa."""
        return json.dumps({
            "tienda_id": self.tid,
            "proveedor": "Quala S.A.",
            "fecha_recibido": datetime(2026, 8, 21, tzinfo=timezone.utc).isoformat(),
            "valor_total": 100000,
            "tipo_pago": "contado",
            "items": [{"producto_id": 1, "cantidad": 2}],
        })

    def test_sin_foto_rebota_con_400_legible(self):
        r = self.client.post("/api/v1/facturas/", data={"data": self._payload()})
        self.assertEqual(r.status_code, 400)
        # El mensaje tiene que ser el de la foto, no otro 400 cualquiera: así se
        # prueba que rebotó POR la foto y no por un producto inexistente.
        self.assertIn("foto", r.json()["detail"].lower())
        self.assertIn("obligatoria", r.json()["detail"].lower())

    def test_foto_vacia_no_pasa_como_valida(self):
        """Una parte vacía (sin nombre ni contenido) no cuela como foto: se rechaza
        igual. FastAPI la corta en el parseo del multipart (422) antes de llegar al
        candado; lo que importa es que NO se registra un ingreso sin comprobante."""
        r = self.client.post(
            "/api/v1/facturas/",
            data={"data": self._payload()},
            files={"imagen": ("", b"", "application/octet-stream")})
        self.assertGreaterEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
