"""Tasa de consumo diaria por producto, aprendida del HISTÓRICO DE VENTAS.

POR QUÉ EXISTE. El consumo con el que se dispara «alcanza X días» y la cantidad
sugerida salía de las SALIDAS de inventario de los últimos 14 días ÷ 14. Eso
tiene tres problemas: mezcla ventas con mermas, preparaciones y correcciones; la
ventana es corta, así que un pico de un solo día pesa 1/14 y un producto nuevo
se diluye entre ceros; y no distingue el sábado del martes.

Acá el consumo sale de lo que REALMENTE se vendió, sobre 8 semanas, con MEDIANA
POR DÍA DE LA SEMANA: un día atípico (un evento, una venta corporativa) no mueve
la mediana, y los días cerrados no entran como 0 (no es "no vendió", es "no
abrió"). Es la misma metodología, ya probada, de la proyección de plata
(`costos._venta_esperada_por_dia_semana`).

Se divide entre 7 —no entre los días abiertos— para que la tasa quede POR DÍA
CALENDARIO, comparable con el `lead_time` (que es en días calendario) y con la
cuenta vieja de /14. Un producto que solo vende los sábados: su mediana de
sábado ÷ 7 dice cuánto se consume "por día" a lo largo de la semana, así el
«alcanza» proyecta hasta el próximo sábado sin inventar consumo entre medio.

CÓMO SE REPARTE LA VENTA AL INVENTARIO — idéntico a la caja al vender (`pos.py`):
  · un producto con stock propio (`controla_stock`) descuenta de sí mismo;
  · un producto con receta (`ProductoInsumo`) descuenta cada insumo × cantidad;
  · un combo se abre en sus productos reales (`TicketItemComboSeleccion`).
Un solo nivel, sin recursión, como el POS.

NO REEMPLAZA a las salidas. El que llama (`pedidos._items_base`) toma el MÁXIMO
entre esta tasa y la de salidas físicas, para no quedar nunca por debajo de lo
que salió del estante —mermas y preparaciones incluidas—: errar hacia no
quedarse sin stock. Cuando no hay ventas en la ventana, un producto no aparece
en el dict y el llamador usa su tasa de salidas como siempre.
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from sqlalchemy.orm import Session

from app.core.tz import rango_col_utc, dia_col
from app.models.models import (
    Producto, ProductoInsumo, Ticket, TicketItem, TicketItemComboSeleccion,
)

# 56 días = exactamente 8 muestras de cada día de la semana (ver costos.SEMANAS_HISTORIA).
SEMANAS = 8


def tasa_diaria_por_producto(db: Session, tienda_id: int, hoy: date) -> dict[int, float]:
    """{producto_id de inventario: unidades consumidas por día}, del histórico de ventas.

    Solo trae los productos con alguna venta en la ventana; el resto no está en
    el dict y el llamador cae a su tasa de salidas. Ventana [hoy-56, hoy-1]: HOY
    queda afuera (día a medio vender, hundiría la mediana de su propio día).
    """
    d_utc, h_utc = rango_col_utc(hoy - timedelta(days=SEMANAS * 7),
                                 hoy - timedelta(days=1))

    # Líneas de venta de la ventana, con la fecha de su ticket para agrupar por día.
    filas = (
        db.query(TicketItem.id, TicketItem.producto_id, TicketItem.cantidad, Ticket.fecha)
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(
            Ticket.tienda_id == tienda_id,
            Ticket.fecha >= d_utc,
            Ticket.fecha <= h_utc,
            Ticket.estado.notin_(("anulado", "reversado")),
        )
        .all()
    )
    if not filas:
        return {}

    # Selecciones de combo: una línea de combo se abre en sus productos reales.
    item_ids = [f[0] for f in filas]
    combos: dict[int, list[tuple[int, float]]] = {}
    for tii, pid, cant in (
        db.query(TicketItemComboSeleccion.ticket_item_id,
                 TicketItemComboSeleccion.producto_id,
                 TicketItemComboSeleccion.cantidad)
        .filter(TicketItemComboSeleccion.ticket_item_id.in_(item_ids))
        .all()
    ):
        combos.setdefault(tii, []).append((pid, float(cant)))

    # Recetas y control de stock (tablas chicas: una consulta cada una).
    recetas: dict[int, list[tuple[int, float]]] = {}
    for pid, iid, cant in db.query(
        ProductoInsumo.producto_id, ProductoInsumo.insumo_id, ProductoInsumo.cantidad
    ).all():
        recetas.setdefault(pid, []).append((iid, float(cant)))
    controla: dict[int, bool] = dict(db.query(Producto.id, Producto.controla_stock).all())

    # Unidades por (producto de inventario, día Colombia) y el set de días abiertos.
    unidades: dict[tuple[int, date], float] = defaultdict(float)
    dias_abiertos: set[date] = set()
    for tii, pid, cant, fecha in filas:
        if fecha is None:
            continue
        d = dia_col(fecha)
        dias_abiertos.add(d)
        # Producto(s) real(es): si la línea es un combo, sus componentes; si no, ella misma.
        sel = combos.get(tii)
        reales = [(rp, rc * float(cant)) for rp, rc in sel] if sel else [(pid, float(cant))]
        for rp, rq in reales:
            # Mismo reparto que la caja: stock propio (si controla) + insumos de receta.
            if controla.get(rp):
                unidades[(rp, d)] += rq
            for iid, icant in recetas.get(rp, ()):  # noqa: SIM118
                unidades[(iid, d)] += icant * rq

    # Días abiertos por día de la semana: el denominador de cada mediana.
    abiertos_por_dow: dict[int, list[date]] = defaultdict(list)
    for d in dias_abiertos:
        abiertos_por_dow[d.weekday()].append(d)

    productos = {pid for (pid, _d) in unidades}
    tasas: dict[int, float] = {}
    for pid in productos:
        # Suma de la mediana de cada día de la semana, entre 7. Un día de semana que
        # nunca abrió no suma (es un 0 real: ese día no se vende). Las muestras de un
        # día de semana incluyen los días abiertos donde el producto vendió 0, para no
        # sobreestimar (vender 3 de 8 sábados es menos que vender los 8).
        total_semana = 0.0
        for dow, dias in abiertos_por_dow.items():
            muestras = [unidades.get((pid, d), 0.0) for d in dias]
            total_semana += median(muestras)
        tasa = total_semana / 7.0
        if tasa > 0:
            tasas[pid] = tasa
    return tasas
