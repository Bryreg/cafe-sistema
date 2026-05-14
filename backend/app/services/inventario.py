from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import Inventario, MovimientoInventario, LoteInventario, Producto
from datetime import datetime
from app.services import audit


def get_inventario_tienda(db: Session, tienda_id: int):
    items = db.query(Inventario).filter(Inventario.tienda_id == tienda_id).all()
    result = []
    for item in items:
        result.append({
            "id": item.id,
            "producto_id": item.producto_id,
            "tienda_id": item.tienda_id,
            "stock_actual": round(item.stock_actual),
            "stock_minimo": round(item.stock_minimo),
            "producto_nombre": item.producto.nombre,
            "categoria": item.producto.categoria.value,
            "unidad_medida": item.producto.unidad_medida,
            "alerta": item.stock_actual <= item.stock_minimo,
        })
    return result


def registrar_movimiento(db: Session, producto_id: int, tienda_id: int, tipo: str,
                          cantidad: float, motivo: str | None, usuario_id: int,
                          fecha_vencimiento: datetime | None = None, commit: bool = True):
    if tipo not in {"entrada", "salida", "ajuste"}:
        raise HTTPException(status_code=400, detail="tipo debe ser entrada, salida o ajuste")
    if tipo in {"entrada", "salida"} and cantidad <= 0:
        raise HTTPException(status_code=400, detail="cantidad debe ser mayor a 0")
    if tipo == "ajuste" and cantidad < 0:
        raise HTTPException(status_code=400, detail="cantidad no puede ser negativa en ajuste")
    inv = db.query(Inventario).filter(
        Inventario.producto_id == producto_id,
        Inventario.tienda_id == tienda_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario de esta tienda")

    if tipo == "entrada":
        inv.stock_actual += cantidad
        agregar_lote(db, producto_id, tienda_id, cantidad, usuario_id, fecha_vencimiento)
    elif tipo == "salida":
        if inv.stock_actual - cantidad < 0:
            raise HTTPException(status_code=400, detail="Stock insuficiente")
        inv.stock_actual -= cantidad
        consumir_fifo(db, producto_id, tienda_id, cantidad)
    elif tipo == "ajuste":
        # Etapa 2: sincronizar lotes FIFO al ajustar stock
        diferencia = cantidad - inv.stock_actual
        inv.stock_actual = cantidad
        if diferencia > 0:
            # Stock aumentó → lote de ajuste positivo
            agregar_lote(db, producto_id, tienda_id, diferencia, usuario_id)
        elif diferencia < 0:
            # Stock disminuyó → consumir diferencia de lotes más antiguos
            consumir_fifo(db, producto_id, tienda_id, abs(diferencia))

    mov = MovimientoInventario(
        producto_id=producto_id, tienda_id=tienda_id, tipo=tipo,
        cantidad=cantidad, usuario_id=usuario_id, motivo=motivo
    )
    db.add(mov)

    _tick_checklist_inventario(db, tienda_id)
    audit.registrar(
        db, accion=f"inventario_{tipo}", tabla="movimientos_inventario",
        registro_id=None, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"producto_id": producto_id, "tipo": tipo,
                       "cantidad": cantidad, "motivo": motivo,
                       "stock_resultante": inv.stock_actual},
    )
    if commit:
        db.commit()
        db.refresh(inv)
    return inv


def agregar_lote(db: Session, producto_id: int, tienda_id: int,
                 cantidad: float, usuario_id: int,
                 fecha_vencimiento: datetime | None = None):
    """Crea un lote FIFO. NO hace commit — debe estar dentro de una transacción."""
    lote = LoteInventario(
        producto_id=producto_id,
        tienda_id=tienda_id,
        cantidad_inicial=cantidad,
        cantidad_restante=cantidad,
        usuario_id=usuario_id,
        fecha_vencimiento=fecha_vencimiento,
    )
    db.add(lote)


def consumir_fifo(db: Session, producto_id: int, tienda_id: int, cantidad: float):
    """Descuenta cantidad de los lotes más antiguos (FIFO). NO hace commit."""
    lotes = db.query(LoteInventario).filter(
        LoteInventario.producto_id == producto_id,
        LoteInventario.tienda_id == tienda_id,
        LoteInventario.cantidad_restante > 0,
    ).order_by(LoteInventario.fecha_entrada.asc()).all()

    restante = cantidad
    for lote in lotes:
        if restante <= 0:
            break
        consumido = min(lote.cantidad_restante, restante)
        lote.cantidad_restante -= consumido
        restante -= consumido
    # Si restante > 0, los lotes no cubren (stock registrado antes del FIFO).
    # Se ignora silenciosamente para no bloquear operaciones.


def get_lotes(db: Session, tienda_id: int, producto_id: int):
    """Lotes FIFO activos (con stock) de un producto. Solo para admin."""
    return db.query(LoteInventario).filter(
        LoteInventario.tienda_id == tienda_id,
        LoteInventario.producto_id == producto_id,
    ).order_by(LoteInventario.fecha_entrada.asc()).all()


def get_alertas(db: Session, tienda_id: int):
    items = db.query(Inventario).filter(
        Inventario.tienda_id == tienda_id,
        Inventario.stock_actual <= Inventario.stock_minimo
    ).all()
    return [{
        "producto_id": i.producto_id,
        "producto": i.producto.nombre,
        "unidad": i.producto.unidad_medida,
        "stock_actual": round(i.stock_actual),
        "stock_minimo": round(i.stock_minimo),
        "cantidad_sugerida": max(1, round(i.stock_minimo - i.stock_actual + i.stock_minimo)),
        "nivel": "agotado" if i.stock_actual <= 0 else "bajo",
    } for i in items]


def _tick_checklist_inventario(db: Session, tienda_id: int):
    from app.services.caja import _tick_checklist
    _tick_checklist(db, tienda_id, inventario_check=True)
