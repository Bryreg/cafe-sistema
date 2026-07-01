from datetime import datetime, timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin, get_barista_actor
from app.models.models import Usuario, Producto, Inventario, Tienda, CategoriaProductoEnum, LoteInventario
from app.schemas.inventario import (
    MovimientoInvRequest, ProductoCreate, ProductoUpdate, StockMinimoUpdate, UmbralesStockUpdate,
)
from app.services import inventario as svc

router = APIRouter(prefix="/inventario", tags=["inventario"])

@router.get("/tienda/{tienda_id}")
def get_inventario(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_inventario_tienda(db, tienda_id)

@router.post("/movimiento")
def movimiento(data: MovimientoInvRequest, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user),
               barista: tuple = Depends(get_barista_actor)):
    ensure_tienda_access(user, data.tienda_id)
    return svc.registrar_movimiento(db, data.producto_id, data.tienda_id, data.tipo, data.cantidad, data.motivo, user.id,
                                    barista_id=barista[0], barista_nombre=barista[1])

@router.get("/alertas/{tienda_id}")
def alertas(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_alertas(db, tienda_id)


@router.get("/lotes-trazabilidad")
def lotes_trazabilidad(
    tienda_id: Optional[int] = Query(None),
    producto_id: Optional[int] = Query(None),
    proveedor: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Trazabilidad de lotes (baristas y admin): origen, vencimiento, consumo, estado."""
    if tienda_id is not None:
        ensure_tienda_access(user, tienda_id)
    return svc.get_trazabilidad(db, tienda_id, producto_id, proveedor, estado)

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
               "insumo": CategoriaProductoEnum.insumo,
               "porciones": CategoriaProductoEnum.porciones}
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
               "insumo": CategoriaProductoEnum.insumo,
               "porciones": CategoriaProductoEnum.porciones}
    if data.nombre is not None: p.nombre = data.nombre
    if data.categoria is not None:
        if data.categoria not in cat_map: raise HTTPException(400, "Categoría inválida")
        p.categoria = cat_map[data.categoria]
    if data.unidad_medida is not None: p.unidad_medida = data.unidad_medida
    if data.controla_stock is not None: p.controla_stock = data.controla_stock
    if data.lead_time_dias is not None: p.lead_time_dias = data.lead_time_dias
    if data.proveedor is not None: p.proveedor = data.proveedor if data.proveedor.strip() else None
    if data.incluir_en_conteo is not None: p.incluir_en_conteo = data.incluir_en_conteo
    db.commit()
    return {"id": p.id, "nombre": p.nombre, "categoria": p.categoria.value,
            "unidad_medida": p.unidad_medida, "controla_stock": p.controla_stock,
            "incluir_en_conteo": p.incluir_en_conteo}

@router.patch("/tienda/{tienda_id}/producto/{producto_id}/minimo")
def actualizar_minimo(tienda_id: int, producto_id: int, data: StockMinimoUpdate,
                      db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    inv = db.query(Inventario).filter_by(tienda_id=tienda_id, producto_id=producto_id).first()
    if not inv:
        raise HTTPException(404, "Registro de inventario no encontrado")
    inv.stock_minimo = data.stock_minimo
    db.commit()
    return {"ok": True}

@router.patch("/tienda/{tienda_id}/producto/{producto_id}/umbrales")
def actualizar_umbrales(tienda_id: int, producto_id: int, data: UmbralesStockUpdate,
                        db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Módulo 6: setea stock_minimo, stock_ideal y stock_critico por producto/sede.
    Valida coherencia: critico <= minimo <= ideal (los que vengan)."""
    inv = db.query(Inventario).filter_by(tienda_id=tienda_id, producto_id=producto_id).first()
    if not inv:
        raise HTTPException(404, "Registro de inventario no encontrado")
    if data.stock_minimo is not None:
        inv.stock_minimo = data.stock_minimo
    if data.stock_ideal is not None:
        inv.stock_ideal = data.stock_ideal
    if data.stock_critico is not None:
        inv.stock_critico = data.stock_critico
    # Usar `is not None` (no truthiness): un umbral legítimamente en 0 es falsy y
    # antes saltaba la validación de coherencia.
    if inv.stock_critico is not None and inv.stock_minimo is not None and inv.stock_critico > inv.stock_minimo:
        raise HTTPException(400, "stock_critico no puede ser mayor que stock_minimo")
    if inv.stock_ideal is not None and inv.stock_minimo is not None and inv.stock_ideal < inv.stock_minimo:
        raise HTTPException(400, "stock_ideal no puede ser menor que stock_minimo")
    db.commit()
    return {
        "ok": True,
        "stock_minimo": inv.stock_minimo,
        "stock_ideal": inv.stock_ideal,
        "stock_critico": inv.stock_critico,
    }

@router.get("/admin/resumen")
def resumen_admin(db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Todos los productos con stock por tienda — para el panel de admin."""
    tiendas = db.query(Tienda).filter_by(activa=True).all()
    tienda_ids = [t.id for t in tiendas]
    productos = db.query(Producto).order_by(Producto.categoria, Producto.nombre).all()

    # Single query for all inventarios across all active stores — eliminates N×M loop
    inventarios = (
        db.query(Inventario)
        .filter(Inventario.tienda_id.in_(tienda_ids))
        .all()
    )
    inv_map: dict[tuple[int, int], Inventario] = {
        (i.producto_id, i.tienda_id): i for i in inventarios
    }

    result = []
    for p in productos:
        stocks = {}
        for t in tiendas:
            inv = inv_map.get((p.id, t.id))
            stocks[str(t.id)] = {
                "stock_actual": inv.stock_actual if inv else 0,
                "stock_minimo": inv.stock_minimo if inv else 0,
                "stock_ideal": inv.stock_ideal if inv else 0,
                "stock_critico": inv.stock_critico if inv else 0,
                "alerta": (inv.stock_actual <= inv.stock_minimo) if inv else False,
            }
        result.append({
            "id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "unidad_medida": p.unidad_medida,
            "controla_stock": p.controla_stock,
            "incluir_en_conteo": p.incluir_en_conteo if p.incluir_en_conteo is not None else True,
            "precio_venta": p.precio_venta or 0.0,
            "fraccionable": bool(p.fraccionable),
            "envase": p.envase,
            "stocks": stocks,
        })
    return {"tiendas": [{"id": t.id, "nombre": t.nombre} for t in tiendas], "productos": result}

@router.delete("/productos/{producto_id}")
def eliminar_producto(producto_id: int, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_admin)):
    """Elimina un producto si no tiene movimientos ni conteos relacionados."""
    from app.models.models import MovimientoInventario, LoteInventario
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    # Chequear dependencias
    mov = db.query(MovimientoInventario).filter_by(producto_id=producto_id).first()
    if mov:
        raise HTTPException(400, "El producto tiene movimientos registrados y no puede eliminarse")
    # Eliminar tablas dependientes y el producto
    db.query(LoteInventario).filter_by(producto_id=producto_id).delete()
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
        .options(joinedload(LoteInventario.producto))
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
