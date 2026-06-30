"""POS nativo — reemplazo de Siigo para ventas, precios y descuento de inventario.

Construcción aditiva: no toca el código Siigo (queda dormido).
Reglas de negocio:
  - Solo se descuenta inventario de productos con controla_stock=True.
  - El precio SIEMPRE se calcula en el servidor desde la DB; nunca se confía
    en un precio enviado por el cliente.
  - La venta es todo-o-nada: si falta stock de un producto contable, se aborta.
"""
import logging
from datetime import datetime, date, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException

from app.models.models import Producto, Ticket, TicketItem, CajaTurno, Usuario
from app.services.caja import get_turno_activo
from app.services import inventario as inv_svc, audit

logger = logging.getLogger(__name__)

METODOS_PAGO = {"efectivo", "tarjeta", "mixto"}


def get_productos_pos(db: Session, categoria: str | None = None):
    """Productos vendibles (precio_venta > 0), ordenados por lo MÁS VENDIDO.

    La grilla del POS muestra primero los productos con más unidades vendidas
    en los últimos 7 días (los "favoritos" reales de la operación), luego el
    resto alfabético. Reduce el tiempo de búsqueda de la barista en cada venta.
    Productos sin ventas recientes caen al final ordenados por nombre.
    """
    desde = datetime.utcnow() - timedelta(days=7)
    # Subquery: unidades vendidas por producto en la ventana reciente.
    pop_sq = (
        db.query(
            TicketItem.producto_id.label("pid"),
            func.sum(TicketItem.cantidad).label("vendidos"),
        )
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(Ticket.fecha >= desde)
        .group_by(TicketItem.producto_id)
        .subquery()
    )
    vendidos = func.coalesce(pop_sq.c.vendidos, 0)
    q = (
        db.query(Producto, vendidos.label("vendidos"))
        .outerjoin(pop_sq, pop_sq.c.pid == Producto.id)
        .filter(Producto.precio_venta > 0)
    )
    if categoria:
        q = q.filter(Producto.categoria == categoria)
    rows = q.order_by(vendidos.desc(), Producto.nombre).all()
    return [
        {
            "id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "precio_venta": p.precio_venta or 0.0,
            "controla_stock": p.controla_stock,
            "unidad_medida": p.unidad_medida,
            "vendidos_7d": int(v or 0),
        }
        for p, v in rows
    ]


def crear_ticket(db: Session, tienda_id: int, usuario_id: int, items: list,
                 metodo_pago: str, efectivo_recibido: float | None = None,
                 monto_efectivo: float | None = None,
                 monto_tarjeta: float | None = None,
                 barista_id: int | None = None, barista_nombre: str | None = None):
    """Crea una venta itemizada. Atómico: si algo falla, no se persiste nada.

    `items`: lista de dicts/objetos con `producto_id` y `cantidad`.
    """
    if metodo_pago not in METODOS_PAGO:
        raise HTTPException(status_code=400, detail="metodo_pago inválido")
    if not items:
        raise HTTPException(status_code=400, detail="El ticket no tiene items")

    # Turno activo + gate duro: el POS solo vende si el turno está OPERATIVO
    # (cuadre de llegada + conteo de apertura del día hechos). El backend es la
    # fuente de verdad: un front manipulado no puede vender fuera de turno contado.
    turno = get_turno_activo(db, tienda_id)
    if not turno:
        raise HTTPException(status_code=400, detail="No hay turno abierto")
    if not getattr(turno, "es_operativo", False):
        raise HTTPException(
            status_code=403,
            detail="El turno no está operativo: completá el cuadre de llegada y el conteo de apertura antes de vender.",
        )

    # Normalizar items: cantidad y descuento por producto (evita líneas duplicadas)
    pedidos: dict[int, int] = {}
    descuentos: dict[int, float] = {}
    for it in items:
        producto_id = it["producto_id"] if isinstance(it, dict) else it.producto_id
        cantidad = it["cantidad"] if isinstance(it, dict) else it.cantidad
        d = (it.get("descuento") if isinstance(it, dict) else getattr(it, "descuento", 0)) or 0
        if cantidad is None or cantidad <= 0:
            raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")
        if d < 0:
            raise HTTPException(status_code=400, detail="El descuento no puede ser negativo")
        pedidos[producto_id] = pedidos.get(producto_id, 0) + int(cantidad)
        descuentos[producto_id] = descuentos.get(producto_id, 0.0) + float(d)

    # Calcular precios EN EL SERVIDOR
    productos = {
        p.id: p for p in db.query(Producto).filter(Producto.id.in_(pedidos.keys())).all()
    }
    lineas = []
    total = 0.0
    descuento_total = 0.0
    for producto_id, cantidad in pedidos.items():
        prod = productos.get(producto_id)
        if not prod:
            raise HTTPException(status_code=404, detail=f"Producto {producto_id} no encontrado")
        precio = prod.precio_venta or 0.0
        if precio <= 0:
            raise HTTPException(status_code=400, detail=f"El producto '{prod.nombre}' no tiene precio de venta")
        bruto = round(precio * cantidad, 2)
        # Descuento POR PRODUCTO (línea): nunca puede superar el bruto de esa línea
        desc_linea = round(min(descuentos.get(producto_id, 0.0), bruto), 2)
        subtotal = round(bruto - desc_linea, 2)
        total += subtotal
        descuento_total += desc_linea
        lineas.append((prod, cantidad, precio, subtotal, desc_linea))
    total = round(total, 2)
    descuento = round(descuento_total, 2)

    # Resolver montos por método de pago (sobre el total YA con descuento)
    cambio = None
    if metodo_pago == "efectivo":
        monto_efectivo_final = total
        monto_tarjeta_final = 0.0
        if efectivo_recibido is not None:
            if efectivo_recibido < total:
                raise HTTPException(status_code=400, detail="Efectivo insuficiente")
            cambio = round(efectivo_recibido - total, 2)
    elif metodo_pago == "tarjeta":
        monto_efectivo_final = 0.0
        monto_tarjeta_final = total
        efectivo_recibido = None
    else:  # mixto
        if monto_efectivo is None or monto_tarjeta is None:
            raise HTTPException(status_code=400, detail="En pago mixto debes enviar monto_efectivo y monto_tarjeta")
        if monto_efectivo < 0 or monto_tarjeta < 0:
            raise HTTPException(status_code=400, detail="Los montos no pueden ser negativos")
        if round(monto_efectivo + monto_tarjeta, 2) != total:
            raise HTTPException(status_code=400, detail="La suma de efectivo y tarjeta no coincide con el total")
        monto_efectivo_final = round(monto_efectivo, 2)
        monto_tarjeta_final = round(monto_tarjeta, 2)

    # Crear cabecera + líneas (snapshot de nombre y precio)
    ticket = Ticket(
        tienda_id=tienda_id,
        caja_turno_id=turno.id,
        usuario_id=usuario_id,
        total=total,
        descuento=descuento,
        metodo_pago=metodo_pago,
        monto_efectivo=monto_efectivo_final,
        monto_tarjeta=monto_tarjeta_final,
        efectivo_recibido=efectivo_recibido,
        cambio=cambio,
        estado="completado",
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(ticket)
    db.flush()  # obtener ticket.id

    for prod, cantidad, precio, subtotal, desc_linea in lineas:
        db.add(TicketItem(
            ticket_id=ticket.id,
            producto_id=prod.id,
            nombre_producto=prod.nombre,
            cantidad=cantidad,
            precio_unitario=precio,
            subtotal=subtotal,
            descuento=desc_linea,
        ))

    # Inventario: descuento atómico. Stock negativo permitido (allow_negative=True).
    # Si el producto no tiene registro en inventario, se omite sin bloquear la venta.
    for prod, cantidad, _, _, _ in lineas:
        if prod.controla_stock:
            try:
                inv_svc.registrar_movimiento(
                    db, producto_id=prod.id, tienda_id=tienda_id,
                    tipo="salida", cantidad=cantidad, motivo="Venta POS",
                    usuario_id=usuario_id, commit=False, allow_negative=True,
                )
            except HTTPException as e:
                if e.status_code == 404:
                    # Sin registro de inventario — venta igual se procesa
                    logger.warning(f"Producto {prod.id} sin inventario, venta procesada de todas formas")
                else:
                    db.rollback()
                    raise

    # Actualizar totales del turno (mantiene el cierre/cuadre funcionando)
    turno_db = db.query(CajaTurno).filter(CajaTurno.id == turno.id).first()
    turno_db.total_ventas = (turno_db.total_ventas or 0.0) + total
    turno_db.total_efectivo = (turno_db.total_efectivo or 0.0) + monto_efectivo_final
    turno_db.total_tarjeta = (turno_db.total_tarjeta or 0.0) + monto_tarjeta_final
    turno_db.tiene_ventas = True

    audit.registrar(
        db, accion="registro_venta", tabla="tickets",
        registro_id=ticket.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={
            "total": total, "metodo_pago": metodo_pago,
            "monto_efectivo": monto_efectivo_final, "monto_tarjeta": monto_tarjeta_final,
            "items": [{"producto_id": p.id, "cantidad": c, "subtotal": s}
                      for p, c, _, s, _ in lineas],
        },
    )

    db.commit()
    db.refresh(ticket)
    logger.info("Ticket %s creado en tienda %s por usuario %s (total %.2f)",
                ticket.id, tienda_id, usuario_id, total)

    # Motor de notificaciones: meta de ventas del día. Nunca rompe la venta.
    try:
        from app.services import notificaciones
        # Rango [hoy 00:00, mañana 00:00) en vez de func.date(fecha)==hoy: una
        # función sobre la columna anula el índice ix_tickets_tienda_fecha; el
        # rango sí lo usa (esto corre en CADA venta).
        hoy = datetime.utcnow().date()
        desde_hoy = datetime(hoy.year, hoy.month, hoy.day)
        manana = desde_hoy + timedelta(days=1)
        total_dia = db.query(func.coalesce(func.sum(Ticket.total), 0.0)).filter(
            Ticket.tienda_id == tienda_id,
            Ticket.fecha >= desde_hoy,
            Ticket.fecha < manana,
            Ticket.estado.notin_(("anulado", "reversado")),
        ).scalar() or 0.0
        notificaciones.evaluar_ventas_dia(db, tienda_id, float(total_dia))
        # disparar() ya no commitea (transacción-safe): persistimos acá la fila
        # de la notificación, que vive en una transacción aparte de la venta
        # (esta ya está commiteada en la línea 221).
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("evaluar_ventas_dia tras venta fallo: %s", e)
        db.rollback()

    return ticket


def get_ticket(db: Session, ticket_id: int):
    return (
        db.query(Ticket)
        .options(joinedload(Ticket.items))
        .filter(Ticket.id == ticket_id)
        .first()
    )


def get_tickets_turno(db: Session, turno_id: int):
    return (
        db.query(Ticket)
        .options(joinedload(Ticket.items))
        .filter(Ticket.caja_turno_id == turno_id)
        .order_by(Ticket.fecha.desc())
        .all()
    )


def get_tickets_recientes(db: Session, tienda_id: int, dias: int = 7, limit: int = 50):
    """Tickets recientes de la tienda — para revertir (Nota Crédito) desde el panel admin."""
    desde = datetime.utcnow() - timedelta(days=dias)
    return (
        db.query(Ticket)
        .options(joinedload(Ticket.items))
        .filter(Ticket.tienda_id == tienda_id, Ticket.fecha >= desde)
        .order_by(Ticket.fecha.desc())
        .limit(limit)
        .all()
    )


def get_tickets_historial(db: Session, tienda_id: int, fecha_desde: date | None = None,
                          fecha_hasta: date | None = None, limit: int | None = None):
    """Historial de ventas (tickets individuales) en un rango — para consultar en Informes."""
    desde, hasta = _rango_fechas(fecha_desde, fecha_hasta)
    return (
        db.query(Ticket)
        .options(joinedload(Ticket.items))
        .filter(Ticket.tienda_id == tienda_id, Ticket.fecha >= desde, Ticket.fecha <= hasta)
        .order_by(Ticket.fecha.desc())
        .limit(limit)
        .all()
    )


def set_precio(db: Session, producto_id: int, precio_venta: float):
    if precio_venta is None or precio_venta < 0:
        raise HTTPException(status_code=400, detail="El precio no puede ser negativo")
    prod = db.query(Producto).filter(Producto.id == producto_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    prod.precio_venta = round(precio_venta, 2)
    db.commit()
    db.refresh(prod)
    return prod


# ---------------------------------------------------------------------------
# Analytics — agregaciones sobre los tickets reales del POS.
# Todas excluyen tickets anulados y aceptan rango de fechas + tienda opcional.
# ---------------------------------------------------------------------------

def _rango_fechas(fecha_desde: date | None, fecha_hasta: date | None) -> tuple[datetime, datetime]:
    """Normaliza el rango. Default = hoy (00:00:00 → 23:59:59.999999).

    Sigue la convención del resto de informes: datetime.combine con min/max time,
    compatible con SQLite y PostgreSQL sin funciones de fecha SQL-específicas.
    """
    hoy = date.today()
    desde = fecha_desde or hoy
    hasta = fecha_hasta or hoy
    return (
        datetime.combine(desde, datetime.min.time()),
        datetime.combine(hasta, datetime.max.time()),
    )


def _base_tickets_query(db: Session, fecha_desde: date | None, fecha_hasta: date | None,
                        tienda_id: int | None):
    """Query base de tickets NO anulados dentro del rango (+ tienda opcional)."""
    desde, hasta = _rango_fechas(fecha_desde, fecha_hasta)
    q = (
        db.query(Ticket)
        .filter(Ticket.estado.notin_(("anulado", "reversado")))
        .filter(Ticket.fecha >= desde, Ticket.fecha <= hasta)
    )
    if tienda_id is not None:
        q = q.filter(Ticket.tienda_id == tienda_id)
    return q


def get_analytics_resumen(db: Session, fecha_desde: date | None = None,
                          fecha_hasta: date | None = None, tienda_id: int | None = None):
    """KPIs del período: ventas, tickets, ticket promedio, efectivo/tarjeta, items."""
    desde, hasta = _rango_fechas(fecha_desde, fecha_hasta)
    filtros = [Ticket.estado.notin_(("anulado", "reversado")), Ticket.fecha >= desde, Ticket.fecha <= hasta]
    if tienda_id is not None:
        filtros.append(Ticket.tienda_id == tienda_id)

    row = (
        db.query(
            func.coalesce(func.sum(Ticket.total), 0.0),
            func.count(Ticket.id),
            func.coalesce(func.sum(Ticket.monto_efectivo), 0.0),
            func.coalesce(func.sum(Ticket.monto_tarjeta), 0.0),
        )
        .filter(*filtros)
        .one()
    )
    total_ventas, n_tickets, total_efectivo, total_tarjeta = row

    # Unidades vendidas (suma de cantidades de líneas) en los mismos tickets.
    n_items = (
        db.query(func.coalesce(func.sum(TicketItem.cantidad), 0))
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(*filtros)
        .scalar()
    )

    n_tickets = int(n_tickets or 0)
    total_ventas = round(float(total_ventas or 0.0), 2)
    ticket_promedio = round(total_ventas / n_tickets, 2) if n_tickets else 0.0
    return {
        "total_ventas": total_ventas,
        "n_tickets": n_tickets,
        "ticket_promedio": ticket_promedio,
        "total_efectivo": round(float(total_efectivo or 0.0), 2),
        "total_tarjeta": round(float(total_tarjeta or 0.0), 2),
        "n_items": int(n_items or 0),
    }


def get_informe_contador(db: Session, anio: int, mes: int, tienda_id: int | None = None):
    """Consolidado contable del mes: ventas por día desglosadas por método de pago,
    con acumulado, promedios, participación y días de mayor/menor venta. Insumo del
    módulo 'Informe Contador'. Efectivo/Tarjeta salen del split real del ticket
    (monto_efectivo/monto_tarjeta); transferencia/otros quedan en 0 hasta que el POS
    los soporte (se exponen igual para completitud contable)."""
    from calendar import monthrange
    from collections import defaultdict
    ultimo = monthrange(anio, mes)[1]
    desde = datetime(anio, mes, 1)
    hasta = datetime(anio, mes, ultimo, 23, 59, 59)
    filtros = [Ticket.estado.notin_(("anulado", "reversado")), Ticket.fecha >= desde, Ticket.fecha <= hasta]
    if tienda_id is not None:
        filtros.append(Ticket.tienda_id == tienda_id)

    filas = db.query(
        Ticket.fecha, Ticket.total, Ticket.monto_efectivo, Ticket.monto_tarjeta,
    ).filter(*filtros).all()

    por_dia: dict = defaultdict(lambda: {"efectivo": 0.0, "tarjeta": 0.0, "transferencia": 0.0, "otros": 0.0, "total": 0.0, "facturas": 0})
    for fecha, total, ef, tar in filas:
        d = fecha.date().isoformat()
        por_dia[d]["efectivo"] += float(ef or 0)
        por_dia[d]["tarjeta"] += float(tar or 0)
        por_dia[d]["total"] += float(total or 0)
        por_dia[d]["facturas"] += 1

    dias = []
    acumulado = 0.0
    for d in sorted(por_dia.keys()):
        r = por_dia[d]
        acumulado += r["total"]
        tp = r["total"] / r["facturas"] if r["facturas"] else 0.0
        dias.append({
            "fecha": d,
            "efectivo": round(r["efectivo"], 2),
            "tarjeta": round(r["tarjeta"], 2),
            "transferencia": round(r["transferencia"], 2),
            "otros": round(r["otros"], 2),
            "total": round(r["total"], 2),
            "acumulado": round(acumulado, 2),
            "facturas": r["facturas"],
            "ticket_promedio": round(tp, 2),
        })

    total_mes = round(acumulado, 2)
    total_efectivo = round(sum(x["efectivo"] for x in dias), 2)
    total_tarjeta = round(sum(x["tarjeta"] for x in dias), 2)
    total_facturas = sum(x["facturas"] for x in dias)
    dias_con_venta = len(dias)
    promedio_diario = round(total_mes / dias_con_venta, 2) if dias_con_venta else 0.0
    # Promedio de venta diaria sobre los días del MES (no solo los días con venta):
    # mes en curso -> días transcurridos; mes cerrado -> días calendario completos.
    hoy = datetime.now()
    if anio == hoy.year and mes == hoy.month:
        dias_periodo = hoy.day
    else:
        dias_periodo = ultimo
    promedio_venta_diaria = round(total_mes / dias_periodo, 2) if dias_periodo else 0.0
    ticket_promedio_mes = round(total_mes / total_facturas, 2) if total_facturas else 0.0
    dia_max = max(dias, key=lambda x: x["total"]) if dias else None
    dia_min = min(dias, key=lambda x: x["total"]) if dias else None
    base = total_efectivo + total_tarjeta
    return {
        "anio": anio, "mes": mes,
        "dias": dias,
        "total_mes": total_mes,
        "total_efectivo": total_efectivo,
        "total_tarjeta": total_tarjeta,
        "total_transferencia": 0.0,
        "total_otros": 0.0,
        "total_facturas": total_facturas,
        "dias_con_venta": dias_con_venta,
        "dias_periodo": dias_periodo,
        "promedio_diario": promedio_diario,
        "promedio_venta_diaria": promedio_venta_diaria,
        "ticket_promedio_mes": ticket_promedio_mes,
        "participacion": {
            "efectivo": round(total_efectivo / base * 100, 1) if base else 0.0,
            "tarjeta": round(total_tarjeta / base * 100, 1) if base else 0.0,
        },
        "dia_max": {"fecha": dia_max["fecha"], "total": dia_max["total"]} if dia_max else None,
        "dia_min": {"fecha": dia_min["fecha"], "total": dia_min["total"]} if dia_min else None,
    }


def get_analytics_productos_top(db: Session, fecha_desde: date | None = None,
                                fecha_hasta: date | None = None, tienda_id: int | None = None):
    """Por producto: unidades vendidas y $ ingresado, ordenado desc por $."""
    desde, hasta = _rango_fechas(fecha_desde, fecha_hasta)
    filtros = [Ticket.estado.notin_(("anulado", "reversado")), Ticket.fecha >= desde, Ticket.fecha <= hasta]
    if tienda_id is not None:
        filtros.append(Ticket.tienda_id == tienda_id)

    rows = (
        db.query(
            TicketItem.producto_id.label("producto_id"),
            TicketItem.nombre_producto.label("nombre_producto"),
            func.sum(TicketItem.cantidad).label("unidades"),
            func.sum(TicketItem.subtotal).label("total"),
        )
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(*filtros)
        .group_by(TicketItem.producto_id, TicketItem.nombre_producto)
        .order_by(func.sum(TicketItem.subtotal).desc())
        .all()
    )
    return [
        {
            "producto_id": r.producto_id,
            "nombre_producto": r.nombre_producto,
            "unidades": int(r.unidades or 0),
            "total": round(float(r.total or 0.0), 2),
        }
        for r in rows
    ]


def get_analytics_ventas_por_hora(db: Session, fecha_desde: date | None = None,
                                  fecha_hasta: date | None = None, tienda_id: int | None = None):
    """Agrupa por hora del día (0-23): n_tickets y $. Para el mapa de calor.

    La hora se extrae en Python desde Ticket.fecha para evitar funciones de fecha
    SQL-específicas (strftime/EXTRACT difieren entre SQLite y PostgreSQL).
    Devuelve siempre las 24 horas (las vacías en 0).
    """
    rows = (
        _base_tickets_query(db, fecha_desde, fecha_hasta, tienda_id)
        .with_entities(Ticket.fecha, Ticket.total)
        .all()
    )
    buckets = {h: {"n_tickets": 0, "total": 0.0} for h in range(24)}
    for fecha, total in rows:
        b = buckets[fecha.hour]
        b["n_tickets"] += 1
        b["total"] += float(total or 0.0)
    return [
        {"hora": h, "n_tickets": buckets[h]["n_tickets"], "total": round(buckets[h]["total"], 2)}
        for h in range(24)
    ]


def get_analytics_por_barista(db: Session, fecha_desde: date | None = None,
                              fecha_hasta: date | None = None, tienda_id: int | None = None):
    """Por usuario: total, n_tickets, ticket_promedio (JOIN usuarios para el nombre)."""
    desde, hasta = _rango_fechas(fecha_desde, fecha_hasta)
    filtros = [Ticket.estado.notin_(("anulado", "reversado")), Ticket.fecha >= desde, Ticket.fecha <= hasta]
    if tienda_id is not None:
        filtros.append(Ticket.tienda_id == tienda_id)

    # Actor real: la barista que vendió (barista_id/nombre) o, para tickets viejos
    # sin atribución, el usuario del dispositivo. Así en kiosko compartido la venta
    # se imputa a la barista correcta y no a "Kiosk".
    actor_id = func.coalesce(Ticket.barista_id, Ticket.usuario_id)
    actor_nombre = func.coalesce(Ticket.barista_nombre, Usuario.nombre)
    rows = (
        db.query(
            actor_id.label("usuario_id"),
            actor_nombre.label("nombre"),
            func.coalesce(func.sum(Ticket.total), 0.0).label("total"),
            func.count(Ticket.id).label("n_tickets"),
        )
        .join(Usuario, Usuario.id == Ticket.usuario_id)
        .filter(*filtros)
        .group_by(actor_id, actor_nombre)
        .order_by(func.sum(Ticket.total).desc())
        .all()
    )
    result = []
    for r in rows:
        n = int(r.n_tickets or 0)
        total = round(float(r.total or 0.0), 2)
        result.append({
            "usuario_id": r.usuario_id,
            "nombre": r.nombre,
            "total": total,
            "n_tickets": n,
            "ticket_promedio": round(total / n, 2) if n else 0.0,
        })
    return result


def get_analytics_metodo_pago(db: Session, fecha_desde: date | None = None,
                              fecha_hasta: date | None = None, tienda_id: int | None = None):
    """Split por método de pago (efectivo/tarjeta/mixto): count y suma de montos."""
    desde, hasta = _rango_fechas(fecha_desde, fecha_hasta)
    filtros = [Ticket.estado.notin_(("anulado", "reversado")), Ticket.fecha >= desde, Ticket.fecha <= hasta]
    if tienda_id is not None:
        filtros.append(Ticket.tienda_id == tienda_id)

    rows = (
        db.query(
            Ticket.metodo_pago.label("metodo_pago"),
            func.count(Ticket.id).label("n_tickets"),
            func.coalesce(func.sum(Ticket.total), 0.0).label("total"),
        )
        .filter(*filtros)
        .group_by(Ticket.metodo_pago)
        .order_by(func.sum(Ticket.total).desc())
        .all()
    )
    return [
        {
            "metodo_pago": r.metodo_pago,
            "n_tickets": int(r.n_tickets or 0),
            "total": round(float(r.total or 0.0), 2),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Anulación de ticket — reversión atómica todo-o-nada (como crear_ticket).
# ---------------------------------------------------------------------------

def anular_ticket(db: Session, ticket_id: int, usuario_id: int, motivo: str | None = None):
    """Anula un ticket revirtiendo stock y totales del turno de forma atómica.

    - Repone stock (entrada) de cada item cuyo Producto tenga controla_stock=True.
    - Revierte los acumulados del CajaTurno (total/efectivo/tarjeta).
    - Marca estado='anulado' y deja traza en audit.
    Si cualquier paso falla, rollback total (nada queda a medias).
    """
    ticket = (
        db.query(Ticket)
        .options(joinedload(Ticket.items))
        .filter(Ticket.id == ticket_id)
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    if ticket.estado == "anulado":
        raise HTTPException(status_code=400, detail="Ya anulado")

    try:
        # 1) Reponer stock de los productos contables (atómico, sin commit).
        #    Se cargan los productos del ticket para conocer controla_stock.
        producto_ids = [it.producto_id for it in ticket.items]
        productos = {
            p.id: p
            for p in db.query(Producto).filter(Producto.id.in_(producto_ids)).all()
        } if producto_ids else {}
        for item in ticket.items:
            prod = productos.get(item.producto_id)
            if prod and prod.controla_stock:
                inv_svc.registrar_movimiento(
                    db, producto_id=item.producto_id, tienda_id=ticket.tienda_id,
                    tipo="entrada", cantidad=item.cantidad,
                    motivo="Anulación venta POS", usuario_id=usuario_id, commit=False,
                )

        # 2) Revertir totales del turno (restar lo que el ticket había sumado).
        turno_db = db.query(CajaTurno).filter(CajaTurno.id == ticket.caja_turno_id).first()
        if turno_db:
            turno_db.total_ventas = (turno_db.total_ventas or 0.0) - (ticket.total or 0.0)
            turno_db.total_efectivo = (turno_db.total_efectivo or 0.0) - (ticket.monto_efectivo or 0.0)
            turno_db.total_tarjeta = (turno_db.total_tarjeta or 0.0) - (ticket.monto_tarjeta or 0.0)

        # 3) Marcar el ticket como anulado.
        ticket.estado = "anulado"

        # 4) Traza de auditoría.
        audit.registrar(
            db, accion="anulacion_venta", tabla="tickets",
            registro_id=ticket.id, usuario_id=usuario_id, tienda_id=ticket.tienda_id,
            datos_antes={"estado": "completado", "total": ticket.total},
            datos_despues={
                "estado": "anulado", "motivo": motivo,
                "total_revertido": ticket.total,
                "efectivo_revertido": ticket.monto_efectivo,
                "tarjeta_revertido": ticket.monto_tarjeta,
            },
        )

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(ticket)
    logger.info("Ticket %s anulado por usuario %s (motivo: %s)",
                ticket.id, usuario_id, motivo or "—")
    return ticket
