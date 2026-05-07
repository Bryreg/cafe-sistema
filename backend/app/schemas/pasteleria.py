from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class PasteleriaRequest(BaseModel):
    tienda_id: int
    producto_id: int
    cantidad: float
    numero_lote: Optional[str] = None
    fecha_vencimiento: datetime
    fecha_frescura: Optional[datetime] = None  # legado, se ignora

