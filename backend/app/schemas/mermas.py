from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class RegistrarMermaRequest(BaseModel):
    tienda_id: int
    producto_id: int
    cantidad: float
    motivo: str = Field(..., min_length=1)   # rechazar motivo vacío (registro sin razón)
    tipo: str = "consumo"                    # consumo | traslado | daño
    tienda_destino_id: Optional[int] = None  # solo para traslado
    quien: Optional[str] = None              # quién consumió (consumo dueños/reuniones)
    confirmar: bool = False                  # traslado: confirma reenvío pese al guard anti-duplicado


class MermaOut(BaseModel):
    id: int
    tienda_id: int
    producto_id: int
    cantidad: float
    motivo: str
    tipo: str
    quien: Optional[str] = None
    tienda_destino_id: Optional[int] = None
    recibido: bool
    fecha_recibido: Optional[datetime] = None
    fecha_registro: datetime
    barista_nombre: Optional[str] = None
    producto_nombre: Optional[str] = None
    unidad_medida: Optional[str] = None

    class Config:
        from_attributes = True
