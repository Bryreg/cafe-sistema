"""Los endpoints de parámetros de nómina y de sueldo en SMMLV, sobre HTTP real.

Mismo andamiaje que `test_horarios_api.py` —router solo, DB temporal, auth
sobreescrita— y por el mismo motivo: importar `app.main` sembraría y migraría
contra la base de verdad. Lo que se prueba acá es el CONTRATO HTTP: qué se
puede escribir, qué rebota y con qué código. La aritmética de la liquidación ya
tiene sus 33 tests en `test_liquidacion_colombia.py`.

Por qué cada test de rechazo mira además el valor guardado: un 400 que igual
escribió la fila es peor que no validar nada, porque deja la nómina rota y al
dueño convencido de que su cambio no entró.
"""
import os
import tempfile
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user, require_admin
from app.core.tz import hoy_col
from app.database import Base, get_db
from app.models.models import ContratoBarista, RolEnum, Tienda, Usuario
from app.routers import horarios as router_horarios
from app.services import parametros_nomina as pnsvc


class _BaseApi(unittest.TestCase):
    """Sede con dos baristas activas y una dada de baja, admin autenticado."""

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
        # Ya no trabaja acá: `baristas_de` no la devuelve, y su contrato viejo
        # tiene que quedar exactamente como está para que sus meses ya
        # liquidados sigan dando el mismo número.
        self.retirada = Usuario(nombre="Inés", email="ines@t.local", password_hash="h",
                                rol=RolEnum.barista, tienda_id=self.t.id, activo=False)
        self.db.add_all([self.admin, self.cath, self.eli, self.retirada])
        self.db.commit()

        app = FastAPI()
        app.include_router(router_horarios.router, prefix="/api/v1")
        self.app = app
        self._como(self.admin)
        self.client = TestClient(app)

    def _como(self, usuario: Usuario):
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

    # ── Utilidades ──────────────────────────────────────────────────────────

    def _vigencias(self) -> list[dict]:
        r = self.client.get("/api/v1/horarios/parametros-nomina")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _smmlv_de_hoy(self) -> float:
        """El mínimo vigente HOY, resuelto por el mismo servicio que usa la
        liquidación. No se escribe el número en el test a propósito: quedaría
        obsoleto el día que se siembre la vigencia del año que viene."""
        params = pnsvc.para(self.db, hoy_col())
        self.assertIsNotNone(params)
        # Que sea un mínimo de verdad y no un cero heredado de una fila vacía.
        self.assertGreater(params.smmlv, 1_000_000)
        return float(params.smmlv)

    def _contrato_de(self, usuario_id: int) -> ContratoBarista:
        self.db.expire_all()   # el endpoint escribió desde OTRA sesión
        return self.db.query(ContratoBarista).filter(
            ContratoBarista.usuario_id == usuario_id).first()

    def _contratos_api(self) -> dict:
        r = self.client.get("/api/v1/horarios/contratos",
                            params={"tienda_id": self.t.id})
        self.assertEqual(r.status_code, 200, r.text)
        return {c["nombre"]: c for c in r.json()}


class ParametrosNominaApiTest(_BaseApi):
    """GET/PUT de las vigencias del mínimo, el auxilio y los aportes."""

    def test_la_lista_se_siembra_sola_y_trae_las_vigencias_ordenadas(self):
        filas = self._vigencias()
        self.assertGreaterEqual(len(filas), 2)
        fechas = [f["vigente_desde"] for f in filas]
        self.assertEqual(fechas, sorted(fechas))
        for f in filas:
            self.assertGreater(f["smmlv"], 0)
            self.assertGreater(f["auxilio_transporte"], 0)
            self.assertTrue(f["nota"])
        # Recién sembrado, nadie lo validó todavía: el cartel tiene que estar.
        self.assertTrue(all(f["confirmar_contador"] for f in filas))

    def test_editar_una_vigencia_responde_y_persiste_el_valor_nuevo(self):
        objetivo = self._vigencias()[-1]
        # ARL clase II: la cafetería que además hornea sube de riesgo.
        r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"arl": 0.01044, "nota": "Clase II"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(r.json()["arl"], 0.01044)
        self.assertEqual(r.json()["nota"], "Clase II")

        guardada = [f for f in self._vigencias() if f["id"] == objetivo["id"]][0]
        self.assertAlmostEqual(guardada["arl"], 0.01044)

    def test_escribir_cualquier_campo_baja_el_cartel_del_contador(self):
        objetivo = self._vigencias()[-1]
        self.assertTrue(objetivo["confirmar_contador"])
        # Se escribe lo CONTRARIO de lo que trae la siembra: mandar el mismo
        # valor que ya estaba no probaría que el campo se escribió, y el default
        # sembrado de la exoneración ya cambió una vez.
        opuesto = not objetivo["exonerado_114_1"]
        r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"exonerado_114_1": opuesto})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["exonerado_114_1"], opuesto)
        self.assertFalse(r.json()["confirmar_contador"])

    def test_se_puede_bajar_el_cartel_sin_tocar_ningun_numero(self):
        """«Lo revisé y está bien como está» también es haberlo revisado."""
        objetivo = self._vigencias()[-1]
        r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"confirmar_contador": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["confirmar_contador"])
        self.assertEqual(r.json()["smmlv"], objetivo["smmlv"])
        self.assertEqual(r.json()["arl"], objetivo["arl"])

    def test_mover_la_fecha_de_una_vigencia_rebota_y_no_escribe_nada(self):
        """Correr `vigente_desde` recalcula meses ya pagados. Tiene que fallar
        RUIDOSAMENTE: descartar el campo en silencio devolvería 200 y el dueño
        se iría creyendo que movió la fecha."""
        objetivo = self._vigencias()[-1]
        r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"vigente_desde": "2027-01-01", "smmlv": 9_999_999})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("vigencia", r.json()["detail"].lower())

        guardada = [f for f in self._vigencias() if f["id"] == objetivo["id"]][0]
        self.assertEqual(guardada["vigente_desde"], objetivo["vigente_desde"])
        # Y el smmlv que venía en el mismo payload tampoco entró.
        self.assertEqual(guardada["smmlv"], objetivo["smmlv"])

    def test_un_minimo_negativo_o_en_cero_no_pasa(self):
        objetivo = self._vigencias()[-1]
        for valor in (-1_750_905, 0):
            r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                                json={"smmlv": valor})
            self.assertEqual(r.status_code, 400, f"smmlv={valor}: {r.text}")
        r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"auxilio_transporte": -1})
        self.assertEqual(r.status_code, 400, r.text)

        guardada = [f for f in self._vigencias() if f["id"] == objetivo["id"]][0]
        self.assertEqual(guardada["smmlv"], objetivo["smmlv"])
        self.assertEqual(guardada["auxilio_transporte"], objetivo["auxilio_transporte"])

    def test_un_porcentaje_tecleado_como_entero_no_pasa(self):
        """El 4% se carga como 0.04. Escribir 4 multiplica el aporte por cien."""
        objetivo = self._vigencias()[-1]
        for campo in ("salud_empleado", "arl", "prima"):
            r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                                json={campo: 4})
            self.assertEqual(r.status_code, 400, f"{campo}: {r.text}")
        guardada = [f for f in self._vigencias() if f["id"] == objetivo["id"]][0]
        self.assertAlmostEqual(guardada["salud_empleado"], objetivo["salud_empleado"])

    def test_los_campos_en_smmlv_no_se_validan_como_porcentajes(self):
        """El tope del auxilio son 2 SMMLV y el fondo de solidaridad arranca en
        4: si alguien los mete en la bolsa de los porcentajes (0 a 1) quedan
        imposibles de corregir desde la pantalla para siempre."""
        objetivo = self._vigencias()[-1]
        r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"tope_auxilio_smmlv": 2.5, "fsp_desde_smmlv": 4.0})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(r.json()["tope_auxilio_smmlv"], 2.5)
        self.assertAlmostEqual(r.json()["fsp_desde_smmlv"], 4.0)

        # Pero cero sigue sin tener sentido: nadie tendría derecho al auxilio.
        r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"tope_auxilio_smmlv": 0})
        self.assertEqual(r.status_code, 400, r.text)

    def test_el_divisor_del_auxilio_no_puede_quedar_en_cero(self):
        objetivo = self._vigencias()[-1]
        r = self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"dias_base_auxilio": 0})
        self.assertEqual(r.status_code, 400, r.text)

    def test_editar_una_vigencia_que_no_existe_da_404(self):
        r = self.client.put("/api/v1/horarios/parametros-nomina/9999",
                            json={"arl": 0.00522})
        self.assertEqual(r.status_code, 404, r.text)

    def test_la_barista_no_ve_ni_toca_los_parametros(self):
        objetivo = self._vigencias()[-1]
        self._como(self.cath)
        self.assertEqual(
            self.client.get("/api/v1/horarios/parametros-nomina").status_code, 403)
        self.assertEqual(
            self.client.put(f"/api/v1/horarios/parametros-nomina/{objetivo['id']}",
                            json={"smmlv": 1}).status_code, 403)


class SalarioEnSmmlvApiTest(_BaseApi):
    """El contrato atado al mínimo: `salario_en_smmlv` sobre /contratos."""

    def test_atar_al_minimo_devuelve_el_salario_ya_resuelto(self):
        minimo = self._smmlv_de_hoy()
        r = self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                            json={"salario_mensual": 0, "salario_en_smmlv": 1.0})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["salario_en_smmlv"], 1.0)
        self.assertEqual(r.json()["salario_resuelto"], minimo)
        self.assertEqual(r.json()["smmlv_vigente"], minimo)

        # La pantalla arma "1 SMMLV = $1.750.905" con lo que trae el listado,
        # sin recalcular nada en el cliente.
        cath = self._contratos_api()["Catherin"]
        self.assertEqual(cath["salario_en_smmlv"], 1.0)
        self.assertEqual(cath["salario_resuelto"], minimo)
        self.assertEqual(cath["smmlv_vigente"], minimo)

    def test_el_multiplo_manda_sobre_los_pesos_fijos(self):
        minimo = self._smmlv_de_hoy()
        self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                        json={"salario_mensual": 1_200_000, "salario_en_smmlv": 1.0})
        cath = self._contratos_api()["Catherin"]
        # El mensual queda como referencia informativa, pero no es lo que gana.
        self.assertEqual(cath["salario_mensual"], 1_200_000)
        self.assertEqual(cath["salario_resuelto"], minimo)

    def test_null_explicito_vuelve_a_pesos_fijos(self):
        self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                        json={"salario_mensual": 0, "salario_en_smmlv": 1.0})
        r = self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                            json={"salario_mensual": 2_400_000, "salario_en_smmlv": None})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["salario_en_smmlv"])
        self.assertEqual(r.json()["salario_resuelto"], 2_400_000)
        self.assertIsNone(self._contrato_de(self.cath.id).salario_en_smmlv)

    def test_un_formulario_que_no_conoce_el_campo_no_desata_del_minimo(self):
        """Regresión: si el PUT reemplazara TODO, un cliente viejo —o cualquier
        pantalla que no mande el campo— devolvería a pesos fijos, en silencio, a
        la persona que el dueño acababa de ajustar al mínimo."""
        minimo = self._smmlv_de_hoy()
        self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                        json={"salario_mensual": 0, "salario_en_smmlv": 1.0})

        r = self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                            json={"salario_mensual": 1_500_000, "activo": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["salario_en_smmlv"], 1.0)
        self.assertEqual(r.json()["salario_resuelto"], minimo)

    def test_cien_minimos_o_un_negativo_no_pasan_y_no_pisan_lo_guardado(self):
        self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                        json={"salario_mensual": 0, "salario_en_smmlv": 1.0})
        for valor in (100, -1):
            r = self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                                json={"salario_mensual": 0, "salario_en_smmlv": valor})
            self.assertEqual(r.status_code, 400, f"salario_en_smmlv={valor}: {r.text}")
        self.assertEqual(self._contrato_de(self.cath.id).salario_en_smmlv, 1.0)

    def test_cero_se_guarda_como_pesos_fijos_y_no_como_cero(self):
        """Un 0.0 en la columna diría «atada al mínimo» y liquidaría por pesos:
        un valor que dice una cosa y hace otra."""
        r = self.client.put(f"/api/v1/horarios/contratos/{self.cath.id}",
                            json={"salario_mensual": 1_800_000, "salario_en_smmlv": 0})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["salario_en_smmlv"])
        self.assertIsNone(self._contrato_de(self.cath.id).salario_en_smmlv)
        self.assertEqual(r.json()["salario_resuelto"], 1_800_000)

    def test_sin_contrato_el_listado_no_inventa_un_sueldo(self):
        cath = self._contratos_api()["Catherin"]
        self.assertFalse(cath["tiene_contrato"])
        self.assertIsNone(cath["salario_en_smmlv"])
        self.assertEqual(cath["salario_resuelto"], 0.0)
        self.assertEqual(cath["smmlv_vigente"], self._smmlv_de_hoy())


class AjustarAlMinimoApiTest(_BaseApi):
    """La operación masiva: «ajustá la nómina de los baristas al SMMLV»."""

    def _ajustar(self, tienda_id=None):
        r = self.client.post("/api/v1/horarios/contratos/ajustar-al-minimo",
                             json={"tienda_id": tienda_id or self.t.id})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_deja_a_todas_las_activas_en_un_minimo(self):
        minimo = self._smmlv_de_hoy()
        # Una con contrato en pesos y otra sin contrato: la que no tiene fila es
        # justo la que se olvidaría si esto se hiciera de a una.
        self.client.put(f"/api/v1/horarios/contratos/{self.eli.id}",
                        json={"salario_mensual": 1_300_000})

        data = self._ajustar()
        self.assertEqual(data["ajustadas"], 2)
        self.assertEqual(data["smmlv_vigente"], minimo)
        self.assertEqual({b["nombre"] for b in data["baristas"]},
                         {"Catherin", "Eliana"})

        contratos = self._contratos_api()
        for nombre in ("Catherin", "Eliana"):
            self.assertEqual(contratos[nombre]["salario_en_smmlv"], 1.0, nombre)
            self.assertEqual(contratos[nombre]["salario_resuelto"], minimo, nombre)
        # El mensual anterior sobrevive como referencia de lo que ganaba.
        self.assertEqual(contratos["Eliana"]["salario_mensual"], 1_300_000)
        eli = [b for b in data["baristas"] if b["nombre"] == "Eliana"][0]
        self.assertEqual(eli["salario_anterior"], 1_300_000)
        self.assertEqual(eli["salario_nuevo"], minimo)

    def test_no_toca_el_contrato_inactivo_pero_lo_reporta(self):
        """Una barista dada de baja conserva su contrato apagado: reactivarle el
        sueldo desde acá le cambiaría los meses ya liquidados."""
        self.client.put(f"/api/v1/horarios/contratos/{self.eli.id}",
                        json={"salario_mensual": 1_100_000, "activo": False})

        data = self._ajustar()
        self.assertEqual(data["ajustadas"], 1)
        self.assertEqual({b["nombre"] for b in data["baristas"]}, {"Catherin"})
        self.assertEqual([o["nombre"] for o in data["omitidas"]], ["Eliana"])

        eli = self._contrato_de(self.eli.id)
        self.assertIsNone(eli.salario_en_smmlv)
        self.assertEqual(float(eli.salario_mensual), 1_100_000)

    def test_no_toca_a_la_que_ya_no_trabaja_en_la_sede(self):
        """Usuario inactivo: `baristas_de` ni la devuelve, así que no aparece ni
        siquiera entre las omitidas."""
        self.db.add(ContratoBarista(usuario_id=self.retirada.id,
                                    salario_mensual=900_000, activo=True))
        self.db.commit()

        data = self._ajustar()
        nombres = {b["nombre"] for b in data["baristas"]}
        nombres |= {o["nombre"] for o in data["omitidas"]}
        self.assertNotIn("Inés", nombres)
        self.assertIsNone(self._contrato_de(self.retirada.id).salario_en_smmlv)

    def test_correrlo_dos_veces_no_vuelve_a_ajustar_a_nadie(self):
        primera = self._ajustar()
        self.assertEqual(primera["ajustadas"], 2)
        self.assertEqual(primera["ya_estaban"], 0)

        segunda = self._ajustar()
        self.assertEqual(segunda["ajustadas"], 0)
        self.assertEqual(segunda["ya_estaban"], 2)
        # Sigue contestando "cuáles quedaron en el mínimo", que es lo que la
        # pantalla muestra después de correrlo.
        self.assertEqual(len(segunda["baristas"]), 2)

    def test_no_se_lleva_por_delante_a_la_otra_sede(self):
        otra = Tienda(nombre="Palmetto", direccion="y")
        self.db.add(otra)
        self.db.flush()
        ajena = Usuario(nombre="Laura", email="laura@t.co", password_hash="h",
                        rol=RolEnum.barista, tienda_id=otra.id, activo=True)
        self.db.add(ajena)
        self.db.commit()

        data = self._ajustar()
        self.assertNotIn("Laura", {b["nombre"] for b in data["baristas"]})
        self.assertIsNone(self._contrato_de(ajena.id))

    def test_la_sede_se_acepta_por_query_y_con_el_cuerpo_vacio(self):
        """Así es EXACTAMENTE como lo llama la pantalla (`SueldosPanel.tsx`):
        `api.post(url, null, {params: {tienda_id}})`. Exigir la sede en el body
        devolvía 422 y el botón no ajustaba a nadie, sin que ningún test de
        backend lo notara porque los dos lados están bien por separado."""
        minimo = self._smmlv_de_hoy()
        r = self.client.post("/api/v1/horarios/contratos/ajustar-al-minimo",
                             params={"tienda_id": self.t.id})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["tienda_id"], self.t.id)
        self.assertEqual(r.json()["ajustadas"], 2)

        contratos = self._contratos_api()
        self.assertEqual(contratos["Catherin"]["salario_resuelto"], minimo)
        self.assertEqual(contratos["Eliana"]["salario_resuelto"], minimo)

    def test_sin_sede_por_ningun_lado_no_ajusta_nada(self):
        r = self.client.post("/api/v1/horarios/contratos/ajustar-al-minimo")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIsNone(self._contrato_de(self.cath.id))

    def test_la_barista_no_puede_ajustar_la_nomina(self):
        self._como(self.cath)
        r = self.client.post("/api/v1/horarios/contratos/ajustar-al-minimo",
                             json={"tienda_id": self.t.id})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
