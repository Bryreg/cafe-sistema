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

from app.models.models import (
    Producto, ProductoInsumo, Ticket, TicketItem, CajaTurno, Usuario,
    Combo, ComboGrupo, ComboOpcion, ComboOpcionProducto, ComboTienda,
    TicketItemComboSeleccion,
)
from app.services.caja import get_turno_activo
from app.services import inventario as inv_svc, audit
from app.core.tz import (
    hoy_col, inicio_dia_col_utc, dia_col, hora_col, rango_col_utc,
)

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


def get_combos_pos(db: Session, tienda_id: int):
    """Combos activos disponibles en la tienda, con grupos, opciones y productos.

    Es el catálogo que el POS usa para pintar las pestañas de combos y el
    selector de opciones. Solo combos activos Y asociados a esa tienda.
    """
    combos = (
        db.query(Combo)
        .join(ComboTienda, ComboTienda.combo_id == Combo.id)
        .filter(Combo.activo == True, ComboTienda.tienda_id == tienda_id)  # noqa: E712
        .options(
            joinedload(Combo.grupos)
            .joinedload(ComboGrupo.opciones)
            .joinedload(ComboOpcion.productos)
            .joinedload(ComboOpcionProducto.producto)
        )
        .order_by(Combo.orden, Combo.nombre)
        .all()
    )
    return [
        {
            "id": c.id,
            "nombre": c.nombre,
            "precio_venta": c.precio_venta or 0.0,
            "orden": c.orden,
            "grupos": [
                {
                    "id": g.id,
                    "nombre": g.nombre,
                    "orden": g.orden,
                    "opciones": [
                        {
                            "id": o.id,
                            "nombre": o.nombre,
                            "orden": o.orden,
                            "productos": [
                                {
                                    "producto_id": op.producto_id,
                                    "nombre": op.producto.nombre if op.producto else "",
                                    "cantidad": int(op.cantidad or 1),
                                }
                                for op in o.productos
                            ],
                        }
                        for o in g.opciones
                    ],
                }
                for g in c.grupos
            ],
        }
        for c in combos
    ]


def _resolver_combos(db: Session, tienda_id: int, combos_req: list):
    """Valida y resuelve los combos del ticket CONTRA LA DB (nunca contra el cliente).

    Reglas:
      - Combo existente, activo y disponible en la tienda.
      - Exactamente UNA opción por grupo; la opción debe pertenecer al grupo.
      - Un grupo con UNA sola opción es fijo: se auto-selecciona si no viene.
      - El precio SIEMPRE es Combo.precio_venta del servidor.

    Devuelve por combo: cantidad, precio, subtotal, selecciones resueltas
    [(grupo, opcion, [(producto, cantidad_por_combo)])] y consumos de inventario
    [(producto, cantidad_total)].
    """
    resultado = []
    for c in combos_req:
        combo_id = c["combo_id"] if isinstance(c, dict) else c.combo_id
        cantidad = c["cantidad"] if isinstance(c, dict) else c.cantidad
        selecciones_req = (c.get("selecciones") if isinstance(c, dict)
                           else getattr(c, "selecciones", None)) or []
        if cantidad is None or int(cantidad) <= 0:
            raise HTTPException(status_code=400, detail="La cantidad del combo debe ser mayor a 0")
        cantidad = int(cantidad)

        combo = (
            db.query(Combo)
            .options(
                joinedload(Combo.grupos)
                .joinedload(ComboGrupo.opciones)
                .joinedload(ComboOpcion.productos)
                .joinedload(ComboOpcionProducto.producto)
            )
            .filter(Combo.id == combo_id)
            .first()
        )
        if not combo:
            raise HTTPException(status_code=404, detail=f"Combo {combo_id} no encontrado")
        if not combo.activo:
            raise HTTPException(status_code=400, detail=f"El combo '{combo.nombre}' no está activo")
        disponible = db.query(ComboTienda).filter(
            ComboTienda.combo_id == combo.id, ComboTienda.tienda_id == tienda_id
        ).first()
        if not disponible:
            raise HTTPException(
                status_code=400,
                detail=f"El combo '{combo.nombre}' no está disponible en esta tienda",
            )
        precio = float(combo.precio_venta or 0.0)
        if precio <= 0:
            raise HTTPException(
                status_code=400, detail=f"El combo '{combo.nombre}' no tiene precio de venta")
        # Sin grupos no hay componentes que elegir ni consumir: venderlo sería
        # cobrar el precio completo sin entregar (ni descontar) nada.
        if not combo.grupos:
            raise HTTPException(
                status_code=400,
                detail=f"El combo '{combo.nombre}' no tiene grupos de opciones configurados",
            )

        # Selección por grupo (a lo sumo una opción por grupo)
        sel_map: dict[int, int] = {}
        for s in selecciones_req:
            gid = s["grupo_id"] if isinstance(s, dict) else s.grupo_id
            oid = s["opcion_id"] if isinstance(s, dict) else s.opcion_id
            if gid in sel_map and sel_map[gid] != oid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Hay más de una opción seleccionada para un grupo del combo '{combo.nombre}'",
                )
            sel_map[gid] = oid
        grupos_ids = {g.id for g in combo.grupos}
        sobrantes = set(sel_map.keys()) - grupos_ids
        if sobrantes:
            raise HTTPException(
                status_code=400,
                detail=f"Una selección no corresponde a ningún grupo del combo '{combo.nombre}'",
            )

        selecciones = []
        consumos: list[tuple[Producto, float]] = []
        for g in combo.grupos:
            oid = sel_map.get(g.id)
            if oid is None:
                if len(g.opciones) == 1:
                    # Grupo fijo (una sola opción): auto-seleccionado
                    opcion = g.opciones[0]
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Falta elegir una opción del grupo '{g.nombre}' en el combo '{combo.nombre}'",
                    )
            else:
                opcion = next((o for o in g.opciones if o.id == oid), None)
                if not opcion:
                    raise HTTPException(
                        status_code=400,
                        detail=f"La opción elegida no pertenece al grupo '{g.nombre}' del combo '{combo.nombre}'",
                    )
            productos_op = [(op.producto, int(op.cantidad or 1)) for op in opcion.productos
                            if op.producto is not None]
            selecciones.append((g, opcion, productos_op))
            consumos.extend((p, cant * cantidad) for p, cant in productos_op)

        resultado.append({
            "combo": combo,
            "cantidad": cantidad,
            "precio": precio,
            "subtotal": round(precio * cantidad, 2),
            "selecciones": selecciones,
            "consumos": consumos,
        })
    return resultado


def crear_ticket(db: Session, tienda_id: int, usuario_id: int, items: list,
                 metodo_pago: str, efectivo_recibido: float | None = None,
                 monto_efectivo: float | None = None,
                 monto_tarjeta: float | None = None,
                 barista_id: int | None = None, barista_nombre: str | None = None,
                 combos: list | None = None):
    """Crea una venta itemizada. Atómico: si algo falla, no se persiste nada.

    `items`: lista de dicts/objetos con `producto_id` y `cantidad`.
    `combos`: lista de dicts/objetos con `combo_id`, `cantidad` y `selecciones`
    ([{grupo_id, opcion_id}]). El combo entra como UNA línea del ticket a su
    precio fijo (vía producto sombra); los componentes elegidos quedan en
    ticket_item_combo_selecciones y descuentan inventario/recetas igual que
    una venta normal — nunca como líneas con precio (no duplican ingresos).
    """
    combos = combos or []
    if metodo_pago not in METODOS_PAGO:
        raise HTTPException(status_code=400, detail="metodo_pago inválido")
    if not items and not combos:
        raise HTTPException(status_code=400, detail="El ticket no tiene items")
    items = items or []

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
    # El conteo de cierre pone el turno EN CIERRE y el POS deja de facturar (para
    # que el conteo registrado refleje el estado final). Si llega una venta de
    # último momento, NO es un callejón sin salida: un admin reabre el cierre
    # (Cuadres → "Reabrir cierre") y el POS vuelve a vender; el conteo real se
    # registra de nuevo al cerrar. El mensaje guía al remedio en vez de frenar en seco.
    if getattr(turno, "tiene_conteo_cierre", False):
        raise HTTPException(
            status_code=403,
            detail="El turno ya registró el conteo de cierre. ¿Llegó una venta de último momento? "
                   "Un administrador puede reabrir el cierre (Cuadres → Reabrir cierre) para volver a "
                   "facturar; después se registra de nuevo el conteo.",
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

    # Combos: validación estricta + precio SIEMPRE del servidor (Combo.precio_venta)
    lineas_combo = _resolver_combos(db, tienda_id, combos)
    for lc in lineas_combo:
        total += lc["subtotal"]

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

    # Líneas de combo: UNA línea por combo a su precio fijo (producto sombra,
    # snapshot de nombre/precio como los demás items) + registro de la
    # combinación elegida vinculado a esa línea (precio 0 implícito: los
    # componentes NO son líneas del ticket).
    for lc in lineas_combo:
        combo = lc["combo"]
        item_combo = TicketItem(
            ticket_id=ticket.id,
            producto_id=combo.producto_id,
            nombre_producto=combo.nombre,
            cantidad=lc["cantidad"],
            precio_unitario=lc["precio"],
            subtotal=lc["subtotal"],
            descuento=0,
        )
        db.add(item_combo)
        db.flush()  # obtener item_combo.id
        for grupo, opcion, productos_op in lc["selecciones"]:
            for prod_comp, cant_comp in productos_op:
                db.add(TicketItemComboSeleccion(
                    ticket_item_id=item_combo.id,
                    combo_id=combo.id,
                    grupo_id=grupo.id,
                    opcion_id=opcion.id,
                    nombre_grupo=grupo.nombre,
                    nombre_opcion=opcion.nombre,
                    producto_id=prod_comp.id,
                    cantidad=cant_comp,
                ))

    # Consumos de inventario: items normales + componentes de combos, con la
    # MISMA lógica (stock propio y recetas). Los componentes descuentan igual
    # que una venta individual del producto.
    consumos_brutos: list[tuple[Producto, float]] = [(p, c) for p, c, _, _, _ in lineas]
    for lc in lineas_combo:
        consumos_brutos.extend(lc["consumos"])
    # Fusionar por producto (misma semántica que la fusión de `pedidos`):
    # producto suelto + componente de combo (o dos combos) en el mismo ticket
    # generan UN solo movimiento de inventario con la cantidad sumada.
    consumos_map: dict[int, list] = {}
    for prod, cant in consumos_brutos:
        e = consumos_map.get(prod.id)
        if e is None:
            consumos_map[prod.id] = [prod, float(cant)]
        else:
            e[1] += float(cant)
    consumos: list[tuple[Producto, float]] = [(p, c) for p, c in consumos_map.values()]

    # Inventario: descuento atómico. Stock negativo permitido (allow_negative=True).
    # Si el producto no tiene registro en inventario, se omite sin bloquear la venta.
    for prod, cantidad in consumos:
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

    # Insumos por receta (producto_insumos): productos compuestos descuentan sus
    # ingredientes (ej. 1 waffle pandebono = 4 bolas de masa). SOLO movimiento de
    # inventario — nunca como item del ticket, para no contaminar ventas/analytics.
    prod_ids = list({p.id for p, _ in consumos})
    receta_rows = db.query(ProductoInsumo).filter(
        ProductoInsumo.producto_id.in_(prod_ids)
    ).all() if prod_ids else []
    insumos_por_prod: dict[int, list[ProductoInsumo]] = {}
    for r in receta_rows:
        insumos_por_prod.setdefault(r.producto_id, []).append(r)
    for prod, cantidad in consumos:
        # Fuga de inventario: producto vendido SIN receta y SIN stock propio no
        # descuenta nada. Avisar al admin (dedupe diario por producto) — la venta
        # sigue normal, la alerta alimenta el reporte de cobertura de recetas.
        if not prod.controla_stock and prod.id not in insumos_por_prod:
            try:
                from app.services import notificaciones
                notificaciones.evaluar_venta_sin_descuento(db, tienda_id, prod.id, prod.nombre)
            except Exception:  # noqa: BLE001 — una alerta nunca tumba la venta
                pass
        for r in insumos_por_prod.get(prod.id, []):
            try:
                # consumir_insumo aplica la cascada a sustituto (ej. leche entera →
                # deslactosada cuando la entera se agota).
                inv_svc.consumir_insumo(
                    db, producto_id=r.insumo_id, tienda_id=tienda_id,
                    cantidad=r.cantidad * cantidad,
                    motivo=f"Venta POS — insumo de {prod.nombre}",
                    usuario_id=usuario_id,
                )
            except HTTPException as e:
                if e.status_code == 404:
                    logger.warning(f"Insumo {r.insumo_id} sin inventario, venta procesada de todas formas")
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
            "combos": [
                {
                    "combo_id": lc["combo"].id,
                    "nombre": lc["combo"].nombre,
                    "cantidad": lc["cantidad"],
                    "subtotal": lc["subtotal"],
                    "selecciones": [f"{g.nombre}: {o.nombre}"
                                    for g, o, _ in lc["selecciones"]],
                }
                for lc in lineas_combo
            ],
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
        hoy = hoy_col()
        desde_hoy = inicio_dia_col_utc(hoy)
        manana = inicio_dia_col_utc(hoy + timedelta(days=1))
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
        .options(joinedload(Ticket.items).joinedload(TicketItem.combo_selecciones))
        .filter(Ticket.id == ticket_id)
        .first()
    )


def get_tickets_turno(db: Session, turno_id: int):
    return (
        db.query(Ticket)
        .options(joinedload(Ticket.items).joinedload(TicketItem.combo_selecciones))
        .filter(Ticket.caja_turno_id == turno_id)
        .order_by(Ticket.fecha.desc())
        .all()
    )


def get_tickets_recientes(db: Session, tienda_id: int, dias: int = 7, limit: int = 50):
    """Tickets recientes de la tienda — para revertir (Nota Crédito) desde el panel admin."""
    desde = datetime.utcnow() - timedelta(days=dias)
    return (
        db.query(Ticket)
        .options(joinedload(Ticket.items).joinedload(TicketItem.combo_selecciones))
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
        .options(joinedload(Ticket.items).joinedload(TicketItem.combo_selecciones))
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
    """Normaliza el rango a UTC cubriendo días Colombia. Default = hoy Colombia.

    Los tickets se guardan en UTC pero el negocio opera en Colombia (UTC-5). El
    rango devuelto en UTC corresponde a los días calendario Colombia pedidos,
    compatible con SQLite y PostgreSQL sin funciones de fecha SQL-específicas.
    """
    return rango_col_utc(fecha_desde, fecha_hasta)


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
        d = dia_col(fecha).isoformat()
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
    # Los tickets se guardan en UTC, pero el negocio opera en Colombia (UTC-5, sin
    # horario de verano). Sin este ajuste, una venta de la mañana aparece 5 horas
    # más tarde (p. ej. 9am -> 2pm). hora_col() centraliza esa conversión.
    buckets = {h: {"n_tickets": 0, "total": 0.0} for h in range(24)}
    for fecha, total in rows:
        b = buckets[hora_col(fecha)]
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

def revertir_consumos(db: Session, consumos: list[tuple[int, float]], tienda_id: int,
                      usuario_id: int, motivo: str):
    """Repone lo CONSUMIDO por una venta — espejo del descuento de crear_ticket.

    `consumos`: [(producto_id, cantidad_total)] — items normales o componentes
    de combo. Los productos con controla_stock reponen su stock; los que tienen
    receta (ProductoInsumo) reponen sus insumos. Sin fila de inventario se omite
    (la venta tampoco descontó nada). No commitea: el caller cierra la transacción.
    Lo usan anular_ticket y la Nota Crédito (componentes de combo no usados).
    """
    producto_ids = list({pid for pid, _ in consumos})
    productos = {
        p.id: p
        for p in db.query(Producto).filter(Producto.id.in_(producto_ids)).all()
    } if producto_ids else {}
    for pid, cant in consumos:
        prod = productos.get(pid)
        if prod and prod.controla_stock:
            try:
                inv_svc.registrar_movimiento(
                    db, producto_id=pid, tienda_id=tienda_id,
                    tipo="entrada", cantidad=cant,
                    motivo=motivo, usuario_id=usuario_id, commit=False,
                )
            except HTTPException as e:
                # Espejo de crear_ticket: sin fila de inventario la venta no
                # descontó nada — al revertir tampoco hay nada que reponer.
                if e.status_code == 404:
                    logger.warning(f"Producto {pid} sin inventario al reponer; se omite")
                else:
                    raise

    # Insumos consumidos por receta (producto_insumos) — espejo del descuento
    # de crear_ticket. Si el insumo no tiene inventario, se omite.
    receta_rows = db.query(ProductoInsumo).filter(
        ProductoInsumo.producto_id.in_(producto_ids)
    ).all() if producto_ids else []
    insumos_por_prod: dict[int, list[ProductoInsumo]] = {}
    for r in receta_rows:
        insumos_por_prod.setdefault(r.producto_id, []).append(r)
    for pid, cant in consumos:
        for r in insumos_por_prod.get(pid, []):
            try:
                inv_svc.registrar_movimiento(
                    db, producto_id=r.insumo_id, tienda_id=tienda_id,
                    tipo="entrada", cantidad=r.cantidad * cant,
                    motivo=f"{motivo} — insumo", usuario_id=usuario_id, commit=False,
                )
            except HTTPException as e:
                if e.status_code == 404:
                    logger.warning(f"Insumo {r.insumo_id} sin inventario al reponer; se omite")
                else:
                    raise


def consumos_de_items(db: Session, items) -> list[tuple[int, float]]:
    """(producto_id, cantidad_total) realmente consumidos por líneas de ticket.

    Los items normales consumen su producto; las líneas de combo consumen sus
    COMPONENTES elegidos (la línea apunta al producto sombra, que no controla
    stock). La cantidad de la selección es POR combo → total = cantidad ×
    item.cantidad.
    """
    item_ids = [it.id for it in items]
    sel_rows = db.query(TicketItemComboSeleccion).filter(
        TicketItemComboSeleccion.ticket_item_id.in_(item_ids)
    ).all() if item_ids else []
    sel_por_item: dict[int, list[TicketItemComboSeleccion]] = {}
    for s in sel_rows:
        sel_por_item.setdefault(s.ticket_item_id, []).append(s)
    consumos: list[tuple[int, float]] = []
    for item in items:
        sels = sel_por_item.get(item.id)
        if sels:
            consumos.extend(
                (s.producto_id, (s.cantidad or 1) * item.cantidad) for s in sels)
        else:
            consumos.append((item.producto_id, item.cantidad))
    return consumos


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
    # Solo tickets del turno ABIERTO: anular tras el cierre (o tras un conteo posterior)
    # repondría stock que el conteo ya fijó y corrompería totales de un turno cerrado.
    turno_ticket = db.query(CajaTurno).filter(CajaTurno.id == ticket.caja_turno_id).first()
    estado_turno = getattr(turno_ticket.estado, "value", turno_ticket.estado) if turno_ticket else None
    if estado_turno != "abierto":
        raise HTTPException(
            status_code=400,
            detail="Solo se puede anular un ticket del turno abierto — este turno ya cerró y su cuadre e inventario quedaron fijados.",
        )
    if getattr(turno_ticket, "tiene_conteo_cierre", False):
        raise HTTPException(
            status_code=400,
            detail="El conteo de cierre ya fue registrado — no se pueden anular ventas de un turno en cierre.",
        )

    try:
        # 1) Reponer stock e insumos de lo realmente consumido (atómico, sin
        #    commit): items normales + componentes de combos.
        consumos_revertir = consumos_de_items(db, ticket.items)
        revertir_consumos(db, consumos_revertir, ticket.tienda_id, usuario_id,
                          motivo="Anulación venta POS")

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
