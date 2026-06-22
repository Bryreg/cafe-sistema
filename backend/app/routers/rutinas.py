"""Router del Motor de Rutinas — pendientes, registro de eventos, cumplimiento."""
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Form, UploadFile, File, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user, require_admin, ensure_tienda_access, get_barista_actor
from app.models.models import Usuario
from app.services import rutinas as svc
from app.core.storage import upload_imagen

router = APIRouter(prefix="/rutinas", tags=["rutinas"])


class PlantillaCreate(BaseModel):
    clave: str
    nombre: str
    categoria: str = "otro"
    frecuencia: str = "por_turno"
    esperadas_por_periodo: int = 1
    requiere_evidencia: bool = False
    requiere_valor: bool = False
    tienda_id: Optional[int] = None


@router.get("/pendientes")
def pendientes(tienda_id: int, db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_pendientes(db, tienda_id)


@router.post("/eventos", status_code=201)
async def registrar_evento(
    tienda_id: int = Form(...),
    plantilla_id: int = Form(...),
    valor: Optional[float] = Form(None),
    nota: Optional[str] = Form(None),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    ensure_tienda_access(user, tienda_id)
    imagen_url = await upload_imagen(imagen)
    ev = svc.registrar_evento(db, tienda_id, plantilla_id, user.id, valor, nota, imagen_url,
                              barista_id=barista[0], barista_nombre=barista[1])
    return {"id": ev.id, "plantilla_id": ev.plantilla_id, "fecha": ev.fecha.isoformat()}


@router.get("/cumplimiento")
def cumplimiento(tienda_id: int, dia_operativo_id: Optional[int] = Query(None),
                 db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_cumplimiento(db, tienda_id, dia_operativo_id)


@router.get("/plantillas")
def plantillas(tienda_id: Optional[int] = Query(None), db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    return svc.listar_plantillas(db, tienda_id)


@router.post("/plantillas", status_code=201)
def crear_plantilla(data: PlantillaCreate, db: Session = Depends(get_db),
                    user: Usuario = Depends(require_admin)):
    p = svc.crear_plantilla(db, data.dict())
    return {"id": p.id, "clave": p.clave, "nombre": p.nombre}


@router.get("/estado-turno")
def estado_turno(tienda_id: int, db: Session = Depends(get_db),
                 user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_estado_turno(db, tienda_id)


class QuickRutinaIn(BaseModel):
    tienda_id: int
    clave: str
    nota: Optional[str] = None


@router.post("/quick", status_code=201)
def quick_rutina(data: QuickRutinaIn, db: Session = Depends(get_db),
                 user: Usuario = Depends(get_current_user),
                 barista: tuple = Depends(get_barista_actor)):
    ensure_tienda_access(user, data.tienda_id)
    ev = svc.registrar_por_clave(db, data.tienda_id, data.clave, user.id, data.nota,
                                 barista_id=barista[0], barista_nombre=barista[1])
    return {"id": ev.id, "clave": data.clave, "fecha": ev.fecha.isoformat()}


@router.get("/frecuencias")
def frecuencias(user: Usuario = Depends(get_current_user)):
    return svc.get_frecuencias()


@router.get("/bitacora")
def bitacora(tienda_id: int, db: Session = Depends(get_db),
             user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_bitacora(db, tienda_id)


@router.get("/cumplimiento-semana")
def cumplimiento_semana(tienda_id: int, db: Session = Depends(get_db),
                        user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_cumplimiento_semana(db, tienda_id)
