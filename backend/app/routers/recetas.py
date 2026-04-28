from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.core.deps import get_current_user, require_admin
from app.models.models import Usuario, Receta, RecetaIngrediente, Producto, Inventario
from datetime import datetime

router = APIRouter(prefix="/recetas", tags=["recetas"])


# ─── Schemas ────────────────────────────────────────────────────────────────────

class IngredienteIn(BaseModel):
    producto_id: int
    cantidad: float

class RecetaCreate(BaseModel):
    nombre: str
    categoria: str = "bebida"        # bebida | pasteleria | comida
    precio_venta: Optional[float] = None
    ingredientes: list[IngredienteIn] = []

class RecetaUpdate(BaseModel):
    nombre: Optional[str] = None
    categoria: Optional[str] = None
    precio_venta: Optional[float] = None
    activa: Optional[bool] = None
    ingredientes: Optional[list[IngredienteIn]] = None


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _serializar(r: Receta, db: Session, tienda_id: Optional[int] = None) -> dict:
    ingredientes = []
    costo_total = 0.0
    for ing in r.ingredientes:
        p = ing.producto
        costo_und = None
        if tienda_id:
            inv = db.query(Inventario).filter_by(producto_id=p.id, tienda_id=tienda_id).first()
            # costo_und se podría calcular si hubiera precio de compra; por ahora None
        ingredientes.append({
            "id": ing.id,
            "producto_id": p.id,
            "producto_nombre": p.nombre,
            "unidad_medida": p.unidad_medida,
            "cantidad": ing.cantidad,
        })
    food_cost_pct = None
    if r.precio_venta and r.precio_venta > 0 and costo_total > 0:
        food_cost_pct = round(costo_total / r.precio_venta * 100, 1)
    return {
        "id": r.id,
        "nombre": r.nombre,
        "categoria": r.categoria,
        "precio_venta": r.precio_venta,
        "activa": r.activa,
        "ingredientes": ingredientes,
        "food_cost_pct": food_cost_pct,
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/")
def listar(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    recetas = db.query(Receta).filter_by(activa=True).order_by(Receta.categoria, Receta.nombre).all()
    return [_serializar(r, db) for r in recetas]


@router.get("/todas")
def listar_todas(db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    recetas = db.query(Receta).order_by(Receta.activa.desc(), Receta.categoria, Receta.nombre).all()
    return [_serializar(r, db) for r in recetas]


@router.post("/", status_code=201)
def crear(data: RecetaCreate, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    r = Receta(nombre=data.nombre, categoria=data.categoria, precio_venta=data.precio_venta)
    db.add(r)
    db.flush()
    for ing in data.ingredientes:
        p = db.query(Producto).filter_by(id=ing.producto_id).first()
        if not p:
            raise HTTPException(400, f"Producto {ing.producto_id} no encontrado")
        db.add(RecetaIngrediente(receta_id=r.id, producto_id=ing.producto_id, cantidad=ing.cantidad))
    db.commit()
    db.refresh(r)
    return _serializar(r, db)


@router.patch("/{receta_id}")
def actualizar(receta_id: int, data: RecetaUpdate, db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    r = db.query(Receta).filter_by(id=receta_id).first()
    if not r:
        raise HTTPException(404, "Receta no encontrada")
    if data.nombre is not None:       r.nombre = data.nombre
    if data.categoria is not None:    r.categoria = data.categoria
    if data.precio_venta is not None: r.precio_venta = data.precio_venta
    if data.activa is not None:       r.activa = data.activa
    if data.ingredientes is not None:
        # Reemplazar ingredientes completos
        for ing in r.ingredientes:
            db.delete(ing)
        db.flush()
        for ing in data.ingredientes:
            p = db.query(Producto).filter_by(id=ing.producto_id).first()
            if not p:
                raise HTTPException(400, f"Producto {ing.producto_id} no encontrado")
            db.add(RecetaIngrediente(receta_id=r.id, producto_id=ing.producto_id, cantidad=ing.cantidad))
    db.commit()
    db.refresh(r)
    return _serializar(r, db)


@router.delete("/{receta_id}", status_code=204)
def eliminar(receta_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    r = db.query(Receta).filter_by(id=receta_id).first()
    if not r:
        raise HTTPException(404, "Receta no encontrada")
    r.activa = False   # soft delete
    db.commit()
