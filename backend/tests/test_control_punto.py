"""Control del punto — el Google Form «Control de Médium Café», en el sistema.

Había un formulario de Google POR SEDE, así que comparar Vida contra Palmetto
era abrir dos formularios y dos hojas de respuestas. Acá la sede es un campo.

El eje de estos tests es la distinción entre «no cumple» y «nadie lo revisó».
Son quince preguntas Sí/No y el formulario permitía dejarlas en blanco; si el
blanco se guardara como False, una revisión hecha a medias se leería como una
revisión con fallas, y el dueño saldría a corregir cosas que nadie verificó. Es
el mismo error que en el conteo mensual hacía pasar lo no contado por cuadrado.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (AuditoriaControlPunto, AuditoriaControlPuntoItem,
                               RolEnum, Tienda, Usuario)
from app.services import auditorias as svc


class ControlPuntoTest(unittest.TestCase):
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
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _todas(self, valor):
        return {k: valor for k in svc.CONTROL_PUNTO_KEYS}

    # ── El formato es el del formulario ───────────────────────────────────────
    def test_el_formato_tiene_las_cuatro_secciones_y_quince_preguntas(self):
        f = svc.get_control_punto_formato()
        self.assertEqual([s["nombre"] for s in f["secciones"]],
                         ["Operativo", "Máquina espresso", "Presentación personal",
                          "Administrativo"])
        self.assertEqual(f["total_preguntas"], 15)
        self.assertEqual(sum(len(s["preguntas"]) for s in f["secciones"]), 15)

    def test_las_preguntas_por_seccion_son_las_del_formulario(self):
        f = {s["key"]: [p["key"] for p in s["preguntas"]]
             for s in svc.get_control_punto_formato()["secciones"]}
        # «Formularios» y «Limpieza general» se movieron de espresso a operativo:
        # no son cosas de la máquina. Las CLAVES no cambiaron.
        self.assertEqual(len(f["operativo"]), 5)
        self.assertIn("formularios", f["operativo"])
        self.assertIn("limpieza_general", f["operativo"])
        self.assertEqual(len(f["espresso"]), 5)
        self.assertNotIn("formularios", f["espresso"])
        self.assertEqual(len(f["presentacion"]), 4)
        self.assertEqual(len(f["administrativo"]), 1)

    def test_las_claves_no_se_repiten(self):
        """Una clave repetida haría que dos preguntas compartan respuesta."""
        self.assertEqual(len(svc.CONTROL_PUNTO_KEYS), len(set(svc.CONTROL_PUNTO_KEYS)))

    # ── Sí / No / sin responder ───────────────────────────────────────────────
    def test_una_revision_completa_cuenta_bien(self):
        r = svc.crear_control_punto(self.db, self.palmetto.id, date.today(),
                                    self._todas(True), self.admin.id)
        self.assertEqual(r["cumplen"], 15)
        self.assertEqual(r["fallan"], 0)
        self.assertEqual(r["sin_responder"], 0)
        self.assertEqual(r["incumplidas"], [])

    def test_lo_no_respondido_NO_cuenta_como_falla(self):
        """El corazón del módulo: una revisión a medias no es una con fallas."""
        r = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    {"loza": True, "unas": False}, self.admin.id)
        self.assertEqual(r["cumplen"], 1)
        self.assertEqual(r["fallan"], 1)
        self.assertEqual(r["sin_responder"], 13)
        self.assertEqual([i["label"] for i in r["incumplidas"]],
                         ["Uñas cortas y sin esmalte"])

    def test_el_none_se_guarda_como_none_no_como_false(self):
        svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                {"loza": None}, self.admin.id)
        it = self.db.query(AuditoriaControlPuntoItem).filter_by(pregunta_key="loza").first()
        self.assertIsNone(it.cumple)

    def test_deja_una_fila_por_pregunta_del_formato(self):
        """Siempre las quince, aunque el cliente mande dos: así la cobertura se
        puede contar sin adivinar qué faltó."""
        svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                {"loza": True}, self.admin.id)
        self.assertEqual(self.db.query(AuditoriaControlPuntoItem).count(), 15)

    def test_una_clave_inventada_por_el_cliente_no_entra(self):
        r = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    {"loza": True, "clave_que_no_existe": False},
                                    self.admin.id)
        self.assertNotIn("clave_que_no_existe", r["respuestas"])
        self.assertEqual(r["fallan"], 0)
        claves = {it.pregunta_key for it in self.db.query(AuditoriaControlPuntoItem).all()}
        self.assertEqual(claves, set(svc.CONTROL_PUNTO_KEYS))

    def test_las_incumplidas_vienen_con_su_texto(self):
        """El dueño necesita QUÉ arreglar, no cuántas fallaron."""
        r = svc.crear_control_punto(self.db, self.palmetto.id, date.today(),
                                    {"past_rotulada": False, "uniforme": False,
                                     "loza": True}, self.admin.id)
        self.assertEqual([i["label"] for i in r["incumplidas"]],
                         ["Pastelería rotulada",
                          "Uniforme completo: gorra, camiseta, delantal y cofia"])

    # ── Las dos sedes ─────────────────────────────────────────────────────────
    def test_sirve_para_las_dos_sedes(self):
        svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                self._todas(True), self.admin.id)
        svc.crear_control_punto(self.db, self.palmetto.id, date.today(),
                                self._todas(False), self.admin.id)
        todas = svc.listar_control_punto(self.db)
        self.assertEqual({a["tienda_nombre"] for a in todas}, {"Vida", "Palmetto"})

    def test_se_puede_filtrar_por_sede(self):
        svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                self._todas(True), self.admin.id)
        svc.crear_control_punto(self.db, self.palmetto.id, date.today(),
                                self._todas(True), self.admin.id)
        solo = svc.listar_control_punto(self.db, self.palmetto.id)
        self.assertEqual(len(solo), 1)
        self.assertEqual(solo[0]["tienda_nombre"], "Palmetto")

    def test_el_historial_viene_del_mas_reciente(self):
        hoy = date.today()
        svc.crear_control_punto(self.db, self.vida.id, hoy - timedelta(days=7),
                                self._todas(True), self.admin.id)
        svc.crear_control_punto(self.db, self.vida.id, hoy,
                                self._todas(True), self.admin.id)
        fechas = [a["fecha_revision"] for a in svc.listar_control_punto(self.db)]
        self.assertEqual(fechas, [hoy.isoformat(), (hoy - timedelta(days=7)).isoformat()])

    # ── Fecha ─────────────────────────────────────────────────────────────────
    def test_una_fecha_futura_se_rechaza(self):
        """Una revisión no se puede haber hecho mañana."""
        with self.assertRaises(HTTPException):
            svc.crear_control_punto(self.db, self.vida.id, date.today() + timedelta(days=1),
                                    self._todas(True), self.admin.id)

    def test_se_puede_cargar_una_visita_de_ayer(self):
        r = svc.crear_control_punto(self.db, self.vida.id, date.today() - timedelta(days=1),
                                    self._todas(True), self.admin.id)
        self.assertEqual(r["fecha_revision"], (date.today() - timedelta(days=1)).isoformat())

    # ── Edición y VoBo ────────────────────────────────────────────────────────
    def test_editar_cambia_las_respuestas(self):
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    {"loza": False}, self.admin.id)
        r = svc.actualizar_control_punto(self.db, a["id"], self.vida.id,
                                         {"loza": True, "unas": False}, self.admin.id,
                                         observaciones="se corrigió en el momento")
        self.assertEqual(r["cumplen"], 1)
        self.assertEqual(r["fallan"], 1)
        self.assertEqual(r["observaciones"], "se corrigió en el momento")

    def test_editar_puede_devolver_una_respuesta_a_sin_responder(self):
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    {"loza": True}, self.admin.id)
        r = svc.actualizar_control_punto(self.db, a["id"], self.vida.id,
                                         {"loza": None}, self.admin.id)
        self.assertEqual(r["sin_responder"], 15)

    def test_despues_del_vobo_no_se_edita(self):
        """El registro tiene que seguir siendo lo que se revisó ese día."""
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    self._todas(True), self.admin.id)
        svc.vobo_control_punto(self.db, a["id"], self.vida.id, self.admin.id)
        with self.assertRaises(HTTPException):
            svc.actualizar_control_punto(self.db, a["id"], self.vida.id,
                                         self._todas(False), self.admin.id)

    def test_despues_del_vobo_no_se_elimina(self):
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    self._todas(True), self.admin.id)
        svc.vobo_control_punto(self.db, a["id"], self.vida.id, self.admin.id)
        with self.assertRaises(HTTPException):
            svc.eliminar_control_punto(self.db, a["id"], self.vida.id, self.admin.id)
        self.assertEqual(self.db.query(AuditoriaControlPunto).count(), 1)

    def test_el_vobo_es_idempotente(self):
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    self._todas(True), self.admin.id)
        p = svc.vobo_control_punto(self.db, a["id"], self.vida.id, self.admin.id)
        s = svc.vobo_control_punto(self.db, a["id"], self.vida.id, self.admin.id)
        self.assertEqual(p["vobo_fecha"], s["vobo_fecha"])

    def test_no_se_toca_la_auditoria_de_otra_sede(self):
        """El id viaja en la URL: sin el filtro de sede se podría editar la
        revisión de la otra sede pasando su número."""
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    self._todas(True), self.admin.id)
        with self.assertRaises(HTTPException) as ctx:
            svc.actualizar_control_punto(self.db, a["id"], self.palmetto.id,
                                         self._todas(False), self.admin.id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_eliminar_borra_tambien_sus_items(self):
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    self._todas(True), self.admin.id)
        svc.eliminar_control_punto(self.db, a["id"], self.vida.id, self.admin.id)
        self.assertEqual(self.db.query(AuditoriaControlPunto).count(), 0)
        self.assertEqual(self.db.query(AuditoriaControlPuntoItem).count(), 0)

    # ── Nota y foto por hallazgo ──────────────────────────────────────────────
    def test_la_nota_y_la_foto_viajan_con_el_hallazgo(self):
        """Un «No» en «Pastelería rotulada» no dice CUÁL. La nota sí."""
        r = svc.crear_control_punto(self.db, self.palmetto.id, date.today(), {
            "past_rotulada": {"cumple": False, "nota": "las 3 tortas sin fecha",
                              "foto_url": "https://ej/1.jpg"},
        }, self.admin.id)
        inc = r["incumplidas"][0]
        self.assertEqual(inc["nota"], "las 3 tortas sin fecha")
        self.assertEqual(inc["foto_url"], "https://ej/1.jpg")
        self.assertEqual(r["respuestas"]["past_rotulada"]["nota"], "las 3 tortas sin fecha")

    def test_el_booleano_suelto_sigue_funcionando(self):
        """Las pruebas y los scripts mandan el valor pelado; la pantalla manda
        objetos. Las dos formas entran."""
        r = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    {"loza": True, "unas": False}, self.admin.id)
        self.assertEqual(r["cumplen"], 1)
        self.assertEqual(r["fallan"], 1)

    def test_la_nota_no_se_borra_al_corregir(self):
        """Cuando el hallazgo pasa a Sí, el detalle de qué estaba mal es justo lo
        que se quiere releer en la visita siguiente."""
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(), {
            "loza": {"cumple": False, "nota": "tazas con residuo"}}, self.admin.id)
        r = svc.actualizar_control_punto(self.db, a["id"], self.vida.id,
                                          {"loza": {"cumple": True}}, self.admin.id)
        self.assertEqual(r["respuestas"]["loza"]["nota"], "tazas con residuo")
        self.assertEqual(r["cumplen"], 1)

    def test_la_nota_se_puede_vaciar_explicitamente(self):
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(), {
            "loza": {"cumple": False, "nota": "me equivoqué"}}, self.admin.id)
        r = svc.actualizar_control_punto(self.db, a["id"], self.vida.id,
                                          {"loza": {"cumple": False, "nota": ""}},
                                          self.admin.id)
        self.assertIsNone(r["respuestas"]["loza"]["nota"])

    def test_la_nota_larga_se_recorta_y_no_revienta(self):
        r = svc.crear_control_punto(self.db, self.vida.id, date.today(), {
            "loza": {"cumple": False, "nota": "x" * 900}}, self.admin.id)
        self.assertEqual(len(r["respuestas"]["loza"]["nota"]), 300)

    # ── La visita anterior ────────────────────────────────────────────────────
    def test_sin_visitas_anteriores_devuelve_nada(self):
        self.assertIsNone(svc.revision_anterior(self.db, self.vida.id))

    def test_la_anterior_trae_lo_que_fallo(self):
        """Una auditoría cuyas fallas nadie verifica en la visita siguiente es
        teatro: esto las pone delante de quien revisa."""
        svc.crear_control_punto(self.db, self.palmetto.id, date.today() - timedelta(days=8), {
            "past_rotulada": {"cumple": False, "nota": "tortas sin fecha"},
            "uniforme": False, "loza": True}, self.admin.id)
        ant = svc.revision_anterior(self.db, self.palmetto.id)
        self.assertEqual(ant["fallan"], 2)
        self.assertEqual([i["label"] for i in ant["incumplidas"]],
                         ["Pastelería rotulada",
                          "Uniforme completo: gorra, camiseta, delantal y cofia"])
        self.assertEqual(ant["incumplidas"][0]["nota"], "tortas sin fecha")

    def test_la_anterior_es_la_de_SU_sede(self):
        svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                self._todas(False), self.admin.id)
        self.assertIsNone(svc.revision_anterior(self.db, self.palmetto.id))

    def test_al_editar_la_anterior_no_es_ella_misma(self):
        vieja = svc.crear_control_punto(self.db, self.vida.id, date.today() - timedelta(days=7),
                                        {"loza": False}, self.admin.id)
        nueva = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                        {"loza": True}, self.admin.id)
        ant = svc.revision_anterior(self.db, self.vida.id, excluir_id=nueva["id"])
        self.assertEqual(ant["id"], vieja["id"])

    # ── Tendencia por pregunta ────────────────────────────────────────────────
    def test_la_tendencia_ordena_por_lo_que_mas_falla(self):
        """«El rotulado falla 3 de 3» y «falló una vez» piden cosas distintas."""
        hoy = date.today()
        for i in range(3):
            svc.crear_control_punto(self.db, self.palmetto.id, hoy - timedelta(days=i * 7),
                                    {"past_rotulada": False, "loza": True,
                                     "unas": True if i else False}, self.admin.id)
        t = svc.tendencia_control_punto(self.db, self.palmetto.id)
        self.assertEqual(t["visitas"], 3)
        primero = t["items"][0]
        self.assertEqual(primero["key"], "past_rotulada")
        self.assertEqual(primero["fallan"], 3)
        self.assertEqual(primero["respondidas"], 3)
        unas = next(i for i in t["items"] if i["key"] == "unas")
        self.assertEqual(unas["fallan"], 1)

    def test_el_denominador_es_lo_respondido_no_las_visitas(self):
        """Una pregunta contestada 2 veces y fallada las 2 es 2 de 2, no 2 de 9.
        Mezclarlas diría que casi nunca falla cuando casi nunca se revisa."""
        hoy = date.today()
        for i in range(5):
            respuestas = {"loza": True}
            if i < 2:
                respuestas["velinos"] = False
            svc.crear_control_punto(self.db, self.vida.id, hoy - timedelta(days=i),
                                    respuestas, self.admin.id)
        t = svc.tendencia_control_punto(self.db, self.vida.id)
        vel = next(i for i in t["items"] if i["key"] == "velinos")
        self.assertEqual((vel["fallan"], vel["respondidas"], vel["sin_responder"]), (2, 2, 3))

    def test_la_tendencia_solo_mira_las_ultimas_visitas_pedidas(self):
        hoy = date.today()
        for i in range(4):
            svc.crear_control_punto(self.db, self.vida.id, hoy - timedelta(days=i),
                                    {"loza": False}, self.admin.id)
        t = svc.tendencia_control_punto(self.db, self.vida.id, visitas=2)
        self.assertEqual(t["visitas"], 2)
        self.assertEqual(next(i for i in t["items"] if i["key"] == "loza")["fallan"], 2)

    def test_la_tendencia_sin_visitas_no_revienta(self):
        t = svc.tendencia_control_punto(self.db, self.vida.id)
        self.assertEqual(t["visitas"], 0)
        self.assertEqual(len(t["items"]), 15)
        self.assertTrue(all(i["fallan"] == 0 for i in t["items"]))

    # ── Una pregunta nueva no miente sobre el pasado ───────────────────────────
    def test_una_pregunta_nueva_sale_sin_responder_en_las_viejas(self):
        """Si mañana se agrega una pregunta al formato, las revisiones ya hechas
        no pueden mostrarla como cumplida ni como fallada: nadie la revisó."""
        a = svc.crear_control_punto(self.db, self.vida.id, date.today(),
                                    self._todas(True), self.admin.id)
        original = list(svc.CONTROL_PUNTO_SECCIONES)
        try:
            svc.CONTROL_PUNTO_SECCIONES.append(
                ("nueva", "Sección nueva", None, [("pregunta_nueva", "Algo nuevo")]))
            svc.CONTROL_PUNTO_KEYS.append("pregunta_nueva")
            vieja = svc.listar_control_punto(self.db, self.vida.id)[0]
            self.assertIsNone(vieja["respuestas"]["pregunta_nueva"]["cumple"])
            self.assertEqual(vieja["cumplen"], 15)
            self.assertEqual(vieja["sin_responder"], 1)
            self.assertEqual(vieja["total"], 16)
        finally:
            svc.CONTROL_PUNTO_SECCIONES[:] = original
            svc.CONTROL_PUNTO_KEYS.remove("pregunta_nueva")
        _ = a


if __name__ == "__main__":
    unittest.main()
