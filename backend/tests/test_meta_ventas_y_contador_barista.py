"""Meta de ventas mensual por sede + contador abierto a baristas.

- /auth/config/meta-ventas/{tienda_id}: GET para cualquier usuario con acceso a
  esa sede (la barista lee la meta de SU tienda), PUT solo admin (meta >= 0;
  0 = sin meta). Se guarda en `configuracion` (clave meta_ventas_mes_{tienda_id}),
  mismo patrón key-value del kiosk_pin — sin migración.
- /pos/analytics/contador: deja de ser solo-admin; la barista lo consulta
  scopeada a SU tienda (sin tienda_id se fuerza la suya; otra sede → 403).
  El admin conserva el comportamiento actual (tienda_id opcional = todas).
Los demás analytics_* siguen siendo solo-admin.
"""
import os
import tempfile
import unittest
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.database import Base, get_db
from app.models.models import (
    CajaTurno, EstadoTurnoEnum, RolEnum, Ticket, Tienda, Usuario,
)
from app.routers import auth as auth_router
from app.routers import pos as pos_router


class MetaVentasYContadorBaristaTest(unittest.TestCase):
    """sqlite temporal + routers reales de auth y pos (patrón de la suite)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tienda_1 = Tienda(nombre="Vida", direccion="Sede Vida")
        self.tienda_2 = Tienda(nombre="Palmetto", direccion="Sede Palmetto")
        self.db.add_all([self.tienda_1, self.tienda_2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@test.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.tienda_1.id, activo=True)
        self.barista = Usuario(nombre="Barista Uno", email="barista1@test.local",
                               password_hash="h", rol=RolEnum.barista,
                               tienda_id=self.tienda_1.id, activo=True)
        self.db.add_all([self.admin, self.barista])
        self.db.commit()

        app = FastAPI(title="Test meta-ventas y contador barista")
        app.include_router(auth_router.router, prefix="/api/v1")
        app.include_router(pos_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def set_current_user(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def crear_ticket(self, tienda, total):
        """Venta completada del 15/jul/2026 a las 10:00 Colombia. Ticket.fecha
        se guarda en UTC (= Colombia + 5h) → 15:00 UTC del mismo día."""
        turno = CajaTurno(tienda_id=tienda.id, usuario_apertura_id=self.admin.id,
                          base_real=0.0, estado=EstadoTurnoEnum.abierto)
        self.db.add(turno)
        self.db.flush()
        self.db.add(Ticket(
            tienda_id=tienda.id, caja_turno_id=turno.id, usuario_id=self.admin.id,
            fecha=datetime(2026, 7, 15, 15, 0, 0), total=total,
            estado="completado", metodo_pago="efectivo", monto_efectivo=total,
        ))
        self.db.commit()

    def _meta_url(self, tienda_id):
        return f"/api/v1/auth/config/meta-ventas/{tienda_id}"

    # ── Meta de ventas ───────────────────────────────────────────────────────

    def test_barista_lee_meta_de_su_tienda_default_cero(self):
        self.set_current_user(self.barista)
        r = self.client.get(self._meta_url(self.tienda_1.id))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"tienda_id": self.tienda_1.id, "meta": 0.0})

    def test_admin_define_meta_y_barista_la_lee(self):
        self.set_current_user(self.admin)
        r = self.client.put(self._meta_url(self.tienda_1.id), json={"meta": 5000000})
        self.assertEqual(r.status_code, 200)
        self.set_current_user(self.barista)
        r = self.client.get(self._meta_url(self.tienda_1.id))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["meta"], 5000000.0)

    def test_barista_no_puede_definir_meta(self):
        self.set_current_user(self.barista)
        r = self.client.put(self._meta_url(self.tienda_1.id), json={"meta": 1000})
        self.assertEqual(r.status_code, 403)

    def test_meta_negativa_400(self):
        self.set_current_user(self.admin)
        r = self.client.put(self._meta_url(self.tienda_1.id), json={"meta": -1})
        self.assertEqual(r.status_code, 400)

    def test_barista_no_lee_meta_de_otra_tienda(self):
        self.set_current_user(self.barista)
        r = self.client.get(self._meta_url(self.tienda_2.id))
        self.assertEqual(r.status_code, 403)

    # ── Contador para baristas (tienda-scoped) ───────────────────────────────

    def test_barista_contador_sin_tienda_id_scopea_su_tienda(self):
        self.crear_ticket(self.tienda_1, 15000)
        self.crear_ticket(self.tienda_2, 99000)
        self.set_current_user(self.barista)
        r = self.client.get("/api/v1/pos/analytics/contador",
                            params={"anio": 2026, "mes": 7})
        self.assertEqual(r.status_code, 200)
        # Solo la venta de SU tienda — la de tienda_2 no puede filtrarse.
        self.assertEqual(r.json()["total_mes"], 15000.0)

    def test_barista_contador_de_otra_tienda_403(self):
        self.set_current_user(self.barista)
        r = self.client.get("/api/v1/pos/analytics/contador",
                            params={"anio": 2026, "mes": 7,
                                    "tienda_id": self.tienda_2.id})
        self.assertEqual(r.status_code, 403)
        # La barrera debe ser la de sede (ensure_tienda_access), no la de rol.
        self.assertIn("tienda", r.json()["detail"])

    def test_admin_contador_sin_tienda_id_agrega_todas(self):
        self.crear_ticket(self.tienda_1, 15000)
        self.crear_ticket(self.tienda_2, 99000)
        self.set_current_user(self.admin)
        r = self.client.get("/api/v1/pos/analytics/contador",
                            params={"anio": 2026, "mes": 7})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total_mes"], 114000.0)


if __name__ == "__main__":
    unittest.main()
