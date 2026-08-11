"""Diagnóstico de stock: por qué hay negativos y por qué el motor no avisa.

El dueño preguntó dos cosas —«contá los umbrales» y «por qué tengo inventario
negativo»— y la respuesta correcta no es un .sql que él pegue en una consola:
es que el sistema se lo conteste, en la pantalla donde ya está parado.

Este archivo cubre las dos mitades:

  1. `clasificar_causa_negativo` — función PURA sobre datos, sin DB. Es la que
     convierte un número negativo en una frase que dice qué hacer. La regla dura
     que se testea acá es que la frase se declare SOSPECHA y nunca veredicto, y
     que cuando dos causas aplican se diga cuál gana Y que la otra existía.

  2. `diagnostico` — la lectura agregada (umbrales, consumo, negativos, recetas
     sospechosas de unidad). Read-only de punta a punta: se verifica que no
     escriba nada.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (CategoriaProductoEnum, Inventario,
                               MovimientoInventario, Producto, ProductoInsumo,
                               RolEnum, Tienda, TipoMovInvEnum, Usuario)
from app.services import diagnostico_stock as diag


# ─── 1. La clasificación de causa: función pura ──────────────────────────────

class TestClasificarCausa(unittest.TestCase):
    """Sin DB, sin sesión: entra un puñado de hechos, sale una sospecha."""

    AHORA = datetime(2026, 8, 10, 12, 0, 0)

    def clasificar(self, *, controla_stock=True, precio_venta=0.0,
                   tiene_receta_propia=False, ultima_entrada=None,
                   ahora=None):
        return diag.clasificar_causa_negativo(
            controla_stock=controla_stock,
            precio_venta=precio_venta,
            tiene_receta_propia=tiene_receta_propia,
            ultima_entrada=ultima_entrada,
            ahora=ahora or self.AHORA,
        )

    # — caso 1: preparable sin registrar NINGUNA tanda —
    def test_preparable_sin_registrar_la_preparacion(self):
        r = self.clasificar(controla_stock=True, precio_venta=0.0,
                            tiene_receta_propia=True, ultima_entrada=None)
        self.assertEqual(r["causa"], "preparable_sin_registrar")
        self.assertIn("no se registra una tanda", r["sospecha"])
        # Y NO puede afirmar «nunca entró»: la misma causa cubre al preparable
        # que registró tandas hace 90 días, y ahí ese absoluto sería falso.
        self.assertNotIn("nunca", r["sospecha"].lower())

    def test_preparable_con_tandas_registradas_no_acusa_de_no_registrarlas(self):
        """`registrar_preparacion` escribe la tanda como `tipo=entrada`
        (inventario.py:577). O sea que una barra que SÍ registra tandas tiene
        entradas recientes y aun así puede quedar en negativo.

        Decirle a esa barra «nadie registró la tanda» es exigirle lo que ya está
        haciendo — y encima al lado de un «último ingreso: hace 3 días» que lo
        desmiente en la misma pantalla. Cuando las tandas están, lo que falla es
        el rendimiento por tanda o la receta, y eso es otra acción."""
        r = self.clasificar(controla_stock=True, precio_venta=0.0,
                            tiene_receta_propia=True,
                            ultima_entrada=self.AHORA - timedelta(days=3))
        self.assertEqual(r["causa"], "preparable_no_alcanza")
        self.assertNotIn("nadie registró", r["sospecha"])
        self.assertIn("rinde", r["que_hacer"] + r["sospecha"])
        # Entrada reciente: ninguna otra causa ESPECÍFICA aplica.
        self.assertEqual(r["tambien_aplica"], [])
        self.assertIsNone(r["por_que_gana"])

    def test_el_preparable_con_tandas_viejas_si_es_falta_de_registro(self):
        """Dejaron de registrarlas: ahí la acusación sí se sostiene."""
        r = self.clasificar(controla_stock=True, precio_venta=0.0,
                            tiene_receta_propia=True,
                            ultima_entrada=self.AHORA - timedelta(days=90))
        self.assertEqual(r["causa"], "preparable_sin_registrar")
        self.assertEqual(r["tambien_aplica"], ["entrada_vieja"])
        self.assertIsNotNone(r["por_que_gana"])

    def test_no_es_preparable_si_se_vende_en_el_pos(self):
        """Un producto CON precio de venta y receta es una bebida del POS, no un
        preparable. Que tenga receta no lo convierte en mezcla intermedia."""
        r = self.clasificar(controla_stock=True, precio_venta=9000.0,
                            tiene_receta_propia=True, ultima_entrada=None)
        self.assertEqual(r["causa"], "sin_entrada_registrada")

    def test_no_es_preparable_sin_receta(self):
        r = self.clasificar(controla_stock=True, precio_venta=0.0,
                            tiene_receta_propia=False,
                            ultima_entrada=self.AHORA - timedelta(days=2))
        self.assertEqual(r["causa"], "consumo_sin_registro")

    # — caso 2: nunca se registró una entrada —
    def test_nunca_se_registro_una_entrada(self):
        r = self.clasificar(tiene_receta_propia=False, ultima_entrada=None)
        self.assertEqual(r["causa"], "sin_entrada_registrada")
        self.assertEqual(r["tambien_aplica"], [])

    # — caso 3: la última entrada es vieja —
    def test_entrada_de_hace_mas_de_60_dias(self):
        r = self.clasificar(ultima_entrada=self.AHORA - timedelta(days=90))
        self.assertEqual(r["causa"], "entrada_vieja")
        # El número tiene que estar EN la frase: "hace mucho" no manda a nadie a
        # buscar una factura, "hace 90 días" sí.
        self.assertIn("90", r["sospecha"])
        self.assertEqual(r["dias_sin_entrada"], 90)

    def test_borde_exacto_de_60_dias_no_es_entrada_vieja(self):
        justo = self.clasificar(ultima_entrada=self.AHORA - timedelta(days=60))
        self.assertEqual(justo["causa"], "consumo_sin_registro")
        uno_mas = self.clasificar(ultima_entrada=self.AHORA - timedelta(days=61))
        self.assertEqual(uno_mas["causa"], "entrada_vieja")

    # — caso 4: el cajón de sastre —
    def test_cajon_de_sastre(self):
        r = self.clasificar(ultima_entrada=self.AHORA - timedelta(days=5))
        self.assertEqual(r["causa"], "consumo_sin_registro")
        self.assertEqual(r["tambien_aplica"], [])

    # — caso 5: DOS causas aplican —
    def test_dos_causas_preparable_y_sin_entrada(self):
        r = self.clasificar(controla_stock=True, precio_venta=0.0,
                            tiene_receta_propia=True, ultima_entrada=None)
        self.assertEqual(r["causa"], "preparable_sin_registrar")
        # La segunda causa NO se esconde.
        self.assertIn("sin_entrada_registrada", r["tambien_aplica"])
        # Y se dice POR QUÉ gana la primera.
        self.assertTrue(r["por_que_gana"])

    def test_dos_causas_preparable_y_entrada_vieja(self):
        r = self.clasificar(controla_stock=True, precio_venta=0.0,
                            tiene_receta_propia=True,
                            ultima_entrada=self.AHORA - timedelta(days=200))
        self.assertEqual(r["causa"], "preparable_sin_registrar")
        self.assertIn("entrada_vieja", r["tambien_aplica"])
        self.assertTrue(r["por_que_gana"])

    # — la regla dura: es una SOSPECHA, no un veredicto —
    def test_toda_causa_se_declara_como_sospecha(self):
        casos = [
            dict(controla_stock=True, precio_venta=0.0, tiene_receta_propia=True,
                 ultima_entrada=None),
            dict(ultima_entrada=None),
            dict(ultima_entrada=self.AHORA - timedelta(days=120)),
            dict(ultima_entrada=self.AHORA - timedelta(days=1)),
        ]
        for kwargs in casos:
            with self.subTest(**kwargs):
                r = self.clasificar(**kwargs)
                self.assertTrue(
                    r["sospecha"].startswith("Sospecha"),
                    f"la frase tiene que declararse sospecha: {r['sospecha']!r}")
                self.assertIn(r["causa"], diag.CAUSAS)
                self.assertTrue(r["titulo"])

    def test_ninguna_frase_habla_de_robo_ni_culpa(self):
        """Mismo principio que la escalera de conciliación: se mide, no se
        atribuye. Un negativo es un registro que falta, no una acusación."""
        prohibidas = ("robo", "roba", "hurto", "culpa", "responsable", "sustraj")
        for causa, txt in diag.CAUSAS.items():
            plano = (txt["titulo"] + " " + txt["sospecha_base"]).lower()
            for p in prohibidas:
                self.assertNotIn(p, plano, f"{causa} usa la palabra {p!r}")


# ─── 2. El diagnóstico agregado ──────────────────────────────────────────────

class TestDiagnostico(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(f"sqlite:///{self.db_path}",
                                    connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.t1 = Tienda(nombre="Vida", direccion="x")
        self.t2 = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.t1, self.t2])
        self.db.flush()
        self.admin = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                             rol=RolEnum.admin, tienda_id=self.t1.id, activo=True)
        self.db.add(self.admin)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # helpers
    def producto(self, nombre, unidad="und", precio=0.0, controla=True,
                 conteo=True, categoria=CategoriaProductoEnum.insumo):
        p = Producto(nombre=nombre, categoria=categoria, unidad_medida=unidad,
                     controla_stock=controla, incluir_en_conteo=conteo,
                     precio_venta=precio)
        self.db.add(p)
        self.db.flush()
        return p

    def inv(self, p, tienda, stock=0.0, minimo=0.0, critico=0.0, ideal=0.0):
        i = Inventario(producto_id=p.id, tienda_id=tienda.id, stock_actual=stock,
                       stock_minimo=minimo, stock_critico=critico, stock_ideal=ideal)
        self.db.add(i)
        self.db.flush()
        return i

    def mov(self, p, tienda, tipo, cantidad=1.0, dias_atras=0):
        m = MovimientoInventario(
            producto_id=p.id, tienda_id=tienda.id, tipo=tipo, cantidad=cantidad,
            usuario_id=self.admin.id,
            fecha=datetime.utcnow() - timedelta(days=dias_atras))
        self.db.add(m)
        self.db.flush()
        return m

    # — umbrales —
    def test_umbrales_cuenta_por_sede_y_en_total(self):
        a = self.producto("Café")
        b = self.producto("Leche")
        self.inv(a, self.t1, stock=5, minimo=2, critico=1, ideal=10)
        self.inv(b, self.t1, stock=5)                       # inerte
        self.inv(a, self.t2, stock=5)                       # inerte
        self.db.commit()

        r = diag.diagnostico(self.db)
        self.assertEqual(r["umbrales"]["total"]["filas"], 3)
        self.assertEqual(r["umbrales"]["total"]["con_minimo"], 1)
        self.assertEqual(r["umbrales"]["total"]["con_critico"], 1)
        self.assertEqual(r["umbrales"]["total"]["con_ideal"], 1)

        por_sede = {s["tienda"]: s for s in r["umbrales"]["por_sede"]}
        self.assertEqual(por_sede["Vida"]["filas"], 2)
        self.assertEqual(por_sede["Vida"]["con_minimo"], 1)
        self.assertEqual(por_sede["Palmetto"]["filas"], 1)
        self.assertEqual(por_sede["Palmetto"]["con_minimo"], 0)

    def test_umbrales_separa_el_inventario_gestionado(self):
        """Contar sobre TODAS las filas mezcla los archivados (controla_stock
        False / fuera del conteo) con lo que el motor de pedidos mira de verdad.
        Las dos cuentas van, y la fracción que se le muestra al dueño es la del
        inventario gestionado."""
        vivo = self.producto("Café")
        archivado = self.producto("Agua vieja", controla=False, conteo=False)
        self.inv(vivo, self.t1, minimo=3)
        self.inv(archivado, self.t1, minimo=0)
        self.db.commit()

        tot = diag.diagnostico(self.db)["umbrales"]["total"]
        self.assertEqual(tot["filas"], 2)
        self.assertEqual(tot["filas_gestionadas"], 1)
        self.assertEqual(tot["con_minimo_gestionadas"], 1)

    def test_umbrales_filtra_por_sede(self):
        a = self.producto("Café")
        self.inv(a, self.t1, minimo=2)
        self.inv(a, self.t2, minimo=0)
        self.db.commit()

        r = diag.diagnostico(self.db, tienda_id=self.t2.id)
        self.assertEqual(r["umbrales"]["total"]["filas"], 1)
        self.assertEqual(r["umbrales"]["total"]["con_minimo"], 0)
        self.assertEqual(len(r["umbrales"]["por_sede"]), 1)

    # — consumo —
    def test_consumo_cuenta_productos_con_salidas(self):
        a, b, c = self.producto("A"), self.producto("B"), self.producto("C")
        for p in (a, b, c):
            self.inv(p, self.t1)
        self.mov(a, self.t1, TipoMovInvEnum.salida, dias_atras=2)
        self.mov(a, self.t1, TipoMovInvEnum.salida, dias_atras=3)   # mismo producto
        self.mov(b, self.t1, TipoMovInvEnum.salida, dias_atras=20)  # fuera de 14d
        self.mov(c, self.t1, TipoMovInvEnum.salida, dias_atras=45)  # fuera de 30d
        self.mov(c, self.t1, TipoMovInvEnum.entrada, dias_atras=1)  # no es salida
        self.db.commit()

        r = diag.diagnostico(self.db)["consumo"]
        self.assertEqual(r["productos_con_salidas_30d"], 2)
        self.assertEqual(r["productos_con_salidas_14d"], 1)
        # El motor de pedidos NO usa 30 días: usa DIAS_ANALISIS (14).
        self.assertEqual(r["dias_analisis_motor"], 14)

    def test_consumo_en_cero_apaga_el_eje_tiempo(self):
        a = self.producto("A")
        self.inv(a, self.t1)
        self.db.commit()
        r = diag.diagnostico(self.db)["consumo"]
        self.assertEqual(r["productos_con_salidas_30d"], 0)
        self.assertTrue(r["motor_sin_datos"])

    # — negativos —
    def test_negativo_de_preparable_sin_entrada(self):
        mezcla = self.producto("Mezcla granizado", unidad="g", precio=0.0)
        insumo = self.producto("Azúcar", unidad="g")
        self.db.add(ProductoInsumo(producto_id=mezcla.id, insumo_id=insumo.id, cantidad=100))
        self.inv(mezcla, self.t1, stock=-4000)
        self.inv(insumo, self.t1, stock=500)
        self.db.commit()

        negs = diag.diagnostico(self.db)["negativos"]
        self.assertEqual(len(negs), 1)
        n = negs[0]
        self.assertEqual(n["producto"], "Mezcla granizado")
        self.assertEqual(n["sede"], "Vida")
        self.assertEqual(n["stock"], -4000)
        self.assertEqual(n["unidad"], "g")
        self.assertIsNone(n["ultima_entrada"])
        self.assertEqual(n["causa"], "preparable_sin_registrar")
        self.assertIn("sin_entrada_registrada", n["tambien_aplica"])

    def test_negativo_cuenta_las_recetas_que_lo_consumen(self):
        leche = self.producto("Leche", unidad="g")
        latte = self.producto("Latte", unidad="und", precio=9000, controla=False)
        capp = self.producto("Cappuccino", unidad="und", precio=9500, controla=False)
        self.db.add_all([
            ProductoInsumo(producto_id=latte.id, insumo_id=leche.id, cantidad=180),
            ProductoInsumo(producto_id=capp.id, insumo_id=leche.id, cantidad=150),
        ])
        self.inv(leche, self.t1, stock=-2000)
        self.mov(leche, self.t1, TipoMovInvEnum.entrada, dias_atras=4)
        self.db.commit()

        n = diag.diagnostico(self.db)["negativos"][0]
        self.assertEqual(n["lo_consumen_n_recetas"], 2)
        self.assertEqual(n["causa"], "consumo_sin_registro")
        self.assertIsNotNone(n["ultima_entrada"])

    def test_la_ultima_entrada_es_por_sede(self):
        """Una entrada en Palmetto no explica el negativo de Vida."""
        p = self.producto("Café", unidad="g")
        self.inv(p, self.t1, stock=-500)
        self.inv(p, self.t2, stock=100)
        self.mov(p, self.t2, TipoMovInvEnum.entrada, dias_atras=1)
        self.db.commit()

        negs = diag.diagnostico(self.db)["negativos"]
        self.assertEqual(len(negs), 1)
        self.assertEqual(negs[0]["sede"], "Vida")
        self.assertIsNone(negs[0]["ultima_entrada"])
        self.assertEqual(negs[0]["causa"], "sin_entrada_registrada")

    def test_una_salida_no_cuenta_como_entrada(self):
        p = self.producto("Café", unidad="g")
        self.inv(p, self.t1, stock=-500)
        self.mov(p, self.t1, TipoMovInvEnum.salida, dias_atras=1)
        self.db.commit()
        n = diag.diagnostico(self.db)["negativos"][0]
        self.assertIsNone(n["ultima_entrada"])
        self.assertEqual(n["causa"], "sin_entrada_registrada")

    def test_negativos_ordenados_del_peor_al_menos_malo(self):
        a, b = self.producto("A"), self.producto("B")
        self.inv(a, self.t1, stock=-10)
        self.inv(b, self.t1, stock=-900)
        self.db.commit()
        negs = diag.diagnostico(self.db)["negativos"]
        self.assertEqual([n["producto"] for n in negs], ["B", "A"])

    def test_sin_negativos_lista_vacia(self):
        a = self.producto("A")
        self.inv(a, self.t1, stock=12)
        self.db.commit()
        r = diag.diagnostico(self.db)
        self.assertEqual(r["negativos"], [])
        self.assertFalse(r["negativos_truncado"])

    def test_negativos_filtra_por_sede(self):
        p = self.producto("Café")
        self.inv(p, self.t1, stock=-5)
        self.inv(p, self.t2, stock=-7)
        self.db.commit()
        negs = diag.diagnostico(self.db, tienda_id=self.t1.id)["negativos"]
        self.assertEqual(len(negs), 1)
        self.assertEqual(negs[0]["sede"], "Vida")

    # — recetas sospechosas de unidad —
    def test_receta_grande_sobre_insumo_en_unidad_grande(self):
        café = self.producto("Café en grano", unidad="kg")
        latte = self.producto("Latte", unidad="und", precio=9000, controla=False)
        self.db.add(ProductoInsumo(producto_id=latte.id, insumo_id=café.id, cantidad=18))
        self.db.commit()

        sos = diag.diagnostico(self.db)["recetas_sospechosas"]
        self.assertEqual(len(sos), 1)
        s = sos[0]
        self.assertEqual(s["producto_vendido"], "Latte")
        self.assertEqual(s["insumo"], "Café en grano")
        self.assertEqual(s["dice_la_receta"], 18)
        self.assertEqual(s["unidad_del_insumo"], "kg")
        self.assertEqual(s["insumo_id"], café.id)
        self.assertTrue(s["sospecha"].startswith("Sospecha"))

    def test_receta_minuscula_sobre_insumo_en_unidad_chica(self):
        azucar = self.producto("Azúcar", unidad="g")
        latte = self.producto("Latte", unidad="und", precio=9000, controla=False)
        self.db.add(ProductoInsumo(producto_id=latte.id, insumo_id=azucar.id, cantidad=0.2))
        self.db.commit()
        sos = diag.diagnostico(self.db)["recetas_sospechosas"]
        self.assertEqual(len(sos), 1)
        self.assertEqual(sos[0]["dice_la_receta"], 0.2)

    def test_receta_razonable_no_es_sospechosa(self):
        leche = self.producto("Leche", unidad="g")
        latte = self.producto("Latte", unidad="und", precio=9000, controla=False)
        self.db.add(ProductoInsumo(producto_id=latte.id, insumo_id=leche.id, cantidad=180))
        self.db.commit()
        self.assertEqual(diag.diagnostico(self.db)["recetas_sospechosas"], [])

    def test_unidad_se_compara_sin_importar_mayusculas(self):
        p = self.producto("Leche", unidad="LT")
        latte = self.producto("Latte", unidad="und", precio=9000, controla=False)
        self.db.add(ProductoInsumo(producto_id=latte.id, insumo_id=p.id, cantidad=8))
        self.db.commit()
        self.assertEqual(len(diag.diagnostico(self.db)["recetas_sospechosas"]), 1)

    # — read-only —
    def test_el_diagnostico_no_escribe_nada(self):
        p = self.producto("Café", unidad="g")
        self.inv(p, self.t1, stock=-300)
        self.db.commit()
        antes_mov = self.db.query(MovimientoInventario).count()
        antes_stock = self.db.query(Inventario).filter_by(
            producto_id=p.id, tienda_id=self.t1.id).first().stock_actual

        diag.diagnostico(self.db)

        self.db.expire_all()
        self.assertEqual(self.db.query(MovimientoInventario).count(), antes_mov)
        self.assertEqual(self.db.query(Inventario).filter_by(
            producto_id=p.id, tienda_id=self.t1.id).first().stock_actual, antes_stock)


if __name__ == "__main__":
    unittest.main()
