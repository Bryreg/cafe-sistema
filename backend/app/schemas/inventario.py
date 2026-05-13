from pydantic import BaseModel
from typing import Optional  # noqa: F401
from datetime import datetime

class MovimientoInvRequest(BaseModel):
    producto_id: int
    tienda_id: int
    tipo: str  # entrada | salida | ajuste
    cantidad: float
    motivo: Optional[str] = None

class ProductoCreate(BaseModel):
    nombre: str
    categoria: str   # pasteleria | bebida | insumo
    unidad_medida: str
    controla_stock: bool = True

class ProductoUpdate(BaseModel):
    nombre: Optional[str] = None
    categoria: Optional[str] = None
    unidad_medida: Optional[str] = None
    controla_stock: Optional[bool] = None

class StockMinimoUpdate(BaseModel):
    stock_minimo: float
