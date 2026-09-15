from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.core.deps import require_admin, ensure_tienda_access
from app.models.models import Usuario
from app.core.storage import upload_imagen
from app.services import auditorias as svc

router = APIRouter(prefix="/auditorias", tags=["auditorias"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ItemInv(BaseModel):
    producto_id: int
    cantidad_real: float
    observacion: Optional[str] = None

class CrearAuditoriaInv(BaseModel):
    tienda_id: int
    fecha: datetime
    descripcion: str
    causa: Optional[str] = None
    observaciones: Optional[str] = None
    items: list[ItemInv]

class CerrarAuditoriaInv(BaseModel):
    causa: Optional[str] = None
    acciones_tomadas: Optional[str] = None

class ItemLimp(BaseModel):
    tarea_key: str
    realizado: bool = False
    realizado_por: Optional[str] = None

class CrearAuditoriaLimp(BaseModel):
    tienda_id: int
    semana: str           # "2026-W07"
    fecha_inicio: datetime
    observaciones: Optional[str] = None
    items: list[ItemLimp]

class ActualizarAuditoriaLimp(BaseModel):
    observaciones: Optional[str] = None
    items: list[ItemLimp]


class RespuestaControlPunto(BaseModel):
    # True (cumple) / False (no cumple) / None (sin responder). El None es un
    # valor válido, no un campo faltante: una revisión a medias no es una
    # revisión con fallas.
    cumple: Optional[bool] = None
    # Qué falló, no solo que falló.
    nota: Optional[str] = None
    # URL que devuelve POST /control-punto/foto.
    foto_url: Optional[str] = None


class ControlPuntoBody(BaseModel):
    tienda_id: int
    fecha_revision: date
    respuestas: dict[str, RespuestaControlPunto] = {}
    observaciones: Optional[str] = None


class ActualizarControlPuntoBody(BaseModel):
    respuestas: dict[str, RespuestaControlPunto] = {}
    observaciones: Optional[str] = None


# ─── Control del punto ────────────────────────────────────────────────────────

@router.get("/control-punto/formato")
def formato_control_punto(_: Usuario = Depends(require_admin)):
    """Las secciones y preguntas del formato, en blanco.

    El texto vive en el backend y no duplicado en el front: si mañana se agrega
    una pregunta, aparece en la pantalla y en las auditorías viejas como «sin
    responder» sin tocar dos archivos."""
    return svc.get_control_punto_formato()


@router.post("/control-punto")
def crear_control_punto(body: ControlPuntoBody, db: Session = Depends(get_db),
                        user: Usuario = Depends(require_admin)):
    """Registra una revisión del punto. Sirve igual para Vida y para Palmetto:
    la sede es un campo, no un formulario aparte."""
    respuestas = {k: v.model_dump(exclude_unset=True) for k, v in body.respuestas.items()}
    return svc.crear_control_punto(db, body.tienda_id, body.fecha_revision,
                                   respuestas, user.id, body.observaciones)


@router.get("/control-punto")
def listar_control_punto(tienda_id: Optional[int] = Query(None),
                         limite: int = Query(50, ge=1, le=200),
                         db: Session = Depends(get_db),
                         _: Usuario = Depends(require_admin)):
    """Historial. Sin `tienda_id` trae las dos sedes, para poder compararlas."""
    return svc.listar_control_punto(db, tienda_id, limite)


@router.patch("/control-punto/{auditoria_id}")
def actualizar_control_punto(auditoria_id: int, body: ActualizarControlPuntoBody,
                             tienda_id: int = Query(...), db: Session = Depends(get_db),
                             user: Usuario = Depends(require_admin)):
    respuestas = {k: v.model_dump(exclude_unset=True) for k, v in body.respuestas.items()}
    return svc.actualizar_control_punto(db, auditoria_id, tienda_id, respuestas,
                                        user.id, body.observaciones)


@router.get("/control-punto/anterior")
def anterior_control_punto(tienda_id: int = Query(...),
                           excluir_id: Optional[int] = Query(None),
                           db: Session = Depends(get_db),
                           _: Usuario = Depends(require_admin)):
    """La última revisión de la sede, para arrancar la siguiente mirándola.

    Sirve para poner delante de quien revisa lo que falló la vez pasada: una
    auditoría cuyas fallas nadie verifica en la visita siguiente es teatro."""
    return svc.revision_anterior(db, tienda_id, excluir_id)


@router.get("/control-punto/tendencia")
def tendencia_control_punto(tienda_id: int = Query(...),
                            visitas: int = Query(10, ge=1, le=60),
                            db: Session = Depends(get_db),
                            _: Usuario = Depends(require_admin)):
    """Cuántas veces falló cada pregunta en las últimas visitas de la sede.

    Separa el problema de proceso del martes malo. El denominador de cada
    pregunta es cuántas veces se RESPONDIÓ, no cuántas visitas hubo."""
    return svc.tendencia_control_punto(db, tienda_id, visitas)


@router.post("/control-punto/foto")
async def subir_foto_control_punto(imagen: UploadFile = File(...),
                                   _: Usuario = Depends(require_admin)):
    """Sube la foto de un hallazgo y devuelve su URL.

    Va aparte del guardado a propósito: una revisión puede llevar hasta quince
    fotos, y mandarlas todas juntas con el formulario haría un request enorme
    que se cae con mala señal justo cuando ya se llenó todo. Acá cada foto sube
    al elegirla y el guardado solo manda URLs."""
    url = await upload_imagen(imagen)
    if not url:
        raise HTTPException(400, "No se pudo subir la imagen")
    return {"url": url}


@router.patch("/control-punto/{auditoria_id}/vobo")
def vobo_control_punto(auditoria_id: int, tienda_id: int = Query(...),
                       db: Session = Depends(get_db),
                       user: Usuario = Depends(require_admin)):
    """Cierra la revisión: después del VoBo no se edita."""
    return svc.vobo_control_punto(db, auditoria_id, tienda_id, user.id)


@router.delete("/control-punto/{auditoria_id}")
def eliminar_control_punto(auditoria_id: int, tienda_id: int = Query(...),
                           db: Session = Depends(get_db),
                           user: Usuario = Depends(require_admin)):
    return svc.eliminar_control_punto(db, auditoria_id, tienda_id, user.id)


# ─── Inventario ───────────────────────────────────────────────────────────────

@router.post("/inventario")
def crear_inv(body: CrearAuditoriaInv, db: Session = Depends(get_db),
              user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, body.tienda_id)
    return svc.crear_auditoria_inv(
        db, tienda_id=body.tienda_id, usuario_id=user.id,
        fecha=body.fecha, descripcion=body.descripcion,
        items=[it.dict() for it in body.items],
        causa=body.causa, observaciones=body.observaciones,
    )

@router.get("/inventario")
def listar_inv(tienda_id: int = Query(...), db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.listar_auditorias_inv(db, tienda_id)

@router.patch("/inventario/{auditoria_id}/cerrar")
def cerrar_inv(auditoria_id: int, body: CerrarAuditoriaInv,
               tienda_id: int = Query(...),
               db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.cerrar_auditoria_inv(db, auditoria_id, tienda_id,
                                    body.acciones_tomadas, body.causa)

@router.delete("/inventario/{auditoria_id}")
def eliminar_inv(auditoria_id: int, tienda_id: int = Query(...),
                 db: Session = Depends(get_db),
                 user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.eliminar_auditoria_inv(db, auditoria_id, tienda_id)


# ─── Limpieza ─────────────────────────────────────────────────────────────────

@router.get("/limpieza/tareas")
def tareas(_: Usuario = Depends(require_admin)):
    return svc.get_tareas()

@router.post("/limpieza")
def crear_limp(body: CrearAuditoriaLimp, db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, body.tienda_id)
    return svc.crear_auditoria_limp(
        db, tienda_id=body.tienda_id, usuario_id=user.id,
        semana=body.semana, fecha_inicio=body.fecha_inicio,
        items=[it.dict() for it in body.items],
        observaciones=body.observaciones,
    )

@router.get("/limpieza")
def listar_limp(tienda_id: int = Query(...), db: Session = Depends(get_db),
                user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.listar_auditorias_limp(db, tienda_id)

@router.patch("/limpieza/{auditoria_id}")
def actualizar_limp(auditoria_id: int, body: ActualizarAuditoriaLimp,
                    tienda_id: int = Query(...),
                    db: Session = Depends(get_db),
                    user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.actualizar_auditoria_limp(
        db, auditoria_id, tienda_id,
        [it.dict() for it in body.items], body.observaciones,
    )

@router.patch("/limpieza/{auditoria_id}/vobo")
def vobo_limp(auditoria_id: int, tienda_id: int = Query(...),
              db: Session = Depends(get_db),
              user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.vobo_auditoria_limp(db, auditoria_id, tienda_id, user.id)

@router.delete("/limpieza/{auditoria_id}")
def eliminar_limp(auditoria_id: int, tienda_id: int = Query(...),
                  db: Session = Depends(get_db),
                  user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.eliminar_auditoria_limp(db, auditoria_id, tienda_id)
