"""Router de control de temperaturas — equipos y lecturas."""
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user, require_admin, ensure_tienda_access
from app.models.models import Usuario
from app.services import temperaturas as svc

router = APIRouter(prefix="/temperaturas", tags=["temperaturas"])


class EquipoCreate(BaseModel):
    tienda_id: int
    nombre: str
    tipo: str = "refrigerador"
    temp_min: float = 0.0
    temp_max: float = 8.0


class LecturaCreate(BaseModel):
    tienda_id: int
    equipo_id: int
    valor: float
    observacion: Optional[str] = None


def _eq(e):
    return {
        "id": e.id, "nombre": e.nombre,
        "tipo": e.tipo.value if hasattr(e.tipo, "value") else e.tipo,
        "temp_min": e.temp_min, "temp_max": e.temp_max, "activo": e.activo,
    }


def _lec(l):
    return {
        "id": l.id, "equipo_id": l.equipo_id, "valor": l.valor,
        "fuera_de_rango": l.fuera_de_rango, "observacion": l.observacion,
        "fecha": l.fecha.isoformat() if l.fecha else None,
    }


@router.get("/equipos")
def equipos(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return [_eq(e) for e in svc.listar_equipos(db, tienda_id)]


@router.post("/equipos", status_code=201)
def crear_equipo(data: EquipoCreate, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    return _eq(svc.crear_equipo(db, data.tienda_id, data.nombre, data.tipo, data.temp_min, data.temp_max))


@router.post("/lecturas", status_code=201)
def registrar_lectura(data: LecturaCreate, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    return _lec(svc.registrar_lectura(db, data.tienda_id, data.equipo_id, data.valor, user.id, data.observacion))


@router.get("/lecturas")
def lecturas(tienda_id: int, equipo_id: Optional[int] = Query(None),
             db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return [_lec(l) for l in svc.get_lecturas(db, tienda_id, equipo_id)]
