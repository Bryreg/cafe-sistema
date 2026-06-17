"""POS nativo — reemplazo de Siigo para ventas, precios y descuento de inventario.

Construcción aditiva: no toca el código Siigo (queda dormido).
Reglas de negocio:
  - Solo se descuenta inventario de productos con controla_stock=True.
  - El precio SIEMPRE se calcula en el servidor desde la DB; nunca se confía
    en un precio enviado por el cliente.
  - La venta es todo-o-nada: si falta stock de un producto contable, se aborta.
"""
import logging
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException

from app.models.models import Producto, Ticket, TicketItem, CajaTurno
from app.services.caja import get_turno_activo
from app.services import inventario as inv_svc, audit

logger = logging.getLogger(__name__)

METODOS_PAGO = {"efectivo", "tarjeta", "mixto"}


def get_productos_pos(db: Session, categoria: str | None = None):
    """Productos vendibles (precio_venta > 0), opcionalmente por categoría."""
    q = db.query(Producto).filter(Producto.precio_venta > 0)
    if categoria:
        q = q.filter(Producto.categoria == categoria)
    productos = q.order_by(Producto.categoria, Producto.nombre).all()
    return [
        {
            "id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "precio_venta": p.precio_venta or 0.0,
            "controla_stock": p.controla_stock,
            "unidad_medida": p.unidad_medida,
        }
        for p in productos
    ]


def crear_ticket(db: Session, tienda_id: int, usuario_id: int, items: list,
                 metodo_pago: str, efectivo_recibido: float | None = None,
                 monto_efectivo: float | None = None,
                 monto_tarjeta: float | None = None):
    """Crea una venta itemizada. Atómico: si algo falla, no se persiste nada.

    `items`: lista de dicts/objetos con `producto_id` y `cantidad`.
    """
    if metodo_pago not in METODOS_PAGO:
        raise HTTPException(status_code=400, detail="metodo_pago inválido")
    if not items:
        raise HTTPException(status_code=400, detail="El ticket no tiene items")

    # Turno activo + flujo obligatorio
    turno = get_turno_activo(db, tienda_id)
    if not turno:
        raise HTTPException(status_code=400, detail="No hay turno abierto")
    if not turno.tiene_conteo_apertura:
        raise HTTPException(status_code=400, detail="Debes completar el conteo de apertura antes de vender")

    # Normalizar items y agregar cantidades por producto (evita líneas duplicadas)
    pedidos: dict[int, int] = {}
    for it in items:
        producto_id = it["producto_id"] if isinstance(it, dict) else it.producto_id
        cantidad = it["cantidad"] if isinstance(it, dict) else it.cantidad
        if cantidad is None or cantidad <= 0:
            raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")
        pedidos[producto_id] = pedidos.get(producto_id, 0) + int(cantidad)

    # Calcular precios EN EL SERVIDOR
    productos = {
        p.id: p for p in db.query(Producto).filter(Producto.id.in_(pedidos.keys())).all()
    }
    lineas = []
    total = 0.0
    for producto_id, cantidad in pedidos.items():
        prod = productos.get(producto_id)
        if not prod:
            raise HTTPException(status_code=404, detail=f"Producto {producto_id} no encontrado")
        precio = prod.precio_venta or 0.0
        if precio <= 0:
            raise HTTPException(status_code=400, detail=f"El producto '{prod.nombre}' no tiene precio de venta")
        subtotal = round(precio * cantidad, 2)
        total += subtotal
        lineas.append((prod, cantidad, precio, subtotal))
    total = round(total, 2)

    # Resolver montos por método de pago
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
        metodo_pago=metodo_pago,
        monto_efectivo=monto_efectivo_final,
        monto_tarjeta=monto_tarjeta_final,
        efectivo_recibido=efectivo_recibido,
        cambio=cambio,
        estado="completado",
    )
    db.add(ticket)
    db.flush()  # obtener ticket.id

    for prod, cantidad, precio, subtotal in lineas:
        db.add(TicketItem(
            ticket_id=ticket.id,
            producto_id=prod.id,
            nombre_producto=prod.nombre,
            cantidad=cantidad,
            precio_unitario=precio,
            subtotal=subtotal,
        ))

    # Inventario: descuento atómico solo para productos contables.
    # registrar_movimiento(commit=False) lanza HTTPException(400) si falta stock;
    # eso aborta toda la transacción → venta todo-o-nada.
    try:
        for prod, cantidad, _, _ in lineas:
            if prod.controla_stock:
                inv_svc.registrar_movimiento(
                    db, producto_id=prod.id, tienda_id=tienda_id,
                    tipo="salida", cantidad=cantidad, motivo="Venta POS",
                    usuario_id=usuario_id, commit=False,
                )
    except HTTPException as e:
        db.rollback()
        if e.status_code == 400 and "insuficiente" in (e.detail or "").lower():
            raise HTTPException(status_code=400, detail="Stock insuficiente para completar la venta")
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
                      for p, c, _, s in lineas],
        },
    )

    db.commit()
    db.refresh(ticket)
    logger.info("Ticket %s creado en tienda %s por usuario %s (total %.2f)",
                ticket.id, tienda_id, usuario_id, total)
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
