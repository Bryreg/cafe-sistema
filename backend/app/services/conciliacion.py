"""Escalera de conciliación por producto: POR QUÉ falta, no solo CUÁNTO.

El cierre de mes entrega hoy UN número por producto —físico contado menos
sistema— y ese número mezcla en la misma cifra el consumo normal, la merma no
registrada, el error de conteo, la receta mal cargada y el robo. Todos producen
el mismo síntoma (un negativo) y ninguno se puede distinguir del otro.

La escalera descompone ese número renglón por renglón sobre un RANGO DE FECHAS
arbitrario:

    stock inicial (del libro, al arrancar el rango)
  + entradas                (compras, recepciones, traslados que entran)
  − ventas                  (lo que el POS descontó por venta)
  − mermas                  (consumo y daño registrados)
  − traslados               (lo que salió a otra sede)
  − preparaciones           (insumos que se transformaron en otro producto)
  − otras salidas           (registradas pero sin causa nombrada)
  + reversas                (anulaciones que repusieron stock)
  ± ajustes                 (correcciones manuales, como DELTA)
  = STOCK ESPERADO
    stock físico − STOCK ESPERADO = DIFERENCIA INEXPLICADA   ← la fuga

Cada renglón es una CAUSA CONOCIDA; lo que sobra al final es lo único que merece
investigación. Hoy el dueño investiga el total, con la escalera investiga el
residuo.

CON UNA EXCEPCIÓN QUE HAY QUE DECIR EN VOZ ALTA: `ajustes_conteo`
Aplicar un conteo físico escribe un movimiento tipo `ajuste` (conteos.py:40,
inventario_mensual.py:496). Ese renglón NO es una causa: es un residuo
inexplicado ANTERIOR que ya se volcó al libro. Va separado de los ajustes
manuales justamente porque una sede que aplica conteos parciales dentro del mes
vería residuo ~0 y leería "nada queda sin explicar" con la fuga escondida.

Y EL RESIDUO NO ES UN CULPABLE
Lo inexplicado es, por construcción, la SUMA de todo lo que no se registró:
sobre-servida y dosificación a ojo, consumo del personal, degustaciones,
reprocesos, derrames, error de conteo, contar en una unidad distinta a la del
libro — y también robo. Las cuatro primeras son legítimas y comparten con la
última la única propiedad que la escalera puede ver: nadie las anotó. Este
módulo mide y NUNCA atribuye; ningún campo de acá dice ni sugiere robo.

POR QUÉ SE RECONSTRUYE DESDE EL LIBRO Y NO DESDE LA FOTO DEL CIERRE
`InventarioMensualItem.cantidad_sistema` se congela en el primer instante en que
alguien ABRE la pantalla del kiosko ese mes: el consumo legítimo de las semanas
siguientes aparece después como faltante. La escalera no toca esa foto —
reconstruye el esperado desde `MovimientoInventario`, que sí tiene fecha. De ahí
sale gratis la parametrización por rango: pasar de mensual a semanal no cambia
una línea de este módulo.

LA IDENTIDAD ES EXACTA POR CONSTRUCCIÓN
`stock_esperado` es el saldo del LIBRO al corte, y la suma de los renglones da
exactamente ese saldo: los buckets solo reparten movimientos que ya están
contados, y el bucket `otras_salidas` recoge todo lo que la clasificación por
motivo no sabe nombrar. Un motivo nuevo puede quedar mal ETIQUETADO, pero nunca
puede caerse de la escalera ni ensuciar el residuo.

EL CONSUMO TEÓRICO VA APARTE, COMO CONTRASTE
`consumo_teorico` (receta × unidades vendidas) NO entra en la identidad: entra
como comparación contra lo que el libro descontó de verdad. Si no coinciden, la
causa es la receta o la cascada a sustituto — una causa distinta del robo, que
merece su propio número (`descuadre_receta`) en vez de esconderse en el residuo.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_

from app.core.tz import inicio_dia_col_utc, fin_dia_col_utc
from app.models.models import (Inventario, InventarioMensual,
                               MovimientoInventario, Producto, ProductoInsumo,
                               Ticket, TicketItem, TicketItemComboSeleccion)
from app.services import preparables as preparables_svc

# Tolerancia de redondeo: el stock es Float y la escalera suma decenas de
# movimientos. Por debajo de esto no hay diferencia, hay ruido de punto flotante.
EPS = 0.001

# ─── Costo unitario: UNA sola fuente, priorizada y con el origen a la vista ───

# Etiquetas del ORIGEN del costo. El dueño tiene que poder distinguir un valor
# FIRME de uno ESTIMADO antes de decidir si un faltante vale la investigación.
ORIGEN_LABEL = {
    "oficial": "costo oficial cargado a mano",
    "factura": "promedio ponderado de facturas",
    "receta": "suma de los insumos de su receta",
    "estimado": "estimado con el precio de venta (sobrestima)",
    "sin_costo": "sin costo cargado — la fuga no se puede valorizar",
}


def _rendimiento_preparables(db) -> dict[int, float]:
    """producto_id → rendimiento de UNA tanda, solo de los PREPARABLES.

    Un preparable (`services/inventario.get_preparables`) es el producto que
    controla stock, tiene receta y NO se vende en el POS: la mezcla de granizado,
    el almíbar. Su receta describe UNA TANDA y su `contenido_por_unidad` dice
    cuántas unidades de INVENTARIO rinde esa tanda (2.820 gr de mezcla por cada
    360 gr de azúcar).

    Existe para no confundir las dos unidades al valorizar. `contenido_por_unidad`
    tiene DOS significados en el catálogo —rendimiento de la preparación y gr de
    la bolsa sellada del conteo (models.py:276)—, así que dividir por él a ciegas
    rompería el costo de cualquier producto de reventa que venga en bolsa. Acá se
    devuelve SOLO donde significa rendimiento.

    La definición de preparable y esta tabla viven en `services/preparables.py`:
    acá quedó el nombre que ya usa `costo_unitario` más abajo, no una segunda
    copia de las reglas.
    """
    return preparables_svc.rendimiento_por_tanda(db)


def costo_unitario(db) -> dict[int, tuple[float, str]]:
    """(costo por unidad de INVENTARIO, origen) de cada producto.

    Prioridad explícita, de más firme a más flojo:
      1. `Producto.precio_costo` — el costo que el dueño fijó a mano.
      2. Promedio PONDERADO por cantidad de `FacturaCompraItem`.
      3. Receta: Σ insumo × su costo (preparables que nunca se compran hechos).
      4. `precio_venta` como último recurso, MARCADO como estimado.
      5. Sin nada: 0 y `sin_costo` — nunca un cero mudo.

    Los pasos 1-3 se delegan a `rentabilidad._costos_insumos` /
    `_costo_unitario_productos`: son la verdad que ya usa el P&L y duplicarla acá
    crearía una tercera versión del costo del mismo producto en otra pantalla,
    que es exactamente el problema que este módulo viene a cerrar.

    El paso 4 existe porque es lo que el cierre venía haciendo y sacarlo de golpe
    bajaría el valor de meses YA cerrados sin avisar. Se conserva, pero deja de
    ser invisible: viaja etiquetado `estimado` hasta la pantalla.

    EL PASO 3 CAMBIA DE UNIDAD Y HAY QUE CONVERTIRLO
    `_costo_unitario_productos` devuelve costo por unidad de VENTA —o sea por
    TANDA en un preparable— y lo dice en su propio docstring (rentabilidad.py:51).
    Su rama de receta suma `pi.cantidad × costo` de UNA tanda y hace `continue`
    antes de la guarda de granel (rentabilidad.py:64-77). Tomar ese número como
    costo por GRAMO multiplica el residuo por el rendimiento: 1 gr de mezcla de
    granizado valía $3.600 en vez de $1,28, encabezaba el ranking con una fuga
    fabricada y llegaba así al P&L. Acá se divide por el rendimiento; sin
    rendimiento cargado no hay conversión posible y se declara `sin_costo` en vez
    de inventar el factor.
    """
    from app.services import rentabilidad

    # Costo por unidad de inventario (oficial > promedio ponderado de facturas).
    base, _ = rentabilidad._costos_insumos(db)
    # Costo por TANDA de los preparables por receta (nunca entran por factura).
    por_receta = rentabilidad._costo_unitario_productos(db)
    rendimientos = _rendimiento_preparables(db)

    oficiales = {
        pid for pid, in db.query(Producto.id).filter(
            Producto.precio_costo.isnot(None), Producto.precio_costo > 0).all()
    }

    out: dict[int, tuple[float, str]] = {}
    for p in db.query(Producto).all():
        if p.id in oficiales:
            out[p.id] = (float(base[p.id]), "oficial")
        elif p.id in base:
            out[p.id] = (float(base[p.id]), "factura")
        elif p.id in por_receta and float(por_receta[p.id]) > 0:
            costo_tanda = float(por_receta[p.id])
            if p.id in rendimientos:
                rinde = rendimientos[p.id]
                out[p.id] = ((costo_tanda / rinde, "receta") if rinde > 0
                             else (0.0, "sin_costo"))
            else:
                # No es preparable: se cuenta en la misma unidad en que se vende,
                # así que el costo de la receta ya está en la unidad correcta.
                out[p.id] = (costo_tanda, "receta")
        elif float(p.precio_venta or 0) > 0:
            out[p.id] = (float(p.precio_venta), "estimado")
        else:
            out[p.id] = (0.0, "sin_costo")
    return out


# ─── Clasificación de movimientos ────────────────────────────────────────────
# El libro no tiene una columna de causa: solo `tipo` (entrada/salida/ajuste) y
# el texto de `motivo` que escribe cada servicio. Esta tabla mapea esos textos a
# los renglones de la escalera. Si un servicio cambia su motivo, el movimiento
# NO se pierde: cae en el bucket genérico (`entradas` / `otras_salidas`) y la
# identidad sigue cerrando. Lo único que se degrada es la etiqueta.
#
# Y la etiqueta ES el producto: el renglón que el dueño LEE tiene que decir la
# causa REAL. Cada prefijo de acá está cotejado contra el `motivo` que escribe su
# servicio, con la línea al lado. Un prefijo que no matchea no rompe la identidad
# pero le miente al que la lee, que es exactamente lo que este módulo evita.
_PREFIJOS_SALIDA = (
    ("Venta POS", "ventas"),                        # pos.py:463 y :501
    ("Consumo", "mermas"),                          # mermas.py:76
    ("Daño", "mermas"),                             # mermas.py:78
    ("Traslado a", "traslados"),                    # mermas.py:80
    ("Preparación:", "preparaciones"),              # inventario.py:569
    ("Preparación pastelería", "preparaciones"),    # pasteleria.py:100 — SIN dos puntos
    ("Anulación", "reversas_salida"),               # mermas.py:265 (revertir recibo)
    ("Eliminación factura", "reversas_salida"),     # facturas.py:44
    ("Corrección factura", "reversas_salida"),      # facturas.py:499 y :513
)
_PREFIJOS_ENTRADA = (
    ("Anulación", "reversas"),                      # pos.py:1092, mermas.py:276 y :287
    ("Nota crédito", "reversas"),                   # notas_credito.py:109
    ("Preparación:", "preparaciones_producidas"),   # inventario.py:580
    ("Recibo traslado", "traslados_recibidos"),     # mermas.py:221
    # Unificar dos fichas duplicadas mueve el stock del archivado al que queda:
    # inventario.py:645 escribe el MISMO motivo en la entrada del keeper y en la
    # salida del archivado. La salida cae en `otras_salidas`, que no afirma nada;
    # la entrada caía en el bucket genérico rotulado "compras y recepciones", y
    # una unificación de stock no es una compra: nadie compró ni recibió nada,
    # el mismo producto cambió de ficha. Renglón propio para no inflar la
    # mercadería que se cree que entró al local.
    ("Unificación", "unificaciones"),               # inventario.py:645
)
# Ajustes que NO son una causa: son un residuo inexplicado ANTERIOR que ya se
# escribió al libro. Ver el comentario de `ajustes_conteo` en RENGLONES.
_PREFIJOS_AJUSTE = (
    ("Conteo #", "ajustes_conteo"),                 # conteos.py:43
    ("Verificación de conteo", "ajustes_conteo"),   # conteos.py:347
    ("Inventario mensual", "ajustes_conteo"),       # inventario_mensual.py:498
    ("Ajuste por conteo", "ajustes_conteo"),        # compras.py:67
)

RENGLONES = [
    # (clave, etiqueta, signo con el que entra al esperado)
    ("entradas", "Entradas (compras y recepciones)", +1),
    ("traslados_recibidos", "Recibido de otra sede", +1),
    ("unificaciones", "Recibido al unificar productos duplicados", +1),
    ("reversas", "Reversas de anulaciones", +1),
    ("preparaciones_producidas", "Producido en preparaciones", +1),
    ("ventas", "Consumo por ventas registradas", -1),
    ("mermas", "Mermas registradas", -1),
    ("traslados", "Traslados a otra sede", -1),
    ("preparaciones", "Consumido en preparaciones", -1),
    ("reversas_salida", "Reversas y correcciones de compra", -1),
    ("otras_salidas", "Otras salidas registradas", -1),
    # Un conteo físico aplicado escribe un `ajuste` con el stock contado
    # (conteos.py:40, inventario_mensual.py:496): eso NO es una causa, es un
    # residuo inexplicado ANTERIOR ya volcado al libro. Sin separarlo, una sede
    # que aplica conteos parciales dentro del mes ve residuo ~0 y la pantalla le
    # dice "nada queda sin explicar" con la fuga escondida adentro de "ajustes
    # manuales". Va en su propio renglón para que se pueda leer y sumar aparte.
    ("ajustes_conteo", "Ajustes de conteos aplicados (esto también era fuga)", +1),
    ("ajustes", "Ajustes manuales", +1),   # ya viene con signo propio
]

# Renglones que son SALIDA de mercadería. El denominador de "cuánto se movió",
# que es lo que convierte un residuo en un porcentaje comparable entre productos.
_SALIDAS = ("ventas", "mermas", "traslados", "preparaciones",
            "reversas_salida", "otras_salidas")

# Un residuo crónico y chico contra el consumo es PROCESO (dosificación, servida
# a ojo); un salto grande es EVENTO. Son umbrales de PRESENTACIÓN —sirven para
# decidir qué mirar primero, no para afirmar una causa— y por eso están acá
# nombrados en vez de escondidos en la pantalla.
PCT_PROCESO = 5.0
PCT_EVENTO = 20.0

# Prioridad del ranking. Un EVENTO y un PROCESO piden acciones distintas —uno se
# investiga, el otro se corrige entrenando la dosificación— y mezclarlos en un
# único orden por plata pone arriba siempre al producto de más rotación, que es
# el que más varianza NORMAL acumula: la leche con 3% de servida de más le gana
# al frasco de jarabe que efectivamente desapareció. Se agrupa por patrón y la
# plata ordena DENTRO de cada grupo, que es donde comparar pesos tiene sentido.
# `None` (el producto no tuvo salidas en el período, así que no hay % contra qué
# medirlo) va después de "revisar": que algo se mueva sin haberse consumido no es
# rutina, pero tampoco es un patrón medido.
_ORDEN_PATRON = {"evento": 0, "revisar": 1, None: 2, "proceso": 3}


def _bucket(tipo: str, motivo: str | None) -> str:
    m = (motivo or "").strip()
    if tipo == "entrada":
        for pref, clave in _PREFIJOS_ENTRADA:
            if m.startswith(pref):
                return clave
        return "entradas"
    if tipo == "salida":
        for pref, clave in _PREFIJOS_SALIDA:
            if m.startswith(pref):
                return clave
        return "otras_salidas"
    for pref, clave in _PREFIJOS_AJUSTE:
        if m.startswith(pref):
            return clave
    return "ajustes"


# ─── Saldo del libro en cualquier instante ───────────────────────────────────

def _tipo(m) -> str:
    return getattr(m.tipo, "value", m.tipo)


def _saldos(movs: list, stock_hoy: float) -> tuple[list, float, list, bool]:
    """`despues[i]` = saldo del libro DESPUÉS de `movs[i]`, más el saldo previo a
    todo el libro; y en paralelo, si cada uno de esos saldos es FIRME o ESTIMADO.

    Hace falta esta gimnasia porque un movimiento tipo `ajuste` guarda en
    `cantidad` el stock RESULTANTE, no el delta. Hacia adelante eso es un ancla
    perfecta (después del ajuste el saldo ES ese número); hacia atrás es un muro
    (el saldo previo al ajuste no quedó registrado en ninguna parte).

    Tres pasadas, de más firme a más floja:
      A. hacia ATRÁS desde el stock vivo de Inventario — el ancla más confiable,
         porque está atada a la realidad de hoy. Se frena en el primer ajuste.
      B. hacia ADELANTE desde el primer ajuste — ancla absoluta, cubre el tramo
         intermedio que la pasada A no alcanzó.
      C. hacia ADELANTE desde CERO al inicio del libro — cubre el tramo más viejo
         y es la única ESTIMADA: asume que el producto arrancó en cero y que todo
         lo que entró después pasó por el libro. En producción es así (las filas
         de Inventario se crean en 0 y todo movimiento pasa por
         `registrar_movimiento`), pero es un supuesto y viaja marcado como tal
         hasta la pantalla en vez de hacerse pasar por un dato.
    """
    n = len(movs)
    despues: list = [None] * n
    estimado: list = [False] * n

    # A · hacia atrás desde el stock vivo.
    s = float(stock_hoy or 0)
    previo: float | None = None
    corto = False
    for i in range(n - 1, -1, -1):
        despues[i] = s
        if _tipo(movs[i]) == "ajuste":
            corto = True
            break
        s += (-float(movs[i].cantidad or 0) if _tipo(movs[i]) == "entrada"
              else float(movs[i].cantidad or 0))
    if not corto:
        previo = s

    # B · hacia adelante desde el primer ajuste (ancla absoluta).
    primer_ajuste = next((i for i, m in enumerate(movs) if _tipo(m) == "ajuste"), None)
    if primer_ajuste is not None:
        s = float(movs[primer_ajuste].cantidad or 0)
        for i in range(primer_ajuste, n):
            if i > primer_ajuste:
                s = _aplicar(s, movs[i])
            if despues[i] is None:
                despues[i] = s

    # C · hacia adelante desde cero (estimación del tramo más viejo).
    previo_estimado = previo is None
    if previo is None:
        previo = 0.0
    s = previo
    for i in range(n):
        s = _aplicar(s, movs[i])
        if despues[i] is None:
            despues[i] = s
            estimado[i] = True
        else:
            s = despues[i]   # re-anclar en cuanto vuelve a haber dato firme
    return despues, previo, estimado, previo_estimado


def _aplicar(saldo: float, m) -> float:
    t = _tipo(m)
    if t == "ajuste":
        return float(m.cantidad or 0)
    return saldo + (float(m.cantidad or 0) if t == "entrada" else -float(m.cantidad or 0))


def _saldo_en(movs: list, despues: list, previo: float, estimado: list,
              previo_estimado: bool, corte: datetime) -> tuple[float, bool]:
    """Saldo del libro al instante `corte` (incluye lo ocurrido hasta ahí) y si
    ese saldo es estimado."""
    idx = None
    for i, m in enumerate(movs):
        if m.fecha is not None and m.fecha <= corte:
            idx = i
        else:
            break
    if idx is None:
        return previo, previo_estimado
    return despues[idx], estimado[idx]


# ─── Consumo teórico (receta × unidades vendidas) ────────────────────────────

def _consumo_teorico(db, ctx, tienda_id: int | None, d_utc: datetime,
                     h_utc: datetime) -> tuple[dict[int, float], set[int]]:
    """Cuánto DEBIÓ salir de cada producto según las recetas y lo que se vendió.

    Devuelve (consumo por producto, productos con alguna vía de consumo). Un
    producto que no aparece en ninguna receta y que tampoco se vende NO tiene
    vía: su consumo teórico no se puede calcular y se informa como desconocido,
    nunca como 0 — decir 0 sería afirmar que no se consumió nada.

    Las líneas de combo apuntan al producto SOMBRA, que no consume nada: lo real
    son los componentes elegidos (`TicketItemComboSeleccion`), igual que hace el
    POS al descontar.
    """
    recetas, con_via_base, controla = ctx.recetas()
    con_via: set[int] = set(con_via_base)

    q = (db.query(TicketItem.id, TicketItem.producto_id, TicketItem.cantidad)
         .join(Ticket, Ticket.id == TicketItem.ticket_id)
         .filter(Ticket.estado.notin_(("anulado", "reversado")),
                 Ticket.fecha >= d_utc, Ticket.fecha <= h_utc))
    if tienda_id is not None:
        q = q.filter(Ticket.tienda_id == tienda_id)
    filas = q.all()

    item_ids = [f[0] for f in filas]
    sels: dict[int, list] = defaultdict(list)
    if item_ids:
        for s in db.query(TicketItemComboSeleccion).filter(
                TicketItemComboSeleccion.ticket_item_id.in_(item_ids)).all():
            sels[s.ticket_item_id].append(s)

    # (producto realmente consumido, unidades) — combos ya expandidos.
    brutos: list[tuple[int, float]] = []
    for item_id, pid, cant in filas:
        elegidas = sels.get(item_id)
        if elegidas:
            brutos.extend((s.producto_id, (s.cantidad or 1) * float(cant or 0))
                          for s in elegidas)
        else:
            brutos.append((pid, float(cant or 0)))

    out: dict[int, float] = defaultdict(float)
    for pid, unidades in brutos:
        # Producto con stock propio vendido directo: se descuenta a sí mismo.
        if pid in controla:
            out[pid] += unidades
            con_via.add(pid)
        for pi in recetas.get(pid, []):
            out[pi.insumo_id] += float(pi.cantidad) * unidades
    return dict(out), con_via


class _Ctx:
    """Memo de las lecturas caras: catálogo y libro COMPLETO de cada sede, mapa
    de costos y recetas.

    Existe por el P&L: pedir "este año" dispara una escalera por cada mes cerrado
    y por cada sede, y sin este memo cada una volvería a leer la historia entera
    de movimientos y a recalcular el costo de todos los productos. Una pantalla
    de consulta no puede costar doce veces lo mismo.
    """

    def __init__(self, db, horizonte: date | None = None):
        self.db = db
        # Fecha de arranque de la escalera MÁS VIEJA que este contexto va a
        # pedir. Es lo único que permite no leer el libro entero: ver
        # `_corte_libro`. Sin ella el contexto se comporta como antes y lee todo.
        self.horizonte = horizonte
        self._costos = None
        self._recetas = None
        self._sedes: dict[int, tuple] = {}
        self._saldos_prod: dict[tuple[int, int], tuple] = {}

    def costos(self) -> dict[int, tuple[float, str]]:
        if self._costos is None:
            self._costos = costo_unitario(self.db)
        return self._costos

    def recetas(self):
        """(receta por producto, productos con vía de consumo, los que controlan
        stock). «Con vía» es ESTRUCTURAL, no del período: un producto que se
        vende pero no se vendió este mes tiene consumo teórico 0, que es un dato;
        uno que no se vende ni entra en ninguna receta no tiene forma de saberlo,
        que es la ausencia de un dato. Son cosas distintas y se informan distinto."""
        if self._recetas is None:
            recetas: dict[int, list] = defaultdict(list)
            con_via: set[int] = set()
            for pi in self.db.query(ProductoInsumo).all():
                recetas[pi.producto_id].append(pi)
                con_via.add(pi.insumo_id)
            controla = set()
            for pid, cs, pv in self.db.query(
                    Producto.id, Producto.controla_stock, Producto.precio_venta).all():
                if cs:
                    controla.add(pid)
                    if float(pv or 0) > 0:
                        con_via.add(pid)
            self._recetas = (recetas, con_via, controla)
        return self._recetas

    def _corte_libro(self, tienda_id: int, ids: list[int]) -> datetime | None:
        """Desde qué instante alcanza con leer el libro SIN perder un saldo firme.

        Existe porque leer la historia COMPLETA de movimientos de una sede crece
        sin techo con la edad del local: con dos años de operación son cientos de
        miles de filas materializadas en memoria por cada pantalla de consulta.

        Y una cota INGENUA rompe la reconstrucción, porque `_saldos` no lee el
        libro hacia adelante: lo reconstruye hacia atrás desde el stock vivo. Cada
        una de sus tres pasadas reacciona distinto a un corte:

          A · hacia atrás desde el stock vivo — correcta sobre CUALQUIER sufijo
              del libro, porque su ancla es el presente y no el pasado. Se frena
              en el ajuste más nuevo que encuentra.
          B · hacia adelante desde el ajuste más VIEJO del tramo cargado —
              correcta siempre: `cantidad` de un ajuste es el stock ABSOLUTO
              resultante, así que es un ancla que no depende de lo anterior.
          C · desde cero al inicio del libro — la ÚNICA que asume dónde empieza
              la historia, y por eso la única que un corte puede arruinar. Solo
              alcanza a los índices ANTERIORES al ajuste más viejo cargado.

        De ahí sale la cota segura, producto por producto:

          · sin ningún ajuste después del arranque del rango → la pasada A llega
            entera hasta el arranque y hasta el saldo previo: alcanza con leer
            desde ahí;
          · con algún ajuste después → hace falta un ancla firme ANTES del rango,
            y esa ancla es su ajuste más nuevo anterior al arranque: se lee desde
            ese instante;
          · con ajustes después y NINGUNO antes → no hay ancla posible, la pasada
            C es inevitable y ese producto necesita el libro entero. Manda él:
            se devuelve `None` y se lee todo, porque es preferible una consulta
            cara a un stock inicial inventado.

        La cota es por eso EQUIVALENTE, no aproximada: los saldos de todos los
        índices desde el arranque del rango en adelante salen idénticos con corte
        y sin corte. `_saldos` no se toca.
        """
        if self.horizonte is None or not ids:
            return None
        # Instante justo anterior al rango: es el saldo que la escalera necesita
        # como arranque, así que la cota tiene que dejarlo reconstruible.
        pre = inicio_dia_col_utc(self.horizonte) - timedelta(microseconds=1)
        # Las dos consultas de acá abajo devuelven a lo sumo UNA fila por
        # producto: no vuelven a traer el libro por la ventana.
        base = self.db.query(MovimientoInventario.producto_id).filter(
            MovimientoInventario.tienda_id == tienda_id,
            MovimientoInventario.tipo == "ajuste",
            MovimientoInventario.producto_id.in_(ids),
            MovimientoInventario.fecha.isnot(None))
        posteriores = [pid for pid, in
                       base.filter(MovimientoInventario.fecha > pre).distinct().all()]
        if not posteriores:
            # Nadie tiene un ajuste después del arranque: la pasada hacia atrás
            # llega entera hasta el saldo previo sin leer un solo movimiento
            # anterior al rango.
            return pre
        anclas = (self.db.query(MovimientoInventario.producto_id,
                                func.max(MovimientoInventario.fecha))
                  .filter(MovimientoInventario.tienda_id == tienda_id,
                          MovimientoInventario.tipo == "ajuste",
                          MovimientoInventario.producto_id.in_(posteriores),
                          MovimientoInventario.fecha.isnot(None),
                          MovimientoInventario.fecha <= pre)
                  .group_by(MovimientoInventario.producto_id).all())
        if len(anclas) < len(posteriores):
            return None      # alguien no tiene ancla previa: libro entero
        return min([pre, *(f for _pid, f in anclas)])

    def sede(self, tienda_id: int):
        """(filas inventario+producto, libro por producto) de una sede."""
        if tienda_id not in self._sedes:
            filas = (self.db.query(Inventario, Producto)
                     .join(Producto, Producto.id == Inventario.producto_id)
                     .filter(Inventario.tienda_id == tienda_id,
                             Producto.controla_stock.is_(True))
                     .all())
            movs: dict[int, list] = defaultdict(list)
            if filas:
                ids = [p.id for _, p in filas]
                q = (self.db.query(MovimientoInventario)
                     .filter(MovimientoInventario.tienda_id == tienda_id,
                             MovimientoInventario.producto_id.in_(ids)))
                corte = self._corte_libro(tienda_id, ids)
                if corte is not None:
                    # Los de fecha NULL entran igual: ordenan primero con corte y
                    # sin corte, así que dejarlos afuera SÍ cambiaría `_saldos`.
                    q = q.filter(or_(MovimientoInventario.fecha >= corte,
                                     MovimientoInventario.fecha.is_(None)))
                for m in q.order_by(MovimientoInventario.fecha.asc(),
                                    MovimientoInventario.id.asc()).all():
                    movs[m.producto_id].append(m)
            self._sedes[tienda_id] = (filas, movs)
        return self._sedes[tienda_id]

    def saldos(self, tienda_id: int, producto_id: int, movs: list, stock_actual):
        """`_saldos` de un producto, calculado UNA sola vez por contexto.

        `_saldos` re-escanea la historia COMPLETA de movimientos del producto —
        tres pasadas— y el rango pedido no cambia su resultado: el saldo del libro
        en cada instante es el mismo se pregunte por enero o por marzo. Sin este
        memo, el P&L de un año sobre una sede repetía ese barrido una vez por mes
        cerrado y por sede sobre exactamente los mismos movimientos, que salen del
        `sede()` memoizado de acá arriba y no cambian mientras viva el contexto.
        """
        key = (tienda_id, producto_id)
        if key not in self._saldos_prod:
            self._saldos_prod[key] = _saldos(movs, stock_actual)
        return self._saldos_prod[key]


# ─── La escalera ─────────────────────────────────────────────────────────────

def escalera_rango(db, tienda_id: int, desde: date, hasta: date,
                   fisicos: dict[int, float] | None = None,
                   fotos: dict[int, float] | None = None,
                   hasta_instante: datetime | None = None, ctx=None) -> dict:
    """Escalera de conciliación de TODOS los productos con stock de una sede
    sobre [desde, hasta]. Funciona para cualquier rango: mes calendario, semana
    o los 9 días que van de un conteo al siguiente.

    `fisicos` es lo CONTADO por producto; sin él la escalera muestra la
    reconstrucción y deja el residuo en None (no hay contra qué compararla).
    `fotos` es el `cantidad_sistema` congelado del cierre, solo para tender el
    puente con el número que el dueño ya conoce.
    `hasta_instante` corta en el momento exacto del conteo en vez de al final del
    día: un cierre hecho el 28 no puede cargar con las ventas del 29 al 31.
    `ctx` reusa las lecturas caras entre escaleras seguidas (lo usa el P&L).
    """
    fisicos = fisicos or {}
    fotos = fotos or {}
    # EL HORIZONTE DEL CONTEXTO NO PUEDE SER MÁS NUEVO QUE EL RANGO QUE SE PIDE.
    # `_corte_libro` acota la lectura del libro con `ctx.horizonte`, no con este
    # `desde`. Reusar un contexto sobre un rango MÁS VIEJO que su horizonte deja
    # afuera los movimientos de ese tramo y `_saldo_en` cae a `previo`, que es el
    # saldo del corte y NO el del arranque pedido: el `stock_inicial` sale
    # EQUIVOCADO, no meramente estimado, y ni siquiera se marca como estimado.
    # Hoy el único que comparte contexto es `fuga_medida`, y siempre con el
    # horizonte más viejo de todos — o sea que no muerde. Esto está para que el
    # próximo reuso no lo descubra en producción.
    assert ctx is None or ctx.horizonte is None or ctx.horizonte <= desde, (
        f"contexto con horizonte {ctx.horizonte} reusado sobre un rango que "
        f"arranca antes ({desde}): el stock inicial saldría mal")
    ctx = ctx or _Ctx(db, horizonte=desde)
    d_utc = inicio_dia_col_utc(desde)
    h_utc = hasta_instante or fin_dia_col_utc(hasta)
    # Instante justo anterior al rango: el saldo de arranque es lo que había
    # ANTES del primer movimiento del período, nunca incluyéndolo.
    pre_utc = d_utc - timedelta(microseconds=1)

    filas, movs_por_prod = ctx.sede(tienda_id)
    if not filas:
        return {"tienda_id": tienda_id, "desde": desde.isoformat(),
                "hasta": hasta.isoformat(), "corte": h_utc.isoformat(),
                "productos": [], "ranking": [], "ranking_sin_costo": [],
                "resumen": _resumen_vacio(),
                "renglones": [{"clave": c, "etiqueta": e, "signo": s}
                              for c, e, s in RENGLONES]}

    teoricos, con_via = _consumo_teorico(db, ctx, tienda_id, d_utc, h_utc)
    costos = ctx.costos()

    productos = []
    for inv_row, prod in filas:
        movs = movs_por_prod.get(prod.id, [])
        productos.append(_escalera_producto(
            prod, movs, ctx.saldos(tienda_id, prod.id, movs, inv_row.stock_actual),
            d_utc, h_utc, pre_utc,
            teoricos.get(prod.id), prod.id in con_via,
            fisicos.get(prod.id), fotos.get(prod.id),
            costos.get(prod.id, (0.0, "sin_costo"))))

    # El ranking es del RESIDUO, no de la diferencia bruta: se investiga lo que
    # NADA explica. Un producto que se movió muchísimo pero con todo registrado
    # no tiene por qué aparecer arriba solo por su volumen.
    #
    # Y ordenar por plata a secas reintroducía ese mismo defecto por la ventana:
    # el tope quedaba SIEMPRE en el producto de más rotación, que es el que más
    # varianza normal acumula. El % del consumo estaba solo como desempate, o sea
    # que no ordenaba nunca —dos floats no empatan exacto—. Ahora manda el PATRÓN
    # (evento / revisar / sin dato / proceso) y la plata ordena DENTRO de cada
    # grupo, que es donde comparar pesos sí quiere decir algo: un evento se
    # investiga, un proceso crónico se corrige entrenando la dosificación.
    con_residuo = [p for p in productos
                   if p["diferencia_inexplicada"] is not None
                   and abs(p["diferencia_inexplicada"]) > EPS]
    ranking = sorted(
        [p for p in con_residuo if p["valor_origen"] != "sin_costo"],
        key=lambda p: (_ORDEN_PATRON.get(p["patron"], 2),
                       -abs(p["valor_inexplicado"] or 0),
                       -abs(p["diferencia_inexplicada"])),
    )[:20]
    # Los que NO se pueden valorizar van en su PROPIA lista, ordenados por
    # CANTIDAD y por nada más. En el orden por plata valen $0, se hunden al fondo
    # y con el corte en 20 pueden no llegar nunca a la pantalla por más kilos que
    # hayan desaparecido: el resumen lo declaraba, pero el que más falta podía ser
    # justo el que no se veía. Acá no hay pesos que mostrar, así que ordena lo
    # único que se sabe de ellos.
    #
    # Y NO SE AGRUPA POR PATRÓN. Agrupar acá reintroduce por la ventana el defecto
    # que esta lista vino a corregir: el clavo al que le faltan 5 unidades sobre un
    # consumo de 10 es "evento" y se le pone ENCIMA a la harina a la que le faltan
    # 900 sobre 30.000, que es "proceso". Con once eventos chicos el corte en 10
    # deja el faltante más grande afuera del payload, antes incluso de que la
    # pantalla lo pueda mostrar. El ranking EN PESOS sí ordena por patrón, porque
    # ahí la plata da la escala que acá falta.
    ranking_sin_costo = sorted(
        [p for p in con_residuo if p["valor_origen"] == "sin_costo"],
        key=lambda p: -abs(p["diferencia_inexplicada"]),
    )[:10]

    return {
        "tienda_id": tienda_id,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "corte": h_utc.isoformat(),
        "productos": productos,
        "ranking": ranking,
        "ranking_sin_costo": ranking_sin_costo,
        "resumen": _resumen(productos),
        "renglones": [{"clave": c, "etiqueta": e, "signo": s} for c, e, s in RENGLONES],
        "nota": (
            "El esperado se reconstruye desde el libro de movimientos del rango, "
            "no desde la foto que el cierre congela al abrir la pantalla. Cada "
            "renglón es una causa ya registrada; lo inexplicado es lo único que "
            "queda por investigar."
        ),
    }


def _escalera_producto(prod, movs, saldos, d_utc, h_utc, pre_utc,
                       teorico, tiene_via, fisico, foto, costo_par) -> dict:
    despues, previo, estimado, previo_estimado = saldos
    inicial, inicial_estimado = _saldo_en(
        movs, despues, previo, estimado, previo_estimado, pre_utc)

    buckets: dict[str, float] = {c: 0.0 for c, _, _ in RENGLONES}
    n_movs = 0
    for i, m in enumerate(movs):
        if m.fecha is None or m.fecha < d_utc or m.fecha > h_utc:
            continue
        n_movs += 1
        tipo = _tipo(m)
        if tipo == "ajuste":
            # El delta de un ajuste es saldo_después − saldo_antes; `cantidad`
            # guarda el ABSOLUTO resultante y sumarlo como delta rompería todo.
            antes = despues[i - 1] if i > 0 else previo
            buckets[_bucket(tipo, m.motivo)] += despues[i] - antes
        else:
            buckets[_bucket(tipo, m.motivo)] += float(m.cantidad or 0)

    esperado = inicial
    for clave, _, signo in RENGLONES:
        esperado += signo * buckets[clave]
    esperado = round(esperado, 3)

    dif = None if fisico is None else round(fisico - esperado, 3)
    costo, origen = costo_par
    valor = None if dif is None else round(dif * costo, 2)

    # ── Residuo contra el CONSUMO del período ────────────────────────────────
    # Ordenar por plata absoluta garantiza que arriba aparezcan siempre los
    # productos de más rotación, que son los que más varianza normal acumulan: el
    # peor orden posible para decidir qué investigar. El porcentaje sí discrimina
    # —3% crónico es dosificación, 40% es un evento— y sale del dato que la
    # escalera ya tiene. `None` cuando no hubo salidas: dividir por cero no
    # convierte la ausencia de consumo en un porcentaje.
    consumo = sum(buckets[c] for c in _SALIDAS)
    pct = (None if dif is None or consumo <= EPS
           else round(dif / consumo * 100, 1))
    if pct is None:
        patron = None
    elif abs(pct) < PCT_PROCESO:
        patron = "proceso"
    elif abs(pct) < PCT_EVENTO:
        patron = "revisar"
    else:
        patron = "evento"

    # Puente con el número que el dueño ya conoce: la diferencia bruta del cierre
    # (físico − foto congelada) se parte en lo que el movimiento del período
    # explica y lo que no. Sin este puente, dos números distintos sobre el mismo
    # producto se leen como una contradicción del sistema.
    bruta = explicado = None
    if foto is not None and fisico is not None:
        bruta = round(fisico - foto, 3)
        explicado = round(esperado - foto, 3)

    return {
        "producto_id": prod.id,
        "producto_nombre": prod.nombre,
        "unidad_medida": prod.unidad_medida,
        "categoria": getattr(prod.categoria, "value", None) or str(prod.categoria or ""),
        "stock_inicial": round(inicial, 3),
        # El arranque salió de asumir que el libro empieza en cero (hay un ajuste
        # viejo cuyo saldo previo nadie registró). Se dice, no se disimula.
        "stock_inicial_estimado": inicial_estimado,
        **{c: round(buckets[c], 3) for c, _, _ in RENGLONES},
        "stock_esperado": esperado,
        "stock_fisico": fisico,
        "diferencia_inexplicada": dif,
        "valor_unitario": round(costo, 4),
        "valor_origen": origen,
        "valor_origen_label": ORIGEN_LABEL[origen],
        "valor_inexplicado": valor,
        # Cuánto se movió de verdad en el período y qué tajada de eso quedó sin
        # explicar. Es lo único que distingue una varianza crónica de proceso de
        # un evento puntual; NO es una atribución de causa y no puede leerse
        # como tal.
        "consumo_periodo": round(consumo, 3),
        "pct_inexplicado": pct,
        "patron": patron,
        # Contraste, NO parte de la identidad: si el libro descontó algo distinto
        # de lo que la receta manda, la causa es la receta (o la cascada a
        # sustituto), y merece su propio número en vez de contaminar el residuo.
        "consumo_teorico": None if not tiene_via else round(teorico or 0.0, 3),
        "sin_receta": not tiene_via,
        "descuadre_receta": (None if not tiene_via
                             else round(buckets["ventas"] - (teorico or 0.0), 3)),
        "diferencia_bruta": bruta,
        "explicado_por_movimiento": explicado,
        "movimientos": n_movs,
    }


def _resumen_vacio() -> dict:
    return {"con_residuo": 0, "faltantes": 0, "sobrantes": 0, "sin_costo": 0,
            "estimados": 0, "valor_inexplicado": 0.0, "valor_faltante": 0.0,
            "valor_sobrante": 0.0, "arranques_estimados": 0, "contados": 0,
            "productos": 0, "eventos": 0, "ajustes_conteo_productos": 0,
            "valor_ajustes_conteo": 0.0}


def _resumen(productos: list) -> dict:
    con = [p for p in productos
           if p["diferencia_inexplicada"] is not None
           and abs(p["diferencia_inexplicada"]) > EPS]
    faltan = [p for p in con if p["diferencia_inexplicada"] < 0]
    sobran = [p for p in con if p["diferencia_inexplicada"] > 0]
    return {
        "productos": len(productos),
        "contados": sum(1 for p in productos if p["stock_fisico"] is not None),
        "con_residuo": len(con),
        "faltantes": len(faltan),
        "sobrantes": len(sobran),
        # Cuántos faltantes REALES no se pudieron poner en pesos. Sin este
        # número, un total en $0 se lee como "no hay fuga" cuando lo que pasa es
        # que nadie cargó el costo de esos productos.
        "sin_costo": sum(1 for p in con if p["valor_origen"] == "sin_costo"),
        "estimados": sum(1 for p in con if p["valor_origen"] == "estimado"),
        "valor_inexplicado": round(sum(p["valor_inexplicado"] or 0 for p in con), 2),
        "valor_faltante": round(sum(p["valor_inexplicado"] or 0 for p in faltan), 2),
        "valor_sobrante": round(sum(p["valor_inexplicado"] or 0 for p in sobran), 2),
        # Productos cuyo arranque se estimó asumiendo un libro que empieza en 0.
        "arranques_estimados": sum(1 for p in con if p["stock_inicial_estimado"]),
        # Residuos que se salen del patrón del propio producto: los que valen una
        # mirada aunque no encabecen el ranking en pesos.
        "eventos": sum(1 for p in con if p["patron"] == "evento"),
        # Fuga que YA se escribió al libro como ajuste de un conteo aplicado
        # dentro del período. Sin este número, una sede que aplica conteos
        # parciales ve residuo ~0 y lee "nada queda sin explicar" con la fuga
        # escondida adentro de un renglón que se llama "ajustes".
        "ajustes_conteo_productos": sum(
            1 for p in productos if abs(p["ajustes_conteo"]) > EPS),
        "valor_ajustes_conteo": round(sum(
            p["ajustes_conteo"] * p["valor_unitario"] for p in productos
            if p["valor_origen"] != "sin_costo"), 2),
    }


# ─── Enganche con el cierre mensual ──────────────────────────────────────────

def get_escalera_mensual(db, tienda_id: int, anio: int, mes: int,
                         fisicos: dict[int, float] | None = None,
                         ctx=None) -> dict | None:
    """La escalera del mes, tomando como físico lo que el conteo mensual CONTÓ.

    Solo cuenta lo que marcó `fue_contado`: `cerrar()` rellena `cantidad_real`
    con el sistema para todo lo no contado, así que leer esa columna sin filtrar
    inventaría un conteo que nadie hizo y un residuo de 0 que nadie verificó.

    El corte es el instante del cierre cuando existe, no el fin de mes: un conteo
    hecho el 28 no puede cargar con las ventas del 29 al 31.
    """
    inv = db.query(InventarioMensual).filter_by(
        tienda_id=tienda_id, anio=anio, mes=mes).first()
    desde = date(anio, mes, 1)
    hasta = date(anio, mes, monthrange(anio, mes)[1])
    if inv is None:
        return escalera_rango(db, tienda_id, desde, hasta, fisicos=fisicos, ctx=ctx)

    reales = dict(fisicos or {})
    fotos = {}
    for it in inv.items:
        fotos[it.producto_id] = float(it.cantidad_sistema or 0)
        if it.fue_contado and it.cantidad_real is not None and it.producto_id not in reales:
            reales[it.producto_id] = float(it.cantidad_real)

    # El corte se ACOTA al fin de mes. `fecha_cierre` es lo más cerca que el
    # sistema tiene del momento del conteo, pero no es el conteo: cerrar julio el
    # 3 de agosto es normal, y estirar el rango hasta ahí le descontaría a julio
    # tres días de ventas de agosto — un sobrante inventado en cada producto que
    # rota. Cerrar el 28 sí adelanta el corte, porque ahí el conteo pasó antes de
    # que terminara el mes y las ventas del 29 al 31 no las vio nadie.
    fin_mes = fin_dia_col_utc(hasta)
    bruto = inv.fecha_cierre or inv.fecha_primer_cierre
    corte = min(bruto, fin_mes) if bruto else None
    out = escalera_rango(db, tienda_id, desde, hasta, fisicos=reales, fotos=fotos,
                         hasta_instante=corte, ctx=ctx)
    out["inventario_id"] = inv.id
    out["anio"] = anio
    out["mes"] = mes
    out["estado"] = inv.estado
    out["corte_por"] = ("cierre" if corte and corte < fin_mes else "fin_de_mes")
    return out


def fuga_medida(db, desde: date, hasta: date, tienda_id: int | None = None) -> dict:
    """La fuga que los cierres del período MIDIERON, valorizada — el término que
    el P&L nunca vio.

    Se cuentan solo los meses cuyo mes calendario cae COMPLETO dentro del rango y
    que ya pasaron por un cierre: media medición no es una medición, y un mes sin
    cerrar todavía no midió nada. Si no hay ninguno, devuelve `None` y no 0: cero
    significa "se midió y no falta nada", que es una afirmación muy distinta de
    "nadie contó".
    """
    from app.models.models import Tienda

    q = db.query(InventarioMensual).filter(
        InventarioMensual.fecha_primer_cierre.isnot(None))
    if tienda_id is not None:
        q = q.filter(InventarioMensual.tienda_id == tienda_id)

    sedes = [tienda_id] if tienda_id is not None else [
        t.id for t in db.query(Tienda).all()]
    total = 0.0
    periodos = []
    # LOS ABSOLUTOS SON PRODUCTO-MES, NO PRODUCTOS
    # Sumar la cobertura de cada cierre a lo largo del rango da un número que no
    # existe en ninguna parte: tres meses cerrados de 97 productos se leían como
    # "cubre 36 de 291 productos" cuando el local nunca tuvo 291 productos. El
    # RATIO sí es correcto —está bien formado mes a mes—, así que se conserva y
    # se nombra por lo que es, con la cantidad de cierres al lado para que el
    # denominador se pueda dividir de vuelta.
    contados = total_items = 0
    # Estos dos, en cambio, se cuentan por PRODUCTO DISTINTO: "3 productos sin
    # costo cargado" tiene que ser 3 productos, no el mismo producto en 3 cierres.
    # Son una instrucción de trabajo (andá y cargá esos costos), y repetido por
    # mes manda a buscar fichas que no existen.
    sin_costo_ids: set[int] = set()
    # Residuos valorizados con el PRECIO DE VENTA porque no hay costo ni factura.
    # Un producto de reventa (costo 1.500, venta 5.000) infla su fuga 3,3× y hasta
    # acá esa estimación llegaba al P&L sin declararse, leyéndose como un número
    # firme. Viaja hasta la pantalla junto al total que ayudó a formar.
    estimados_ids: set[int] = set()
    meses: set[tuple[int, int]] = set()
    # Qué SEDES aportaron una medición. La cobertura por meses no alcanza para
    # declarar el tramo: con "Todas las sedes", el margen del P&L suma las ventas y
    # el COGS de TODAS, y la fuga solo de las que efectivamente cerraron un conteo.
    # Una sede que nunca cierra desaparece del término de fuga sin ninguna señal, y
    # el sesgo va para el mismo lado que el de los meses: subdeclara.
    sedes_medidas: set[int] = set()
    # Un solo contexto para TODOS los meses: sin esto, pedir el P&L de un año
    # releería la historia completa de movimientos una vez por mes y por sede.
    # `horizonte` es el arranque del rango pedido, que es lo más viejo que
    # cualquiera de estas escaleras va a preguntar: acota la lectura del libro
    # sin perder un solo saldo firme (ver `_Ctx._corte_libro`).
    ctx = _Ctx(db, horizonte=desde)
    for inv in q.all():
        if inv.tienda_id not in sedes:
            continue
        ini = date(inv.anio, inv.mes, 1)
        fin = date(inv.anio, inv.mes, monthrange(inv.anio, inv.mes)[1])
        if ini < desde or fin > hasta:
            continue
        esc = get_escalera_mensual(db, inv.tienda_id, inv.anio, inv.mes, ctx=ctx)
        if esc is None:
            continue
        r = esc["resumen"]
        total += r["valor_inexplicado"]
        contados += r["contados"]
        total_items += r["productos"]
        meses.add((inv.anio, inv.mes))
        sedes_medidas.add(inv.tienda_id)
        for p in esc["productos"]:
            d = p["diferencia_inexplicada"]
            if d is None or abs(d) <= EPS:
                continue
            if p["valor_origen"] == "sin_costo":
                sin_costo_ids.add(p["producto_id"])
            elif p["valor_origen"] == "estimado":
                estimados_ids.add(p["producto_id"])
        periodos.append({"tienda_id": inv.tienda_id, "anio": inv.anio, "mes": inv.mes,
                         "valor_inexplicado": r["valor_inexplicado"],
                         "con_residuo": r["con_residuo"],
                         "contados": r["contados"], "productos": r["productos"]})
    if not periodos:
        return {"valor": None, "periodos": [], "sin_costo": 0, "estimados": 0,
                "contados": 0, "productos": 0, "cierres": 0, "meses": 0,
                "sedes": 0, "sedes_ids": []}
    return {"valor": round(total, 2), "periodos": periodos,
            "sin_costo": len(sin_costo_ids), "estimados": len(estimados_ids),
            # Producto-mes, no productos: el nombre del campo miente menos que el
            # número suelto, y `cierres` deja dividir.
            "contados": contados, "productos": total_items,
            "cierres": len(periodos), "meses": len(meses),
            # Sedes que aportaron al menos un cierre. El otro eje de la cobertura:
            # sin él, "Todas las sedes" compara un margen de N sedes contra una
            # fuga de las pocas que cuentan.
            #
            # Viajan los IDS y no solo el conteo: comparar CARDINALIDADES deja pasar
            # el caso cruzado —una sede que cerró pero no vendió tapando a otra que
            # vendió y nunca cerró— y ahí el aviso no aparece justo cuando más falta.
            # Quien compara necesita intersecar conjuntos, no restar números.
            "sedes": len(sedes_medidas), "sedes_ids": sorted(sedes_medidas)}
