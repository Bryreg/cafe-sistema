from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_turno_access, ensure_tienda_access, get_current_user, get_barista_actor
from app.models.models import Usuario
from app.schemas.conteos import RegistrarConteoRequest, ConteoFisicoOut
from app.services import conteos as svc
from typing import List

router = APIRouter(prefix="/conteos", tags=["conteos"])


@router.post("/", response_model=ConteoFisicoOut)
def registrar(data: RegistrarConteoRequest, db: Session = Depends(get_db),
              user: Usuario = Depends(get_current_user),
              barista: tuple = Depends(get_barista_actor)):
    ensure_tienda_access(user, data.tienda_id)
    items = [{"producto_id": i.producto_id, "cantidad_real": i.cantidad_real}
             for i in data.items]
    return svc.registrar_conteo(db, data.tienda_id, data.tipo, items, user.id,
                                barista_id=barista[0], barista_nombre=barista[1])


@router.get("/turno/{turno_id}", response_model=List[ConteoFisicoOut])
def conteos_turno(turno_id: int, db: Session = Depends(get_db),
                  user: Usuario = Depends(get_current_user)):
    ensure_turno_access(db, user, turno_id)
    return svc.get_conteos_turno(db, turno_id)
