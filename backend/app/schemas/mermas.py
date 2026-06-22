from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class RegistrarMermaRequest(BaseModel):
    tienda_id: int
    producto_id: int
    cantidad: float
    motivo: str
    tipo: str = "consumo"                    # consumo | traslado | daño
    tienda_destino_id: Optional[int] = None  # solo para traslado


class MermaOut(BaseModel):
    id: int
    tienda_id: int
    producto_id: int
    cantidad: float
    motivo: str
    tipo: str
    tienda_destino_id: Optional[int] = None
    recibido: bool
    fecha_recibido: Optional[datetime] = None
    fecha_registro: datetime
    barista_nombre: Optional[str] = None

    class Config:
        from_attributes = True
