"""Etapa 7: Gestión de notificaciones operativas internas."""
from sqlalchemy.orm import Session
from app.models.models import Notificacion


def crear(db: Session, tienda_id: int, tipo: str, mensaje: str,
          nivel: str = "info", referencia_id: int | None = None) -> Notificacion:
    """Crea una notificación. NO hace commit — el caller lo hace."""
    notif = Notificacion(
        tienda_id=tienda_id,
        tipo=tipo,
        mensaje=mensaje,
        nivel=nivel,
        referencia_id=referencia_id,
    )
    db.add(notif)
    return notif


def get_todas(db: Session, tienda_id: int, solo_no_leidas: bool = False,
              limit: int = 50) -> list:
    q = db.query(Notificacion).filter(Notificacion.tienda_id == tienda_id)
    if solo_no_leidas:
        q = q.filter(Notificacion.leida == False)
    return q.order_by(Notificacion.fecha.desc()).limit(limit).all()


def marcar_leida(db: Session, notif_id: int, tienda_id: int) -> bool:
    notif = db.query(Notificacion).filter(
        Notificacion.id == notif_id,
        Notificacion.tienda_id == tienda_id,
    ).first()
    if notif and not notif.leida:
        notif.leida = True
        db.commit()
        return True
    return False


def marcar_todas_leidas(db: Session, tienda_id: int) -> int:
    updated = db.query(Notificacion).filter(
        Notificacion.tienda_id == tienda_id,
        Notificacion.leida == False,
    ).update({"leida": True})
    db.commit()
    return updated
