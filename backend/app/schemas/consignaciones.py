from datetime import date
from typing import Optional

from pydantic import BaseModel


class RecogidaCreate(BaseModel):
    """«Recogí $X de la sede Y el día Z» — el dato que le faltaba al sistema.

    A PROPÓSITO SIN `Field(gt=0)`, `Field(max_length=300)` NI VALIDATORS. Todas las
    reglas de negocio se validan en el handler y vuelven como HTTPException(400,
    "<mensaje en castellano>"). Razón dura ya pagada en este repo: el `detail` de
    un 422 de pydantic es una LISTA de errores y el cliente solo sabe renderizar
    strings, así que el dueño veía "Reintenta" en vez de "El monto de la recogida
    va en positivo". Este schema solo se ocupa de la FORMA (qué campos llegan y de
    qué tipo); el PORQUÉ está en routers/consignaciones.py.
    """
    tienda_id: int
    fecha: date          # el día COLOMBIA en que recogió, no el día en que teclea
    monto: float
    nota: Optional[str] = None
    # El turno (día) que esta recogida salda. Con él, se imputa a ESE día y solo a
    # ese —el dueño lo marcó en su tarjeta—; sin él (pasada suelta, cliente viejo)
    # cae al reparto histórico del más viejo primero. El servicio lo valida.
    turno_id: Optional[int] = None
