from pydantic import BaseModel
from datetime import datetime

class PasteleriaRequest(BaseModel):
    tienda_id: int
    producto_id: int
    cantidad: float
    fecha_frescura: datetime

class PasteleriaOut(BaseModel):
    id: int
    tienda_id: int
    producto_id: int
    producto_nombre: str
    cantidad: float
    fecha_frescura: datetime
    fecha_registro: datetime
    class Config: from_attributes = True
