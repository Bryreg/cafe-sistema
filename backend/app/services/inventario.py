from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import Inventario, MovimientoInventario, LoteInventario, Producto, Tienda, TipoMovInvEnum
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
            "stock_actual": item.stock_actual,
            "stock_minimo": item.stock_minimo,
            "producto_nombre": item.producto.nombre,
            "categoria": item.producto.categoria.value,
            "unidad_medida": item.producto.unidad_medida,
            "alerta": item.stock_actual <= item.stock_minimo,
        })
    return result


def registrar_movimiento(db: Session, producto_id: int, tienda_id: int, tipo: str,
                          cantidad: float, motivo: str | None, usuario_id: int,
                          fecha_vencimiento: datetime | None = None):
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
        "stock_actual": i.stock_actual,
        "stock_minimo": i.stock_minimo,
        "cantidad_sugerida": max(1, round(i.stock_minimo - i.stock_actual + i.stock_minimo)),
        "nivel": "agotado" if i.stock_actual <= 0 else "bajo",
    } for i in items]


def registrar_traslado(db: Session, producto_id: int, tienda_origen_id: int,
                       tienda_destino_id: int, cantidad: float, motivo: str | None,
                       usuario_id: int):
    """Traslada stock de una sede a otra en una sola transacción."""
    if tienda_origen_id == tienda_destino_id:
        raise HTTPException(400, "Las sedes deben ser distintas")
    if cantidad <= 0:
        raise HTTPException(400, "La cantidad debe ser mayor a 0")

    origen  = db.query(Tienda).filter_by(id=tienda_origen_id).first()
    destino = db.query(Tienda).filter_by(id=tienda_destino_id).first()
    if not origen or not destino:
        raise HTTPException(404, "Sede no encontrada")

    inv_origen  = db.query(Inventario).filter_by(producto_id=producto_id, tienda_id=tienda_origen_id).first()
    inv_destino = db.query(Inventario).filter_by(producto_id=producto_id, tienda_id=tienda_destino_id).first()
    if not inv_origen:
        raise HTTPException(404, "Producto no encontrado en la sede origen")
    if not inv_destino:
        raise HTTPException(404, "Producto no encontrado en la sede destino")
    if inv_origen.stock_actual < cantidad:
        raise HTTPException(400, f"Stock insuficiente en {origen.nombre}: hay {inv_origen.stock_actual} disponibles")

    nota = f" | {motivo}" if motivo else ""

    # ── Salida de origen ──────────────────────────────────────────────────────
    inv_origen.stock_actual -= cantidad
    consumir_fifo(db, producto_id, tienda_origen_id, cantidad)
    db.add(MovimientoInventario(
        producto_id=producto_id, tienda_id=tienda_origen_id,
        tipo=TipoMovInvEnum.salida, cantidad=cantidad, usuario_id=usuario_id,
        motivo=f"Traslado → {destino.nombre}{nota}",
    ))

    # ── Entrada a destino ─────────────────────────────────────────────────────
    inv_destino.stock_actual += cantidad
    agregar_lote(db, producto_id, tienda_destino_id, cantidad, usuario_id)
    db.add(MovimientoInventario(
        producto_id=producto_id, tienda_id=tienda_destino_id,
        tipo=TipoMovInvEnum.entrada, cantidad=cantidad, usuario_id=usuario_id,
        motivo=f"Traslado ← {origen.nombre}{nota}",
    ))

    audit.registrar(
        db, accion="inventario_traslado", tabla="movimientos_inventario",
        registro_id=None, usuario_id=usuario_id, tienda_id=tienda_origen_id,
        datos_despues={"producto_id": producto_id, "cantidad": cantidad,
                       "origen": origen.nombre, "destino": destino.nombre},
    )
    db.commit()

    return {
        "ok": True,
        "producto_id": producto_id,
        "cantidad": cantidad,
        "origen": origen.nombre,
        "destino": destino.nombre,
        "stock_origen": inv_origen.stock_actual,
        "stock_destino": inv_destino.stock_actual,
    }


def get_traslados(db: Session, limit: int = 40):
    """Traslados recientes — lee los movimientos de salida marcados como traslado."""
    movs = (
        db.query(MovimientoInventario)
        .filter(MovimientoInventario.motivo.like("Traslado →%"))
        .order_by(MovimientoInventario.fecha.desc())
        .limit(limit)
        .all()
    )
    result = []
    for m in movs:
        partes = m.motivo.split("→", 1)[1].split("|", 1)
        destino = partes[0].strip()
        nota    = partes[1].strip() if len(partes) > 1 else None
        result.append({
            "id": m.id,
            "fecha": m.fecha.isoformat(),
            "producto_id": m.producto_id,
            "producto_nombre": m.producto.nombre,
            "unidad_medida": m.producto.unidad_medida,
            "cantidad": m.cantidad,
            "origen": m.tienda.nombre,
            "destino": destino,
            "nota": nota,
            "usuario": m.usuario.nombre,
        })
    return result


def _tick_checklist_inventario(db: Session, tienda_id: int):
    from app.services.caja import _tick_checklist
    _tick_checklist(db, tienda_id, inventario_check=True)
