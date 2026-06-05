from sqlalchemy.orm import Session
from sqlalchemy import update as sa_update
from fastapi import HTTPException
from datetime import datetime
from app.models.models import Merma, Inventario, MovimientoInventario, TipoMovInvEnum, Tienda
from app.services.inventario import consumir_fifo
from app.services import audit
import logging

logger = logging.getLogger(__name__)

TIPOS_VALIDOS = {"consumo", "traslado", "daño"}


def registrar_merma(db: Session, tienda_id: int, producto_id: int,
                    cantidad: float, motivo: str, usuario_id: int,
                    tipo: str = "consumo", tienda_destino_id: int | None = None):

    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"Tipo inválido. Usa: {', '.join(TIPOS_VALIDOS)}")

    if tipo == "traslado":
        if not tienda_destino_id:
            raise HTTPException(400, "Debes indicar la sede destino para un traslado")
        if tienda_destino_id == tienda_id:
            raise HTTPException(400, "La sede destino debe ser diferente a la sede origen")
        if not db.query(Tienda).filter_by(id=tienda_destino_id).first():
            raise HTTPException(404, "Sede destino no encontrada")

    # Verify product exists and check stock before attempting atomic update
    inv = db.query(Inventario).filter(
        Inventario.producto_id == producto_id,
        Inventario.tienda_id == tienda_id,
    ).first()
    if not inv:
        raise HTTPException(404, "Producto no encontrado en inventario")

    merma = Merma(
        tienda_id=tienda_id,
        producto_id=producto_id,
        cantidad=cantidad,
        motivo=motivo,
        tipo=tipo,
        tienda_destino_id=tienda_destino_id if tipo == "traslado" else None,
        recibido=False,
        usuario_id=usuario_id,
    )
    db.add(merma)

    mov_motivo = {
        "consumo":  f"Consumo: {motivo}",
        "daño":     f"Daño: {motivo}",
        "traslado": f"Traslado a tienda {tienda_destino_id}: {motivo}",
    }[tipo]

    mov = MovimientoInventario(
        producto_id=producto_id,
        tienda_id=tienda_id,
        tipo=TipoMovInvEnum.salida,
        cantidad=cantidad,
        usuario_id=usuario_id,
        motivo=mov_motivo,
    )
    db.add(mov)

    # Atomic decrement with stock sufficiency check
    rows = db.execute(
        sa_update(Inventario)
        .where(
            Inventario.producto_id == producto_id,
            Inventario.tienda_id == tienda_id,
            Inventario.stock_actual >= cantidad,
        )
        .values(stock_actual=Inventario.stock_actual - cantidad)
    ).rowcount
    if rows == 0:
        raise HTTPException(400, f"Stock insuficiente.")
    consumir_fifo(db, producto_id, tienda_id, cantidad)

    audit.registrar(
        db, accion="registro_merma", tabla="mermas",
        registro_id=None, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"producto_id": producto_id, "cantidad": cantidad,
                       "motivo": motivo, "tipo": tipo,
                       "tienda_destino_id": tienda_destino_id},
    )
    db.commit()
    db.refresh(merma)
    logger.info(f"Merma [{tipo}] registrada: {cantidad} de producto {producto_id} en tienda {tienda_id}")
    return merma


def recibir_traslado(db: Session, merma_id: int, tienda_destino_id: int, usuario_id: int):
    merma = db.query(Merma).filter(
        Merma.id == merma_id,
        Merma.tipo == "traslado",
        Merma.tienda_destino_id == tienda_destino_id,
        Merma.recibido == False,
    ).first()
    if not merma:
        raise HTTPException(404, "Traslado no encontrado o ya confirmado")

    # Ingresar al inventario de la sede destino — atomic increment
    inv = db.query(Inventario).filter(
        Inventario.producto_id == merma.producto_id,
        Inventario.tienda_id == tienda_destino_id,
    ).first()
    if inv:
        db.execute(
            sa_update(Inventario)
            .where(
                Inventario.producto_id == merma.producto_id,
                Inventario.tienda_id == tienda_destino_id,
            )
            .values(stock_actual=Inventario.stock_actual + merma.cantidad)
        )
    else:
        inv = Inventario(
            producto_id=merma.producto_id,
            tienda_id=tienda_destino_id,
            stock_actual=merma.cantidad,
        )
        db.add(inv)

    mov = MovimientoInventario(
        producto_id=merma.producto_id,
        tienda_id=tienda_destino_id,
        tipo=TipoMovInvEnum.entrada,
        cantidad=merma.cantidad,
        usuario_id=usuario_id,
        motivo=f"Recibo traslado desde tienda {merma.tienda_id}",
    )
    db.add(mov)

    merma.recibido = True
    merma.fecha_recibido = datetime.utcnow()
    db.commit()
    db.refresh(merma)
    return merma


def get_mermas_tienda(db: Session, tienda_id: int):
    return (
        db.query(Merma)
        .filter(Merma.tienda_id == tienda_id)
        .order_by(Merma.fecha_registro.desc())
        .limit(50)
        .all()
    )


def get_traslados_pendientes(db: Session, tienda_id: int):
    """Traslados enviados hacia esta tienda aún no confirmados."""
    return (
        db.query(Merma)
        .filter(
            Merma.tipo == "traslado",
            Merma.tienda_destino_id == tienda_id,
            Merma.recibido == False,
        )
        .order_by(Merma.fecha_registro.desc())
        .all()
    )
