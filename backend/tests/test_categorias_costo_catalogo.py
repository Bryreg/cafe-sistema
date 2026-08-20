"""El catálogo de categorías de costo: cómo se clasifica y cómo se amplía.

Dos cosas se fijan acá.

1. LA CLASIFICACIÓN. 'mantenimiento' y 'otros' nacieron en el grupo "variable" y
   estaba mal: variable significa que el costo SUBE CON LA VENTA, y arreglar el
   molino o pagarle al contador no sube porque se venda más. El error era mudo —
   `costos_fijos_devengados` (services/rentabilidad.py) suma solo el grupo
   "fijo", así que esa plata se caía del costo del mes sin que ninguna pantalla
   avisara. Y 'otros' es justo donde hoy caen publicidad, internet, domicilios,
   seguros y el contador.

   La corrección de las bases que ya existen corre UNA SOLA VEZ: desde que el
   catálogo se edita por API, un arreglo que se reaplicara en cada arranque le
   pisaría al dueño su decisión cada vez que se reinicia el servidor.

2. EL ALTA Y LA EDICIÓN. Hasta acá el catálogo eran seis filas sembradas al
   arrancar. La clave la deriva el sistema del nombre y NUNCA se edita: es lo que
   mantiene junta la plata vieja con la nueva cuando alguien renombra una
   categoría.

Andamiaje igual que `test_horarios_api.py` —router solo, DB temporal, auth
sobreescrita— y por el mismo motivo: importar `app.main` sembraría y migraría
contra la base de verdad.
"""
import os
import tempfile
import unittest
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_barista_actor, get_current_user, require_admin
from app.database import Base, get_db
from app.models.models import (
    Configuracion, CostoCategoria, Obligacion, RolEnum, Tienda, Usuario,
)
from app.routers import costos as router_costos
from app.services import costos as svc
from app.services.rentabilidad import get_rentabilidad


class _BaseApi(unittest.TestCase):
    """Una sede, un admin autenticado y el catálogo recién sembrado."""

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
        self.db.add(self.admin)
        self.db.commit()

        app = FastAPI()
        app.include_router(router_costos.router, prefix="/api/v1")
        uid = self.admin.id

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

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[require_admin] = _admin
        app.dependency_overrides[get_barista_actor] = lambda: (None, None)
        self.client = TestClient(app)
        self.hoy = date(2026, 8, 11)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def sembrar(self):
        return svc.sembrar_categorias(self.db)

    def categoria(self, clave):
        return self.db.query(CostoCategoria).filter(
            CostoCategoria.clave == clave).first()

    def obligacion(self, categoria, monto, devengo=None):
        self.db.add(Obligacion(tienda_id=self.t.id, categoria_id=categoria.id,
                               concepto="Cargada a mano", monto=monto,
                               fecha_devengo=devengo or self.hoy,
                               usuario_id=self.admin.id, anulada=False))
        self.db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# (c) LA CLASIFICACIÓN: mantenimiento y otros son costos FIJOS
# ═══════════════════════════════════════════════════════════════════════════════

class CatalogoSembradoTest(_BaseApi):
    def test_una_base_nueva_nace_con_las_seis_categorias_en_fijo(self):
        self.assertEqual(self.sembrar(), 6)
        grupos = {c.clave: c.grupo for c in self.db.query(CostoCategoria).all()}
        self.assertEqual(set(grupos.values()), {"fijo"})

    def test_mantenimiento_y_otros_nacen_fijos(self):
        self.sembrar()
        self.assertEqual(self.categoria("mantenimiento").grupo, "fijo")
        self.assertEqual(self.categoria("otros").grupo, "fijo")

    def test_sembrar_dos_veces_no_duplica_ni_repisa(self):
        self.sembrar()
        self.categoria("otros").nombre = "Varios"
        self.db.commit()
        self.assertEqual(self.sembrar(), 0)
        self.assertEqual(self.categoria("otros").nombre, "Varios")

    def test_proveedores_no_se_siembra(self):
        """La trampa de doble conteo no vuelve por la puerta del catálogo."""
        self.sembrar()
        self.assertIsNone(self.categoria("proveedores"))


class ReclasificacionTest(_BaseApi):
    """La corrección de las bases que ya operan, donde las dos filas existen."""

    def sembrar_como_estaba(self):
        """El catálogo VIEJO: mantenimiento y otros en 'variable'."""
        self.db.add_all([
            CostoCategoria(clave="arriendo", nombre="Arriendo", grupo="fijo", orden=0),
            CostoCategoria(clave="mantenimiento", nombre="Mantenimiento",
                           grupo="variable", orden=3),
            CostoCategoria(clave="otros", nombre="Otros", grupo="variable", orden=5),
        ])
        self.db.commit()

    def test_las_mueve_a_fijo(self):
        self.sembrar_como_estaba()
        self.assertEqual(svc.reclasificar_grupos_v1(self.db), 2)
        self.assertEqual(self.categoria("mantenimiento").grupo, "fijo")
        self.assertEqual(self.categoria("otros").grupo, "fijo")

    def test_no_toca_las_demas(self):
        self.sembrar_como_estaba()
        svc.reclasificar_grupos_v1(self.db)
        self.assertEqual(self.categoria("arriendo").grupo, "fijo")

    def test_corre_una_sola_vez(self):
        """La segunda corrida no hace nada: la marca en `configuracion` es lo que
        permite que el dueño después reclasifique a mano sin que el próximo
        deploy le deshaga el cambio."""
        self.sembrar_como_estaba()
        self.assertEqual(svc.reclasificar_grupos_v1(self.db), 2)
        self.assertEqual(svc.reclasificar_grupos_v1(self.db), 0)

    def test_una_decision_del_dueno_sobrevive_al_reinicio(self):
        """EL MOTIVO de que esto sea one-shot: si «Otros» fuera de verdad
        variable en este negocio, el arreglo no puede volver a pisarlo cada vez
        que arranca el servidor."""
        self.sembrar_como_estaba()
        svc.reclasificar_grupos_v1(self.db)
        self.categoria("otros").grupo = "variable"
        self.db.commit()
        svc.reclasificar_grupos_v1(self.db)
        self.assertEqual(self.categoria("otros").grupo, "variable")

    def test_deja_la_marca_aunque_no_hubiera_nada_que_corregir(self):
        """Una base ya sembrada bien no tiene filas para mover, y aun así la
        migración queda cerrada: si no, quedaría pendiente para siempre."""
        self.sembrar()
        self.assertEqual(svc.reclasificar_grupos_v1(self.db), 0)
        marca = self.db.query(Configuracion).filter(
            Configuracion.clave == svc.RECLASIFICACION_GRUPOS_V1).first()
        self.assertIsNotNone(marca)


class ElGrupoDecideElPisoTest(_BaseApi):
    """Por qué la clasificación importa: solo el grupo "fijo" arma el piso.

    Esto es lo que hacía que el error fuera mudo — la plata seguía en el total de
    gastos, pero desaparecía del número que dice cuánto hay que vender para no
    perder.
    """

    def test_un_gasto_de_mantenimiento_ahora_entra_al_piso_del_mes(self):
        self.sembrar()
        self.obligacion(self.categoria("mantenimiento"), 500_000.0)
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        self.assertEqual(r["resumen"]["costos_fijos_devengados"], 500_000.0)
        self.assertTrue(r["resumen"]["tiene_costos_fijos"])

    def test_lo_que_cae_en_otros_tambien(self):
        """Publicidad, internet, domicilios, seguros y el contador caen todos
        acá hasta que el dueño les cree su categoría."""
        self.sembrar()
        self.obligacion(self.categoria("otros"), 1_200_000.0)
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        self.assertEqual(r["resumen"]["costos_fijos_devengados"], 1_200_000.0)

    def test_clasificada_como_variable_esa_misma_plata_se_cae_del_piso(self):
        """La prueba de que el grupo no es una etiqueta decorativa: el gasto
        sigue en `gastos` y desaparece del piso. Es exactamente lo que pasaba."""
        self.sembrar()
        self.categoria("otros").grupo = "variable"
        self.db.commit()
        self.obligacion(self.categoria("otros"), 1_200_000.0)
        r = get_rentabilidad(self.db, self.hoy, self.hoy)
        self.assertEqual(r["resumen"]["gastos"], 1_200_000.0)
        self.assertEqual(r["resumen"]["costos_fijos_devengados"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# (d) CREAR Y EDITAR CATEGORÍAS
# ═══════════════════════════════════════════════════════════════════════════════

class CrearCategoriaTest(_BaseApi):
    def setUp(self):
        super().setUp()
        self.sembrar()

    def test_crea_con_grupo_fijo_por_defecto(self):
        r = self.client.post("/api/v1/costos/categorias", json={"nombre": "Publicidad"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["grupo"], "fijo")

    def test_la_clave_se_deriva_del_nombre_sin_tildes_ni_espacios(self):
        r = self.client.post("/api/v1/costos/categorias",
                             json={"nombre": "Servicios Públicos"})
        self.assertEqual(r.json()["clave"], "servicios_publicos")

    def test_aparece_en_el_catalogo_que_lee_el_formulario(self):
        self.client.post("/api/v1/costos/categorias", json={"nombre": "Internet"})
        claves = [c["clave"] for c in self.client.get("/api/v1/costos/categorias").json()]
        self.assertIn("internet", claves)

    def test_sirve_para_cargar_una_obligacion(self):
        """La prueba de que la categoría nueva no es decorativa: pasa la puerta
        de `_validar_categoria` y su plata entra al piso del mes."""
        cid = self.client.post("/api/v1/costos/categorias",
                               json={"nombre": "Contador"}).json()["id"]
        r = self.client.post("/api/v1/costos/obligaciones", json={
            "categoria_id": cid, "concepto": "Honorarios agosto",
            "monto": 800_000.0, "fecha_devengo": self.hoy.isoformat(),
            "tienda_id": self.t.id})
        self.assertEqual(r.status_code, 200)
        pl = get_rentabilidad(self.db, self.hoy, self.hoy)
        self.assertEqual(pl["resumen"]["costos_fijos_devengados"], 800_000.0)

    def test_el_nombre_vacio_rebota_con_400_y_un_texto(self):
        """400 y no 422: el `detail` de un 422 es una LISTA y el cliente solo
        sabe leer strings — el dueño vería «error» pelado."""
        r = self.client.post("/api/v1/costos/categorias", json={"nombre": "   "})
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)

    def test_un_grupo_inventado_rebota_con_400_y_un_texto(self):
        r = self.client.post("/api/v1/costos/categorias",
                             json={"nombre": "Rifa", "grupo": "semifijo"})
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)

    def test_un_nombre_repetido_nombra_la_que_ya_esta(self):
        """Nada de sufijos automáticos: «otros_2» al lado de «Otros» es el texto
        libre que la clave estable vino a matar."""
        r = self.client.post("/api/v1/costos/categorias", json={"nombre": "Otros"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Otros", r.json()["detail"])

    def test_no_se_puede_recrear_proveedores(self):
        r = self.client.post("/api/v1/costos/categorias", json={"nombre": "Proveedores"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Compras", r.json()["detail"])

    def test_un_nombre_sin_letras_ni_numeros_rebota(self):
        r = self.client.post("/api/v1/costos/categorias", json={"nombre": "¿¡— !"})
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)

    def test_nada_se_guarda_cuando_el_alta_rebota(self):
        """Un 400 que igual escribió la fila es peor que no validar nada."""
        antes = self.db.query(CostoCategoria).count()
        self.client.post("/api/v1/costos/categorias", json={"nombre": ""})
        self.db.expire_all()
        self.assertEqual(self.db.query(CostoCategoria).count(), antes)


class ElFormularioExplicaLaDiferenciaTest(_BaseApi):
    """La copia sale del backend: es la MISMA regla que decide el piso del mes,
    así que la definición y el número tienen que salir del mismo archivo."""

    def test_el_catalogo_de_grupos_explica_los_dos(self):
        grupos = {g["clave"]: g for g in
                  self.client.get("/api/v1/costos/categorias/grupos").json()}
        self.assertEqual(set(grupos), {"fijo", "variable"})
        for g in grupos.values():
            self.assertTrue(g["que_es"].strip())

    def test_elegir_variable_trae_la_explicacion(self):
        """«Si alguien elige variable, que la pantalla lo explique»: el texto
        viaja con la respuesta para poder mostrarse justo después de guardar."""
        aviso = self.client.get("/api/v1/costos/categorias/grupos").json()
        variable = next(g for g in aviso if g["clave"] == "variable")
        self.assertIn("tasa", variable["advertencia"])

    def test_fijo_no_tiene_nada_que_advertir(self):
        fijo = next(g for g in self.client.get("/api/v1/costos/categorias/grupos").json()
                    if g["clave"] == "fijo")
        self.assertIsNone(fijo["advertencia"])

    def test_la_categoria_creada_como_variable_vuelve_con_la_advertencia(self):
        self.sembrar()
        r = self.client.post("/api/v1/costos/categorias",
                             json={"nombre": "Comisión datáfono", "grupo": "variable"})
        self.assertEqual(r.json()["grupo"], "variable")
        self.assertIsNotNone(r.json()["advertencia"])

    def test_la_creada_como_fija_vuelve_sin_advertencia(self):
        self.sembrar()
        r = self.client.post("/api/v1/costos/categorias", json={"nombre": "Seguros"})
        self.assertIsNone(r.json()["advertencia"])

    def test_la_lista_del_desplegable_no_cambio_de_forma(self):
        """La pantalla de Plata consume una LISTA pelada. Agregar la explicación
        no puede romperla: por eso vive en su propio endpoint."""
        self.sembrar()
        cats = self.client.get("/api/v1/costos/categorias").json()
        self.assertIsInstance(cats, list)
        self.assertEqual(set(cats[0]), {"id", "clave", "nombre", "grupo", "orden"})


class EditarCategoriaTest(_BaseApi):
    def setUp(self):
        super().setUp()
        self.sembrar()
        self.otros = self.categoria("otros")

    def test_cambia_el_grupo(self):
        r = self.client.patch(f"/api/v1/costos/categorias/{self.otros.id}",
                              json={"grupo": "variable"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["grupo"], "variable")

    def test_cambiar_el_grupo_recalcula_el_piso_del_historico(self):
        """No es solo para lo que venga: el P&L agrupa por grupo cada vez que se
        abre, así que una mala clasificación vieja se arregla de una."""
        self.obligacion(self.otros, 900_000.0)
        self.assertEqual(
            get_rentabilidad(self.db, self.hoy, self.hoy)["resumen"]["costos_fijos_devengados"],
            900_000.0)
        self.client.patch(f"/api/v1/costos/categorias/{self.otros.id}",
                          json={"grupo": "variable"})
        self.db.expire_all()
        self.assertEqual(
            get_rentabilidad(self.db, self.hoy, self.hoy)["resumen"]["costos_fijos_devengados"],
            0)

    def test_renombrar_no_mueve_la_clave(self):
        """LO IMPORTANTE de este PATCH: la clave es la identidad en el P&L. Si se
        recalculara al renombrar, el histórico se partiría en dos filas que el
        dueño lee como dos costos distintos."""
        r = self.client.patch(f"/api/v1/costos/categorias/{self.otros.id}",
                              json={"nombre": "Varios"})
        self.assertEqual(r.json()["nombre"], "Varios")
        self.assertEqual(r.json()["clave"], "otros")

    def test_renombrar_deja_la_plata_vieja_junta_con_la_nueva(self):
        self.obligacion(self.otros, 300_000.0)
        self.client.patch(f"/api/v1/costos/categorias/{self.otros.id}",
                          json={"nombre": "Varios"})
        self.obligacion(self.otros, 200_000.0)
        self.db.expire_all()
        por_cat = {c["clave"]: c for c in
                   get_rentabilidad(self.db, self.hoy, self.hoy)["gastos_por_categoria"]}
        self.assertEqual(por_cat["otros"]["total"], 500_000.0)
        self.assertEqual(por_cat["otros"]["n"], 2)

    def test_el_patch_solo_pisa_lo_que_llega(self):
        self.client.patch(f"/api/v1/costos/categorias/{self.otros.id}",
                          json={"grupo": "variable"})
        r = self.client.patch(f"/api/v1/costos/categorias/{self.otros.id}",
                              json={"nombre": "Varios"})
        self.assertEqual(r.json()["grupo"], "variable")

    def test_un_grupo_inventado_rebota_y_no_guarda_nada(self):
        r = self.client.patch(f"/api/v1/costos/categorias/{self.otros.id}",
                              json={"nombre": "Varios", "grupo": "medio_fijo"})
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.json()["detail"], str)
        self.db.expire_all()
        self.assertEqual(self.categoria("otros").nombre, "Otros")

    def test_una_categoria_inexistente_da_404(self):
        r = self.client.patch("/api/v1/costos/categorias/9999", json={"nombre": "X"})
        self.assertEqual(r.status_code, 404)

    def test_proveedores_no_se_edita(self):
        """La fila legacy se conserva para no dejar huérfanas sus obligaciones,
        pero no se le abre una puerta de vuelta al catálogo."""
        self.db.add(CostoCategoria(clave="proveedores", nombre="Proveedores",
                                   grupo="variable", orden=9))
        self.db.commit()
        cid = self.categoria("proveedores").id
        r = self.client.patch(f"/api/v1/costos/categorias/{cid}", json={"grupo": "fijo"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
