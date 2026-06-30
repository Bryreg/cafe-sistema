"""Motor de Rutinas — recurrentes como EVENTOS (no checklists).

Dos piezas: RutinaPlantilla (la regla/expectativa) y RutinaEvento (el hecho).
El cumplimiento NO es un booleano: es la comparación derivada entre lo esperado
(plantilla.esperadas_por_periodo) y lo realizado (COUNT de eventos). Sin scheduler:
la verdad son los eventos; el cumplimiento se calcula al leer.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
from app.models.models import RutinaPlantilla, RutinaEvento
from app.services.caja import get_turno_activo
import logging

logger = logging.getLogger(__name__)


def _plantillas_aplicables(db: Session, tienda_id: int):
    """Plantillas activas de la sede + las globales (tienda_id NULL = todas las sedes)."""
    return (
        db.query(RutinaPlantilla)
        .filter(
            RutinaPlantilla.activa == True,
            (RutinaPlantilla.tienda_id == tienda_id) | (RutinaPlantilla.tienda_id.is_(None)),
        )
        .order_by(RutinaPlantilla.categoria, RutinaPlantilla.nombre)
        .all()
    )


def get_pendientes(db: Session, tienda_id: int):
    """Rutinas esperadas en el turno actual menos las ya registradas en este turno."""
    turno = get_turno_activo(db, tienda_id)
    out = []
    for p in _plantillas_aplicables(db, tienda_id):
        hechas = 0
        if turno:
            hechas = db.query(func.count(RutinaEvento.id)).filter(
                RutinaEvento.plantilla_id == p.id,
                RutinaEvento.turno_id == turno.id,
            ).scalar() or 0
        esperadas = p.esperadas_por_periodo or 1
        out.append({
            "plantilla_id": p.id,
            "clave": p.clave,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "frecuencia": p.frecuencia.value,
            "esperadas": esperadas,
            "hechas": int(hechas),
            "pendientes": max(esperadas - int(hechas), 0),
            "requiere_evidencia": p.requiere_evidencia,
            "requiere_valor": p.requiere_valor,
        })
    return out


def registrar_evento(db: Session, tienda_id: int, plantilla_id: int, usuario_id: int,
                     valor: float | None = None, nota: str | None = None,
                     imagen_url: str | None = None,
                     barista_id: int | None = None, barista_nombre: str | None = None):
    """Registra la ejecución de una rutina como un evento (fecha/usuario/turno)."""
    plantilla = db.query(RutinaPlantilla).filter(RutinaPlantilla.id == plantilla_id).first()
    if not plantilla:
        raise HTTPException(status_code=404, detail="Rutina no encontrada")
    if plantilla.requiere_valor and valor is None:
        raise HTTPException(status_code=400, detail="Esta rutina requiere un valor (ej. temperatura)")
    if plantilla.requiere_evidencia and not imagen_url:
        raise HTTPException(status_code=400, detail="Esta rutina requiere evidencia fotográfica")

    turno = get_turno_activo(db, tienda_id)
    ev = RutinaEvento(
        plantilla_id=plantilla_id,
        tienda_id=tienda_id,
        dia_operativo_id=(turno.dia_operativo_id if turno else None),
        turno_id=(turno.id if turno else None),
        usuario_id=usuario_id,
        valor=valor,
        nota=nota,
        imagen_url=imagen_url,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    logger.info("Rutina '%s' registrada (evento %s) en tienda %s", plantilla.clave, ev.id, tienda_id)
    return ev


def get_cumplimiento(db: Session, tienda_id: int, dia_operativo_id: int | None = None):
    """Esperado vs realizado por plantilla. Acotado al día si se pasa dia_operativo_id."""
    out = []
    for p in _plantillas_aplicables(db, tienda_id):
        q = db.query(func.count(RutinaEvento.id)).filter(RutinaEvento.plantilla_id == p.id)
        if dia_operativo_id:
            q = q.filter(RutinaEvento.dia_operativo_id == dia_operativo_id)
        else:
            q = q.filter(RutinaEvento.tienda_id == tienda_id)
        hechas = int(q.scalar() or 0)
        out.append({
            "plantilla_id": p.id,
            "clave": p.clave,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "esperadas": p.esperadas_por_periodo or 1,
            "hechas": hechas,
        })
    return out


def listar_plantillas(db: Session, tienda_id: int | None = None):
    q = db.query(RutinaPlantilla)
    if tienda_id is not None:
        q = q.filter((RutinaPlantilla.tienda_id == tienda_id) | (RutinaPlantilla.tienda_id.is_(None)))
    return q.order_by(RutinaPlantilla.categoria, RutinaPlantilla.nombre).all()


def crear_plantilla(db: Session, data: dict):
    p = RutinaPlantilla(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# Claves de panel (5 rutinas de 1 clic)
_PANEL_DEFS = [
    {"k": "limpieza", "nombre": "Limpieza General", "every": 120, "track": True},
    {"k": "surtido",  "nombre": "Surtido",           "every": 120, "track": True},
    {"k": "vitrina",  "nombre": "Revisión Vitrina",  "every": 180, "track": True},
    {"k": "novedad",  "nombre": "Novedad",            "every": None, "track": False},
    {"k": "merma_op", "nombre": "Merma rápida",       "every": None, "track": False},
]


def get_estado_turno(db: Session, tienda_id: int):
    """Último evento por clave dentro del turno activo, minutos transcurridos y conteo."""
    from datetime import datetime
    turno = get_turno_activo(db, tienda_id)
    now = datetime.utcnow()
    result = []
    for defn in _PANEL_DEFS:
        q = (
            db.query(RutinaEvento)
            .join(RutinaPlantilla, RutinaEvento.plantilla_id == RutinaPlantilla.id)
            .filter(RutinaPlantilla.clave == defn["k"])
        )
        if turno:
            q = q.filter(RutinaEvento.turno_id == turno.id)
        else:
            q = q.filter(RutinaEvento.tienda_id == tienda_id)
        count = int(q.count())
        last = q.order_by(RutinaEvento.fecha.desc()).first()
        minutes_ago = None
        status = None
        # Solo calcular antigüedad/estado con turno activo: entre turnos el último evento
        # puede ser de hace días y marcaría todo en "alert" sin sentido.
        if last and turno:
            diff = now - last.fecha
            minutes_ago = int(diff.total_seconds() / 60)
            if defn["track"] and defn["every"]:
                ratio = minutes_ago / defn["every"]
                status = "alert" if ratio >= 1 else ("warn" if ratio >= 0.8 else "ok")
        result.append({
            "clave": defn["k"],
            "nombre": defn["nombre"],
            "every": defn["every"],
            "track": defn["track"],
            "ultimo": last.fecha.isoformat() if last else None,
            "minutos": minutes_ago,
            "status": status,
            "count": count,
        })
    return result


def get_frecuencias():
    """Umbrales de frecuencia controlada — no hardcodear en el front."""
    return [
        {"clave": d["k"], "nombre": d["nombre"], "every": d["every"]}
        for d in _PANEL_DEFS
        if d["track"]
    ]


def get_bitacora(db: Session, tienda_id: int):
    """Línea de tiempo del turno activo: inicio + obligatorios + rutinas, orden asc."""
    from app.models.models import Usuario as UsuarioModel
    turno = get_turno_activo(db, tienda_id)
    entries = []
    if not turno:
        return entries

    def _iso(val):
        return val.isoformat() if hasattr(val, "isoformat") else str(val)

    entries.append({"fecha": _iso(turno.fecha_apertura), "txt": "Turno iniciado", "by": None, "hito": True})

    if turno.tiene_cuadre_llegada:
        entries.append({"fecha": _iso(turno.fecha_apertura), "txt": "Cuadre de llegada completado", "by": None, "hito": True})

    if turno.tiene_conteo_apertura:
        ts = turno.ts_conteo_apertura or turno.fecha_apertura
        entries.append({"fecha": _iso(ts), "txt": "Conteo de apertura completado", "by": None, "hito": True})

    eventos = (
        db.query(RutinaEvento)
        .filter(RutinaEvento.turno_id == turno.id)
        .order_by(RutinaEvento.fecha)
        .all()
    )
    for ev in eventos:
        u = db.query(UsuarioModel).filter(UsuarioModel.id == ev.usuario_id).first()
        p = ev.plantilla
        entries.append({
            "fecha": _iso(ev.fecha),
            "txt": f"{p.nombre if p else 'Rutina'} registrada",
            "by": u.nombre if u else None,
            "hito": False,
        })

    entries.sort(key=lambda e: e["fecha"])
    return entries


def get_cumplimiento_semana(db: Session, tienda_id: int):
    """Registros por barista y por rutina en los últimos 7 días."""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from app.models.models import Usuario as UsuarioModel

    desde = datetime.utcnow() - timedelta(days=7)

    por_rutina = []
    for defn in _PANEL_DEFS:
        total = (
            db.query(func.count(RutinaEvento.id))
            .join(RutinaPlantilla, RutinaEvento.plantilla_id == RutinaPlantilla.id)
            .filter(
                RutinaPlantilla.clave == defn["k"],
                RutinaEvento.tienda_id == tienda_id,
                RutinaEvento.fecha >= desde,
            )
            .scalar() or 0
        )
        por_rutina.append({"clave": defn["k"], "nombre": defn["nombre"], "total": int(total), "track": defn["track"]})

    usuarios = db.query(UsuarioModel).filter(
        UsuarioModel.tienda_id == tienda_id, UsuarioModel.rol == "barista"
    ).all()
    por_barista = []
    for u in usuarios:
        cnt = int(
            db.query(func.count(RutinaEvento.id))
            .filter(
                RutinaEvento.tienda_id == tienda_id,
                RutinaEvento.usuario_id == u.id,
                RutinaEvento.fecha >= desde,
            )
            .scalar() or 0
        )
        por_barista.append({"id": u.id, "nombre": u.nombre, "registros": cnt})

    por_barista.sort(key=lambda x: x["registros"], reverse=True)
    max_reg = max((b["registros"] for b in por_barista), default=1) or 1
    for b in por_barista:
        b["pct"] = round(b["registros"] / max_reg * 100)

    return {
        "por_rutina": por_rutina,
        "por_barista": por_barista,
        "total_eventos": sum(b["registros"] for b in por_barista),
    }


def registrar_por_clave(db: Session, tienda_id: int, clave: str, usuario_id: int,
                        nota: str | None = None,
                        barista_id: int | None = None, barista_nombre: str | None = None):
    """Registra un evento buscando la plantilla por clave (global o de tienda)."""
    plantilla = (
        db.query(RutinaPlantilla)
        .filter(
            RutinaPlantilla.clave == clave,
            (RutinaPlantilla.tienda_id == tienda_id) | (RutinaPlantilla.tienda_id.is_(None)),
            RutinaPlantilla.activa == True,
        )
        .first()
    )
    if not plantilla:
        raise HTTPException(status_code=404, detail=f"Rutina '{clave}' no encontrada")
    return registrar_evento(db, tienda_id, plantilla.id, usuario_id, nota=nota,
                            barista_id=barista_id, barista_nombre=barista_nombre)
