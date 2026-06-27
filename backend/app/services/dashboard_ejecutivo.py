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
)


def _rango(fecha_desde: date | None, fecha_hasta: date | None) -> tuple[datetime, datetime]:
    """Normaliza rango de fechas. Default = hoy. Compat SQLite + PostgreSQL."""
    hoy = date.today()
    desde = fecha_desde or hoy
    hasta = fecha_hasta or hoy
    return (
        datetime.combine(desde, datetime.min.time()),
        datetime.combine(hasta, datetime.max.time()),
    )


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

    rows = (
        db.query(
            Producto.categoria,
            func.sum(TicketItem.subtotal),
            func.sum(TicketItem.cantidad),
        )
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .join(Producto, Producto.id == TicketItem.producto_id)
        .filter(*filtros)
        .group_by(Producto.categoria)
        .order_by(func.sum(TicketItem.subtotal).desc())
        .all()
    )
    return [
        {
            "categoria": r[0].value if hasattr(r[0], "value") else str(r[0]),
            "total": round(float(r[1] or 0), 2),
            "unidades": float(r[2] or 0),
        }
        for r in rows
    ]


def inventario_valorizado(
    db: Session,
    tienda_id: int | None = None,
) -> dict:
    """Valor del inventario a precio de venta.

    Nota: no existe costo unitario en la tabla Inventario. Se usa precio_venta
    de Producto como proxy. El resultado se etiqueta explícitamente "a precio
    de venta" para no confundirlo con costo de adquisición.

    Solo incluye productos con controla_stock=True (los que mueven stock real).
    Devuelve total global + desglose por sede + desglose por categoría.
    """
    q = (
        db.query(
            Tienda.id,
            Tienda.nombre,
            Producto.categoria,
            func.sum(Inventario.stock_actual * Producto.precio_venta),
        )
        .join(Inventario, Inventario.tienda_id == Tienda.id)
        .join(Producto, Producto.id == Inventario.producto_id)
        .filter(Producto.controla_stock == True, Tienda.activa == True)
    )
    if tienda_id is not None:
        q = q.filter(Tienda.id == tienda_id)

    rows = q.group_by(Tienda.id, Tienda.nombre, Producto.categoria).all()

    por_sede: dict = {}
    por_cat: dict = {}
    total = 0.0

    for tid, tnom, cat, val in rows:
        v = round(float(val or 0), 2)
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
        "nota": "valorizado a precio de venta (sin costo de adquisición)",
        "por_sede": sorted(por_sede.values(), key=lambda x: -x["valor"]),
        "por_categoria": sorted(por_cat.values(), key=lambda x: -x["valor"]),
    }
