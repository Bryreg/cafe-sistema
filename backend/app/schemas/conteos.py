from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class ConteoItemRequest(BaseModel):
    producto_id: int
    cantidad_real: float


class RegistrarConteoRequest(BaseModel):
    tienda_id: int
    tipo: str  # apertura | cierre
    items: List[ConteoItemRequest]


class ConteoItemOut(BaseModel):
    id: int
    producto_id: int
    cantidad_sistema: float
    cantidad_real: float
    diferencia: float
    class Config: from_attributes = True


class ConteoFisicoOut(BaseModel):
    id: int
    tienda_id: int
    turno_id: int
    tipo: str
    fecha_registro: datetime
    items: List[ConteoItemOut]
    barista_nombre: Optional[str] = None
    class Config: from_attributes = True
