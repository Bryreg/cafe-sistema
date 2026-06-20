"""Router de Novedades — registro, pendientes (handoff) y resolución."""
from typing import Optional
from fastapi import APIRouter, Depends, Form, UploadFile, File, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user, ensure_tienda_access
from app.models.models import Usuario
from app.services import novedades as svc
from app.core.storage import upload_imagen

router = APIRouter(prefix="/novedades", tags=["novedades"])


def _out(n):
    return {
        "id": n.id,
        "tienda_id": n.tienda_id,
        "turno_id": n.turno_id,
        "categoria": n.categoria.value if hasattr(n.categoria, "value") else n.categoria,
        "nivel": n.nivel,
        "titulo": n.titulo,
        "descripcion": n.descripcion,
        "requiere_seguimiento": n.requiere_seguimiento,
        "resuelta": n.resuelta,
        "imagen_url": n.imagen_url,
        "fecha": n.fecha.isoformat() if n.fecha else None,
    }


@router.post("", status_code=201)
async def crear_novedad(
    tienda_id: int = Form(...),
    titulo: str = Form(...),
    categoria: str = Form("otro"),
    nivel: str = Form("info"),
    descripcion: Optional[str] = Form(None),
    requiere_seguimiento: bool = Form(False),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    imagen_url = await upload_imagen(imagen)
    n = svc.crear(db, tienda_id, user.id, titulo, categoria, nivel,
                  descripcion, requiere_seguimiento, imagen_url)
    return _out(n)


@router.get("/pendientes")
def pendientes(tienda_id: int, db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return [_out(n) for n in svc.get_pendientes(db, tienda_id)]


@router.patch("/{novedad_id}/resolver")
def resolver(novedad_id: int, db: Session = Depends(get_db),
             user: Usuario = Depends(get_current_user)):
    return _out(svc.resolver(db, novedad_id, user.id))


@router.get("")
def listar(tienda_id: int, dia_operativo_id: Optional[int] = Query(None),
           db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return [_out(n) for n in svc.listar(db, tienda_id, dia_operativo_id)]
