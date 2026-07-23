"""Servicio de agregados exclusivos del Dashboard Ejecutivo (Módulo 7).

Los endpoints existentes cubren la mayoría de indicadores. Este módulo solo
implementa los tres agregados que NO existen en ningún otro endpoint:
  - ventas_por_sede: Σ ventas por tienda en un rango de fechas
  - ventas_por_categoria: Σ ventas por categoría de producto
  - inventario_valorizado: Σ stock_actual × precio_venta (a precio de venta;
      no hay costo unitario en Inventario — documentado)
"""
from datetime import date, datetime
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Ticket, TicketItem, Tienda, Inventario, Producto, CategoriaProductoEnum,
    FacturaCompraItem, Combo,
)
from app.core.tz import rango_col_utc


def _rango(fecha_desde: date | None, fecha_hasta: date | None) -> tuple[datetime, datetime]:
    """Normaliza rango a UTC cubriendo días Colombia (UTC-5). Default = hoy Colombia.

    Compat SQLite + PostgreSQL (sin funciones de fecha SQL-específicas).
    """
    return rango_col_utc(fecha_desde, fecha_hasta)


def ventas_por_sede(
    db: Session,
    fecha_desde: date | None,
    fecha_hasta: date | None,
) -> list[dict]:
    """Σ ventas y cantidad de tickets por tienda activa en el rango.

    Incluye tiendas con $0 (OUTER JOIN) para que el gráfico de barras no omita
    sedes sin actividad en el período seleccionado.
    """
    desde, hasta = _rango(fecha_desde, fecha_hasta)
    rows = (
        db.query(
            Tienda.id,
            Tienda.nombre,
            func.coalesce(func.sum(Ticket.total), 0.0),
            func.count(Ticket.id),
        )
        .outerjoin(
            Ticket,
            (Ticket.tienda_id == Tienda.id)
            & Ticket.estado.notin_(("anulado", "reversado"))
            & (Ticket.fecha >= desde)
            & (Ticket.fecha <= hasta),
        )
        .filter(Tienda.activa == True)
        .group_by(Tienda.id, Tienda.nombre)
        .order_by(func.coalesce(func.sum(Ticket.total), 0.0).desc())
        .all()
    )
    return [
        {
            "tienda_id": r[0],
            "tienda": r[1],
            "total": round(float(r[2]), 2),
            "n_tickets": int(r[3]),
        }
        for r in rows
    ]


def ventas_por_categoria(
    db: Session,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    tienda_id: int | None = None,
) -> list[dict]:
    """Σ importe y unidades vendidas por categoría de producto en el rango.

    Cruza TicketItem → Producto para obtener la categoría real.
    Filtra tickets NO anulados. Acepta tienda_id opcional.
    """
    desde, hasta = _rango(fecha_desde, fecha_hasta)
    filtros = [
        Ticket.estado.notin_(("anulado", "reversado")),
        Ticket.fecha >= desde,
        Ticket.fecha <= hasta,
    ]
    if tienda_id is not None:
        filtros.append(Ticket.tienda_id == tienda_id)

    # Línea de combo = su producto es el SOMBRA de un Combo (Combo.producto_id):
    # se reporta como categoría propia "combos" en vez de la categoría inerte del
    # sombra — así el ingreso de combos no infla bebida ni esconde pastelería.
    es_combo = Combo.id.isnot(None)
    rows = (
        db.query(
            Producto.categoria,
            es_combo,
            func.sum(TicketItem.subtotal),
            func.sum(TicketItem.cantidad),
        )
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .join(Producto, Producto.id == TicketItem.producto_id)
        .outerjoin(Combo, Combo.producto_id == TicketItem.producto_id)
        .filter(*filtros)
        .group_by(Producto.categoria, es_combo)
        .all()
    )
    acumulado: dict[str, dict] = {}
    for cat, combo_flag, total, unidades in rows:
        nombre = "combos" if combo_flag else (cat.value if hasattr(cat, "value") else str(cat))
        e = acumulado.setdefault(nombre, {"total": 0.0, "unidades": 0.0})
        e["total"] += float(total or 0)
        e["unidades"] += float(unidades or 0)
    return [
        {
            "categoria": nombre,
            "total": round(v["total"], 2),
            "unidades": v["unidades"],
        }
        for nombre, v in sorted(acumulado.items(), key=lambda kv: -kv[1]["total"])
    ]


def inventario_valorizado(
    db: Session,
    tienda_id: int | None = None,
) -> dict:
    """Valor del inventario a COSTO de adquisición.

    Costo unitario = promedio de precio_unitario en facturas de compra del producto.
    Si el producto nunca se compró por factura, cae a precio_venta como proxy. La 'nota'
    informa qué proporción quedó valorizada a costo real.

    Solo incluye productos con controla_stock=True (los que mueven stock real).
    Devuelve total global + desglose por sede + desglose por categoría.
    """
    cost_rows = (
        db.query(FacturaCompraItem.producto_id, func.avg(FacturaCompraItem.precio_unitario))
        .group_by(FacturaCompraItem.producto_id)
        .all()
    )
    cost_map = {pid: float(c or 0) for pid, c in cost_rows}

    q = (
        db.query(
            Tienda.id, Tienda.nombre, Producto.id, Producto.categoria,
            Inventario.stock_actual, Producto.precio_venta,
        )
        .join(Inventario, Inventario.tienda_id == Tienda.id)
        .join(Producto, Producto.id == Inventario.producto_id)
        .filter(Producto.controla_stock == True, Tienda.activa == True)
    )
    if tienda_id is not None:
        q = q.filter(Tienda.id == tienda_id)
    rows = q.all()

    por_sede: dict = {}
    por_cat: dict = {}
    total = 0.0
    con_costo = 0
    total_items = 0

    for tid, tnom, pid, cat, stock, pventa in rows:
        total_items += 1
        costo = cost_map.get(pid)
        if costo and costo > 0:
            con_costo += 1
        else:
            costo = float(pventa or 0)
        v = round(float(stock or 0) * costo, 2)
        total += v
        if tid not in por_sede:
            por_sede[tid] = {"tienda_id": tid, "tienda": tnom, "valor": 0.0}
        por_sede[tid]["valor"] = round(por_sede[tid]["valor"] + v, 2)
        cat_key = cat.value if hasattr(cat, "value") else str(cat)
        if cat_key not in por_cat:
            por_cat[cat_key] = {"categoria": cat_key, "valor": 0.0}
        por_cat[cat_key]["valor"] = round(por_cat[cat_key]["valor"] + v, 2)

    return {
        "total": round(total, 2),
        "nota": f"valorizado a costo de compra ({con_costo}/{total_items} productos con costo real de factura; el resto a precio de venta)",
        "por_sede": sorted(por_sede.values(), key=lambda x: -x["valor"]),
        "por_categoria": sorted(por_cat.values(), key=lambda x: -x["valor"]),
    }
