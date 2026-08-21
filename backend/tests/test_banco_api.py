"""El router del banco sobre HTTP real (TestClient), con una DB temporal.

Monta SOLO el router del módulo con las dependencias de auth/DB sobreescritas: no
importa app.main a propósito, porque ese módulo siembra y migra contra la base de
verdad al importarse. Lo que se prueba acá es el CONTRATO HTTP —códigos, formas de
payload y permisos—; la fórmula del libro ya tiene sus tests en test_banco.py.

Lo que más importa de esta tanda son los 400: cada validación del servicio tiene
que llegar a la pantalla como un mensaje que el dueño pueda leer, no como un 500
ni como un "datos inválidos" que no dice qué corregir.
"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user, require_admin
from app.core.tz import hoy_col
from app.database import Base, get_db
from app.models.models import (Configuracion, CostoCategoria, CuentaBancaria,
                               Obligacion, RolEnum, Tienda, Usuario)
from app.routers import banco as router_banco
from app.services import banco


class BancoApiBase(unittest.TestCase):
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
        self.db.add_all([self.admin, self.cath])
        self.db.commit()

        banco.sembrar_cuentas(self.db)
        self.occ, self.bold = banco.cuentas(self.db)

        app = FastAPI()
        app.include_router(router_banco.router, prefix="/api/v1")
        self.app = app
        self._como(self.admin)
        self.client = TestClient(app)

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

    # ── Helpers ─────────────────────────────────────────────────────────────

    def anclar(self, saldo, fecha):
        """Escribe el ancla por HTTP: es el camino que usa la pantalla."""
        r = self.client.put("/api/v1/banco/ancla",
                            json={"saldo": saldo, "fecha": fecha.isoformat()})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def mover(self, fecha, tipo, monto, cuenta=None, concepto="Consignación", **extra):
        cuerpo = {"fecha": fecha.isoformat(), "cuenta_id": (cuenta or self.occ).id,
                  "tipo": tipo, "monto": monto, "concepto": concepto}
        cuerpo.update(extra)
        return self.client.post("/api/v1/banco/movimientos", json=cuerpo)

    def crudo(self, metodo, ruta, cuerpo):
        """Manda el cuerpo serializado a mano con `json.dumps` (allow_nan por
        defecto) porque httpx se niega a mandar inf/NaN. Sin esto, el caso más
        peligroso —el valor que revienta al serializar— nunca llegaría al
        servidor, que es justo lo que hay que probar. El `json.loads` de Starlette
        sí acepta los literales Infinity/NaN, igual que un cliente real que los
        mande. Mismo patrón que test_costos_flujo.py."""
        return self.client.request(metodo, ruta, content=json.dumps(cuerpo),
                                   headers={"content-type": "application/json"})

    def libro(self, anio, mes):
        r = self.client.get("/api/v1/banco/libro",
                            params={"anio": anio, "mes": mes})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def dia(self, lib, fecha):
        return [d for d in lib["dias"] if d["fecha"] == fecha.isoformat()][0]


class ElLibroLlegaEnteroTest(BancoApiBase):
    def test_el_mes_completo_con_su_fila_por_dia(self):
        lib = self.libro(2026, 8)
        self.assertEqual(len(lib["dias"]), 31)
        self.assertEqual(lib["desde"], "2026-08-01")
        self.assertEqual(lib["hasta"], "2026-08-31")
        # La forma que la pantalla necesita para dibujar la fila entera.
        for clave in ("fecha", "inicial", "entradas", "total_entradas", "salidas",
                      "total_salidas", "final", "en_rojo", "movimientos"):
            self.assertIn(clave, lib["dias"][0])
        for clave in ("entradas", "salidas", "final", "dias_en_rojo", "dia_mas_bajo"):
            self.assertIn(clave, lib["totales"])

    def test_sin_anio_ni_mes_devuelve_el_mes_de_hoy(self):
        r = self.client.get("/api/v1/banco/libro")
        self.assertEqual(r.status_code, 200, r.text)
        hoy = hoy_col()
        self.assertEqual(r.json()["desde"], date(hoy.year, hoy.month, 1).isoformat())

    def test_sin_ancla_el_libro_DECLARA_que_no_hay_cadena(self):
        """En false, los saldos de la serie no se pueden creer. La pantalla lo
        tiene que decir en vez de pintarlos."""
        lib = self.libro(2026, 8)
        self.assertFalse(lib["cadena_completa"])
        self.assertIsNone(lib["ancla"]["fecha"])

    def test_con_ancla_la_cadena_se_declara_completa_y_el_mes_arranca_ahi(self):
        self.anclar(1_000_000, date(2026, 8, 1))
        lib = self.libro(2026, 8)
        self.assertTrue(lib["cadena_completa"])
        self.assertAlmostEqual(self.dia(lib, date(2026, 8, 1))["inicial"], 1_000_000)

    def test_las_cuentas_del_libro_traen_la_columna_de_cada_riel(self):
        lib = self.libro(2026, 8)
        self.assertEqual({c["nombre"] for c in lib["cuentas"]}, {"Occidente", "Bold"})


class ElRoundTripDeUnMovimientoTest(BancoApiBase):
    def test_cargar_borrar_y_el_saldo_se_reacomoda_solo(self):
        self.anclar(1_000_000, date(2026, 8, 1))

        r = self.mover(date(2026, 8, 2), banco.SALIDA, 300_000, concepto="Pago café")
        self.assertEqual(r.status_code, 200, r.text)
        creado = r.json()
        self.assertEqual(creado["tipo"], "salida")
        self.assertAlmostEqual(creado["monto"], 300_000)
        self.assertEqual(creado["cuenta"], "Occidente")
        self.assertFalse(creado["automatico"])

        lib = self.libro(2026, 8)
        d2 = self.dia(lib, date(2026, 8, 2))
        self.assertAlmostEqual(d2["total_salidas"], 300_000)
        self.assertAlmostEqual(d2["final"], 700_000)
        self.assertAlmostEqual(self.dia(lib, date(2026, 8, 31))["final"], 700_000)
        # El movimiento del POST tiene la MISMA forma que el de adentro del día.
        self.assertEqual(d2["movimientos"], [creado])

        r = self.client.delete(f"/api/v1/banco/movimientos/{creado['id']}")
        self.assertEqual(r.status_code, 200, r.text)
        lib = self.libro(2026, 8)
        self.assertAlmostEqual(self.dia(lib, date(2026, 8, 31))["final"], 1_000_000)

    def test_las_entradas_llegan_abiertas_por_cuenta(self):
        self.anclar(0, date(2026, 8, 1))
        self.mover(date(2026, 8, 2), banco.ENTRADA, 1_000_000, self.occ)
        self.mover(date(2026, 8, 2), banco.ENTRADA, 500_000, self.bold)
        d = self.dia(self.libro(2026, 8), date(2026, 8, 2))
        self.assertAlmostEqual(d["entradas"]["Occidente"], 1_000_000)
        self.assertAlmostEqual(d["entradas"]["Bold"], 500_000)
        self.assertAlmostEqual(d["total_entradas"], 1_500_000)

    def test_el_cliente_NO_puede_marcar_un_movimiento_como_automatico(self):
        """`automatico` distingue lo que el sistema sugirió de lo que el dueño
        tecleó. Si el cliente pudiera prenderla, dejaría de significar nada."""
        r = self.mover(date(2026, 8, 2), banco.ENTRADA, 1000, automatico=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["automatico"])

    def test_un_movimiento_puede_quedar_atado_a_una_obligacion(self):
        cat = CostoCategoria(clave="arriendo", nombre="Arriendo", grupo="fijo", orden=0)
        self.db.add(cat)
        self.db.flush()
        ob = Obligacion(categoria_id=cat.id, concepto="Arriendo agosto", monto=2_000_000,
                        fecha_devengo=date(2026, 8, 1), tienda_id=self.t.id,
                        usuario_id=self.admin.id)
        self.db.add(ob)
        self.db.commit()

        r = self.mover(date(2026, 8, 5), banco.SALIDA, 2_000_000,
                       concepto="Arriendo", obligacion_id=ob.id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["obligacion_id"], ob.id)

    def test_borrar_algo_que_no_existe_da_404(self):
        r = self.client.delete("/api/v1/banco/movimientos/9999")
        self.assertEqual(r.status_code, 404)
        self.assertIn("no existe", r.json()["detail"])


class CadaValidacionLlegaComo400Test(BancoApiBase):
    """Con su mensaje, que ya está escrito para que lo lea el dueño."""

    def test_un_tipo_inventado(self):
        r = self.mover(date(2026, 8, 1), "transferencia", 1000)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("entrada", r.json()["detail"])

    def test_un_monto_negativo(self):
        r = self.mover(date(2026, 8, 1), banco.SALIDA, -100_000)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("positivo", r.json()["detail"])

    def test_un_monto_en_cero(self):
        r = self.mover(date(2026, 8, 1), banco.ENTRADA, 0)
        self.assertEqual(r.status_code, 400, r.text)

    def test_un_movimiento_sin_concepto(self):
        r = self.mover(date(2026, 8, 1), banco.ENTRADA, 1000, concepto="   ")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("conciliar", r.json()["detail"])

    def test_una_cuenta_que_no_existe(self):
        r = self.client.post("/api/v1/banco/movimientos", json={
            "fecha": "2026-08-01", "cuenta_id": 9999, "tipo": banco.ENTRADA,
            "monto": 1000, "concepto": "x"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("cuenta", r.json()["detail"].lower())

    def test_una_obligacion_que_no_existe(self):
        r = self.mover(date(2026, 8, 1), banco.SALIDA, 1000, obligacion_id=9999)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("obligación", r.json()["detail"].lower())

    def test_un_monto_que_no_es_un_numero(self):
        """Un `Infinity` solo puede llegar por JSON, y guardado envenena TODO
        saldo posterior — no solo esta escritura."""
        for valor in (float("inf"), float("-inf"), float("nan")):
            r = self.crudo("POST", "/api/v1/banco/movimientos", {
                "fecha": "2026-08-01", "cuenta_id": self.occ.id,
                "tipo": banco.ENTRADA, "monto": valor, "concepto": "x"})
            self.assertEqual(r.status_code, 400, f"{valor}: {r.text}")

    def test_un_monto_con_un_cero_de_mas(self):
        """Más de lo que entra en Numeric(12,2): en Postgres sería un 500."""
        r = self.mover(date(2026, 8, 1), banco.ENTRADA, 1e15)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("ceros", r.json()["detail"])

    def test_un_mes_que_no_existe(self):
        r = self.client.get("/api/v1/banco/libro", params={"anio": 2026, "mes": 13})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Mes", r.json()["detail"])

    def test_un_anio_fuera_de_rango_en_el_libro(self):
        r = self.client.get("/api/v1/banco/libro", params={"anio": 20260, "mes": 8})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Año", r.json()["detail"])

    def test_un_anio_fuera_de_rango_en_la_serie(self):
        r = self.client.get("/api/v1/banco/serie", params={"anio": 0})
        self.assertEqual(r.status_code, 400, r.text)

    def test_un_ancla_negativa(self):
        r = self.client.put("/api/v1/banco/ancla", json={"saldo": -5})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("negativo", r.json()["detail"])

    def test_un_ancla_que_no_es_un_numero(self):
        for valor in (float("inf"), float("-inf"), float("nan")):
            r = self.crudo("PUT", "/api/v1/banco/ancla", {"saldo": valor})
            self.assertEqual(r.status_code, 400, f"{valor}: {r.text}")

    def test_un_ancla_demasiado_grande(self):
        r = self.client.put("/api/v1/banco/ancla", json={"saldo": 1e13})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("grande", r.json()["detail"])

    def test_un_ancla_con_fecha_futura(self):
        manana = (hoy_col() + timedelta(days=1)).isoformat()
        r = self.client.put("/api/v1/banco/ancla",
                            json={"saldo": 1000, "fecha": manana})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("futura", r.json()["detail"])

    def test_ninguna_validacion_rechazada_deja_rastro(self):
        """Un 400 no puede haber escrito nada: si el movimiento quedara cargado,
        el saldo del mes estaría mal justo cuando la pantalla mostró un error."""
        self.anclar(1_000_000, date(2026, 8, 1))
        self.mover(date(2026, 8, 2), banco.SALIDA, -100_000)
        self.mover(date(2026, 8, 2), "transferencia", 100_000)
        self.mover(date(2026, 8, 2), banco.ENTRADA, 100_000, concepto="  ")
        lib = self.libro(2026, 8)
        self.assertEqual(lib["totales"]["entradas"], 0)
        self.assertEqual(lib["totales"]["salidas"], 0)
        self.assertAlmostEqual(self.dia(lib, date(2026, 8, 31))["final"], 1_000_000)


class ElLibroPorSedeSobreHTTPTest(BancoApiBase):
    """El contrato HTTP del libro por sede: ancla por sede, el candado que pide la
    sede desde agosto, y el filtro por `tienda_id`."""

    def test_ancla_por_sede_prende_el_modo_y_pide_la_sede(self):
        from datetime import date
        # Antes de arrancar: un movimiento de agosto SIN sede entra igual.
        r = self.mover(date(2026, 8, 2), banco.ENTRADA, 100_000, concepto="x")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(self.libro(2026, 8)["por_sede"])

        # Cargar el ancla de una sede prende el modo por sede.
        r = self.client.put("/api/v1/banco/ancla",
                            json={"saldo": 1_000_000, "fecha": "2026-08-01",
                                  "tienda_id": self.t.id})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.libro(2026, 8)["por_sede"])

        # Ahora un movimiento de agosto SIN sede rebota, legible.
        r = self.mover(date(2026, 8, 3), banco.ENTRADA, 50_000, concepto="x")
        self.assertEqual(r.status_code, 400)
        self.assertIn("sede", r.json()["detail"].lower())

        # Con la sede, entra, y el libro de esa sede lo muestra.
        r = self.mover(date(2026, 8, 3), banco.ENTRADA, 50_000, concepto="x",
                       tienda_id=self.t.id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["tienda_id"], self.t.id)
        r = self.client.get("/api/v1/banco/libro",
                            params={"anio": 2026, "mes": 8, "tienda_id": self.t.id})
        self.assertEqual(r.status_code, 200, r.text)
        d = [x for x in r.json()["dias"] if x["fecha"] == "2026-08-03"][0]
        self.assertEqual(d["total_entradas"], 50_000)

    def test_una_sede_que_no_existe_en_el_ancla_rebota(self):
        r = self.client.put("/api/v1/banco/ancla",
                            json={"saldo": 1000, "fecha": "2026-08-01", "tienda_id": 9999})
        self.assertEqual(r.status_code, 400)
        self.assertIn("sede", r.json()["detail"].lower())


class ElAnclaSeEditaDesdeAcaTest(BancoApiBase):
    def test_guarda_las_dos_claves_de_configuracion(self):
        """Las MISMAS que escribe POST /costos/saldo-banco: dos escritores con
        reglas distintas sobre la misma fila darían dos verdades según por qué
        pantalla se entró."""
        self.anclar(2_025_023, date(2026, 8, 1))
        # La escritura pasó por OTRA sesión (la del request): sin cerrar la
        # transacción de lectura de esta, el assert podría mirar una foto vieja.
        self.db.rollback()
        filas = {c.clave: c.valor for c in self.db.query(Configuracion).all()}
        self.assertEqual(filas[banco.CLAVE_SALDO], "2025023.0")
        self.assertEqual(filas[banco.CLAVE_SALDO_FECHA], "2026-08-01")

    def test_contesta_con_lo_que_QUEDO_guardado(self):
        cuerpo = self.anclar(2_025_023, date(2026, 8, 1))
        self.assertAlmostEqual(cuerpo["saldo"], 2_025_023)
        self.assertEqual(cuerpo["fecha"], "2026-08-01")
        self.assertIsNotNone(cuerpo["dias_desde"])

    def test_un_ancla_de_hoy_no_esta_desactualizada(self):
        cuerpo = self.anclar(1_000_000, hoy_col())
        self.assertEqual(cuerpo["dias_desde"], 0)
        self.assertFalse(cuerpo["desactualizado"])

    def test_un_ancla_vieja_se_declara_desactualizada(self):
        cuerpo = self.anclar(1_000_000, hoy_col() - timedelta(days=30))
        self.assertEqual(cuerpo["dias_desde"], 30)
        self.assertTrue(cuerpo["desactualizado"])

    def test_reescribirla_mueve_el_libro_entero(self):
        self.anclar(1_000_000, date(2026, 8, 1))
        self.anclar(3_000_000, date(2026, 8, 1))
        self.assertAlmostEqual(
            self.dia(self.libro(2026, 8), date(2026, 8, 1))["inicial"], 3_000_000)


class LaSerieDelAnioTest(BancoApiBase):
    def test_los_doce_meses_con_lo_que_entra_y_lo_que_sale(self):
        self.anclar(0, date(2026, 1, 1))
        self.mover(date(2026, 3, 10), banco.ENTRADA, 5_000_000)
        self.mover(date(2026, 3, 20), banco.SALIDA, 2_000_000)
        r = self.client.get("/api/v1/banco/serie", params={"anio": 2026})
        self.assertEqual(r.status_code, 200, r.text)
        meses = r.json()["meses"]
        self.assertEqual(len(meses), 12)
        marzo = meses[2]
        self.assertAlmostEqual(marzo["entradas"], 5_000_000)
        self.assertAlmostEqual(marzo["salidas"], 2_000_000)
        self.assertAlmostEqual(marzo["neto"], 3_000_000)
        self.assertAlmostEqual(marzo["cierre"], 3_000_000)

    def test_sin_ancla_el_cierre_de_cada_mes_viene_en_null(self):
        """Null es "no se sabe", que es distinto de un cierre en cero."""
        r = self.client.get("/api/v1/banco/serie", params={"anio": 2026})
        self.assertTrue(all(m["cierre"] is None for m in r.json()["meses"]))

    def test_sin_anio_devuelve_el_de_hoy(self):
        r = self.client.get("/api/v1/banco/serie")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["anio"], hoy_col().year)


class LasCuentasTest(BancoApiBase):
    def test_lista_los_rieles_con_su_nota(self):
        r = self.client.get("/api/v1/banco/cuentas")
        self.assertEqual(r.status_code, 200, r.text)
        cuentas = r.json()
        self.assertEqual({c["nombre"] for c in cuentas}, {"Occidente", "Bold"})
        self.assertTrue(all(c["nota"] for c in cuentas))
        self.assertTrue(all(c["activa"] for c in cuentas))

    def test_con_solo_activas_false_tambien_trae_las_apagadas(self):
        self.db.query(CuentaBancaria).filter_by(id=self.bold.id).update({"activa": False})
        self.db.commit()
        activas = self.client.get("/api/v1/banco/cuentas").json()
        todas = self.client.get("/api/v1/banco/cuentas",
                                params={"solo_activas": "false"}).json()
        self.assertEqual(len(activas), 1)
        self.assertEqual(len(todas), 2)


class SoloElAdminEntraTest(BancoApiBase):
    """El saldo del banco no es información de turno."""

    def test_la_barista_no_entra_a_ninguna_ruta(self):
        self._como(self.cath)
        self.assertEqual(self.client.get("/api/v1/banco/libro").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/banco/serie").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/banco/cuentas").status_code, 403)
        self.assertEqual(self.client.post("/api/v1/banco/movimientos", json={
            "fecha": "2026-08-01", "cuenta_id": self.occ.id, "tipo": banco.ENTRADA,
            "monto": 1000, "concepto": "x"}).status_code, 403)
        self.assertEqual(
            self.client.delete("/api/v1/banco/movimientos/1").status_code, 403)
        self.assertEqual(self.client.put("/api/v1/banco/ancla",
                                         json={"saldo": 1000}).status_code, 403)

    def test_la_barista_tampoco_alcanza_a_escribir_nada(self):
        self._como(self.cath)
        self.client.put("/api/v1/banco/ancla", json={"saldo": 9_999_999})
        self.client.post("/api/v1/banco/movimientos", json={
            "fecha": "2026-08-01", "cuenta_id": self.occ.id, "tipo": banco.ENTRADA,
            "monto": 1000, "concepto": "x"})
        self._como(self.admin)
        lib = self.libro(2026, 8)
        self.assertFalse(lib["cadena_completa"])
        self.assertEqual(lib["totales"]["entradas"], 0)


class ElRechazoTIENE_QUE_SER_LEGIBLETest(BancoApiBase):
    """Un 500 no dice qué corregir; un 422 mudo tampoco.

    La primera versión de estos tests verificaba el CÓDIGO DE ESTADO —que está
    cerca de lo que importa— en vez del mensaje. Y el 422 de Pydantic trae
    `detail` como LISTA, que el cliente no sabe leer: al dueño le salía
    «Reintentá», invitándolo a repetir algo que va a fallar siempre igual. Lo
    que se pincha acá es que el texto LLEGUE.
    """

    def _detalle(self, r):
        """Lo que el cliente puede mostrar: solo sirve si `detail` es un string."""
        self.assertEqual(r.status_code, 400, r.text)
        det = r.json().get("detail")
        self.assertIsInstance(det, str, "un detail que no es texto no llega a la pantalla")
        return det

    def test_una_fecha_absurda_se_rechaza_diciendo_por_que(self):
        """9999-12-31 se guardaba y al releer el libro el loop desbordaba
        `date.max` con OverflowError: 500 sobre lo recién creado."""
        self.assertIn("2000", self._detalle(self.mover(date(1, 1, 1), "entrada", 1000)))

    def test_una_fecha_FUTURA_se_rechaza_y_explica_adonde_va(self):
        """El libro es plata que YA se movió. Un débito futuro bajaba el saldo
        del libro y NO bajaba el punto de quiebre, que solo mira la agenda."""
        from app.core.tz import hoy_col
        from datetime import timedelta
        d = self._detalle(self.mover(hoy_col() + timedelta(days=1), "salida", 1000))
        self.assertIn("Obligaciones", d)

    def test_hoy_SI_entra(self):
        from app.core.tz import hoy_col
        self.assertEqual(self.mover(hoy_col(), "entrada", 1000).status_code, 200)

    def test_un_concepto_larguisimo_dice_cual_es_el_tope(self):
        d = self._detalle(self.mover(date(2026, 8, 10), "entrada", 1000,
                                     concepto="x" * 500))
        self.assertIn("160", d)

    def test_un_concepto_de_160_entra(self):
        r = self.mover(date(2026, 8, 10), "entrada", 1000, concepto="x" * 160)
        self.assertEqual(r.status_code, 200, r.text)

    def test_una_nota_larguisima_dice_cual_es_el_tope(self):
        self.assertIn("300", self._detalle(
            self.mover(date(2026, 8, 10), "entrada", 1000, nota="y" * 900)))

    def test_un_rechazo_no_deja_nada_escrito(self):
        antes = self.client.get("/api/v1/banco/libro",
                                params={"anio": 2026, "mes": 8}).json()
        self.mover(date(1, 1, 1), "entrada", 1000)
        self.mover(date(2026, 8, 10), "entrada", 1000, concepto="x" * 500)
        despues = self.client.get("/api/v1/banco/libro",
                                  params={"anio": 2026, "mes": 8}).json()
        self.assertEqual(antes["totales"], despues["totales"])

    def test_el_ANCLA_tambien_corta_la_fecha_vieja(self):
        """Donde más pesa: el ancla es la raíz de la cadena. Con una fecha
        absurdamente vieja, TODOS los días de toda la historia quedaban
        marcados con saldo confiable y el cartel que explica desde cuándo se
        conoce el saldo desaparecía."""
        r = self.client.put("/api/v1/banco/ancla",
                            json={"saldo": 1000, "fecha": "0026-08-16"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIsInstance(r.json().get("detail"), str)


if __name__ == "__main__":
    unittest.main()
