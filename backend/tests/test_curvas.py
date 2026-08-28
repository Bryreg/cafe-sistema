"""La curva del saldo tiene que terminar donde termina la fila.

La tabla de insumos contesta CUÁNTO entró y cuánto salió. La curva contesta
CUÁNDO, y esa es la pregunta que destapa lo que los totales esconden: dos
insumos con los mismos totales pueden ser uno sano —baja parejo y el pedido
llega justo— y otro roto —se agota el miércoles y pasa tres días en negativo—.

El riesgo de dibujar una segunda vista sobre los mismos datos es que calcule por
su cuenta y termine discrepando de la tabla, sin que quien mira sepa cuál de las
dos está mal. Por eso la curva sale de `conciliacion._saldos`, la MISMA función
que le da a la escalera el saldo del libro, y estos tests fijan que las dos
vistas no se puedan separar:

  · LA CURVA CIERRA — su último punto es el `queda` de la fila, y su primero el
    `arranco`. Si algún día dejaran de coincidir, es un bug de una de las dos.

  · EL AJUSTE NO LA ROMPE — un movimiento de tipo `ajuste` guarda el stock
    RESULTANTE y no el delta. Reconstruir la curva hacia atrás desde el stock de
    hoy —que es lo primero que uno intenta— se rompe justo ahí. Este es el caso
    que en el prototipo daba un arranque de cero con el conteo mil unidades por
    encima: parecía una fuga enorme y era la reconstrucción.

  · EL RALEO NO DEFORMA LA SILUETA — con cientos de ventas hay que tirar puntos,
    pero las entradas y los ajustes se mandan todos, así que el techo de la
    sombra (el máximo que el stock alcanzó) sale exacto igual.

  · EL CONTEO DE APERTURA NO CUENTA DOS VECES — en producción copia exacto el
    del cierre de la noche anterior en 119 de 120 casos. Dibujar los dos diría
    que el estante se revisó el doble de veces de lo que se revisó.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.core.tz import hoy_col
from app.database import Base, get_db
from app.models.models import (CajaTurno, CategoriaProductoEnum, ConteoFisico,
                               ConteoFisicoItem, EstadoTurnoEnum, Inventario,
                               MovimientoInventario, Producto, RolEnum, Tienda,
                               TipoConteoEnum, TipoMovInvEnum, Usuario)
from app.routers import inventario as inventario_router
from app.services import curvas as curvas_svc


class CurvaInsumoTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.t = Tienda(nombre="Vida", direccion="x", activa=True)
        self.db.add(self.t)
        self.db.flush()
        self.admin = Usuario(nombre="Bryan", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t.id, activo=True)
        self.db.add(self.admin)
        self.db.flush()
        self.db.commit()
        self.hoy = hoy_col()
        self.desde = self.hoy - timedelta(days=6)

        app = FastAPI(title="Test curvas")
        app.include_router(inventario_router.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.app, self.client = app, TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── fixtures ─────────────────────────────────────────────────────────────
    def producto(self, nombre, stock=0.0, unidad="gr"):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=True, precio_venta=0.0)
        self.db.add(p)
        self.db.flush()
        self.db.add(Inventario(producto_id=p.id, tienda_id=self.t.id,
                               stock_actual=stock, stock_minimo=0))
        self.db.commit()
        return p

    def mov(self, producto, tipo, cantidad, motivo, dias=3, minutos=0):
        """Escribe el movimiento Y mueve el stock, como el flujo real."""
        inv = self.db.query(Inventario).filter_by(
            producto_id=producto.id, tienda_id=self.t.id).first()
        if tipo == TipoMovInvEnum.entrada:
            inv.stock_actual += cantidad
        elif tipo == TipoMovInvEnum.salida:
            inv.stock_actual -= cantidad
        else:
            inv.stock_actual = cantidad
        self.db.add(MovimientoInventario(
            producto_id=producto.id, tienda_id=self.t.id, tipo=tipo,
            cantidad=cantidad, motivo=motivo, usuario_id=self.admin.id,
            fecha=datetime.utcnow() - timedelta(days=dias, minutes=-minutos)))
        self.db.commit()

    def turno(self):
        tu = CajaTurno(tienda_id=self.t.id, usuario_apertura_id=self.admin.id,
                       estado=EstadoTurnoEnum.abierto, base_real=0)
        self.db.add(tu)
        self.db.commit()
        return tu

    def conteo(self, turno, tipo, items, dias=3, sistema=None):
        """items: [(producto, contado)]. `sistema` fuerza la foto del libro."""
        c = ConteoFisico(tienda_id=self.t.id, turno_id=turno.id, tipo=tipo,
                         usuario_id=self.admin.id,
                         fecha_registro=datetime.utcnow() - timedelta(days=dias))
        self.db.add(c)
        self.db.flush()
        for p, real in items:
            inv = self.db.query(Inventario).filter_by(
                producto_id=p.id, tienda_id=self.t.id).first()
            foto = inv.stock_actual if sistema is None else sistema
            self.db.add(ConteoFisicoItem(
                conteo_id=c.id, producto_id=p.id, cantidad_sistema=foto,
                cantidad_real=real, diferencia=real - foto))
        self.db.commit()
        return c

    def fila(self, producto, con_curva=True):
        r = self.client.get("/api/v1/inventario/movimiento-insumos", params={
            "tienda_id": self.t.id, "desde": self.desde.isoformat(),
            "hasta": self.hoy.isoformat(), "con_curva": str(con_curva).lower()})
        self.assertEqual(r.status_code, 200, r.text)
        cuerpo = r.json()
        fila = next(f for f in cuerpo["insumos"] if f["producto_id"] == producto.id)
        return cuerpo, fila

    # ── la curva y la fila son la misma verdad ───────────────────────────────
    def test_la_curva_arranca_y_termina_donde_dice_la_fila(self):
        cafe = self.producto("Cafe Alta Tostion x2500", stock=2444)
        self.mov(cafe, TipoMovInvEnum.entrada, 10000, "Factura #1034 — Cafexcoop", dias=5)
        self.mov(cafe, TipoMovInvEnum.salida, 1320, "Preparación: MEZCLA GRANIZADO", dias=4)
        self.mov(cafe, TipoMovInvEnum.salida, 40, "Venta POS — Cappuccino", dias=2)

        _, f = self.fila(cafe)
        c = f["curva"]
        self.assertEqual(c["puntos"][0]["k"], "inicio")
        self.assertEqual(c["puntos"][-1]["k"], "fin")
        self.assertAlmostEqual(c["puntos"][0]["v"], f["arranco"], places=2)
        self.assertAlmostEqual(c["puntos"][-1]["v"], f["queda"], places=2)
        self.assertEqual(c["n_movs"], 3)
        self.assertEqual(c["ancla"], "libro")

    def test_cada_escalon_de_la_curva_es_el_saldo_de_ese_instante(self):
        azucar = self.producto("Azucar a Granel", stock=1000)
        self.mov(azucar, TipoMovInvEnum.salida, 300, "Venta POS", dias=5)
        self.mov(azucar, TipoMovInvEnum.entrada, 2000, "Factura #77 — Makro", dias=4)
        self.mov(azucar, TipoMovInvEnum.salida, 500, "Venta POS", dias=2)

        _, f = self.fila(azucar)
        # 1.000 al arrancar → −300 → +2.000 → −500 = 2.200, que es el stock vivo.
        self.assertEqual([p["v"] for p in f["curva"]["puntos"]],
                         [1000.0, 700.0, 2700.0, 2200.0, 2200.0])
        self.assertEqual([p["k"] for p in f["curva"]["puntos"]],
                         ["inicio", "salida", "entrada", "salida", "fin"])

    def test_el_ajuste_no_rompe_la_curva_aunque_guarde_el_absoluto(self):
        # `cantidad` de un ajuste es el stock RESULTANTE. Si la curva lo tratara
        # como un delta, sumaría 900 sobre el saldo en vez de fijarlo en 900.
        #
        # El ajuste VIEJO —anterior al rango— es lo que hace firme al arranque:
        # hacia atrás un ajuste es un muro, pero hacia adelante es un ancla
        # absoluta, y desde ahí el saldo de todo lo que sigue es exacto. Así se
        # ve en producción: con 123 insumos y ajustes por todos lados, sólo uno
        # tiene el arranque estimado.
        salsa = self.producto("Salsa Caramelo", stock=900)
        self.mov(salsa, TipoMovInvEnum.ajuste, 1000, "Conteo #2 — ajuste", dias=20)
        self.mov(salsa, TipoMovInvEnum.salida, 200, "Venta POS", dias=5)
        self.mov(salsa, TipoMovInvEnum.ajuste, 900, "Conteo #7 — ajuste de cierre", dias=4)

        _, f = self.fila(salsa)
        self.assertFalse(f["arranque_estimado"])
        self.assertEqual(f["arranco"], 1000.0)
        pts = f["curva"]["puntos"]
        self.assertEqual([p["v"] for p in pts], [1000.0, 800.0, 900.0, 900.0])
        aj = next(p for p in pts if p["k"] == "ajuste")
        self.assertEqual(aj["v"], 900.0)             # FIJA el saldo, no lo suma
        self.assertEqual(aj["c"], 100.0)             # y lo que movió fue +100
        self.assertAlmostEqual(pts[-1]["v"], f["queda"], places=2)

    def test_el_arranque_estimado_viaja_marcado(self):
        # Un ajuste es un muro hacia atrás: el saldo previo no quedó registrado
        # en ninguna parte. La escalera lo estima suponiendo que arrancó en cero,
        # y la curva tiene que DECIRLO en vez de disimularlo.
        viejo = self.producto("Bati Crema", stock=46, unidad="und")
        self.mov(viejo, TipoMovInvEnum.ajuste, 26, "Conteo #1 — ajuste", dias=5)
        self.mov(viejo, TipoMovInvEnum.entrada, 20, "Factura #90", dias=3)

        _, f = self.fila(viejo)
        self.assertTrue(f["arranque_estimado"])
        self.assertEqual(f["curva"]["ancla"], "estimado")
        self.assertTrue(f["curva"]["puntos"][0].get("est"))
        self.assertAlmostEqual(f["curva"]["puntos"][-1]["v"], f["queda"], places=2)

    # ── los conteos, que el libro no conoce ──────────────────────────────────
    def test_el_conteo_llega_con_lo_que_decia_el_sistema_y_lo_que_habia(self):
        helado = self.producto("Helado Vainilla", stock=705)
        self.mov(helado, TipoMovInvEnum.entrada, 10000, "Factura #1020", dias=5)
        self.mov(helado, TipoMovInvEnum.salida, 3600, "Venta POS", dias=4)
        self.conteo(self.turno(), TipoConteoEnum.cierre, [(helado, 6533.0)], dias=2)

        _, f = self.fila(helado)
        cs = f["curva"]["conteos"]
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0]["sistema"], 7105.0)
        self.assertEqual(cs[0]["real"], 6533.0)
        self.assertEqual(cs[0]["dif"], -572.0)
        # El punto se compara contra el MISMO nivel que se dibuja: si no, el
        # punto y la curva contarían historias distintas en la misma fila.
        self.assertEqual(cs[0]["curva"], cs[0]["sistema"])

    def test_la_apertura_que_copia_el_cierre_es_una_sola_mirada(self):
        leche = self.producto("Leche Entera", stock=30, unidad="und")
        self.mov(leche, TipoMovInvEnum.salida, 5, "Venta POS", dias=5)
        cierre, apertura = self.turno(), self.turno()
        self.conteo(cierre, TipoConteoEnum.cierre, [(leche, 41.0)], dias=4)
        # A la mañana nadie vuelve a contar: se copia el número de la noche.
        self.conteo(apertura, TipoConteoEnum.apertura, [(leche, 41.0)], dias=3)

        _, f = self.fila(leche)
        cs = f["curva"]["conteos"]
        self.assertEqual(len(cs), 1, "dos registros iguales son UNA mirada")
        self.assertEqual(cs[0]["registros"], 2)
        self.assertEqual(sorted(cs[0]["tipos"]), ["apertura", "cierre"])

    def test_dos_conteos_distintos_siguen_siendo_dos(self):
        leche = self.producto("Leche Deslactosada", stock=30, unidad="und")
        t1, t2 = self.turno(), self.turno()
        self.conteo(t1, TipoConteoEnum.cierre, [(leche, 28.0)], dias=4)
        self.mov(leche, TipoMovInvEnum.salida, 6, "Venta POS", dias=3)
        self.conteo(t2, TipoConteoEnum.cierre, [(leche, 20.0)], dias=2)

        _, f = self.fila(leche)
        self.assertEqual(len(f["curva"]["conteos"]), 2)
        self.assertEqual([c["real"] for c in f["curva"]["conteos"]], [28.0, 20.0])

    def test_el_atajo_todo_coincide_viaja_marcado(self):
        # No es un conteo: es un eco del stock. Dibujarlo como una mirada al
        # estante mentiría sobre la evidencia que hay detrás de la fila.
        pan = self.producto("Almojabanas", stock=70, unidad="und")
        c = self.conteo(self.turno(), TipoConteoEnum.cierre, [(pan, 70.0)], dias=3)
        c.es_atajo = True
        self.db.commit()

        _, f = self.fila(pan)
        self.assertTrue(f["curva"]["conteos"][0]["es_atajo"])
        self.assertEqual(f["curva"]["conteos"][0]["dif"], 0.0)

    # ── el raleo ─────────────────────────────────────────────────────────────
    def test_el_raleo_conserva_los_extremos_las_entradas_y_los_ajustes(self):
        cafe = self.producto("Cafe Alta Tostion x2500", stock=0)
        for i in range(200):
            self.mov(cafe, TipoMovInvEnum.salida, 10, "Venta POS", dias=5, minutos=i)
        self.mov(cafe, TipoMovInvEnum.entrada, 5000, "Factura #1034", dias=4)
        for i in range(200):
            self.mov(cafe, TipoMovInvEnum.salida, 10, "Venta POS", dias=3, minutos=i)

        _, f = self.fila(cafe)
        c = f["curva"]
        self.assertEqual(c["puntos_total"], 403)          # 401 movs + inicio + fin
        self.assertLessEqual(len(c["puntos"]), curvas_svc.MUESTRAS)
        self.assertEqual(c["puntos"][0]["k"], "inicio")
        self.assertEqual(c["puntos"][-1]["k"], "fin")
        # Lo único que SUBE se manda entero: sin la entrada, el techo de la
        # sombra —el máximo que el stock alcanzó— saldría mal.
        self.assertEqual(sum(1 for p in c["puntos"] if p["k"] == "entrada"), 1)
        self.assertEqual(max(p["v"] for p in c["puntos"]),
                         max(p["v"] for p in c["puntos"] if p["k"] != "salida"))
        self.assertAlmostEqual(c["puntos"][-1]["v"], f["queda"], places=2)
        # Y cada salida que quedó dice cuánto salió DESDE el punto anterior que
        # quedó, no cuánto salió en el último de los movimientos que representa.
        # Es la invariante fuerte: si algún día vuelve a fallar, es que un tramo
        # volvió a cruzar algo que no era una venta y se llevó su cantidad.
        for antes, p in zip(c["puntos"], c["puntos"][1:]):
            if p["k"] == "salida":
                self.assertAlmostEqual(p["c"], antes["v"] - p["v"], places=2,
                                       msg=f'el escalón de {p["causa"]} no coincide con la caída')
        # Nada se pierde y nada se cuenta dos veces: las 400 ventas de 10 siguen
        # sumando 4.000 repartidas entre los pocos escalones que quedaron. Y
        # alguno agrupa de verdad: si `n` fuera 1 en todos, no se raleó nada.
        self.assertAlmostEqual(sum(p["c"] for p in c["puntos"]
                                   if p["k"] == "salida"), 4000.0, places=2)
        self.assertGreater(max(p.get("n", 1) for p in c["puntos"]), 1,
                           "el raleo no agrupó ninguna venta")

    # ── el consumo medido: para un opcional es el único número que hay ───────
    def test_el_azucar_en_tubos_se_mide_contra_el_conteo_no_contra_el_libro(self):
        # El cliente lo pide o no lo pide: la caja nunca lo descuenta, así que
        # el libro dice que salió CERO. Entre dos conteos, en cambio, la cuenta
        # es del estante y no del libro:
        #     lo contado antes + lo que entró en medio − lo contado después
        tubos = self.producto("Azúcar Blanca Tubos", stock=200, unidad="und")
        t1, t2 = self.turno(), self.turno()
        self.conteo(t1, TipoConteoEnum.cierre, [(tubos, 200.0)], dias=5)
        self.mov(tubos, TipoMovInvEnum.entrada, 100, "Factura #91 — Makro", dias=4)
        self.conteo(t2, TipoConteoEnum.cierre, [(tubos, 230.0)], dias=2)

        _, f = self.fila(tubos)
        self.assertEqual(f["ventas"], 0.0, "la caja no descuenta un opcional")
        cm = f["curva"]["consumo_medido"]
        self.assertEqual(cm["usado"], 70.0)          # 200 + 100 − 230
        self.assertEqual(cm["tramos"], 1)
        self.assertAlmostEqual(cm["por_dia"], 70 / cm["dias"], places=2)

    def test_el_ajuste_no_cuenta_como_algo_que_llegó_al_estante(self):
        # Un ajuste fija el saldo del SISTEMA; no pone ni saca nada del estante.
        # Contarlo como entrada inflaría el consumo medido.
        mez = self.producto("Mezclador Ecológico", stock=500, unidad="und")
        t1, t2 = self.turno(), self.turno()
        self.conteo(t1, TipoConteoEnum.cierre, [(mez, 500.0)], dias=5)
        self.mov(mez, TipoMovInvEnum.ajuste, 480, "Conteo #9 — ajuste", dias=4)
        self.conteo(t2, TipoConteoEnum.cierre, [(mez, 430.0)], dias=2)

        _, f = self.fila(mez)
        self.assertEqual(f["curva"]["consumo_medido"]["usado"], 70.0)   # 500 − 430

    def test_con_un_solo_conteo_no_hay_consumo_que_medir(self):
        # Hace falta un ANTES y un DESPUÉS: con una sola mirada no hay tramo, y
        # devolver 0 diría que no se gastó nada, que es otra cosa.
        pan = self.producto("SERVILLETAS", stock=50, unidad="und")
        self.conteo(self.turno(), TipoConteoEnum.cierre, [(pan, 48.0)], dias=3)

        _, f = self.fila(pan)
        self.assertIsNone(f["curva"]["consumo_medido"])

    def test_un_insumo_opcional_viaja_marcado(self):
        splenda = self.producto("ENDULZANTE DIET O STEVIA", stock=100, unidad="und")
        _, antes = self.fila(splenda)
        self.assertFalse(antes["consumo_opcional"])

        r = self.client.patch(f"/api/v1/inventario/productos/{splenda.id}",
                              json={"consumo_opcional": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["consumo_opcional"])

        _, ahora = self.fila(splenda)
        self.assertTrue(ahora["consumo_opcional"])

    def test_el_instante_de_arranque_viaja_con_su_zona(self):
        # Sin la «Z», `new Date()` en el navegador lo toma como hora LOCAL: en la
        # tablet (UTC−5) eso corría todos los globos cinco horas y un conteo de
        # cierre de las 8 de la noche se mostraba a la 1 de la mañana.
        agua = self.producto("AGUA MEDIUM BOTELLA", stock=57, unidad="und")
        self.mov(agua, TipoMovInvEnum.salida, 7, "Venta POS", dias=3)

        cuerpo, _ = self.fila(agua)
        self.assertTrue(cuerpo["desde_utc"].endswith("Z"), cuerpo["desde_utc"])
        # Y es de verdad el arranque del día COLOMBIA, no del día UTC.
        from datetime import datetime
        d = datetime.fromisoformat(cuerpo["desde_utc"].replace("Z", "+00:00"))
        self.assertEqual((d.hour, d.minute), (5, 0))

    def test_el_raleo_no_le_cambia_la_causa_a_lo_que_junta(self):
        # Con el raleo viejo, el punto que sobrevivía se quedaba con la SUMA de
        # los descartados pero con SU causa: en producción los globos del café
        # sumaban 22.710 gr de «se vendió» cuando 9.540 eran preparaciones y
        # traslados. Ahora sólo se ralean las VENTAS.
        cafe = self.producto("Cafe Alta Tostion x2500", stock=0)
        for i in range(120):
            self.mov(cafe, TipoMovInvEnum.salida, 10, "Venta POS", dias=5, minutos=i)
        self.mov(cafe, TipoMovInvEnum.salida, 900, "Preparación: MEZCLA GRANIZADO", dias=4)
        self.mov(cafe, TipoMovInvEnum.salida, 300, "Traslado a Palmetto", dias=4, minutos=5)
        self.mov(cafe, TipoMovInvEnum.salida, 150, "Daño: se derramó", dias=4, minutos=10)

        _, f = self.fila(cafe)
        pts = f["curva"]["puntos"]
        self.assertLess(len(pts), f["curva"]["puntos_total"], "esta curva se raleó")
        # Lo que suman los globos, por causa, contra lo que dice la fila.
        suma: dict = {}
        for p in pts:
            if p["k"] == "salida":
                suma[p["causa"]] = suma.get(p["causa"], 0) + p["c"]
        self.assertAlmostEqual(suma.get("preparaciones", 0), 900, places=2)
        self.assertAlmostEqual(suma.get("traslados", 0), 300, places=2)
        self.assertAlmostEqual(suma.get("mermas", 0), 150, places=2)
        self.assertAlmostEqual(suma.get("ventas", 0), f["ventas"], places=2)
        # Y no sobra ni falta un gramo en el total.
        self.assertAlmostEqual(sum(suma.values()), f["total_salio"], places=2)
        # Y un escalón raleado dice cuántos movimientos junta.
        juntos = [p for p in pts if p.get("n")]
        self.assertTrue(juntos, "algún escalón junta varias ventas")
        self.assertTrue(all(p["causa"] == "ventas" for p in juntos))

    def test_sin_pedirla_la_curva_no_viaja(self):
        agua = self.producto("AGUA MEDIUM BOTELLA", stock=57, unidad="und")
        self.mov(agua, TipoMovInvEnum.salida, 7, "Venta POS", dias=3)

        cuerpo, f = self.fila(agua, con_curva=False)
        self.assertNotIn("curva", f)
        self.assertIn("desde_utc", cuerpo)
        # Y la fila es la MISMA fila: la curva no cambia ningún total.
        _, con = self.fila(agua, con_curva=True)
        self.assertEqual({k: v for k, v in con.items() if k != "curva"}, f)


if __name__ == "__main__":
    unittest.main()
