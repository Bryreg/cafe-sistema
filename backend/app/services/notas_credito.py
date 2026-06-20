"""Nota Crédito — reversión de venta (acción del admin).

Conecta contabilidad con inventario:
  - Devuelve la plata SIEMPRE (revierte los totales del turno).
  - El inventario solo recupera los productos marcados como NO usados.
Ej: el Latte ya hecho (se usó la leche) queda descontado; el Croissant intacto vuelve.
"""
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
from app.models.models import Ticket, NotaCredito, NotaCreditoItem, Producto, CajaTurno, Inventario
from app.services import inventario as inv_svc, audit
import logging

logger = logging.getLogger(__name__)


def revertir_venta(db: Session, ticket_id: int, usuario_admin_id: int,
                   motivo: str, items_usado: dict[int, bool]):
    """items_usado: {producto_id: producto_usado}. Default usado=True (no devuelve stock)."""
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

        for it in ticket.items:
            usado = items_usado.get(it.producto_id, True)
            db.add(NotaCreditoItem(
                nota_credito_id=nota.id, producto_id=it.producto_id,
                cantidad=it.cantidad, producto_usado=usado,
            ))
            prod = productos.get(it.producto_id)
            if prod and prod.controla_stock and not usado:
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
                "items": [{"producto_id": pid, "usado": items_usado.get(pid, True)} for pid in producto_ids],
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
