from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ConteoComprasItemCreate(BaseModel):
    producto_id: int
    cantidad_real: float


class ConteoComprasCreate(BaseModel):
    tienda_id: int
    fecha_conteo: datetime
    nota: Optional[str] = None
    items: List[ConteoComprasItemCreate]


class ConteoComprasItemOut(BaseModel):
    id: int
    producto_id: int
    producto_nombre: str
    categoria: str
    unidad_medida: str
    cantidad_sistema: float
    cantidad_real: float
    diferencia: float

    class Config:
        from_attributes = True


class ConteoComprasOut(BaseModel):
    id: int
    tienda_id: int
    fecha_conteo: datetime
    ajustado: bool
    fecha_ajuste: Optional[datetime]
    nota: Optional[str]
    fecha_registro: datetime
    usuario_nombre: str
    usuario_ajuste_nombre: Optional[str]
    items: List[ConteoComprasItemOut]

    class Config:
        from_attributes = True
