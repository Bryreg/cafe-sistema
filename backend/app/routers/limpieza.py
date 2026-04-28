from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Optional

from app.database import get_db
from app.core.deps import get_current_user, require_admin, ensure_tienda_access
from app.models.models import Usuario, LimpiezaSemanal

router = APIRouter(prefix="/limpieza", tags=["limpieza"])

# ─── Catálogo fijo de tareas (del Cronograma de Aseo y Mantenimiento) ──────────
TAREAS = [
    {"key": "pisos_puntos_ciegos",  "label": "Aseo general pisos y puntos ciegos"},
    {"key": "computador_caja",      "label": "Limpieza del computador, cajón monedero, impresora, teléfono, datafono"},
    {"key": "congelador_helado",    "label": "Lavar congelador de helado"},
    {"key": "nevera_pasteleria",    "label": "Lavar nevera de pastelería"},
    {"key": "nevera_leche",         "label": "Lavar nevera de leche"},
    {"key": "trampa_grasas",        "label": "Lavar trampa de grasas"},
    {"key": "gabinetes_cajones",    "label": "Asear y organizar gabinetes, puertas, cajones y materias primas por fecha"},
    {"key": "maquinas",             "label": "Aseo de máquinas (licuadoras, hornos y molinos)"},
    {"key": "recipientes",          "label": "Limpieza de recipientes (Milo, Oreo, granizado, café descafeinado, azúcar)"},
    {"key": "loza",                 "label": "Limpieza y desmanchado de loza (tazas, platos y copas)"},
    {"key": "utensilios",           "label": "Desinfección de utensilios (jarras, espresso, cucharas, jigger, cuchillos)"},
    {"key": "avisos_pop",           "label": "Limpieza de avisos y material POP"},
    {"key": "sillas_mesas_barra",   "label": "Sillas, mesas y barra (aseo general patas y por debajo)"},
]
TAREA_KEYS = {t["key"] for t in TAREAS}


def semana_del_mes(d: date) -> int:
    """Devuelve la semana del mes (1–4) dado un día."""
    return (d.day - 1) // 7 + 1


def inicio_fin_mes(mes: int, anio: int):
    inicio = date(anio, mes, 1)
    if mes == 12:
        fin = date(anio + 1, 1, 1)
    else:
        fin = date(anio, mes + 1, 1)
    return inicio, fin


def formato_registro(r: LimpiezaSemanal) -> dict:
    fecha = r.fecha.date() if isinstance(r.fecha, datetime) else r.fecha
    return {
        "id":             r.id,
        "tarea_key":      r.tarea_key,
        "fecha":          fecha.isoformat(),
        "semana":         semana_del_mes(fecha),
        "usuario_nombre": r.usuario.nombre,
        "usuario_id":     r.usuario_id,
        "vobo":           r.vobo,
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/tareas")
def get_tareas():
    """Catálogo fijo de las 13 tareas semanales."""
    return TAREAS


@router.get("/{tienda_id}/semanal")
def get_registros(
    tienda_id: int,
    mes: int,
    anio: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Devuelve los registros de limpieza semanal del mes indicado."""
    ensure_tienda_access(user, tienda_id)
    inicio, fin = inicio_fin_mes(mes, anio)
    registros = (
        db.query(LimpiezaSemanal)
        .filter(
            LimpiezaSemanal.tienda_id == tienda_id,
            LimpiezaSemanal.fecha >= datetime.combine(inicio, datetime.min.time()),
            LimpiezaSemanal.fecha <  datetime.combine(fin,   datetime.min.time()),
        )
        .all()
    )
    return [formato_registro(r) for r in registros]


class RegistrarTareaIn(BaseModel):
    tarea_key: str
    fecha: Optional[date] = None  # si no se envía, usa hoy


@router.post("/{tienda_id}/semanal", status_code=201)
def registrar_tarea(
    tienda_id: int,
    body: RegistrarTareaIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Registra una tarea de limpieza semanal como completada."""
    ensure_tienda_access(user, tienda_id)
    if body.tarea_key not in TAREA_KEYS:
        raise HTTPException(400, "Tarea no válida")

    fecha = body.fecha or date.today()
    semana = semana_del_mes(fecha)
    inicio, fin = inicio_fin_mes(fecha.month, fecha.year)

    # Verificar si ya existe para esta semana
    existentes = (
        db.query(LimpiezaSemanal)
        .filter(
            LimpiezaSemanal.tienda_id == tienda_id,
            LimpiezaSemanal.tarea_key == body.tarea_key,
            LimpiezaSemanal.fecha >= datetime.combine(inicio, datetime.min.time()),
            LimpiezaSemanal.fecha <  datetime.combine(fin,   datetime.min.time()),
        )
        .all()
    )
    ya_esta_semana = [
        r for r in existentes
        if semana_del_mes((r.fecha.date() if isinstance(r.fecha, datetime) else r.fecha)) == semana
    ]
    if ya_esta_semana:
        raise HTTPException(400, "Esta tarea ya fue registrada en la semana actual")

    registro = LimpiezaSemanal(
        tienda_id=tienda_id,
        usuario_id=user.id,
        tarea_key=body.tarea_key,
        fecha=datetime.combine(fecha, datetime.min.time()),
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return formato_registro(registro)


class VoBoBody(BaseModel):
    valor: bool


@router.patch("/{tienda_id}/semanal/{registro_id}/vobo")
def toggle_vobo(
    tienda_id: int,
    registro_id: int,
    body: VoBoBody,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Admin: marcar o quitar VoBo de un registro."""
    ensure_tienda_access(user, tienda_id)
    registro = db.query(LimpiezaSemanal).filter_by(id=registro_id, tienda_id=tienda_id).first()
    if not registro:
        raise HTTPException(404, "Registro no encontrado")
    registro.vobo = body.valor
    db.commit()
    return {"id": registro.id, "vobo": registro.vobo}


@router.delete("/{tienda_id}/semanal/{registro_id}", status_code=204)
def eliminar_registro(
    tienda_id: int,
    registro_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Elimina un registro (solo el autor o un admin)."""
    ensure_tienda_access(user, tienda_id)
    registro = db.query(LimpiezaSemanal).filter_by(id=registro_id, tienda_id=tienda_id).first()
    if not registro:
        raise HTTPException(404, "Registro no encontrado")
    if registro.usuario_id != user.id and user.rol != "admin":
        raise HTTPException(403, "Sin permiso para eliminar este registro")
    db.delete(registro)
    db.commit()
