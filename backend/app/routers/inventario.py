from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin
from app.models.models import Usuario, Producto, Inventario, Tienda, CategoriaProductoEnum, LoteInventario
from app.schemas.inventario import MovimientoInvRequest, ProductoCreate, ProductoUpdate, StockMinimoUpdate
from app.services import inventario as svc

router = APIRouter(prefix="/inventario", tags=["inventario"])

@router.get("/tienda/{tienda_id}")
def get_inventario(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_inventario_tienda(db, tienda_id)

@router.post("/movimiento")
def movimiento(data: MovimientoInvRequest, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    return svc.registrar_movimiento(db, data.producto_id, data.tienda_id, data.tipo, data.cantidad, data.motivo, user.id)

@router.get("/alertas/{tienda_id}")
def alertas(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_alertas(db, tienda_id)

@router.get("/productos")
def productos(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    rows = db.query(Producto).order_by(Producto.categoria, Producto.nombre).all()
    return [{"id": p.id, "nombre": p.nombre, "categoria": p.categoria.value,
             "unidad_medida": p.unidad_medida, "controla_stock": p.controla_stock} for p in rows]

@router.post("/productos")
def crear_producto(data: ProductoCreate, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_admin)):
    cat_map = {"pasteleria": CategoriaProductoEnum.pasteleria,
               "bebida": CategoriaProductoEnum.bebida,
               "insumo": CategoriaProductoEnum.insumo}
    if data.categoria not in cat_map:
        raise HTTPException(400, "Categoría inválida")
    p = Producto(nombre=data.nombre, categoria=cat_map[data.categoria],
                 unidad_medida=data.unidad_medida, controla_stock=data.controla_stock)
    db.add(p)
    db.flush()
    for t in db.query(Tienda).all():
        db.add(Inventario(producto_id=p.id, tienda_id=t.id, stock_actual=0.0, stock_minimo=0.0))
    db.commit()
    db.refresh(p)
    return {"id": p.id, "nombre": p.nombre, "categoria": p.categoria.value,
            "unidad_medida": p.unidad_medida, "controla_stock": p.controla_stock}

@router.patch("/productos/{producto_id}")
def editar_producto(producto_id: int, data: ProductoUpdate, db: Session = Depends(get_db),
                    user: Usuario = Depends(require_admin)):
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    cat_map = {"pasteleria": CategoriaProductoEnum.pasteleria,
               "bebida": CategoriaProductoEnum.bebida,
               "insumo": CategoriaProductoEnum.insumo}
    if data.nombre is not None: p.nombre = data.nombre
    if data.categoria is not None:
        if data.categoria not in cat_map: raise HTTPException(400, "Categoría inválida")
        p.categoria = cat_map[data.categoria]
    if data.unidad_medida is not None: p.unidad_medida = data.unidad_medida
    if data.controla_stock is not None: p.controla_stock = data.controla_stock
    db.commit()
    return {"id": p.id, "nombre": p.nombre, "categoria": p.categoria.value,
            "unidad_medida": p.unidad_medida, "controla_stock": p.controla_stock}

@router.patch("/tienda/{tienda_id}/producto/{producto_id}/minimo")
def actualizar_minimo(tienda_id: int, producto_id: int, data: StockMinimoUpdate,
                      db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    inv = db.query(Inventario).filter_by(tienda_id=tienda_id, producto_id=producto_id).first()
    if not inv:
        raise HTTPException(404, "Registro de inventario no encontrado")
    inv.stock_minimo = data.stock_minimo
    db.commit()
    return {"ok": True}

@router.get("/admin/resumen")
def resumen_admin(db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Todos los productos con stock por tienda — para el panel de admin."""
    tiendas = db.query(Tienda).filter_by(activa=True).all()
    productos = db.query(Producto).order_by(Producto.categoria, Producto.nombre).all()
    result = []
    for p in productos:
        stocks = {}
        for t in tiendas:
            inv = db.query(Inventario).filter_by(producto_id=p.id, tienda_id=t.id).first()
            stocks[str(t.id)] = {
                "stock_actual": inv.stock_actual if inv else 0,
                "stock_minimo": inv.stock_minimo if inv else 0,
                "alerta": (inv.stock_actual <= inv.stock_minimo) if inv else False,
            }
        result.append({
            "id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "unidad_medida": p.unidad_medida,
            "controla_stock": p.controla_stock,
            "stocks": stocks,
        })
    return {"tiendas": [{"id": t.id, "nombre": t.nombre} for t in tiendas], "productos": result}

@router.delete("/productos/{producto_id}")
def eliminar_producto(producto_id: int, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_admin)):
    """Elimina un producto si no tiene movimientos ni conteos relacionados."""
    from app.models.models import MovimientoInventario, ConteoItem
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    # Chequear dependencias
    mov = db.query(MovimientoInventario).filter_by(producto_id=producto_id).first()
    if mov:
        raise HTTPException(400, "El producto tiene movimientos registrados y no puede eliminarse")
    # Eliminar inventario rows y el producto
    db.query(Inventario).filter_by(producto_id=producto_id).delete()
    db.delete(p)
    db.commit()
    return {"ok": True}

@router.get("/lotes/{tienda_id}/{producto_id}")
def lotes(tienda_id: int, producto_id: int, db: Session = Depends(get_db),
          user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_lotes(db, tienda_id, producto_id)


@router.get("/pasteleria-impulso/{tienda_id}")
def pasteleria_impulso(tienda_id: int, db: Session = Depends(get_db),
                       user: Usuario = Depends(get_current_user)):
    """
    Lotes de pastelería con 3+ días en inventario.
    Se usan para mostrar el pop-up de impulso al barista al entrar al Hub.
    Rotación objetivo: 5 días desde recepción.
    """
    ensure_tienda_access(user, tienda_id)
    corte = datetime.utcnow() - timedelta(days=3)
    ahora = datetime.utcnow()
    lotes_q = (
        db.query(LoteInventario)
        .join(Producto, LoteInventario.producto_id == Producto.id)
        .filter(
            LoteInventario.tienda_id == tienda_id,
            LoteInventario.cantidad_restante > 0,
            LoteInventario.fecha_entrada <= corte,
            Producto.categoria == CategoriaProductoEnum.pasteleria,
        )
        .order_by(LoteInventario.fecha_entrada.asc())
        .all()
    )
    result = []
    for l in lotes_q:
        dias = (ahora - l.fecha_entrada).days
        result.append({
            "lote_id": l.id,
            "producto_id": l.producto_id,
            "producto_nombre": l.producto.nombre,
            "cantidad_restante": l.cantidad_restante,
            "fecha_entrada": l.fecha_entrada.isoformat(),
            "dias_en_inventario": dias,
            "urgente": dias >= 5,          # 5+ días = ya pasó la ventana de rotación
        })
    return result
