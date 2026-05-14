from datetime import datetime, date
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import Mantenimiento, TipoMantenimientoEnum


def crear(db: Session, tienda_id: int, usuario_id: int, tipo: str, titulo: str,
          fecha_realizado: datetime, descripcion: str | None = None,
          fecha_proximo: datetime | None = None, costo: float | None = None,
          tecnico: str | None = None, imagen_url: str | None = None):
    if not titulo.strip():
        raise HTTPException(status_code=400, detail="El título es obligatorio")
    m = Mantenimiento(
        tienda_id=tienda_id,
        usuario_id=usuario_id,
        tipo=tipo,
        titulo=titulo.strip(),
        descripcion=descripcion,
        fecha_realizado=fecha_realizado,
        fecha_proximo=fecha_proximo,
        costo=costo,
        tecnico=tecnico,
        imagen_url=imagen_url,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _serial(m)


def listar(db: Session, tienda_id: int, tipo: str | None = None):
    q = db.query(Mantenimiento).filter(Mantenimiento.tienda_id == tienda_id)
    if tipo:
        q = q.filter(Mantenimiento.tipo == tipo)
    rows = q.order_by(Mantenimiento.fecha_realizado.desc()).all()
    return [_serial(r) for r in rows]


def proximos(db: Session, tienda_id: int | None = None):
    """Mantenimientos con fecha_proximo definida, ordenados por fecha_proximo asc."""
    q = db.query(Mantenimiento).filter(Mantenimiento.fecha_proximo.isnot(None))
    if tienda_id:
        q = q.filter(Mantenimiento.tienda_id == tienda_id)
    rows = q.order_by(Mantenimiento.fecha_proximo.asc()).all()
    hoy = datetime.utcnow()
    result = []
    for r in rows:
        s = _serial(r)
        dias = (r.fecha_proximo - hoy).days if r.fecha_proximo else None
        s["dias_para_proximo"] = dias
        s["vencido"] = dias is not None and dias < 0
        result.append(s)
    return result


def eliminar(db: Session, mantenimiento_id: int, tienda_id: int):
    m = db.query(Mantenimiento).filter(
        Mantenimiento.id == mantenimiento_id,
        Mantenimiento.tienda_id == tienda_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mantenimiento no encontrado")
    db.delete(m)
    db.commit()
    return {"ok": True}


def _serial(m: Mantenimiento) -> dict:
    return {
        "id": m.id,
        "tienda_id": m.tienda_id,
        "tipo": m.tipo,
        "titulo": m.titulo,
        "descripcion": m.descripcion,
        "fecha_realizado": m.fecha_realizado,
        "fecha_proximo": m.fecha_proximo,
        "costo": m.costo,
        "tecnico": m.tecnico,
        "imagen_url": m.imagen_url,
        "usuario_nombre": m.usuario.nombre if m.usuario else None,
        "created_at": m.created_at,
    }
