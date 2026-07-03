"""Inventario físico mensual + conciliación valorizada.

Relacional con el resto del sistema: cada conteo pertenece a una sede y un usuario;
cada ítem referencia un producto real. La existencia teórica se toma del Inventario
vigente; la diferencia se valoriza con el costo promedio de compra (FacturaCompraItem)
y, si el producto nunca se compró por factura, cae al precio de venta.
"""
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import (
    InventarioMensual, InventarioMensualItem, Inventario, Producto, FacturaCompraItem,
)
from app.services import audit


def _valor_unitario_map(db: Session) -> dict:
    """Costo unitario por producto = promedio de precio_unitario en facturas de compra."""
    rows = (
        db.query(FacturaCompraItem.producto_id, func.avg(FacturaCompraItem.precio_unitario))
        .group_by(FacturaCompraItem.producto_id)
        .all()
    )
    return {pid: float(avg or 0) for pid, avg in rows}


def _serializar(inv: InventarioMensual) -> dict:
    # Mismo orden que el conteo (planilla de pedidos): orden_conteo primero, resto
    # alfabético al final — para que revisar la conciliación siga el papel.
    items = sorted(
        inv.items,
        key=lambda x: (
            (x.producto.orden_conteo if x.producto else None) is None,
            (x.producto.orden_conteo if x.producto else 0) or 0,
            x.producto.nombre if x.producto else '',
        ),
    )
    return {
        "id": inv.id, "tienda_id": inv.tienda_id, "anio": inv.anio, "mes": inv.mes,
        "estado": inv.estado, "barista_nombre": inv.barista_nombre,
        "fecha_inicio": inv.fecha_inicio, "fecha_cierre": inv.fecha_cierre,
        "valor_diferencia_total": float(inv.valor_diferencia_total or 0),
        "items": [{
            "id": it.id, "producto_id": it.producto_id,
            "producto_nombre": it.producto.nombre if it.producto else "",
            "categoria": it.categoria, "unidad_medida": it.unidad_medida,
            "fraccionable": bool(it.producto.fraccionable) if it.producto else False,
            "envase": it.producto.envase if it.producto else None,
            "cantidad_sistema": it.cantidad_sistema,
            "cantidad_real": it.cantidad_real,
            "diferencia": it.diferencia,
            "valor_unitario": float(it.valor_unitario or 0),
            "valor_diferencia": float(it.valor_diferencia or 0),
        } for it in items],
    }


def iniciar(db: Session, tienda_id: int, anio: int, mes: int, usuario_id: int,
            barista_id: int | None = None, barista_nombre: str | None = None) -> dict:
    """Obtiene el conteo del período o lo crea pre-poblando los productos que controlan
    stock con su existencia teórica actual. Idempotente (1 por sede/mes por UniqueConstraint)."""
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    if inv:
        return _serializar(inv)
    inv = InventarioMensual(tienda_id=tienda_id, anio=anio, mes=mes, usuario_id=usuario_id,
                            barista_id=barista_id, barista_nombre=barista_nombre)
    db.add(inv)
    db.flush()
    val = _valor_unitario_map(db)
    rows = (
        db.query(Inventario, Producto)
        .join(Producto, Producto.id == Inventario.producto_id)
        .filter(Inventario.tienda_id == tienda_id, Producto.controla_stock == True)  # noqa: E712
        .all()
    )
    for invrow, prod in rows:
        db.add(InventarioMensualItem(
            inventario_id=inv.id, producto_id=prod.id,
            categoria=prod.categoria.value, unidad_medida=prod.unidad_medida,
            cantidad_sistema=invrow.stock_actual or 0,
            cantidad_real=None, diferencia=0,
            valor_unitario=val.get(prod.id, float(prod.precio_venta or 0)),
            valor_diferencia=0,
        ))
    db.commit()
    db.refresh(inv)
    return _serializar(inv)


def reiniciar(db: Session, tienda_id: int, anio: int, mes: int, usuario_id: int) -> dict:
    """Borra el conteo mensual EN PROCESO y lo re-siembra con el conteo del sistema
    actual. Pensado para cuando cambia el modelo/las unidades (p.ej. la conversión a
    gramos del 3-jul dejó cantidad_sistema en unidades viejas). Los cerrados son
    históricos intocables."""
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    if inv:
        if inv.estado == "cerrado":
            raise HTTPException(400, "El inventario del mes ya está cerrado — es histórico y no se reinicia")
        audit.registrar(
            db, accion="inventario_mensual_reiniciado", tabla="inventarios_mensuales",
            registro_id=inv.id, usuario_id=usuario_id, tienda_id=tienda_id,
            datos_antes={"anio": anio, "mes": mes, "items": len(inv.items)},
        )
        db.delete(inv)   # cascade borra los items
        db.commit()
    return iniciar(db, tienda_id, anio, mes, usuario_id)


def get_actual(db: Session, tienda_id: int, anio: int, mes: int):
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    return _serializar(inv) if inv else None


def guardar(db: Session, inv_id: int, items: list) -> dict:
    """Guarda la existencia física (cantidad_real) de los ítems. items: [{id, cantidad_real}]."""
    inv = db.query(InventarioMensual).filter_by(id=inv_id).first()
    if not inv:
        raise HTTPException(404, "Inventario no encontrado")
    if inv.estado == "cerrado":
        raise HTTPException(400, "El inventario ya está cerrado")
    by_id = {it.id: it for it in inv.items}
    for upd in items:
        it = by_id.get(upd.get("id"))
        if it is not None and upd.get("cantidad_real") is not None:
            it.cantidad_real = float(upd["cantidad_real"])
    db.commit()
    return _serializar(inv)


def cerrar(db: Session, inv_id: int, usuario_id: int) -> dict:
    """Finaliza el conteo: calcula diferencia (física − sistema) y su valor económico por
    ítem y el neto total. Los no contados se asumen iguales al sistema (sin diferencia)."""
    inv = db.query(InventarioMensual).filter_by(id=inv_id).first()
    if not inv:
        raise HTTPException(404, "Inventario no encontrado")
    if inv.estado == "cerrado":
        return _serializar(inv)
    total = 0.0
    for it in inv.items:
        real = it.cantidad_real if it.cantidad_real is not None else (it.cantidad_sistema or 0)
        it.cantidad_real = real
        it.diferencia = round(real - (it.cantidad_sistema or 0), 3)
        it.valor_diferencia = round(it.diferencia * float(it.valor_unitario or 0), 2)
        total += it.valor_diferencia
    inv.valor_diferencia_total = round(total, 2)
    inv.estado = "cerrado"
    inv.fecha_cierre = datetime.utcnow()
    audit.registrar(
        db, accion="cerrar_inventario_mensual", tabla="inventarios_mensuales",
        registro_id=inv.id, usuario_id=usuario_id, tienda_id=inv.tienda_id,
        datos_despues={"anio": inv.anio, "mes": inv.mes, "valor_diferencia": inv.valor_diferencia_total},
    )
    db.commit()
    db.refresh(inv)
    return _serializar(inv)


def get_conciliacion(db: Session, tienda_id: int, anio: int, mes: int):
    """Pantalla de conciliación (admin): teórico vs físico vs diferencia valorizada,
    clasificación, totales por categoría y ranking de mayores diferencias."""
    inv = db.query(InventarioMensual).filter_by(tienda_id=tienda_id, anio=anio, mes=mes).first()
    if not inv:
        return None
    base = _serializar(inv)
    items = base["items"]
    positivas = [i for i in items if (i["diferencia"] or 0) > 0]
    negativas = [i for i in items if (i["diferencia"] or 0) < 0]
    sin = [i for i in items if (i["diferencia"] or 0) == 0]

    por_cat: dict = {}
    for i in items:
        c = i["categoria"] or "—"
        g = por_cat.setdefault(c, {"categoria": c, "valor_diferencia": 0.0, "items": 0, "con_diferencia": 0})
        g["valor_diferencia"] += i["valor_diferencia"]
        g["items"] += 1
        if (i["diferencia"] or 0) != 0:
            g["con_diferencia"] += 1
    for g in por_cat.values():
        g["valor_diferencia"] = round(g["valor_diferencia"], 2)

    ranking = sorted(
        [i for i in items if (i["diferencia"] or 0) != 0],
        key=lambda x: abs(x["valor_diferencia"]), reverse=True,
    )[:15]

    return {
        **base,
        "resumen": {
            "positivas": len(positivas), "negativas": len(negativas), "sin_diferencia": len(sin),
            "valor_positivo": round(sum(i["valor_diferencia"] for i in positivas), 2),
            "valor_negativo": round(sum(i["valor_diferencia"] for i in negativas), 2),
            "valor_neto": base["valor_diferencia_total"],
        },
        "por_categoria": sorted(por_cat.values(), key=lambda x: x["valor_diferencia"]),
        "ranking": ranking,
    }


def get_historial(db: Session, tienda_id: int | None = None) -> list:
    q = db.query(InventarioMensual)
    if tienda_id is not None:
        q = q.filter_by(tienda_id=tienda_id)
    rows = q.order_by(InventarioMensual.anio.desc(), InventarioMensual.mes.desc()).all()
    return [{
        "id": r.id, "tienda_id": r.tienda_id,
        "tienda_nombre": r.tienda.nombre if r.tienda else None,
        "anio": r.anio, "mes": r.mes, "estado": r.estado,
        "valor_diferencia_total": float(r.valor_diferencia_total or 0),
        "barista_nombre": r.barista_nombre, "fecha_cierre": r.fecha_cierre,
    } for r in rows]
