from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Optional

from app.database import get_db
from app.core.deps import get_current_user, require_admin, ensure_tienda_access
from app.models.models import Usuario, LimpiezaSemanal, TareaLimpieza

router = APIRouter(prefix="/limpieza", tags=["limpieza"])

DEFAULTS = [
    {"key": "pisos_puntos_ciegos", "label": "Aseo general pisos y puntos ciegos"},
    {"key": "computador_caja",     "label": "Limpieza del computador, cajón monedero, impresora, teléfono, datafono"},
    {"key": "congelador_helado",   "label": "Lavar congelador de helado"},
    {"key": "nevera_pasteleria",   "label": "Lavar nevera de pastelería"},
    {"key": "nevera_leche",        "label": "Lavar nevera de leche"},
    {"key": "trampa_grasas",       "label": "Lavar trampa de grasas"},
    {"key": "gabinetes_cajones",   "label": "Asear y organizar gabinetes, puertas, cajones y materias primas por fecha"},
    {"key": "maquinas",            "label": "Aseo de máquinas (licuadoras, hornos y molinos)"},
    {"key": "recipientes",         "label": "Limpieza de recipientes (Milo, Oreo, granizado, café descafeinado, azúcar)"},
    {"key": "loza",                "label": "Limpieza y desmanchado de loza (tazas, platos y copas)"},
    {"key": "utensilios",          "label": "Desinfección de utensilios (jarras, espresso, cucharas, jigger, cuchillos)"},
    {"key": "avisos_pop",          "label": "Limpieza de avisos y material POP"},
    {"key": "sillas_mesas_barra",  "label": "Sillas, mesas y barra (aseo general patas y por debajo)"},
]


def _ensure_seeded(db: Session, tienda_id: int):
    """Si la tienda no tiene tareas, inserta las 13 por defecto."""
    if db.query(TareaLimpieza).filter_by(tienda_id=tienda_id).count() == 0:
        for i, t in enumerate(DEFAULTS):
            db.add(TareaLimpieza(tienda_id=tienda_id, key=t["key"], label=t["label"], orden=i))
        db.commit()


def semana_del_mes(d: date) -> int:
    return (d.day - 1) // 7 + 1


def inicio_fin_mes(mes: int, anio: int):
    inicio = date(anio, mes, 1)
    fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
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


# ─── Catálogo de tareas por tienda ─────────────────────────────────────────────

@router.get("/{tienda_id}/tareas")
def get_tareas(
    tienda_id: int,
    incluir_inactivas: bool = False,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    _ensure_seeded(db, tienda_id)
    q = db.query(TareaLimpieza).filter_by(tienda_id=tienda_id)
    if not incluir_inactivas:
        q = q.filter_by(activa=True)
    tareas = q.order_by(TareaLimpieza.orden, TareaLimpieza.id).all()
    return [{"id": t.id, "key": t.key, "label": t.label, "activa": t.activa, "orden": t.orden} for t in tareas]


class TareaUpdate(BaseModel):
    label:  Optional[str]  = None
    activa: Optional[bool] = None
    orden:  Optional[int]  = None


@router.patch("/{tienda_id}/tareas/{tarea_id}")
def update_tarea(
    tienda_id: int,
    tarea_id:  int,
    body: TareaUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    tarea = db.query(TareaLimpieza).filter_by(id=tarea_id, tienda_id=tienda_id).first()
    if not tarea:
        raise HTTPException(404, "Tarea no encontrada")
    if body.label  is not None: tarea.label  = body.label.strip()
    if body.activa is not None: tarea.activa = body.activa
    if body.orden  is not None: tarea.orden  = body.orden
    db.commit()
    return {"id": tarea.id, "key": tarea.key, "label": tarea.label, "activa": tarea.activa, "orden": tarea.orden}


class TareaCreate(BaseModel):
    label: str


@router.post("/{tienda_id}/tareas", status_code=201)
def create_tarea(
    tienda_id: int,
    body: TareaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "El nombre de la tarea no puede estar vacío")
    key = "custom_" + label.lower().replace(" ", "_")[:40]
    max_orden = db.query(TareaLimpieza).filter_by(tienda_id=tienda_id).count()
    tarea = TareaLimpieza(tienda_id=tienda_id, key=key, label=label, orden=max_orden)
    db.add(tarea)
    db.commit()
    db.refresh(tarea)
    return {"id": tarea.id, "key": tarea.key, "label": tarea.label, "activa": tarea.activa, "orden": tarea.orden}


# ─── Registros semanales ────────────────────────────────────────────────────────

@router.get("/{tienda_id}/semanal")
def get_registros(
    tienda_id: int,
    mes: int,
    anio: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
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
    fecha: Optional[date] = None


@router.post("/{tienda_id}/semanal", status_code=201)
def registrar_tarea(
    tienda_id: int,
    body: RegistrarTareaIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)

    keys_validas = {
        t.key for t in db.query(TareaLimpieza).filter_by(tienda_id=tienda_id, activa=True).all()
    }
    if body.tarea_key not in keys_validas:
        raise HTTPException(400, "Tarea no válida o inactiva para esta tienda")

    fecha = body.fecha or date.today()
    semana = semana_del_mes(fecha)
    inicio, fin = inicio_fin_mes(fecha.month, fecha.year)

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
    tienda_id:   int,
    registro_id: int,
    body: VoBoBody,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    registro = db.query(LimpiezaSemanal).filter_by(id=registro_id, tienda_id=tienda_id).first()
    if not registro:
        raise HTTPException(404, "Registro no encontrado")
    registro.vobo = body.valor
    db.commit()
    return {"id": registro.id, "vobo": registro.vobo}


@router.delete("/{tienda_id}/semanal/{registro_id}", status_code=204)
def eliminar_registro(
    tienda_id:   int,
    registro_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    registro = db.query(LimpiezaSemanal).filter_by(id=registro_id, tienda_id=tienda_id).first()
    if not registro:
        raise HTTPException(404, "Registro no encontrado")
    if registro.usuario_id != user.id and user.rol != "admin":
        raise HTTPException(403, "Sin permiso para eliminar este registro")
    db.delete(registro)
    db.commit()
