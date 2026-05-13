from sqlalchemy.orm import Session
from fastapi import HTTPException
from datetime import datetime
from app.models.models import ConteoCompras, ConteoComprasItem, Inventario
from app.services import inventario as inv_svc
from app.services import audit


def crear_conteo(db: Session, data, usuario_id: int) -> dict:
    if not data.items:
        raise HTTPException(400, "Debes incluir al menos un producto en el conteo")

    conteo = ConteoCompras(
        tienda_id=data.tienda_id,
        usuario_id=usuario_id,
        fecha_conteo=data.fecha_conteo,
        nota=data.nota,
    )
    db.add(conteo)
    db.flush()

    for item in data.items:
        if item.cantidad_real < 0:
            raise HTTPException(400, "La cantidad no puede ser negativa")
        inv = db.query(Inventario).filter_by(
            producto_id=item.producto_id, tienda_id=data.tienda_id
        ).first()
        cantidad_sistema = inv.stock_actual if inv else 0.0
        diferencia = item.cantidad_real - cantidad_sistema
        db.add(ConteoComprasItem(
            conteo_id=conteo.id,
            producto_id=item.producto_id,
            cantidad_sistema=cantidad_sistema,
            cantidad_real=item.cantidad_real,
            diferencia=diferencia,
        ))

    audit.registrar(
        db, accion="crear_conteo_compras", tabla="conteos_compras",
        registro_id=conteo.id, usuario_id=usuario_id, tienda_id=data.tienda_id,
        datos_despues={"items_count": len(data.items), "nota": data.nota},
    )
    db.commit()
    db.refresh(conteo)
    return _serializar(conteo)


def ajustar_stock(db: Session, conteo_id: int, usuario_id: int) -> dict:
    """Admin aprueba el conteo: crea movimientos de ajuste por cada diferencia."""
    conteo = db.query(ConteoCompras).filter_by(id=conteo_id).first()
    if not conteo:
        raise HTTPException(404, "Conteo no encontrado")
    if conteo.ajustado:
        raise HTTPException(400, "Este conteo ya fue ajustado")

    for item in conteo.items:
        if item.diferencia == 0:
            continue
        # Usamos ajuste directo al stock real contado
        inv_svc.registrar_movimiento(
            db,
            producto_id=item.producto_id,
            tienda_id=conteo.tienda_id,
            tipo="ajuste",
            cantidad=item.cantidad_real,
            motivo=f"Ajuste por conteo de compras #{conteo.id}",
            usuario_id=usuario_id,
        )

    conteo.ajustado = True
    conteo.fecha_ajuste = datetime.utcnow()
    conteo.usuario_ajuste_id = usuario_id

    audit.registrar(
        db, accion="ajustar_conteo_compras", tabla="conteos_compras",
        registro_id=conteo.id, usuario_id=usuario_id, tienda_id=conteo.tienda_id,
        datos_despues={"ajustado": True},
    )
    db.commit()
    db.refresh(conteo)
    return _serializar(conteo)


def get_conteos_tienda(db: Session, tienda_id: int) -> list:
    conteos = (
        db.query(ConteoCompras)
        .filter(ConteoCompras.tienda_id == tienda_id)
        .order_by(ConteoCompras.fecha_conteo.desc())
        .all()
    )
    return [_serializar(c) for c in conteos]


def get_conteos_pendientes(db: Session) -> list:
    """Conteos sin ajustar — para la bandeja del admin."""
    conteos = (
        db.query(ConteoCompras)
        .filter(ConteoCompras.ajustado == False)
        .order_by(ConteoCompras.fecha_conteo.desc())
        .all()
    )
    return [_serializar(c) for c in conteos]


def get_panel_pedido(db: Session, tienda_id: int) -> dict:
    """Stock actual vs mínimo para generar lista de pedido."""
    items = db.query(Inventario).filter(Inventario.tienda_id == tienda_id).all()
    productos = []
    for inv in items:
        if not inv.producto.controla_stock:
            continue
        alerta = inv.stock_actual <= inv.stock_minimo
        cantidad_sugerida = max(0, round(inv.stock_minimo * 2 - inv.stock_actual))
        productos.append({
            "producto_id": inv.producto_id,
            "nombre": inv.producto.nombre,
            "categoria": inv.producto.categoria.value,
            "unidad_medida": inv.producto.unidad_medida,
            "stock_actual": round(inv.stock_actual),
            "stock_minimo": round(inv.stock_minimo),
            "alerta": alerta,
            "nivel": "agotado" if inv.stock_actual <= 0 else ("bajo" if alerta else "ok"),
            "cantidad_sugerida": cantidad_sugerida,
        })
    productos.sort(key=lambda x: (0 if x["nivel"] == "agotado" else 1 if x["nivel"] == "bajo" else 2, x["nombre"]))
    return {"tienda_id": tienda_id, "productos": productos}


def _serializar(c: ConteoCompras) -> dict:
    return {
        "id": c.id,
        "tienda_id": c.tienda_id,
        "fecha_conteo": c.fecha_conteo,
        "ajustado": c.ajustado,
        "fecha_ajuste": c.fecha_ajuste,
        "nota": c.nota,
        "fecha_registro": c.fecha_registro,
        "usuario_nombre": c.usuario.nombre if c.usuario else "",
        "usuario_ajuste_nombre": c.usuario_ajuste.nombre if c.usuario_ajuste else None,
        "items": [
            {
                "id": i.id,
                "producto_id": i.producto_id,
                "producto_nombre": i.producto.nombre if i.producto else "",
                "categoria": i.producto.categoria.value if i.producto else "",
                "unidad_medida": i.producto.unidad_medida if i.producto else "",
                "cantidad_sistema": i.cantidad_sistema,
                "cantidad_real": i.cantidad_real,
                "diferencia": i.diferencia,
            }
            for i in c.items
        ],
    }
