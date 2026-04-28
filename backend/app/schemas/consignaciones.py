from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ConsignacionOut(BaseModel):
    id: int
    tienda_id: int
    fecha: datetime
    valor: float
    imagen_url: Optional[str]
    estado: str
    usuario_id: Optional[int] = None
    usuario_nombre: Optional[str] = None
    class Config: from_attributes = True
