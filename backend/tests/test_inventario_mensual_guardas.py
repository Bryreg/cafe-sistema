"""Guardas del cierre de mes: hoy el módulo puede DESTRUIR la evidencia del
período con un clic y sin avisar.

  B1. `reabrir()` re-fotografía `cantidad_sistema` con el stock de HOY y pone las
      diferencias en 0 — también sobre un mes ya CERRADO. Reabrir julio en agosto
      borra irreversiblemente la fuga de julio: la foto del período se pisa con
      un stock que ya incorporó las ventas de agosto.
  B2. `cerrar()` rellena `cantidad_real` con el sistema para todo lo no contado.
      Después del cierre es imposible distinguir «contado y dio exacto» de «nadie
      lo contó»: la fuga queda escondida POR DEFINICIÓN, y un mes con 12 de 180
      productos contados se ve igual que uno contado completo.
  B3. `aplicar()` suma una diferencia congelada contra una foto posiblemente
      vieja y es irreversible. Puede llevar a 0 el stock de decenas de productos
      de un solo clic, sin que nadie haya visto qué iba a pasar.
"""
import os
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (AuditLog, CategoriaProductoEnum, Inventario,
                               Producto, RolEnum, Tienda, Usuario)
from app.services import inventario_mensual as svc


class GuardasCierreMensualTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.t1 = Tienda(nombre="Vida", direccion="x")
        self.db.add(self.t1)
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.prod = Producto(nombre="LECHE ENTERA", categoria=CategoriaProductoEnum.insumo,
                             unidad_medida="und", controla_stock=True, precio_venta=5000)
        self.db.add(self.prod)
        self.db.flush()
        self.inv_row = Inventario(producto_id=self.prod.id, tienda_id=self.t1.id,
                                  stock_actual=100)
        self.db.add(self.inv_row)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _producto(self, nombre, stock, precio=5000):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida="und", controla_stock=True, precio_venta=precio)
        self.db.add(p)
        self.db.flush()
        fila = Inventario(producto_id=p.id, tienda_id=self.t1.id, stock_actual=stock)
        self.db.add(fila)
        self.db.commit()
        return p, fila

    def _item(self, salida, producto_id):
        return next(i for i in salida["items"] if i["producto_id"] == producto_id)

    # ── B1 · reabrir un mes CERRADO no puede borrar la evidencia ─────────────

    def test_reabrir_un_mes_cerrado_conserva_la_foto_del_periodo(self):
        # Julio: sistema 100, contado 85 → fuga de 15. En agosto el stock vivo ya
        # es otro (60, por las ventas de agosto). Reabrir julio re-fotografiaba
        # ese 60 y ponía la diferencia en 0: la fuga de julio desaparecía para
        # siempre, sin traza y sin que nadie lo pidiera.
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        item_id = self._item(inv, self.prod.id)["id"]
        svc.guardar(self.db, inv["id"], [{"id": item_id, "cantidad_real": 85}])
        svc.cerrar(self.db, inv["id"], self.admin.id)

        self.inv_row.stock_actual = 60      # agosto siguió vendiendo
        self.db.commit()

        out = svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)

        it = self._item(out, self.prod.id)
        self.assertEqual(out["estado"], "en_proceso")   # sí se puede seguir contando
        self.assertIsNone(out["fecha_cierre"])
        self.assertEqual(it["cantidad_sistema"], 100)   # la foto de julio, intacta
        self.assertEqual(it["cantidad_real"], 85)
        self.assertEqual(it["diferencia"], -15)         # la fuga sigue ahí
        self.assertEqual(out["valor_diferencia_total"], -75000)

    def test_reabrir_un_mes_cerrado_deja_traza_en_auditoria(self):
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        item_id = self._item(inv, self.prod.id)["id"]
        svc.guardar(self.db, inv["id"], [{"id": item_id, "cantidad_real": 85}])
        svc.cerrar(self.db, inv["id"], self.admin.id)
        svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)

        filas = self.db.query(AuditLog).filter(
            AuditLog.accion == "reabrir_inventario_mensual").all()
        self.assertEqual(len(filas), 1)
        # La traza tiene que decir que se reabrió un mes CERRADO, no solo que
        # alguien llamó a reabrir sobre un conteo en curso.
        self.assertIn('"reabierto": true', (filas[0].datos_despues or ""))

    def test_reabrir_un_conteo_en_proceso_sigue_sincronizando_el_catalogo(self):
        # El caso real del 31-jul (conteo abierto el 1, conversión a gramos el 3):
        # mientras NADIE cerró, no hay foto que proteger y re-sincronizar es lo
        # correcto — lo contado en la unidad vieja no significa nada en la nueva.
        salsa, fila = self._producto("SALSA CHOCOLATE", 2)
        salsa.unidad_medida = "botella"
        self.db.commit()

        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, salsa.id)["id"], "cantidad_real": 0.45}])

        salsa.unidad_medida = "gr"
        fila.stock_actual = 3695
        self.db.commit()

        out = svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)

        it = self._item(out, salsa.id)
        self.assertEqual(it["unidad_medida"], "gr")
        self.assertEqual(it["cantidad_sistema"], 3695)
        self.assertIsNone(it["cantidad_real"])

    # ── B2 · lo no contado no puede parecer contado ──────────────────────────

    def test_el_cierre_distingue_lo_contado_de_lo_que_nadie_conto(self):
        otro, _ = self._producto("SERVILLETAS", 40)
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 100}])

        out = svc.cerrar(self.db, inv["id"], self.admin.id)

        contado = self._item(out, self.prod.id)
        no_contado = self._item(out, otro.id)
        # Contado y dio EXACTO: diferencia 0 igual que el no contado…
        self.assertEqual(contado["diferencia"], 0)
        self.assertEqual(no_contado["diferencia"], 0)
        # …pero ya no son indistinguibles.
        self.assertTrue(contado["fue_contado"])
        self.assertFalse(no_contado["fue_contado"])

    def test_el_cierre_reporta_cuantos_productos_se_contaron_de_cuantos(self):
        self._producto("SERVILLETAS", 40)
        self._producto("VASOS 8 OZ", 300)
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 90}])

        out = svc.cerrar(self.db, inv["id"], self.admin.id)

        # Un mes con 1 de 3 productos contados NO puede verse igual que uno
        # contado completo: el número va en el payload, bien arriba.
        self.assertEqual(out["contados"], 1)
        self.assertEqual(out["total_items"], 3)

    def test_corregir_un_renglon_del_mes_cerrado_lo_marca_como_contado(self):
        otro, _ = self._producto("SERVILLETAS", 40)
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.cerrar(self.db, inv["id"], self.admin.id)
        item_id = self._item(svc.get_actual(self.db, self.t1.id, 2026, 7), otro.id)["id"]

        out = svc.corregir_item(self.db, item_id, 38, self.admin.id)

        self.assertTrue(self._item(out, otro.id)["fue_contado"])
        self.assertEqual(out["contados"], 1)

    def test_la_conciliacion_expone_la_cobertura_del_conteo(self):
        self._producto("SERVILLETAS", 40)
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 90}])
        svc.cerrar(self.db, inv["id"], self.admin.id)

        con = svc.get_conciliacion(self.db, self.t1.id, 2026, 7)
        self.assertEqual(con["resumen"]["contados"], 1)
        self.assertEqual(con["resumen"]["no_contados"], 1)

    # ── B3 · aplicar no puede ser un salto al vacío ──────────────────────────

    def test_previsualizar_no_toca_nada_y_dice_en_que_stock_queda_cada_producto(self):
        otro, fila_otro = self._producto("SERVILLETAS", 40)
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 85},
            {"id": self._item(inv, otro.id)["id"], "cantidad_real": 45}])
        svc.cerrar(self.db, inv["id"], self.admin.id)

        prev = svc.aplicar(self.db, inv["id"], self.admin.id, dry_run=True)

        self.assertTrue(prev["dry_run"])
        por_pid = {i["producto_id"]: i for i in prev["items"]}
        self.assertEqual(por_pid[self.prod.id]["stock_actual"], 100)
        self.assertEqual(por_pid[self.prod.id]["diferencia"], -15)
        self.assertEqual(por_pid[self.prod.id]["stock_nuevo"], 85)
        self.assertEqual(por_pid[otro.id]["stock_nuevo"], 45)
        self.assertEqual(prev["ajustados"], 2)
        self.assertEqual(prev["negativos"], 0)
        self.assertEqual(prev["en_cero"], 0)
        self.assertFalse(prev["bloqueado"])
        # El impacto en pesos, que es lo que hace pensar dos veces antes del clic.
        self.assertEqual(prev["valor_total"], -50000)

        # Y NADA se movió: previsualizar es solo lectura.
        self.db.refresh(self.inv_row)
        self.db.refresh(fila_otro)
        self.assertEqual(self.inv_row.stock_actual, 100)
        self.assertEqual(fila_otro.stock_actual, 40)
        self.assertIsNone(svc.get_actual(self.db, self.t1.id, 2026, 7)["fecha_aplicado"])

    def test_aplicar_se_bloquea_si_algun_producto_quedaria_negativo(self):
        # Diferencia −40 congelada en el cierre, pero el stock vivo ya bajó a 10:
        # 10 + (−40) = −30. Antes esto clampeaba a 0 en silencio y era
        # irreversible; ahora se frena y se explica.
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 60}])
        svc.cerrar(self.db, inv["id"], self.admin.id)
        self.inv_row.stock_actual = 10
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            svc.aplicar(self.db, inv["id"], self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("LECHE ENTERA", ctx.exception.detail)

        # Se frenó ANTES de tocar nada: ni un producto ajustado, ni el mes marcado.
        self.db.refresh(self.inv_row)
        self.assertEqual(self.inv_row.stock_actual, 10)
        self.assertIsNone(svc.get_actual(self.db, self.t1.id, 2026, 7)["fecha_aplicado"])

    def test_la_previsualizacion_avisa_del_bloqueo_antes_de_intentar(self):
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 60}])
        svc.cerrar(self.db, inv["id"], self.admin.id)
        self.inv_row.stock_actual = 10
        self.db.commit()

        prev = svc.aplicar(self.db, inv["id"], self.admin.id, dry_run=True)

        self.assertTrue(prev["bloqueado"])
        self.assertEqual(prev["negativos"], 1)
        it = next(i for i in prev["items"] if i["producto_id"] == self.prod.id)
        self.assertTrue(it["negativo"])
        self.assertEqual(it["stock_nuevo"], -30)   # el número crudo, sin maquillar

    def test_un_producto_que_queda_exactamente_en_cero_no_bloquea_pero_se_cuenta(self):
        # Quedar en 0 es un resultado legítimo (se acabó); quedar en negativo es
        # una foto vieja aplicada sobre un stock que ya se movió.
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 0}])
        svc.cerrar(self.db, inv["id"], self.admin.id)

        prev = svc.aplicar(self.db, inv["id"], self.admin.id, dry_run=True)
        self.assertFalse(prev["bloqueado"])
        self.assertEqual(prev["en_cero"], 1)

        svc.aplicar(self.db, inv["id"], self.admin.id)
        self.db.refresh(self.inv_row)
        self.assertEqual(self.inv_row.stock_actual, 0)

    # ── B4 · el arreglo de B2 no puede autodestruirse con el de B1 ───────────

    def test_la_cobertura_parcial_sobrevive_a_reabrir_y_volver_a_cerrar(self):
        # El caso real: 12 de 180 contados, se reabre el mes (que B1 ahora
        # permite sin perder la foto), se cuentan 3 más y se vuelve a cerrar.
        #
        # `cerrar()` re-derivaba `fue_contado` desde `cantidad_real`, pero el
        # cierre ANTERIOR ya había rellenado `cantidad_real` en TODOS los
        # renglones con el valor del sistema. Resultado: el segundo cierre
        # reportaba 180 de 180 contados. La cobertura parcial —lo ÚNICO que la
        # bandera existe para exponer— desaparecía de forma persistente, y
        # encima por el camino que el arreglo de B1 acababa de habilitar.
        otros = [self._producto(f"INSUMO {n}", 40)[0] for n in range(5)]

        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 90}])
        primero = svc.cerrar(self.db, inv["id"], self.admin.id)
        self.assertEqual(primero["contados"], 1)
        self.assertEqual(primero["total_items"], 6)

        reabierto = svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(reabierto, p.id)["id"], "cantidad_real": 38}
            for p in otros[:3]])

        segundo = svc.cerrar(self.db, inv["id"], self.admin.id)

        # 1 del primer cierre + 3 del segundo = 4 de 6. NUNCA 6 de 6.
        self.assertEqual(segundo["contados"], 4)
        self.assertEqual(segundo["total_items"], 6)
        # Y los que nadie tocó siguen diciendo que nadie los tocó, aunque el
        # primer cierre les haya dejado `cantidad_real` puesta.
        for p in otros[3:]:
            it = self._item(segundo, p.id)
            self.assertFalse(it["fue_contado"])
            self.assertIsNotNone(it["cantidad_real"])   # rellenada por el cierre

    def test_reabrir_dos_veces_seguidas_no_re_fotografia_el_periodo(self):
        # La guarda de B1 se evaluaba contra el estado ACTUAL (`estado ==
        # 'cerrado'`). La primera reabertura dejaba el mes en 'en_proceso'
        # conservando la foto; la SEGUNDA llamada al mismo endpoint ya no veía
        # un mes cerrado y entraba por la rama destructiva: re-fotografiaba
        # `cantidad_sistema` con el stock de hoy y ponía las diferencias en 0.
        # Dos clics del mismo botón y estábamos donde empezamos.
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 85}])
        svc.cerrar(self.db, inv["id"], self.admin.id)

        self.inv_row.stock_actual = 60      # agosto siguió vendiendo
        self.db.commit()

        svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)
        out = svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)

        it = self._item(out, self.prod.id)
        self.assertEqual(it["cantidad_sistema"], 100)   # la foto de julio, intacta
        self.assertEqual(it["cantidad_real"], 85)
        self.assertEqual(it["diferencia"], -15)         # la fuga sigue ahí
        self.assertEqual(out["valor_diferencia_total"], -75000)
        self.assertTrue(it["fue_contado"])

    def test_reiniciar_no_puede_borrar_un_mes_que_ya_se_cerro_alguna_vez(self):
        # Misma destrucción, otra puerta: reabrir deja el mes en 'en_proceso' y
        # `reiniciar` solo miraba ese estado, así que dos clics (reabrir +
        # reiniciar) borraban el conteo entero y lo re-sembraban con el stock de
        # HOY. Si el mes pasó por un cierre, su foto es histórica.
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 85}])
        svc.cerrar(self.db, inv["id"], self.admin.id)
        svc.reabrir(self.db, self.t1.id, 2026, 7, self.admin.id)

        with self.assertRaises(HTTPException) as ctx:
            svc.reiniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        self.assertEqual(ctx.exception.status_code, 400)

        it = self._item(svc.get_actual(self.db, self.t1.id, 2026, 7), self.prod.id)
        self.assertEqual(it["cantidad_real"], 85)
        self.assertEqual(it["cantidad_sistema"], 100)

    # ── B5 · el bloqueo por negativo no puede ser todo-o-nada ────────────────

    def test_aplicar_puede_excluir_los_renglones_negativos_y_ajustar_el_resto(self):
        # El bloqueo de B3 frenaba el conteo ENTERO por un solo renglón: un
        # producto de alta rotación aplicado días después del cierre paraba los
        # otros 179. Y la única salida que ofrecía la pantalla era corregir ese
        # físico a mano — o sea, escribir un número que nadie contó y que
        # `corregir_item` marca como CONTADO, ensuciando justo la cobertura que
        # B2 existe para exponer. El admin tiene que poder avanzar sin mentir.
        sanos = [self._producto(f"INSUMO {n}", 40)[0] for n in range(3)]

        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 60},
            *[{"id": self._item(inv, p.id)["id"], "cantidad_real": 38} for p in sanos],
        ])
        svc.cerrar(self.db, inv["id"], self.admin.id)   # dif −40 y tres dif −2

        self.inv_row.stock_actual = 10   # 10 + (−40) = −30 → el renglón trabado
        self.db.commit()

        res = svc.aplicar(self.db, inv["id"], self.admin.id, omitir_negativos=True)

        self.assertEqual(res["ajustados"], 3)
        self.assertEqual(res["excluidos"], 1)
        # El trabado NO se tocó: su stock queda como estaba.
        self.db.refresh(self.inv_row)
        self.assertEqual(self.inv_row.stock_actual, 10)
        # Los sanos SÍ se ajustaron (40 − 2 = 38).
        for p in sanos:
            fila = self.db.query(Inventario).filter_by(
                producto_id=p.id, tienda_id=self.t1.id).first()
            self.assertEqual(fila.stock_actual, 38)
        # Queda constancia de QUÉ se excluyó y POR QUÉ, para poder revisarlo.
        excluido = res["items_excluidos"][0]
        self.assertEqual(excluido["producto_nombre"], "LECHE ENTERA")
        self.assertEqual(excluido["stock_nuevo"], -30)
        self.assertEqual(excluido["motivo"], "stock_negativo")
        traza = self.db.query(AuditLog).filter(
            AuditLog.accion == "aplicar_inventario_mensual").one()
        self.assertIn("LECHE ENTERA", (traza.datos_despues or ""))

        # Y NADIE quedó marcado como contado por el rescate: la cobertura del
        # mes es exactamente la que era antes de aplicar.
        despues = svc.get_actual(self.db, self.t1.id, 2026, 7)
        self.assertEqual(despues["contados"], 4)
        self.assertTrue(self._item(despues, self.prod.id)["fue_contado"])

    def test_sin_omitir_negativos_aplicar_sigue_frenando_en_seco(self):
        # La exclusión es EXPLÍCITA: el default sigue siendo no tocar nada, para
        # que nadie aplique medio conteo sin haberlo pedido.
        self._producto("INSUMO 0", 40)
        inv = svc.iniciar(self.db, self.t1.id, 2026, 7, self.admin.id)
        svc.guardar(self.db, inv["id"], [
            {"id": self._item(inv, self.prod.id)["id"], "cantidad_real": 60}])
        svc.cerrar(self.db, inv["id"], self.admin.id)
        self.inv_row.stock_actual = 10
        self.db.commit()

        with self.assertRaises(HTTPException):
            svc.aplicar(self.db, inv["id"], self.admin.id)
        self.assertIsNone(svc.get_actual(self.db, self.t1.id, 2026, 7)["fecha_aplicado"])


if __name__ == "__main__":
    unittest.main()
