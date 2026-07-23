"""Nota Crédito — reversión de venta (acción del admin).

Conecta contabilidad con inventario:
  - Devuelve la plata SIEMPRE (revierte los totales del turno).
  - El inventario solo recupera los productos marcados como NO usados.
Ej: el Latte ya hecho (se usó la leche) queda descontado; el Croissant intacto vuelve.
"""
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
from app.models.models import (
    Ticket, NotaCredito, NotaCreditoItem, Producto, CajaTurno, Inventario,
    TicketItemComboSeleccion,
)
from app.services import inventario as inv_svc, audit
from app.services import pos as pos_svc
import logging

logger = logging.getLogger(__name__)


def revertir_venta(db: Session, ticket_id: int, usuario_admin_id: int,
                   motivo: str, items_usado: dict[int, bool],
                   usado_por_producto: dict[int, bool] | None = None):
    """items_usado: {ticket_item_id: producto_usado} — por LÍNEA del ticket, para
    que dos líneas del mismo combo (mismo producto sombra) se marquen
    independiente. `usado_por_producto` es el formato viejo {producto_id: usado}
    por compatibilidad de payload. Default usado=True (no devuelve stock)."""
    usado_por_producto = usado_por_producto or {}
    if not motivo or not motivo.strip():
        raise HTTPException(status_code=400, detail="El motivo es obligatorio")
    ticket = (
        db.query(Ticket).options(joinedload(Ticket.items))
        .filter(Ticket.id == ticket_id).first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    if ticket.estado in ("anulado", "reversado"):
        raise HTTPException(status_code=400, detail="El ticket ya fue revertido o anulado")

    turno = db.query(CajaTurno).filter(CajaTurno.id == ticket.caja_turno_id).first()
    try:
        nota = NotaCredito(
            ticket_id=ticket.id, tienda_id=ticket.tienda_id,
            dia_operativo_id=(turno.dia_operativo_id if turno else None),
            turno_id=ticket.caja_turno_id, usuario_admin_id=usuario_admin_id,
            motivo=motivo.strip(), valor_revertido=ticket.total or 0.0,
        )
        db.add(nota)
        db.flush()

        producto_ids = [it.producto_id for it in ticket.items]
        productos = {
            p.id: p for p in db.query(Producto).filter(Producto.id.in_(producto_ids)).all()
        } if producto_ids else {}

        # Selecciones de combo por línea: una línea de combo apunta al producto
        # SOMBRA (controla_stock=False) — lo que vuelve al inventario son sus
        # COMPONENTES elegidos (stock propio + recetas), no el sombra.
        item_ids = [it.id for it in ticket.items]
        sel_rows = db.query(TicketItemComboSeleccion).filter(
            TicketItemComboSeleccion.ticket_item_id.in_(item_ids)
        ).all() if item_ids else []
        sel_por_item: dict[int, list[TicketItemComboSeleccion]] = {}
        for s in sel_rows:
            sel_por_item.setdefault(s.ticket_item_id, []).append(s)

        usado_por_linea = {
            it.id: items_usado.get(it.id, usado_por_producto.get(it.producto_id, True))
            for it in ticket.items
        }
        consumos_combo: list[tuple[int, float]] = []
        for it in ticket.items:
            usado = usado_por_linea[it.id]
            db.add(NotaCreditoItem(
                nota_credito_id=nota.id, producto_id=it.producto_id,
                cantidad=it.cantidad, producto_usado=usado,
            ))
            if usado:
                continue
            sels = sel_por_item.get(it.id)
            if sels:
                # Línea de combo NO usada: reponer los consumos reales de sus
                # componentes (mismo espejo que anular_ticket, más abajo).
                consumos_combo.extend(
                    (s.producto_id, (s.cantidad or 1) * it.cantidad) for s in sels)
                continue
            prod = productos.get(it.producto_id)
            if prod and prod.controla_stock:
                # No usado → vuelve al inventario (entrada). Asegurar fila de inventario.
                inv = db.query(Inventario).filter(
                    Inventario.producto_id == it.producto_id, Inventario.tienda_id == ticket.tienda_id
                ).first()
                if not inv:
                    inv = Inventario(producto_id=it.producto_id, tienda_id=ticket.tienda_id,
                                     stock_actual=0.0, stock_minimo=0.0)
                    db.add(inv)
                    db.flush()
                inv_svc.registrar_movimiento(
                    db, producto_id=it.producto_id, tienda_id=ticket.tienda_id, tipo="entrada",
                    cantidad=it.cantidad, motivo=f"Nota crédito ticket #{ticket.id}",
                    usuario_id=usuario_admin_id, commit=False,
                )
        if consumos_combo:
            # Espejo de anular_ticket: componentes con controla_stock reponen su
            # stock; componentes con receta reponen insumos; 404 de inventario
            # se tolera (la venta tampoco descontó nada).
            pos_svc.revertir_consumos(
                db, consumos_combo, ticket.tienda_id, usuario_admin_id,
                motivo=f"Nota crédito ticket #{ticket.id}",
            )

        # Revertir totales del turno (la venta deja de contar; si fue efectivo, baja el esperado de caja)
        if turno:
            turno.total_ventas = (turno.total_ventas or 0.0) - (ticket.total or 0.0)
            turno.total_efectivo = (turno.total_efectivo or 0.0) - (ticket.monto_efectivo or 0.0)
            turno.total_tarjeta = (turno.total_tarjeta or 0.0) - (ticket.monto_tarjeta or 0.0)

        ticket.estado = "reversado"
        audit.registrar(
            db, accion="nota_credito", tabla="tickets", registro_id=ticket.id,
            usuario_id=usuario_admin_id, tienda_id=ticket.tienda_id,
            datos_antes={"estado": "completado", "total": ticket.total},
            datos_despues={
                "estado": "reversado", "motivo": motivo,
                "items": [{"item_id": it.id, "producto_id": it.producto_id,
                           "usado": usado_por_linea[it.id]} for it in ticket.items],
            },
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(nota)
    logger.info("Nota crédito %s sobre ticket %s (admin %s)", nota.id, ticket.id, usuario_admin_id)
    return nota


def listar(db: Session, tienda_id: int, limit: int = 50):
    return (
        db.query(NotaCredito).filter(NotaCredito.tienda_id == tienda_id)
        .order_by(NotaCredito.fecha.desc()).limit(limit).all()
    )
