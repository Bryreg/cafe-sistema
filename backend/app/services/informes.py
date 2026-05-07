from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import (
    VentaDiaria, Merma, MovimientoInventario, TipoMovInvEnum,
    CajaTurno, EstadoTurnoEnum, EntregaTurno, Inventario, Producto, Usuario
)
from datetime import datetime, date
from collections import defaultdict


def reporte_ventas(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date):
    """Ventas agrupadas por día."""
    desde = datetime.combine(fecha_desde, datetime.min.time())
    hasta = datetime.combine(fecha_hasta, datetime.max.time())

    ventas = (
        db.query(VentaDiaria)
        .filter(
            VentaDiaria.tienda_id == tienda_id,
            VentaDiaria.fecha_registro >= desde,
            VentaDiaria.fecha_registro <= hasta,
        )
        .order_by(VentaDiaria.fecha_registro.asc())
        .all()
    )

    por_dia: dict[str, dict] = defaultdict(lambda: {
        "fecha": "",
        "venta_total": 0.0,
        "nota_credito": 0.0,
        "vales": 0.0,
        "tarjetas": 0.0,
        "efectivo": 0.0,
        "n_registros": 0,
    })

    for v in ventas:
        key = v.fecha_registro.strftime("%Y-%m-%d")
        d = por_dia[key]
        d["fecha"] = key
        d["venta_total"] += v.venta_total
        d["nota_credito"] += v.nota_credito
        d["vales"] += v.vales
        d["tarjetas"] += v.tarjetas
        d["efectivo"] += v.efectivo_calculado
        d["n_registros"] += 1

    rows = list(por_dia.values())

    totales = {
        "venta_total": sum(r["venta_total"] for r in rows),
        "nota_credito": sum(r["nota_credito"] for r in rows),
        "vales": sum(r["vales"] for r in rows),
        "tarjetas": sum(r["tarjetas"] for r in rows),
        "efectivo": sum(r["efectivo"] for r in rows),
        "n_registros": sum(r["n_registros"] for r in rows),
    }

    return {"filas": rows, "totales": totales}


def reporte_mermas(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date):
    """Mermas agrupadas por producto."""
    desde = datetime.combine(fecha_desde, datetime.min.time())
    hasta = datetime.combine(fecha_hasta, datetime.max.time())

    mermas = (
        db.query(Merma)
        .filter(
            Merma.tienda_id == tienda_id,
            Merma.fecha_registro >= desde,
            Merma.fecha_registro <= hasta,
        )
        .order_by(Merma.fecha_registro.asc())
        .all()
    )

    por_producto: dict[int, dict] = defaultdict(lambda: {
        "producto_id": 0,
        "producto": "",
        "unidad": "",
        "total_cantidad": 0.0,
        "n_registros": 0,
        "detalle": [],
    })

    for m in mermas:
        d = por_producto[m.producto_id]
        d["producto_id"] = m.producto_id
        d["producto"] = m.producto.nombre
        d["unidad"] = m.producto.unidad_medida
        d["total_cantidad"] += m.cantidad
        d["n_registros"] += 1
        d["detalle"].append({
            "fecha": m.fecha_registro.strftime("%Y-%m-%d %H:%M"),
            "cantidad": m.cantidad,
            "motivo": m.motivo,
        })

    rows = list(por_producto.values())
    totales = {
        "total_registros": sum(r["n_registros"] for r in rows),
    }
    return {"filas": rows, "totales": totales}


def reporte_inventario_consumido(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date):
    """Movimientos de salida agrupados por producto (consumo de inventario)."""
    desde = datetime.combine(fecha_desde, datetime.min.time())
    hasta = datetime.combine(fecha_hasta, datetime.max.time())

    movs = (
        db.query(MovimientoInventario)
        .filter(
            MovimientoInventario.tienda_id == tienda_id,
            MovimientoInventario.tipo == TipoMovInvEnum.salida,
            MovimientoInventario.fecha >= desde,
            MovimientoInventario.fecha <= hasta,
        )
        .order_by(MovimientoInventario.fecha.asc())
        .all()
    )

    por_producto: dict[int, dict] = defaultdict(lambda: {
        "producto_id": 0,
        "producto": "",
        "unidad": "",
        "total_salida": 0.0,
        "n_movimientos": 0,
        "detalle": [],
    })

    for m in movs:
        d = por_producto[m.producto_id]
        d["producto_id"] = m.producto_id
        d["producto"] = m.producto.nombre
        d["unidad"] = m.producto.unidad_medida
        d["total_salida"] += m.cantidad
        d["n_movimientos"] += 1
        d["detalle"].append({
            "fecha": m.fecha.strftime("%Y-%m-%d %H:%M"),
            "cantidad": m.cantidad,
            "motivo": m.motivo or "",
        })

    rows = sorted(por_producto.values(), key=lambda x: x["total_salida"], reverse=True)
    totales = {
        "total_movimientos": sum(r["n_movimientos"] for r in rows),
    }
    return {"filas": rows, "totales": totales}


def reporte_entregas(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date):
    """Cuadres de llegada en el período."""
    desde = datetime.combine(fecha_desde, datetime.min.time())
    hasta = datetime.combine(fecha_hasta, datetime.max.time())

    entregas = (
        db.query(EntregaTurno)
        .filter(
            EntregaTurno.tienda_id == tienda_id,
            EntregaTurno.fecha_hora >= desde,
            EntregaTurno.fecha_hora <= hasta,
        )
        .order_by(EntregaTurno.fecha_hora.desc())
        .all()
    )

    filas = [
        {
            "id": e.id,
            "fecha_hora": e.fecha_hora.strftime("%Y-%m-%d %H:%M"),
            "usuario": e.usuario.nombre,
            "efectivo_esperado": e.efectivo_esperado,
            "efectivo_real": e.efectivo_real,
            "diferencia_efectivo": e.diferencia_efectivo,
            "ventas_tarjeta_bold": e.ventas_tarjeta_bold,
            "diferencia_tarjeta": e.diferencia_tarjeta,
            "imagen_url": e.imagen_url,
        }
        for e in entregas
    ]

    return {
        "filas": filas,
        "totales": {
            "n_entregas": len(filas),
            "con_diferencia_efectivo": sum(1 for f in filas if f["diferencia_efectivo"] != 0),
            "con_diferencia_tarjeta": sum(1 for f in filas if f["diferencia_tarjeta"] != 0),
        },
    }


def kpi_mermas(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date):
    """KPI mermas: total por tipo, comparado con ventas del período."""
    desde = datetime.combine(fecha_desde, datetime.min.time())
    hasta = datetime.combine(fecha_hasta, datetime.max.time())

    mermas = (
        db.query(Merma)
        .filter(Merma.tienda_id == tienda_id,
                Merma.fecha_registro >= desde,
                Merma.fecha_registro <= hasta)
        .all()
    )

    ventas = (
        db.query(VentaDiaria)
        .filter(VentaDiaria.tienda_id == tienda_id,
                VentaDiaria.fecha_registro >= desde,
                VentaDiaria.fecha_registro <= hasta)
        .all()
    )
    total_ventas = sum(v.venta_total for v in ventas)

    por_tipo = defaultdict(lambda: {"n": 0, "productos": set()})
    por_producto: dict[int, dict] = defaultdict(lambda: {"nombre": "", "unidad": "", "n": 0, "cantidad": 0.0, "tipo": ""})

    for m in mermas:
        t = m.tipo or "consumo"
        por_tipo[t]["n"] += 1
        por_tipo[t]["productos"].add(m.producto_id)
        p = por_producto[m.producto_id]
        p["nombre"] = m.producto.nombre if m.producto else str(m.producto_id)
        p["unidad"] = m.producto.unidad_medida if m.producto else ""
        p["n"] += 1
        p["cantidad"] += m.cantidad
        p["tipo"] = t

    top_productos = sorted(por_producto.values(), key=lambda x: x["n"], reverse=True)[:10]
    # Limpiar sets para serialización
    tipos_out = {t: {"n": v["n"], "n_productos": len(v["productos"])} for t, v in por_tipo.items()}

    return {
        "total_registros": len(mermas),
        "total_ventas": total_ventas,
        "por_tipo": tipos_out,
        "top_productos": top_productos,
        "tiene_ventas": total_ventas > 0,
    }


def reporte_rotacion(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date):
    """Rotación de inventario por producto en el período."""
    desde = datetime.combine(fecha_desde, datetime.min.time())
    hasta = datetime.combine(fecha_hasta, datetime.max.time())

    inventarios = (
        db.query(Inventario)
        .filter(Inventario.tienda_id == tienda_id)
        .all()
    )

    # Movimientos del período
    movs = (
        db.query(MovimientoInventario)
        .filter(MovimientoInventario.tienda_id == tienda_id,
                MovimientoInventario.fecha >= desde,
                MovimientoInventario.fecha <= hasta)
        .all()
    )

    entradas_por_prod: dict[int, float] = defaultdict(float)
    salidas_por_prod: dict[int, float]  = defaultdict(float)
    for m in movs:
        if m.tipo == TipoMovInvEnum.entrada:
            entradas_por_prod[m.producto_id] += m.cantidad
        elif m.tipo == TipoMovInvEnum.salida:
            salidas_por_prod[m.producto_id]  += m.cantidad

    filas = []
    for inv in inventarios:
        if not inv.producto.controla_stock:
            continue
        entradas = entradas_por_prod.get(inv.producto_id, 0.0)
        salidas  = salidas_por_prod.get(inv.producto_id, 0.0)
        stock    = inv.stock_actual

        # Rotación simple = salidas / stock_actual (si stock>0)
        rotacion = round(salidas / stock, 2) if stock > 0 else None

        if entradas == 0 and salidas == 0:
            estado = "sin_movimiento"
        elif salidas == 0 and stock > 0:
            estado = "estancado"
        elif stock == 0 and salidas > 0:
            estado = "agotado"
        else:
            estado = "activo"

        filas.append({
            "producto_id":   inv.producto_id,
            "producto":      inv.producto.nombre,
            "categoria":     inv.producto.categoria.value,
            "unidad":        inv.producto.unidad_medida,
            "stock_actual":  stock,
            "stock_minimo":  inv.stock_minimo,
            "entradas":      entradas,
            "salidas":       salidas,
            "rotacion":      rotacion,
            "estado":        estado,
            "alerta_min":    stock <= inv.stock_minimo,
        })

    # Ordenar: primero bajo mínimo, luego estancados, luego activos
    orden = {"estancado": 0, "agotado": 1, "activo": 2, "sin_movimiento": 3}
    filas.sort(key=lambda x: (orden.get(x["estado"], 9), -x["salidas"]))

    return {
        "filas": filas,
        "resumen": {
            "activos":          sum(1 for f in filas if f["estado"] == "activo"),
            "estancados":       sum(1 for f in filas if f["estado"] == "estancado"),
            "sin_movimiento":   sum(1 for f in filas if f["estado"] == "sin_movimiento"),
            "agotados":         sum(1 for f in filas if f["estado"] == "agotado"),
            "bajo_minimo":      sum(1 for f in filas if f["alerta_min"]),
        }
    }


def reporte_turnos(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date):
    """Historial de turnos cerrados en el período."""
    desde = datetime.combine(fecha_desde, datetime.min.time())
    hasta = datetime.combine(fecha_hasta, datetime.max.time())

    turnos = (
        db.query(CajaTurno)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            CajaTurno.fecha_cierre >= desde,
            CajaTurno.fecha_cierre <= hasta,
            CajaTurno.estado == EstadoTurnoEnum.cerrado,
        )
        .order_by(CajaTurno.fecha_cierre.desc())
        .all()
    )

    filas = [
        {
            "id": t.id,
            "fecha_apertura": t.fecha_apertura.strftime("%Y-%m-%d %H:%M"),
            "fecha_cierre": t.fecha_cierre.strftime("%Y-%m-%d %H:%M"),
            "usuario_apertura": t.usuario_apertura.nombre,
            "usuario_cierre": t.usuario_cierre.nombre if t.usuario_cierre else "—",
            "base_real": t.base_real,
            "total_ventas": t.total_ventas,
            "total_efectivo": t.total_efectivo,
            "total_tarjeta": t.total_tarjeta,
            "diferencia_cierre": t.diferencia_cierre or 0.0,
            "diferencia_tarjeta": t.diferencia_tarjeta or 0.0,
            "justificacion_cierre": t.justificacion_cierre,
        }
        for t in turnos
    ]

    return {
        "filas": filas,
        "totales": {
            "n_turnos": len(filas),
            "total_ventas": sum(f["total_ventas"] for f in filas),
            "total_efectivo": sum(f["total_efectivo"] for f in filas),
            "total_tarjeta": sum(f["total_tarjeta"] for f in filas),
            "con_diferencia": sum(1 for f in filas if f["diferencia_cierre"] != 0),
        },
    }


def reporte_baristas(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date):
    """Ranking de baristas: cuadres de llegada y cierres con sus diferencias."""
    desde = datetime.combine(fecha_desde, datetime.min.time())
    hasta = datetime.combine(fecha_hasta, datetime.max.time())

    entregas = (
        db.query(EntregaTurno)
        .filter(
            EntregaTurno.tienda_id == tienda_id,
            EntregaTurno.fecha_hora >= desde,
            EntregaTurno.fecha_hora <= hasta,
        )
        .all()
    )

    por_usuario: dict[int, dict] = {}
    for e in entregas:
        uid = e.usuario_id
        if uid not in por_usuario:
            por_usuario[uid] = {
                "usuario_id": uid,
                "nombre": e.usuario.nombre if e.usuario else str(uid),
                "n_recibos": 0,
                "n_cierres": 0,
                "n_diff_efectivo": 0,
                "n_diff_tarjeta": 0,
                "suma_diff_efectivo": 0.0,
                "peor_diferencia": 0.0,
                "ultimo_cuadre": None,
            }
        d = por_usuario[uid]
        if e.tipo == "recibo":
            d["n_recibos"] += 1
        else:
            d["n_cierres"] += 1
        if e.diferencia_efectivo != 0:
            d["n_diff_efectivo"] += 1
            d["suma_diff_efectivo"] += e.diferencia_efectivo
            if abs(e.diferencia_efectivo) > abs(d["peor_diferencia"]):
                d["peor_diferencia"] = e.diferencia_efectivo
        if e.diferencia_tarjeta != 0:
            d["n_diff_tarjeta"] += 1
        if d["ultimo_cuadre"] is None or e.fecha_hora > datetime.strptime(d["ultimo_cuadre"], "%Y-%m-%d %H:%M"):
            d["ultimo_cuadre"] = e.fecha_hora.strftime("%Y-%m-%d %H:%M")

    filas = sorted(
        por_usuario.values(),
        key=lambda x: (x["n_diff_efectivo"], -abs(x["suma_diff_efectivo"])),
        reverse=True,
    )

    return {
        "filas": filas,
        "totales": {
            "n_baristas": len(filas),
            "total_cuadres": sum(f["n_recibos"] + f["n_cierres"] for f in filas),
            "con_diferencia": sum(1 for f in filas if f["n_diff_efectivo"] > 0),
        },
    }
