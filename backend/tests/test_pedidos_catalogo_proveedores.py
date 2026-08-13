"""El catálogo APRENDIDO de proveedores: quién trae qué, y con qué autoridad.

Cada factura que entra por el escáner enseña quién trajo qué producto, a qué
precio y cuántas veces. Ese saber estaba enterrado: la pantalla de pedidos solo
lo usaba para pegarle un string de proveedor al último producto facturado.

Estos tests fijan la FUSIÓN de las dos fuentes y su jerarquía:

  1. `Producto.proveedor` — lo que el dueño asignó a mano. MANDA: marca al
     TITULAR, el proveedor al que ese producto se le pide por defecto.
  2. historial de `facturas_compra_items` — lo que el sistema APRENDIÓ. Pone al
     producto en el catálogo de ese proveedor, con su precio y su frecuencia.

Un producto puede haber venido de dos proveedores: aparece en los DOS catálogos
con sus números reales, y solo uno lo tiene como titular. Lo que no se sabe no
se inventa: sin `contenido_por_empaque` no hay empaques, sin factura no hay
precio, y un preparable no es de nadie porque no se compra.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import (
    CategoriaProductoEnum, FacturaCompra, FacturaCompraItem, Inventario,
    MovimientoInventario, Producto, ProductoInsumo, RolEnum, Tienda,
    TipoMovInvEnum, TipoPagoEnum, Usuario,
)
from app.services import pedidos as svc


class CatalogoProveedoresTest(unittest.TestCase):
    # ─── andamio ──────────────────────────────────────────────────────────────

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.vida = Tienda(nombre="Vida", direccion="x")
        self.palmetto = Tienda(nombre="Palmetto", direccion="y")
        self.db.add_all([self.vida, self.palmetto])
        self.db.flush()
        self.user = Usuario(nombre="Admin", email="a@t.local", password_hash="h",
                            rol=RolEnum.admin, tienda_id=self.vida.id, activo=True)
        self.db.add(self.user)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _producto(self, nombre, unidad="und", proveedor=None, precio_venta=0,
                  contenido_por_empaque=None, contenido_por_unidad=None,
                  controla_stock=True, incluir_en_conteo=True, lead_time_dias=2):
        p = Producto(nombre=nombre, categoria=CategoriaProductoEnum.insumo,
                     unidad_medida=unidad, controla_stock=controla_stock,
                     incluir_en_conteo=incluir_en_conteo, proveedor=proveedor,
                     precio_venta=precio_venta, lead_time_dias=lead_time_dias,
                     contenido_por_empaque=contenido_por_empaque,
                     contenido_por_unidad=contenido_por_unidad)
        self.db.add(p)
        self.db.flush()
        return p

    def _inv(self, producto, tienda=None, stock=0.0, minimo=0.0):
        inv = Inventario(producto_id=producto.id, tienda_id=(tienda or self.vida).id,
                         stock_actual=stock, stock_minimo=minimo)
        self.db.add(inv)
        self.db.flush()
        return inv

    def _factura(self, proveedor, items, tienda=None, dias_atras=1, valor=10000):
        """items: [(producto, cantidad, precio_unitario)]"""
        recibido = datetime.utcnow() - timedelta(days=dias_atras)
        f = FacturaCompra(tienda_id=(tienda or self.vida).id, proveedor=proveedor,
                          valor_total=valor, tipo_pago=TipoPagoEnum.contado,
                          usuario_id=self.user.id, fecha_recibido=recibido,
                          fecha_registro=recibido)
        self.db.add(f)
        self.db.flush()
        for prod, cant, precio in items:
            self.db.add(FacturaCompraItem(factura_id=f.id, producto_id=prod.id,
                                          cantidad=cant, precio_unitario=precio))
        self.db.flush()
        return f

    def _consumo(self, producto, tienda=None, por_dia=1.0, dias=14):
        """Salidas parejas para que haya consumo_diario y cantidad_sugerida > 0."""
        for d in range(dias):
            self.db.add(MovimientoInventario(
                producto_id=producto.id, tienda_id=(tienda or self.vida).id,
                tipo=TipoMovInvEnum.salida, cantidad=por_dia,
                fecha=datetime.utcnow() - timedelta(days=d, hours=1),
                usuario_id=self.user.id))
        self.db.flush()

    # ─── helpers de lectura ───────────────────────────────────────────────────

    def _catalogo(self, tienda=None):
        return svc.catalogo_proveedores(self.db, (tienda or self.vida).id)

    def _prov(self, cat, nombre):
        for g in cat["proveedores"]:
            if g["proveedor"] == nombre:
                return g
        return None

    def _item(self, grupo, producto):
        for it in grupo["productos"]:
            if it["producto_id"] == producto.id:
                return it
        return None

    # ─── 1. la asignación manual manda ────────────────────────────────────────

    def test_asignacion_manual_manda_y_marca_titular(self):
        """`Producto.proveedor` es la palabra del dueño: pone al producto en ese
        catálogo y lo marca titular, aunque no exista ni una factura."""
        torta = self._producto("Torta Red Velvet", proveedor="María María")
        self._inv(torta, stock=1, minimo=4)

        cat = self._catalogo()
        g = self._prov(cat, "María María")
        self.assertIsNotNone(g, "el proveedor asignado a mano debe existir en el catálogo")
        it = self._item(g, torta)
        self.assertIsNotNone(it)
        self.assertTrue(it["titular"])
        self.assertEqual(it["fuente"], "manual")
        self.assertEqual(it["proveedor_manual"], "María María")
        # Sin facturas no hay precio ni frecuencia: no se inventan.
        self.assertIsNone(it["ultimo_precio"])
        self.assertIsNone(it["ultima_compra"])
        self.assertEqual(it["veces_comprado"], 0)
        self.assertEqual(g["origen"], "manual")

    # ─── 2. lo aprendido de las facturas ──────────────────────────────────────

    def test_producto_aprendido_de_facturas_entra_al_catalogo(self):
        """Sin asignación manual, la factura es la que enseña: el producto queda
        en el catálogo del proveedor que lo trajo, con su precio y su fecha."""
        leche = self._producto("Leche Entera", unidad="ml")
        self._inv(leche, stock=0, minimo=10)
        self._factura("Delitas", [(leche, 12, 3400)], dias_atras=3)

        cat = self._catalogo()
        g = self._prov(cat, "Delitas")
        self.assertIsNotNone(g)
        it = self._item(g, leche)
        self.assertIsNotNone(it)
        self.assertEqual(it["fuente"], "compras")
        self.assertTrue(it["titular"], "sin asignación manual, el que lo trajo es el titular")
        self.assertIsNone(it["proveedor_manual"])
        self.assertAlmostEqual(it["ultimo_precio"], 3400.0)
        self.assertEqual(it["veces_comprado"], 1)
        self.assertIsNotNone(it["ultima_compra"])
        self.assertEqual(g["origen"], "compras")

    # ─── 3. dos proveedores, un titular ───────────────────────────────────────

    def test_producto_de_dos_proveedores_aparece_en_ambos_con_un_solo_titular(self):
        """El mismo producto vino de dos lados. Los dos catálogos lo muestran con
        SUS números; la asignación manual decide a quién se le pide."""
        vaso = self._producto("Vaso 12oz", proveedor="Envases del Valle")
        self._inv(vaso, stock=5, minimo=50)
        self._factura("Envases del Valle", [(vaso, 100, 210)], dias_atras=10)
        self._factura("Desechables Ya", [(vaso, 100, 190)], dias_atras=2)

        cat = self._catalogo()
        g_manual = self._prov(cat, "Envases del Valle")
        g_otro = self._prov(cat, "Desechables Ya")
        self.assertIsNotNone(g_manual)
        self.assertIsNotNone(g_otro, "el otro proveedor que lo trajo no se pierde")

        it_manual = self._item(g_manual, vaso)
        it_otro = self._item(g_otro, vaso)
        self.assertTrue(it_manual["titular"])
        self.assertFalse(it_otro["titular"], "solo uno es el titular")
        # Cada catálogo muestra el precio de SUS propias facturas.
        self.assertAlmostEqual(it_manual["ultimo_precio"], 210.0)
        self.assertAlmostEqual(it_otro["ultimo_precio"], 190.0)
        # El manual es titular aunque la factura del otro sea MÁS reciente.
        self.assertEqual(it_otro["proveedor_manual"], "Envases del Valle")
        self.assertEqual(g_manual["origen"], "ambos")
        # El contador del card cuenta lo que el card muestra: el producto se
        # precarga en el card del titular y en el otro queda para agregar. Si los
        # dos lo contaran, un vaso se pediría dos veces.
        self.assertEqual(g_manual["n_en_alerta"] + g_manual["n_necesita"], 1)
        self.assertEqual(g_otro["n_en_alerta"] + g_otro["n_necesita"], 0)

    def test_sin_asignacion_manual_titular_es_la_factura_mas_reciente(self):
        """Dos proveedores, ninguna asignación: gana el último que lo trajo."""
        servilleta = self._producto("Servilleta")
        self._inv(servilleta, stock=0, minimo=20)
        self._factura("Papelera Vieja", [(servilleta, 50, 30)], dias_atras=30)
        self._factura("Papelera Nueva", [(servilleta, 50, 28)], dias_atras=1)

        cat = self._catalogo()
        self.assertFalse(self._item(self._prov(cat, "Papelera Vieja"), servilleta)["titular"])
        self.assertTrue(self._item(self._prov(cat, "Papelera Nueva"), servilleta)["titular"])

    # ─── 4. el bucket «sin proveedor» ─────────────────────────────────────────

    def test_sin_proveedor_solo_lo_que_necesita_pedido(self):
        """Lo que hay que pedir y el sistema no sabe quién lo trae. Lo que no
        necesita nada no entra: es una pantalla de trabajo, no un inventario."""
        huerfano = self._producto("Canela en polvo")
        self._inv(huerfano, stock=0, minimo=5)          # necesita
        tranquilo = self._producto("Sal")
        self._inv(tranquilo, stock=100, minimo=1)       # no necesita nada

        cat = self._catalogo()
        ids = [i["producto_id"] for i in cat["sin_proveedor"]]
        self.assertIn(huerfano.id, ids)
        self.assertNotIn(tranquilo.id, ids)
        item = [i for i in cat["sin_proveedor"] if i["producto_id"] == huerfano.id][0]
        self.assertGreater(item["cantidad_sugerida"], 0)
        self.assertTrue(item["necesita"])

    def test_sin_proveedor_tambien_muestra_lo_agotado_sin_minimo(self):
        """Con los umbrales en cero (el caso real del negocio) la fórmula da 0 y
        el bucket quedaba vacío justo cuando más falta hace: un producto agotado
        y sin dueño es exactamente lo que hay que resolver."""
        agotado = self._producto("Vaso 8oz")
        self._inv(agotado, stock=0, minimo=0)

        item = [i for i in self._catalogo()["sin_proveedor"]
                if i["producto_id"] == agotado.id]
        self.assertEqual(len(item), 1)
        self.assertEqual(item[0]["cantidad_sugerida"], 0)
        self.assertFalse(item[0]["necesita"])
        self.assertTrue(item[0]["en_alerta_sin_sugerencia"])

    # ─── 5. los preparables no se le compran a nadie ──────────────────────────

    def test_preparable_nunca_aparece_como_compra(self):
        """La mezcla de granizado se ARMA. Ni con proveedor tecleado ni con una
        factura vieja encima entra a un catálogo o al bucket de sin proveedor:
        no hay a quién mandarle ese renglón por WhatsApp."""
        azucar = self._producto("Azúcar", unidad="gr")
        mezcla = self._producto("MEZCLA GRANIZADO", unidad="gr",
                                proveedor="María María", contenido_por_unidad=2820)
        self.db.add(ProductoInsumo(producto_id=mezcla.id, insumo_id=azucar.id, cantidad=360))
        self._inv(mezcla, stock=0, minimo=1000)
        self._inv(azucar, stock=5000, minimo=100)
        self._factura("María María", [(mezcla, 3, 5000)], dias_atras=4)

        cat = self._catalogo()
        en_catalogos = [it["producto_id"]
                        for g in cat["proveedores"] for it in g["productos"]]
        self.assertNotIn(mezcla.id, en_catalogos)
        self.assertNotIn(mezcla.id, [i["producto_id"] for i in cat["sin_proveedor"]])
        # Pero su necesidad no se pierde: sale por su propia puerta, con su verbo.
        prep_ids = [i["producto_id"] for i in cat["preparables"]]
        self.assertIn(mezcla.id, prep_ids)
        prep = [i for i in cat["preparables"] if i["producto_id"] == mezcla.id][0]
        self.assertEqual(prep["accion"], "preparar")

    # ─── 6. el empaque no se inventa ──────────────────────────────────────────

    def test_empaque_solo_si_esta_cargado(self):
        """«2 bolsas de 10» solo se puede decir si alguien cargó cuánto trae la
        bolsa. Sin `contenido_por_empaque` el campo viaja en None y la pantalla
        habla en unidades: no hay factor que inventar."""
        con = self._producto("Café en grano", unidad="gr", contenido_por_empaque=2500,
                             proveedor="Café del Huila")
        sin = self._producto("Chocolate", unidad="gr", proveedor="Café del Huila")
        self._inv(con, stock=0, minimo=100)
        self._inv(sin, stock=0, minimo=100)

        g = self._prov(self._catalogo(), "Café del Huila")
        self.assertEqual(self._item(g, con)["contenido_por_empaque"], 2500.0)
        self.assertIsNone(self._item(g, sin)["contenido_por_empaque"])

    # ─── 7. precio y frecuencia por PAR proveedor-producto ────────────────────

    def test_ultimo_precio_y_veces_son_del_par_proveedor_producto(self):
        """Tres compras al mismo proveedor: la cuenta es 3 y el precio es el de
        la más reciente, no el de la más cara ni el de la primera."""
        pulpa = self._producto("Pulpa de mora", unidad="gr")
        self._inv(pulpa, stock=0, minimo=10)
        self._factura("Maxipulpas", [(pulpa, 10, 1000)], dias_atras=20)
        self._factura("Maxipulpas", [(pulpa, 10, 1500)], dias_atras=10)
        self._factura("Maxipulpas", [(pulpa, 10, 1200)], dias_atras=2)

        it = self._item(self._prov(self._catalogo(), "Maxipulpas"), pulpa)
        self.assertEqual(it["veces_comprado"], 3)
        self.assertAlmostEqual(it["ultimo_precio"], 1200.0)

    # ─── 8. la sede: lo aprendido no cruza, pero tampoco se tira ──────────────

    def test_facturas_de_otra_sede_no_cuelgan_el_proveedor_pero_lo_sugieren(self):
        """Una factura es evidencia de que ese proveedor le entrega a ESA sede.
        En la otra sede no se afirma; se ofrece como pista para asignarlo."""
        pan = self._producto("Pan de bono")
        self._inv(pan, tienda=self.vida, stock=0, minimo=10)
        self._inv(pan, tienda=self.palmetto, stock=0, minimo=10)
        self._factura("Panadería La Canasta", [(pan, 20, 800)],
                      tienda=self.palmetto, dias_atras=2)

        # En Palmetto: el proveedor aprendido manda.
        cat_p = self._catalogo(self.palmetto)
        self.assertIsNotNone(self._prov(cat_p, "Panadería La Canasta"))

        # En Vida: nadie le entregó nunca. No se afirma un proveedor…
        cat_v = self._catalogo(self.vida)
        self.assertIsNone(self._prov(cat_v, "Panadería La Canasta"))
        huerfanos = [i for i in cat_v["sin_proveedor"] if i["producto_id"] == pan.id]
        self.assertEqual(len(huerfanos), 1)
        # …pero se dice dónde sí se sabe, para asignarlo de un toque.
        self.assertEqual(huerfanos[0]["visto_en_otra_sede"], "Panadería La Canasta")

    # ─── 9. la cantidad sugerida NO cambia de fórmula ─────────────────────────

    def test_cantidad_sugerida_identica_a_la_de_sugerencia(self):
        """Este módulo CONSUME `cantidad_sugerida`; no la recalcula distinto."""
        cafe = self._producto("Café molido", unidad="gr", proveedor="Café del Huila")
        self._inv(cafe, stock=300, minimo=100)
        self._consumo(cafe, por_dia=50)

        esperado = [i for i in self._items_sugerencia() if i["producto_id"] == cafe.id][0]
        it = self._item(self._prov(self._catalogo(), "Café del Huila"), cafe)
        self.assertEqual(it["cantidad_sugerida"], esperado["cantidad_sugerida"])
        self.assertEqual(it["estado"], esperado["estado"])
        self.assertEqual(it["dias_restantes"], esperado["dias_restantes"])

    def _items_sugerencia(self):
        s = svc.sugerencia_pedido(self.db, self.vida.id)
        return [i for g in s["grupos_fijos"] for i in g["productos"]] + s["insumos_generales"]

    # ─── 10. el mismo proveedor escrito de dos formas es UNO ──────────────────

    def test_nombres_del_mismo_proveedor_se_unifican(self):
        """«Lacteos Andina» y «LÁCTEOS ANDINA» son el mismo teléfono. Se agrupan
        por nombre normalizado y se muestra la grafía que escribió el dueño."""
        queso = self._producto("Queso costeño", proveedor="Lácteos Andina")
        yogurt = self._producto("Yogurt griego")
        self._inv(queso, stock=0, minimo=5)
        self._inv(yogurt, stock=0, minimo=5)
        self._factura("LACTEOS ANDINA", [(queso, 5, 9000)], dias_atras=5)
        self._factura("lacteos  andina", [(yogurt, 5, 7000)], dias_atras=3)

        cat = self._catalogo()
        candidatos = [g for g in cat["proveedores"]
                      if "ANDINA" in g["proveedor"].upper()]
        self.assertEqual(len(candidatos), 1, "tres grafías, un solo proveedor")
        g = candidatos[0]
        self.assertEqual(g["proveedor"], "Lácteos Andina",
                         "manda la grafía que el dueño asignó a mano")
        self.assertEqual({i["producto_id"] for i in g["productos"]}, {queso.id, yogurt.id})

    # ─── 11. el catálogo es más grande que la alerta ──────────────────────────

    def test_catalogo_trae_tambien_lo_que_hoy_no_necesita(self):
        """Poder agregar «ya que llamo, mandame también…» es media utilidad del
        módulo: el catálogo completo viaja, marcado con `necesita`."""
        urge = self._producto("Azúcar morena", unidad="gr", proveedor="La Paola")
        sobra = self._producto("Miel", unidad="gr", proveedor="La Paola")
        self._inv(urge, stock=0, minimo=100)
        self._inv(sobra, stock=5000, minimo=10)

        g = self._prov(self._catalogo(), "La Paola")
        self.assertEqual(len(g["productos"]), 2)
        self.assertTrue(self._item(g, urge)["necesita"])
        self.assertFalse(self._item(g, sobra)["necesita"])
        self.assertEqual(g["n_necesita"], 1)

    def test_producto_sin_inventario_en_la_sede_viaja_sin_stock_inventado(self):
        """El proveedor lo trajo alguna vez pero acá no se cuenta: se puede
        pedir, pero su stock es None — no cero, que sería una afirmación."""
        exotico = self._producto("Sirope de avellana", unidad="ml")
        self._factura("La Paola", [(exotico, 2, 22000)], dias_atras=6)

        it = self._item(self._prov(self._catalogo(), "La Paola"), exotico)
        self.assertIsNotNone(it)
        self.assertFalse(it["gestionado"])
        self.assertIsNone(it["stock_actual"])
        self.assertEqual(it["cantidad_sugerida"], 0)
        self.assertFalse(it["necesita"])

    def test_sin_asignar_trae_todo_lo_no_asignado_para_la_pantalla_de_asignar(self):
        """`sin_proveedor` es la lista de TRABAJO (lo que hay que pedir hoy);
        `sin_asignar` es la de CONFIGURACIÓN: todo lo que no tiene dueño, urja o
        no. Son dos preguntas distintas y por eso son dos listas."""
        urge = self._producto("Canela")
        self._inv(urge, stock=0, minimo=5)
        tranquilo = self._producto("Sal")
        self._inv(tranquilo, stock=100, minimo=1)
        asignado = self._producto("Galleta", proveedor="Wilenses")
        self._inv(asignado, stock=0, minimo=5)

        cat = self._catalogo()
        ids = {i["producto_id"] for i in cat["sin_asignar"]}
        self.assertIn(urge.id, ids)
        self.assertIn(tranquilo.id, ids, "lo que no urge también se puede asignar")
        self.assertNotIn(asignado.id, ids, "ya tiene dueño")

    # ─── 13. agotado sin mínimo cargado: se ve, pero no se inventa cuánto ─────

    def test_agotado_sin_minimo_se_marca_aunque_no_haya_cantidad_sugerida(self):
        """Con `stock_minimo` en 0 y sin consumo registrado, la fórmula da
        `cantidad_sugerida = 0` — y no se toca, que es contrato. Pero el producto
        está AGOTADO: esconderlo porque la cuenta dio cero sería el bug de
        siempre (motor inerte, pantalla que dice «todo bien» con la vitrina
        vacía). Se marca aparte para que la pantalla lo muestre y el dueño
        escriba la cantidad él."""
        torta = self._producto("Torta Chocolate", proveedor="María María")
        self._inv(torta, stock=0, minimo=0)      # umbrales en cero: el caso real

        it = self._item(self._prov(self._catalogo(), "María María"), torta)
        self.assertEqual(it["estado"], "agotado")
        self.assertEqual(it["cantidad_sugerida"], 0, "la fórmula NO cambia")
        self.assertFalse(it["necesita"], "no se precarga una cantidad inventada")
        self.assertTrue(it["en_alerta_sin_sugerencia"], "pero se ve")

        g = self._prov(self._catalogo(), "María María")
        self.assertEqual(g["n_en_alerta"], 1)
        self.assertEqual(g["estado_resumen"], "agotado",
                         "el card no puede decir OK con un producto agotado adentro")

    def test_lo_que_esta_ok_no_se_marca_en_alerta(self):
        """El resto del catálogo sigue siendo resto: solo agotado/urgente sube."""
        miel = self._producto("Miel", proveedor="La Paola")
        self._inv(miel, stock=500, minimo=10)

        it = self._item(self._prov(self._catalogo(), "La Paola"), miel)
        self.assertFalse(it["en_alerta_sin_sugerencia"])
        self.assertFalse(it["necesita"])

    # ─── 12. el listado para el datalist de asignación rápida ─────────────────

    def test_proveedores_conocidos_para_asignar_de_un_toque(self):
        """La asignación en el lugar necesita la lista de nombres ya conocidos,
        incluidos los de la otra sede: se asigna un proveedor, no se inventa."""
        p = self._producto("Galleta", proveedor="Wilenses")
        self._inv(p, stock=0, minimo=5)
        self._factura("Industrias Dulces", [(p, 10, 500)], tienda=self.palmetto, dias_atras=3)

        conocidos = self._catalogo()["proveedores_conocidos"]
        self.assertIn("Wilenses", conocidos)
        self.assertIn("Industrias Dulces", conocidos)


if __name__ == "__main__":
    unittest.main()
