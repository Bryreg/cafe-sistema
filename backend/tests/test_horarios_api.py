"""El router de horarios sobre HTTP real (TestClient), con una DB temporal.

Monta SOLO el router del módulo con las dependencias de auth/DB sobreescritas:
no importa app.main a propósito, porque ese módulo siembra y migra contra la base
de verdad al importarse. Lo que se prueba acá es el contrato HTTP —códigos,
formas de payload y los permisos de la barista— no la lógica, que ya tiene sus
tests propios.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user, require_admin
from app.database import Base, get_db
from app.models.models import RolEnum, Tienda, Usuario
from app.routers import horarios as router_horarios


class HorariosApiTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.t = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="admin@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.cath = Usuario(nombre="Catherin", email="cath@t.local", password_hash="h",
                            rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.eli = Usuario(nombre="Eliana", email="eli@t.local", password_hash="h",
                           rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add_all([self.admin, self.cath, self.eli])
        self.db.commit()

        app = FastAPI()
        app.include_router(router_horarios.router, prefix="/api/v1")
        self.app = app
        self._como(self.admin)
        self.client = TestClient(app)
        self.lunes = date(2026, 8, 10)

    def _como(self, usuario: Usuario):
        """Cambia el usuario autenticado del cliente."""
        uid = usuario.id

        def _db():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        def _user():
            s = self.Session()
            try:
                return s.query(Usuario).filter(Usuario.id == uid).first()
            finally:
                s.close()

        def _admin():
            u = _user()
            if u.rol != RolEnum.admin:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Se requiere rol admin")
            return u

        self.app.dependency_overrides[get_db] = _db
        self.app.dependency_overrides[get_current_user] = _user
        self.app.dependency_overrides[require_admin] = _admin

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Semana ──────────────────────────────────────────────────────────────

    def test_semana_vacia_responde_la_grilla_con_las_baristas(self):
        r = self.client.get("/api/v1/horarios/semana",
                            params={"tienda_id": self.t.id, "lunes": self.lunes.isoformat()})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["dias"]), 7)
        self.assertEqual({b["nombre"] for b in data["baristas"]}, {"Catherin", "Eliana"})
        self.assertGreater(data["jornada_max_semanal"], 0)

    def test_sin_lunes_devuelve_la_semana_en_curso(self):
        r = self.client.get("/api/v1/horarios/semana", params={"tienda_id": self.t.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(date.fromisoformat(r.json()["lunes"]).weekday(), 0)

    def test_ciclo_completo_crear_publicar_y_ver(self):
        r = self.client.post("/api/v1/horarios/turno", json={
            "tienda_id": self.t.id, "usuario_id": self.cath.id,
            "fecha": self.lunes.isoformat(), "hora_inicio": "08:00", "hora_fin": "16:00",
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["estado"], "borrador")
        self.assertEqual(r.json()["horas"], 8.0)

        r = self.client.post("/api/v1/horarios/publicar",
                             json={"tienda_id": self.t.id, "lunes": self.lunes.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["publicados"], 1)

        r = self.client.get("/api/v1/horarios/semana",
                            params={"tienda_id": self.t.id, "lunes": self.lunes.isoformat()})
        cath = [b for b in r.json()["baristas"] if b["nombre"] == "Catherin"][0]
        self.assertEqual(cath["publicados"], 1)
        self.assertEqual(cath["total_horas"], 8.0)

    def test_hora_invalida_da_400_con_mensaje_util(self):
        r = self.client.post("/api/v1/horarios/turno", json={
            "tienda_id": self.t.id, "usuario_id": self.cath.id,
            "fecha": self.lunes.isoformat(), "hora_inicio": "25:00", "hora_fin": "16:00",
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("HH:MM", r.json()["detail"])

    def test_borrar_turno_inexistente_da_404(self):
        self.assertEqual(self.client.delete("/api/v1/horarios/turno/9999").status_code, 404)

    def test_turno_con_almuerzo_devuelve_las_horas_ya_descontadas(self):
        r = self.client.post("/api/v1/horarios/turno", json={
            "tienda_id": self.t.id, "usuario_id": self.cath.id,
            "fecha": self.lunes.isoformat(), "hora_inicio": "07:00", "hora_fin": "15:00",
            "almuerzo_inicio": "13:00", "almuerzo_minutos": 60,
        })
        self.assertEqual(r.status_code, 200, r.text)
        cuerpo = r.json()
        self.assertEqual(cuerpo["horas"], 7.0)
        self.assertEqual(cuerpo["horas_brutas"], 8.0)
        self.assertEqual(cuerpo["almuerzo_fin"], "14:00")

    def test_almuerzo_fuera_del_turno_da_400_con_mensaje_util(self):
        r = self.client.post("/api/v1/horarios/turno", json={
            "tienda_id": self.t.id, "usuario_id": self.cath.id,
            "fecha": self.lunes.isoformat(), "hora_inicio": "08:00", "hora_fin": "16:00",
            "almuerzo_inicio": "18:00", "almuerzo_minutos": 60,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("almuerzo", r.json()["detail"])

    def test_turno_sin_almuerzo_mantiene_el_contrato_viejo(self):
        """Un cliente que no manda los campos nuevos tiene que seguir andando."""
        r = self.client.post("/api/v1/horarios/turno", json={
            "tienda_id": self.t.id, "usuario_id": self.cath.id,
            "fecha": self.lunes.isoformat(), "hora_inicio": "08:00", "hora_fin": "16:00",
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["horas"], 8.0)
        self.assertIsNone(r.json()["almuerzo_inicio"])

    # ── Novedades ───────────────────────────────────────────────────────────

    def test_catalogo_de_tipos_trae_la_razon_de_cada_uno(self):
        r = self.client.get("/api/v1/horarios/novedades/tipos")
        self.assertEqual(r.status_code, 200)
        tipos = r.json()
        self.assertTrue(tipos)
        for t in tipos:
            self.assertTrue(t["razon"])

    def test_crear_y_listar_novedad(self):
        r = self.client.post("/api/v1/horarios/novedades", json={
            "tienda_id": self.t.id, "usuario_id": self.cath.id, "tipo": "incapacidad",
            "fecha_desde": "2026-08-11", "fecha_hasta": "2026-08-13", "nota": "EPS",
        })
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["dias"], 3)
        self.assertTrue(r.json()["acredita_horas"])

        r = self.client.get("/api/v1/horarios/novedades", params={
            "tienda_id": self.t.id, "desde": "2026-08-01", "hasta": "2026-08-31"})
        self.assertEqual(len(r.json()), 1)

    def test_tipo_invalido_da_400(self):
        r = self.client.post("/api/v1/horarios/novedades", json={
            "tienda_id": self.t.id, "usuario_id": self.cath.id, "tipo": "siesta",
            "fecha_desde": "2026-08-11", "fecha_hasta": "2026-08-11",
        })
        self.assertEqual(r.status_code, 400)

    # ── Resumen / CSV ───────────────────────────────────────────────────────

    def test_resumen_mensual_responde_con_su_declaracion_de_base(self):
        r = self.client.get("/api/v1/horarios/resumen",
                            params={"tienda_id": self.t.id, "anio": 2026, "mes": 8})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["base_liquidacion"], "real")
        self.assertTrue(data["advertencias"])
        self.assertEqual(len(data["categorias"]), 8)

    def test_mes_invalido_da_400(self):
        r = self.client.get("/api/v1/horarios/resumen",
                            params={"tienda_id": self.t.id, "anio": 2026, "mes": 13})
        self.assertEqual(r.status_code, 400)

    def test_csv_baja_como_archivo(self):
        r = self.client.get("/api/v1/horarios/resumen.csv",
                            params={"tienda_id": self.t.id, "anio": 2026, "mes": 8})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["content-type"])
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertIn("Barista", r.text)
        self.assertIn("contador", r.text.lower())

    # ── Tasas y festivos ────────────────────────────────────────────────────

    def test_tasas_se_siembran_solas_y_se_pueden_editar(self):
        r = self.client.get("/api/v1/horarios/tasas")
        self.assertEqual(r.status_code, 200)
        tasas = r.json()
        self.assertTrue(tasas)
        self.assertTrue(all(t["nota"] for t in tasas))

        objetivo = tasas[-1]
        r = self.client.patch(f"/api/v1/horarios/tasas/{objetivo['id']}",
                              json={"recargo_dominical": 1.0, "confirmar_contador": False})
        self.assertEqual(r.status_code, 200)
        self.assertAlmostEqual(r.json()["recargo_dominical"], 1.0)
        self.assertFalse(r.json()["confirmar_contador"])

    def test_el_dominical_nocturno_se_expone_derivado(self):
        t = self.client.get("/api/v1/horarios/tasas").json()[0]
        self.assertAlmostEqual(
            t["recargo_dominical_nocturno_efectivo"],
            t["recargo_dominical"] + t["recargo_nocturno"])

    def test_festivos_del_anio_y_override(self):
        r = self.client.get("/api/v1/horarios/festivos", params={"anio": 2026})
        self.assertEqual(r.status_code, 200)
        fechas = {f["fecha"] for f in r.json() if f["es_festivo"]}
        self.assertIn("2026-08-17", fechas)   # Asunción corrida al lunes
        self.assertIn("2026-01-12", fechas)   # Reyes corrido al lunes

        r = self.client.post("/api/v1/horarios/festivos", json={
            "fecha": "2026-08-17", "nombre": "Asunción", "es_festivo": False,
            "nota": "acá se trabaja"})
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/v1/horarios/festivos", params={"anio": 2026})
        activos = {f["fecha"] for f in r.json() if f["es_festivo"]}
        self.assertNotIn("2026-08-17", activos)

    # ── Contratos ───────────────────────────────────────────────────────────

    def test_contratos_lista_todas_y_guarda_el_sueldo(self):
        r = self.client.get("/api/v1/horarios/contratos", params={"tienda_id": self.t.id})
        self.assertEqual(len(r.json()), 2)
        self.assertFalse(r.json()[0]["tiene_contrato"])

        r = self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                            json={"salario_mensual": 1800000})
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/v1/horarios/contratos", params={"tienda_id": self.t.id})
        cath = [c for c in r.json() if c["nombre"] == "Catherin"][0]
        self.assertEqual(cath["salario_mensual"], 1800000)
        self.assertTrue(cath["tiene_contrato"])

    # ── Permisos ────────────────────────────────────────────────────────────

    def test_la_barista_ve_su_horario(self):
        self.client.post("/api/v1/horarios/turno", json={
            "tienda_id": self.t.id, "usuario_id": self.cath.id,
            "fecha": self.lunes.isoformat(), "hora_inicio": "08:00", "hora_fin": "16:00"})
        self.client.post("/api/v1/horarios/publicar",
                         json={"tienda_id": self.t.id, "lunes": self.lunes.isoformat()})

        self._como(self.cath)
        r = self.client.get("/api/v1/horarios/mi-horario", params={
            "desde": self.lunes.isoformat(),
            "hasta": (self.lunes + timedelta(days=7)).isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["turnos"]), 1)
        # El lunes 17 (Asunción corrida por Ley Emiliani) viene marcado como
        # festivo: la barista tiene que verlo antes de que llegue.
        self.assertIn("2026-08-17", r.json()["festivos"])

    def test_una_barista_no_puede_espiar_el_horario_de_otra(self):
        self._como(self.cath)
        r = self.client.get("/api/v1/horarios/mi-horario", params={"usuario_id": self.eli.id})
        self.assertEqual(r.status_code, 403)

    def test_la_barista_no_entra_al_armado_ni_al_resumen(self):
        self._como(self.cath)
        self.assertEqual(self.client.get(
            "/api/v1/horarios/semana", params={"tienda_id": self.t.id}).status_code, 403)
        self.assertEqual(self.client.get(
            "/api/v1/horarios/resumen", params={"tienda_id": self.t.id}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/horarios/tasas").status_code, 403)


if __name__ == "__main__":
    unittest.main()


class KioskoNoFiltraDatosDeSaludTest(HorariosApiTest):
    """El token del kiosko es COMPARTIDO por todas las baristas de la sede (PIN
    común) y vive años. Aceptarlo como llave para cualquier `usuario_id` dejaba
    leer la incapacidad médica de una compañera —nota y certificado— cambiando
    el selector de barista activa. Ningún test lo cubría porque el único de
    permisos usaba login individual."""

    def _kiosko(self):
        k = Usuario(nombre="Kiosk", email="kiosk@t.device", password_hash="h",
                    rol=RolEnum.barista, tienda_id=self.t.id, activo=True)
        self.db.add(k)
        self.db.commit()
        self._como(k)
        return k

    def test_el_kiosko_no_puede_ver_a_alguien_de_otra_sede(self):
        otra = Tienda(nombre="Palmetto", direccion="y")
        self.db.add(otra)
        self.db.flush()
        ajena = Usuario(nombre="Laura", email="laura@t.co", password_hash="h",
                        rol=RolEnum.barista, tienda_id=otra.id, activo=True)
        self.db.add(ajena)
        self.db.commit()
        self._kiosko()

        r = self.client.get(f"/api/v1/horarios/mi-horario?usuario_id={ajena.id}")
        self.assertEqual(403, r.status_code)

    def test_el_payload_del_kiosko_no_lleva_la_nota_medica_ni_el_soporte(self):
        """Ni siquiera para la dueña legítima: la pantalla muestra la etiqueta y
        las fechas, así que la nota y el certificado no viajan."""
        from app.services import novedades_nomina as nsvc
        nsvc.crear(self.db, self.t.id, self.cath.id, "incapacidad",
                   date(2026, 8, 10), date(2026, 8, 14),
                   nota="Incapacidad por embarazo de alto riesgo",
                   soporte_url="https://x/certificado.pdf",
                   creado_por_id=self.admin.id)
        self.db.commit()
        self._kiosko()

        r = self.client.get(
            f"/api/v1/horarios/mi-horario?usuario_id={self.cath.id}"
            "&desde=2026-08-10&hasta=2026-08-14")
        self.assertEqual(200, r.status_code)
        novs = r.json()["novedades"]
        self.assertEqual(1, len(novs))
        self.assertNotIn("nota", novs[0])
        self.assertNotIn("soporte_url", novs[0])
