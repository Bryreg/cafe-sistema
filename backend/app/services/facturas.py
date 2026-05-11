from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
from datetime import datetime
from app.models.models import FacturaCompra, FacturaCompraItem, TipoPagoEnum
from app.services import inventario as inv_svc
from app.services import audit


def crear_factura(db: Session, data, imagen_url: str | None, usuario_id: int) -> FacturaCompra:
    tipo_map = {
        "contado": TipoPagoEnum.contado,
        "credito": TipoPagoEnum.credito,
        "transferencia": TipoPagoEnum.transferencia,
    }
    if data.tipo_pago not in tipo_map:
        raise HTTPException(400, "tipo_pago inválido: contado | credito | transferencia")
    if not data.items:
        raise HTTPException(400, "Debes agregar al menos un producto")

    factura = FacturaCompra(
        tienda_id=data.tienda_id,
        proveedor=data.proveedor,
        numero_factura=data.numero_factura,
        numero_lote=data.numero_lote,
        fecha_recibido=data.fecha_recibido,
        valor_total=data.valor_total,
        tipo_pago=tipo_map[data.tipo_pago],
        imagen_url=imagen_url,
        usuario_id=usuario_id,
    )
    db.add(factura)
    db.flush()

    for item in data.items:
        # Per-item lote takes precedence; fall back to factura-level for legacy clients
        numero_lote_item = item.numero_lote or data.numero_lote
        db.add(FacturaCompraItem(
            factura_id=factura.id,
            producto_id=item.producto_id,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario,
            numero_lote=numero_lote_item,
            fecha_vencimiento=item.fecha_vencimiento,
        ))
        inv_svc.registrar_movimiento(
            db,
            producto_id=item.producto_id,
            tienda_id=data.tienda_id,
            tipo="entrada",
            cantidad=item.cantidad,
            motivo=f"Factura #{data.numero_factura or factura.id} — {data.proveedor}",
            usuario_id=usuario_id,
            fecha_vencimiento=item.fecha_vencimiento,
        )

    audit.registrar(
        db, accion="crear_factura_compra", tabla="facturas_compra",
        registro_id=factura.id, usuario_id=usuario_id, tienda_id=data.tienda_id,
        datos_despues={
            "proveedor": data.proveedor,
            "numero_factura": data.numero_factura,
            "valor_total": data.valor_total,
            "tipo_pago": data.tipo_pago,
            "items_count": len(data.items),
        },
    )
    db.commit()
    db.refresh(factura)
    return factura


def get_proveedores_tienda(db: Session, tienda_id: int) -> list:
    """Devuelve proveedores únicos ordenados por frecuencia descendente."""
    rows = (
        db.query(
            FacturaCompra.proveedor,
            func.count().label("frecuencia"),
            func.max(FacturaCompra.fecha_recibido).label("ultima"),
        )
        .filter(FacturaCompra.tienda_id == tienda_id)
        .group_by(FacturaCompra.proveedor)
        .order_by(func.count().desc())
        .all()
    )
    return [
        {"proveedor": r.proveedor, "frecuencia": r.frecuencia, "ultima": r.ultima}
        for r in rows
    ]


def get_facturas_tienda(db: Session, tienda_id: int) -> list:
    facturas = (
        db.query(FacturaCompra)
        .filter(FacturaCompra.tienda_id == tienda_id)
        .order_by(FacturaCompra.fecha_recibido.desc())
        .all()
    )
    return [_serializar(f) for f in facturas]


def get_factura(db: Session, factura_id: int) -> dict:
    f = db.query(FacturaCompra).filter_by(id=factura_id).first()
    if not f:
        raise HTTPException(404, "Factura no encontrada")
    return _serializar(f)


def _serializar(f: FacturaCompra) -> dict:
    return {
        "id": f.id,
        "tienda_id": f.tienda_id,
        "proveedor": f.proveedor,
        "numero_factura": f.numero_factura,
        "numero_lote": f.numero_lote,
        "fecha_recibido": f.fecha_recibido,
        "valor_total": f.valor_total,
        "tipo_pago": f.tipo_pago.value,
        "imagen_url": f.imagen_url,
        "fecha_registro": f.fecha_registro,
        "usuario_nombre": f.usuario.nombre if f.usuario else "",
        "items": [
            {
                "id": i.id,
                "producto_id": i.producto_id,
                "producto_nombre": i.producto.nombre if i.producto else "",
                "unidad_medida": i.producto.unidad_medida if i.producto else "",
                "cantidad": i.cantidad,
                "precio_unitario": i.precio_unitario,
                "numero_lote": i.numero_lote,
                "fecha_vencimiento": i.fecha_vencimiento,
            }
            for i in f.items
        ],
    }
