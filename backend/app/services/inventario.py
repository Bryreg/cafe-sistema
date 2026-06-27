from sqlalchemy.orm import Session, joinedload
from sqlalchemy import update as sa_update
from fastapi import HTTPException
from app.models.models import Inventario, MovimientoInventario, LoteInventario, Producto
from datetime import datetime
from app.services import audit


def clasificar_estado(stock_actual: float, stock_minimo: float,
                      stock_critico: float, stock_ideal: float = 0.0) -> str:
    """Clasificador de 4 estados de stock. Único punto de verdad.
    AGOTADO  si stock_actual <= 0
    CRITICO  si 0 < stock_actual <= stock_critico (solo si stock_critico está configurado)
    BAJO     si stock_critico < stock_actual <= stock_minimo
    NORMAL   si stock_actual > stock_minimo
    Nota: si stock_critico no está configurado (0), CRITICO no aplica y cae a BAJO/NORMAL."""
    if stock_actual <= 0:
        return "agotado"
    if stock_critico > 0 and stock_actual <= stock_critico:
        return "critico"
    if stock_actual <= stock_minimo:
        return "bajo"
    return "normal"


def get_inventario_tienda(db: Session, tienda_id: int):
    items = db.query(Inventario).options(joinedload(Inventario.producto)).filter(Inventario.tienda_id == tienda_id).all()
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
                          fecha_vencimiento: datetime | None = None, commit: bool = True,
                          allow_negative: bool = False,
                          numero_lote: str | None = None, proveedor: str | None = None,
                          fecha_fabricacion: datetime | None = None, factura_id: int | None = None):
    if tipo not in {"entrada", "salida", "ajuste"}:
        raise HTTPException(status_code=400, detail="tipo debe ser entrada, salida o ajuste")
    if tipo in {"entrada", "salida"} and cantidad <= 0:
        raise HTTPException(status_code=400, detail="cantidad debe ser mayor a 0")
    if tipo == "ajuste" and cantidad < 0:
        raise HTTPException(status_code=400, detail="cantidad no puede ser negativa en ajuste")
    # Verify product exists first (needed for all branches)
    inv = db.query(Inventario).filter(
        Inventario.producto_id == producto_id,
        Inventario.tienda_id == tienda_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario de esta tienda")

    if tipo == "entrada":
        # Atomic increment — no read-modify-write race
        db.execute(
            sa_update(Inventario)
            .where(
                Inventario.producto_id == producto_id,
                Inventario.tienda_id == tienda_id,
            )
            .values(stock_actual=Inventario.stock_actual + cantidad)
        )
        agregar_lote(db, producto_id, tienda_id, cantidad, usuario_id, fecha_vencimiento,
                     numero_lote=numero_lote, proveedor=proveedor,
                     fecha_fabricacion=fecha_fabricacion, factura_id=factura_id)
    elif tipo == "salida":
        if allow_negative:
            # POS mode: permitir stock negativo (proveedor llega después)
            db.execute(
                sa_update(Inventario)
                .where(Inventario.producto_id == producto_id, Inventario.tienda_id == tienda_id)
                .values(stock_actual=Inventario.stock_actual - cantidad)
            )
        else:
            # Modo normal: bloquear si no hay suficiente stock
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
                raise HTTPException(status_code=400, detail="Stock insuficiente")
        consumir_fifo(db, producto_id, tienda_id, cantidad)
    elif tipo == "ajuste":
        # Read current stock to compute FIFO delta, then set atomically
        stock_antes = inv.stock_actual
        db.execute(
            sa_update(Inventario)
            .where(
                Inventario.producto_id == producto_id,
                Inventario.tienda_id == tienda_id,
            )
            .values(stock_actual=cantidad)
        )
        # Etapa 2: sincronizar lotes FIFO al ajustar stock
        diferencia = cantidad - stock_antes
        if diferencia > 0:
            # Stock aumentó → lote de ajuste positivo
            agregar_lote(db, producto_id, tienda_id, diferencia, usuario_id)
        elif diferencia < 0:
            # Stock disminuyó → consumir diferencia de lotes más antiguos
            consumir_fifo(db, producto_id, tienda_id, abs(diferencia))

    # Re-fetch to get the updated value for audit and return
    db.flush()
    inv = db.query(Inventario).filter(
        Inventario.producto_id == producto_id,
        Inventario.tienda_id == tienda_id
    ).first()

    mov = MovimientoInventario(
        producto_id=producto_id, tienda_id=tienda_id, tipo=tipo,
        cantidad=cantidad, usuario_id=usuario_id, motivo=motivo,
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
                 fecha_vencimiento: datetime | None = None,
                 numero_lote: str | None = None, proveedor: str | None = None,
                 fecha_fabricacion: datetime | None = None, factura_id: int | None = None):
    """Crea un lote FIFO con su trazabilidad. NO hace commit — dentro de una transacción."""
    lote = LoteInventario(
        producto_id=producto_id,
        tienda_id=tienda_id,
        cantidad_inicial=cantidad,
        cantidad_restante=cantidad,
        usuario_id=usuario_id,
        fecha_vencimiento=fecha_vencimiento,
        numero_lote=numero_lote,
        proveedor=proveedor,
        fecha_fabricacion=fecha_fabricacion,
        factura_id=factura_id,
    )
    db.add(lote)


def consumir_fifo(db: Session, producto_id: int, tienda_id: int, cantidad: float):
    """Descuenta cantidad de los lotes más antiguos (FIFO). NO hace commit.
    Marca fecha_agotado cuando un lote llega a 0 (trazabilidad de consumo)."""
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
        if lote.cantidad_restante <= 0 and lote.fecha_agotado is None:
            lote.fecha_agotado = datetime.utcnow()
    # Si restante > 0, los lotes no cubren (stock registrado antes del FIFO).
    # Se ignora silenciosamente para no bloquear operaciones.


def get_lotes(db: Session, tienda_id: int, producto_id: int):
    """Lotes FIFO activos (con stock) de un producto. Solo para admin."""
    return db.query(LoteInventario).filter(
        LoteInventario.tienda_id == tienda_id,
        LoteInventario.producto_id == producto_id,
    ).order_by(LoteInventario.fecha_entrada.asc()).all()


def get_trazabilidad(db: Session, tienda_id: int | None = None, producto_id: int | None = None,
                     proveedor: str | None = None, estado: str | None = None):
    """Trazabilidad de lotes: qué lote entró, cuándo, qué proveedor, vencimiento,
    cuánto queda / % consumido, estado (activo/por_vencer/vencido/agotado) y cuándo se
    agotó. Filtrable por sede, producto, proveedor y estado."""
    from datetime import timedelta
    q = db.query(LoteInventario).options(
        joinedload(LoteInventario.producto), joinedload(LoteInventario.tienda),
    )
    if tienda_id is not None:
        q = q.filter(LoteInventario.tienda_id == tienda_id)
    if producto_id is not None:
        q = q.filter(LoteInventario.producto_id == producto_id)
    if proveedor:
        q = q.filter(LoteInventario.proveedor == proveedor)
    lotes = q.order_by(LoteInventario.fecha_entrada.desc()).limit(800).all()

    ahora = datetime.utcnow()
    pronto = ahora + timedelta(days=7)
    out = []
    for l in lotes:
        ini = l.cantidad_inicial or 0
        rest = l.cantidad_restante or 0
        if rest <= 0:
            est = "agotado"
        elif l.fecha_vencimiento and l.fecha_vencimiento < ahora:
            est = "vencido"
        elif l.fecha_vencimiento and l.fecha_vencimiento <= pronto:
            est = "por_vencer"
        else:
            est = "activo"
        out.append({
            "id": l.id,
            "producto_id": l.producto_id,
            "producto_nombre": l.producto.nombre if l.producto else "",
            "unidad_medida": l.producto.unidad_medida if l.producto else "",
            "tienda_id": l.tienda_id,
            "tienda_nombre": l.tienda.nombre if l.tienda else None,
            "proveedor": l.proveedor,
            "numero_lote": l.numero_lote,
            "factura_id": l.factura_id,
            "cantidad_inicial": round(ini, 2),
            "cantidad_restante": round(rest, 2),
            "consumido_pct": round((1 - rest / ini) * 100, 1) if ini else 0,
            "fecha_entrada": l.fecha_entrada,
            "fecha_fabricacion": l.fecha_fabricacion,
            "fecha_vencimiento": l.fecha_vencimiento,
            "fecha_agotado": l.fecha_agotado,
            "estado": est,
        })
    if estado:
        out = [o for o in out if o["estado"] == estado]
    return out


def get_alertas(db: Session, tienda_id: int):
    """Alertas de stock con 4 estados. Filtra todo lo que no es NORMAL.
    Compat: mantiene 'nivel' (agotado|bajo) para AdminHub; agrega 'estado' de 4 estados
    y 'cantidad_sugerida' calculada hacia stock_ideal (o el doble del mínimo si no hay ideal)."""
    items = db.query(Inventario).options(joinedload(Inventario.producto)).filter(
        Inventario.tienda_id == tienda_id,
        Inventario.stock_actual <= Inventario.stock_minimo,
    ).order_by(Inventario.stock_actual.asc()).all()
    out = []
    for i in items:
        estado = clasificar_estado(
            i.stock_actual, i.stock_minimo,
            i.stock_critico or 0.0, i.stock_ideal or 0.0,
        )
        objetivo = i.stock_ideal if (i.stock_ideal and i.stock_ideal > 0) else (i.stock_minimo * 2)
        out.append({
            "producto_id": i.producto_id,
            "producto": i.producto.nombre,
            "unidad": i.producto.unidad_medida,
            "stock_actual": round(i.stock_actual),
            "stock_minimo": round(i.stock_minimo),
            "stock_critico": round(i.stock_critico or 0),
            "stock_ideal": round(i.stock_ideal or 0),
            "estado": estado,                                        # nuevo: agotado|critico|bajo
            "nivel": "agotado" if estado == "agotado" else "bajo",  # COMPAT AdminHub actual
            "cantidad_sugerida": max(1, round(objetivo - i.stock_actual)),
        })
    return out


def _tick_checklist_inventario(db: Session, tienda_id: int):
    from app.services.caja import _tick_checklist
    _tick_checklist(db, tienda_id, inventario_check=True)


