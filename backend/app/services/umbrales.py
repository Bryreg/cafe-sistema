"""Mínimos PROPUESTOS: el sistema propone, el dueño acepta.

En producción 55 de 56 productos tienen `stock_minimo = 0` — el default del
esquema (models.py:303-305), no una decisión de nadie. Con el mínimo en 0:

  · el kiosko de la barista (`alerta: stock <= minimo`) no marca nada NUNCA;
  · `pedidos._estado` se queda sin su único fallback y, para todo producto sin
    consumo medido, degenera en «agotado si stock<=0, si no, todo bien».

Nadie va a inventar 55 números a mano. El sistema ya mide el consumo real de
cada sede y conoce el lead time de cada proveedor: puede PROPONERLOS.

NADA SE ESCRIBE ACÁ
Este módulo solo LEE y devuelve una propuesta. La escritura vive en el handler
del PATCH y necesita que el dueño mande explícitamente qué acepta.


LA FÓRMULA, Y POR QUÉ ESTA Y NO OTRA

    minimo_propuesto = consumo_diario × lead_time_dias

El mínimo significa una sola cosa: «cuando llegues acá, pedí ya». Lo que hay
que tener encima cuando se dispara la alarma es lo que se va a gastar MIENTRAS
LLEGA el pedido — ni un día más, ni uno menos.

Y esa es exactamente la definición de URGENTE que ya tiene el motor:
`pedidos._estado` marca urgente cuando `stock / consumo_diario <= lead_time`.
Despejado, eso es `stock <= consumo_diario × lead_time`. O sea que cruzar el
mínimo propuesto y que el motor diga «urgente» pasan a ser el MISMO evento: el
kiosko —que solo mira el mínimo— y el panel del admin —que mira los días que
quedan— dejan de contradecirse.

Por qué NO se usa `_dias_objetivo` (lead_time + `_COLCHON`) como cobertura del
mínimo, que es la tentación obvia: ese número es el objetivo de REPOSICIÓN
—hasta dónde llenar cuando comprás (`pedidos.sugerencia_pedido`, línea 124)—,
no el punto en que se dispara el pedido. Si el mínimo fuera el objetivo, todo
producto quedaría en alerta el día siguiente a cada entrega, para siempre: 55
productos rojos permanentes es peor que 55 productos mudos. El colchón es cada
CUÁNTO se repone; el lead time es CUÁNDO hay que avisar. Son dos preguntas.

`_dias_objetivo` sí se importa y sí se usa: para decir en la propuesta hasta
dónde va a repone el motor (`motor_repone_hasta`) y como techo verificable —el
mínimo propuesto siempre queda estrictamente por debajo—. `_COLCHON` no se
importa por separado porque `_dias_objetivo` es su único consumidor: volver a
hacer el lookup acá sería la copia que hay que evitar.

`DIAS_ANALISIS` se importa igual: si la propuesta midiera el consumo en otra
ventana que el motor, los dos leerían números distintos del mismo producto.


LO QUE NUNCA SE INVENTA
Consumo medido en cero ⇒ NO hay propuesta. Ese producto viaja en `sin_dato`
con su razón, para que el dueño ponga el número a mano. Proponer un 0 sería
proponer exactamente el default inerte que esto viene a arreglar.
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.models.models import (Inventario, MovimientoInventario, Producto,
                               TipoMovInvEnum)
from app.services import preparables as preparables_svc
from app.services.diagnostico_stock import _gestionado, _num, _recetas_sospechosas
from app.services.inventario import clasificar_estado
from app.services.pedidos import DIAS_ANALISIS, _dias_objetivo

# Unidades DISCRETAS: no existe medio vaso ni 2,4 tortas de umbral. Redondean
# para ARRIBA — hacia abajo el umbral avisaría tarde, y desde 0,4 avisaría nunca.
_UNIDADES_DISCRETAS = ("und", "unidad", "unidades", "u", "unid",
                       "paquete", "paquetes", "bolsa", "bolsas",
                       "botella", "botellas", "caja", "cajas",
                       "porcion", "porción", "porciones", "docena", "docenas")

# Unidades GRANULARES: el gramo ya es la unidad más chica que alguien cuenta.
# Un mínimo de 3,7183 gr no es precisión, es ruido de float en la pantalla.
_UNIDADES_GRANULARES = ("gr", "g", "gramo", "gramos", "ml",
                        "mililitro", "mililitros", "cc")

# El resto (kg, lt, l, litro…) conserva 2 decimales: ahí el decimal SÍ decide —
# 0,05 kg de canela es un umbral real y redondearlo a 0 sería mentir.
_DECIMALES_UNIDAD_GRANDE = 2
_PASO_MINIMO_UNIDAD_GRANDE = 0.01


def redondear_minimo(valor: float, unidad: str | None) -> float:
    """Redondeo con criterio POR UNIDAD, con un piso innegociable: si el valor
    crudo es positivo, el resultado también. Un 0 por redondear de más sería
    indistinguible del default que este módulo viene a reemplazar."""
    u = (unidad or "").strip().lower()
    if u in _UNIDADES_DISCRETAS:
        return max(1, math.ceil(valor))
    if u in _UNIDADES_GRANULARES:
        return max(1, round(valor))
    redondeado = round(valor, _DECIMALES_UNIDAD_GRANDE)
    return redondeado if redondeado > 0 else _PASO_MINIMO_UNIDAD_GRANDE


def _consumo_por_producto(db: Session, tienda_id: int,
                          ahora: datetime) -> tuple[dict[int, float], dict[int, int]]:
    """Total salido y cuántos días DISTINTOS tuvieron salida, por producto, en la
    ventana del motor y en ESTA sede.

    Se agrega en Python y no en SQL a propósito, igual que
    `pedidos.sugerencia_pedido`: contar días de calendario en SQL necesita
    `date()` en SQLite y `date_trunc`/CAST en Postgres, y este repo corre en los
    dos. La consulta ya viene acotada a 14 días de movimientos de una sede.
    """
    cutoff = ahora - timedelta(days=DIAS_ANALISIS)
    filas = (
        db.query(MovimientoInventario.producto_id,
                 MovimientoInventario.cantidad,
                 MovimientoInventario.fecha)
        .filter(MovimientoInventario.tienda_id == tienda_id,
                MovimientoInventario.tipo == TipoMovInvEnum.salida,
                MovimientoInventario.fecha >= cutoff)
        .all()
    )
    total: dict[int, float] = defaultdict(float)
    dias: dict[int, set] = defaultdict(set)
    for pid, cantidad, fecha in filas:
        total[pid] += float(cantidad or 0)
        if fecha is not None:
            dias[pid].add(fecha.date())
    return total, {pid: len(d) for pid, d in dias.items()}


def _advertencias_por_insumo(db: Session) -> dict[int, str]:
    """producto_id → por qué NO confiar en su consumo medido.

    Si una receta descuenta 18 «lt» de leche por unidad vendida cuando quiso
    decir 18 gr, cada venta le saca al inventario mil veces de más: el consumo
    medido queda inflado 1000× y una propuesta construida sobre él heredaría el
    error completo. El cruce va por `insumo_id` —el producto que se desangra—,
    no por el producto vendido, cuyo consumo no se toca.

    La detección no se reimplementa: es la misma de
    `diagnostico_stock._recetas_sospechosas`, que ya alimenta el panel de cada
    producto. Una segunda copia sería la que se desincroniza.
    """
    # La dirección importa y el detector tiene DOS ramas simétricas: la receta
    # «grande» (18 kg donde eran gramos) INFLA el consumo medido 1000× y el
    # mínimo sale gigante; la «chica» (0,2 gr donde eran kilos) lo DESINFLA y el
    # mínimo sale enano. Decir «inflado» en las dos mandaba a mirar para el lado
    # contrario justo en el caso chico. `r["sospecha"]` ya trae la dirección
    # correcta (diagnostico_stock:459-465): se reusa, no se reescribe.
    out: dict[int, str] = {}
    for r in _recetas_sospechosas(db):
        if r["insumo_id"] in out:
            continue
        out[r["insumo_id"]] = (
            f"{r['sospecha']} Este mínimo se calculó sobre ese consumo medido, "
            "así que hereda el error. Revisá la receta antes de aceptar el número."
        )
    return out


def proponer(db: Session, tienda_id: int) -> dict:
    """La propuesta completa de una sede. SOLO LEE.

    Recorre el inventario GESTIONADO de la sede (`diagnostico_stock._gestionado`:
    controla stock y entra al conteo — la misma regla que mira el motor) que
    todavía NO tiene mínimo cargado, y devuelve:

      · `propuestas`  el número, el consumo que lo sostiene, sobre cuántos días
                      se midió, y en qué estado quedaría el producto HOY si se
                      aceptara;
      · `sin_dato`    los que no tienen consumo medido, con su razón. Sin
                      número: ese lo pone el dueño;
      · `impacto`     el antes/después, que es lo que hay que ver ANTES de
                      aceptar.
    """
    ahora = datetime.utcnow()
    total_salidas, dias_con_salida = _consumo_por_producto(db, tienda_id, ahora)
    prep_ids = preparables_svc.ids_preparables(db)
    advertencias = _advertencias_por_insumo(db)

    filas = (
        db.query(Inventario)
        .options(joinedload(Inventario.producto))
        .join(Producto, Producto.id == Inventario.producto_id)
        .filter(Inventario.tienda_id == tienda_id, _gestionado())
        .all()
    )

    propuestas: list[dict] = []
    sin_dato: list[dict] = []

    for inv in filas:
        p = inv.producto
        minimo_actual = float(inv.stock_minimo or 0)
        # Un mínimo puesto a mano es una decisión tomada: esto propone lo que
        # FALTA, no reemplaza lo que alguien ya resolvió.
        if minimo_actual > 0:
            continue

        stock = float(inv.stock_actual or 0)
        critico = float(inv.stock_critico or 0)
        ideal = float(inv.stock_ideal or 0)
        # Mismo default que el motor cuando el producto no tiene lead time.
        lead = p.lead_time_dias or 2
        accion = "preparar" if p.id in prep_ids else "comprar"
        # Mismo redondeo del motor: si acá saliera otro consumo, la propuesta y
        # la pantalla de pedidos mostrarían dos números del mismo producto.
        consumo = round(total_salidas.get(p.id, 0.0) / DIAS_ANALISIS, 3)

        base = {
            "producto_id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "unidad": p.unidad_medida,
            "stock_actual": round(stock, 2),
            "lead_time_dias": lead,
            "accion": accion,
        }

        if consumo <= 0:
            sin_dato.append({
                **base,
                "razon": (
                    f"No hay salidas registradas de este producto en los "
                    f"últimos {DIAS_ANALISIS} días, así que el sistema no puede "
                    f"medir cuánto se gasta. Este mínimo lo ponés vos."
                ),
            })
            continue

        propuesto = redondear_minimo(consumo * lead, p.unidad_medida)
        estado_hoy = clasificar_estado(stock, minimo_actual, critico, ideal)
        quedaria_en = clasificar_estado(stock, propuesto, critico, ideal)
        advertencia = advertencias.get(p.id)

        # Coherencia con umbrales YA cargados: el PATCH rechaza (con razón) un
        # mínimo por encima del ideal o por debajo del crítico, y como el lote es
        # atómico, UNA propuesta en conflicto tumbaría las 55. El conflicto se
        # declara acá —donde el dueño puede decidir— en vez de descubrirse como
        # un 400 después de marcar todo.
        conflicto = None
        if ideal > 0 and propuesto > ideal:
            conflicto = (
                f"Este producto ya tiene un ideal de {_num(ideal)} {p.unidad_medida}, "
                f"menor que el mínimo propuesto: aceptarlo así sería incoherente "
                f"(el sistema lo rechaza). Bajá este mínimo o subí el ideal en su ficha."
            )
        elif critico > 0 and critico > propuesto:
            conflicto = (
                f"Este producto ya tiene un crítico de {_num(critico)} {p.unidad_medida}, "
                f"mayor que el mínimo propuesto: aceptarlo así sería incoherente "
                f"(el sistema lo rechaza). Subí este mínimo o bajá el crítico en su ficha."
            )
        if conflicto:
            advertencia = f"{advertencia} {conflicto}" if advertencia else conflicto

        propuestas.append({
            **base,
            "consumo_diario": consumo,
            "dias_de_datos": dias_con_salida.get(p.id, 0),
            "ventana_dias": DIAS_ANALISIS,
            "minimo_propuesto": propuesto,
            # El mínimo cubre el LEAD TIME: lo que se gasta mientras llega el
            # pedido. Ver el encabezado del módulo.
            "cubre_dias": lead,
            # Hasta dónde repone el motor cuando finalmente comprás. Va al lado
            # a propósito: son dos números distintos y confundirlos es el error
            # que deja todo en rojo permanente.
            "motor_repone_hasta": round(consumo * _dias_objetivo(lead), 2),
            "estado_hoy": estado_hoy,
            "quedaria_en": quedaria_en,
            "cambia_a_alerta": estado_hoy == "normal" and quedaria_en != "normal",
            "advertencia": advertencia,
            # Una propuesta construida sobre un consumo sospechoso no puede
            # entrar en un botón que acepta 55 números de una.
            "en_aceptar_todo": advertencia is None,
        })

    # Primero lo que CAMBIA algo: si aceptar deja 6 productos en alerta hoy, esos
    # 6 son lo que el dueño tiene que mirar, no los 40 que siguen igual.
    propuestas.sort(key=lambda x: (not x["cambia_a_alerta"], x["nombre"]))
    sin_dato.sort(key=lambda x: x["nombre"])

    seguras = [x for x in propuestas if x["en_aceptar_todo"]]
    return {
        "tienda_id": tienda_id,
        "generado": ahora.isoformat(),
        "ventana_dias": DIAS_ANALISIS,
        "propuestas": propuestas,
        "sin_dato": sin_dato,
        "impacto": {
            "propuestas": len(propuestas),
            "sin_dato": len(sin_dato),
            # Los que pasan a necesitar atención HOY MISMO por culpa del mínimo
            # nuevo. Es el número de la frase de arriba del panel.
            "nuevos_en_alerta": sum(1 for x in propuestas if x["cambia_a_alerta"]),
            # Los que YA estaban en alerta antes de tocar nada. Se dicen aparte:
            # meterlos en el número de arriba sería cobrarle al mínimo un
            # problema que ya existía.
            "ya_en_alerta": sum(1 for x in propuestas if x["estado_hoy"] != "normal"),
            "con_advertencia": len(propuestas) - len(seguras),
            "aceptar_todo": {
                "propuestas": len(seguras),
                "nuevos_en_alerta": sum(1 for x in seguras if x["cambia_a_alerta"]),
            },
        },
    }
