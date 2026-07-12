from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError
from app.database import get_db
from app.core.security import decode_token
from app.models.models import CajaTurno, TurnoBarista, EstadoTurnoEnum, Usuario

bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db)
) -> Usuario:
    token = credentials.credentials
    try:
        payload = decode_token(token)
        user_id: int = int(payload.get("sub"))
    except (JWTError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    user = db.query(Usuario).filter(Usuario.id == user_id, Usuario.activo == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
    # Si el token contiene tienda_id (sede seleccionada al iniciar turno), usarla
    tienda_override = payload.get("tienda_id")
    if tienda_override is not None:
        # Expulsar del session antes de mutar para evitar persistencia accidental en DB
        db.expunge(user)
        user.tienda_id = int(tienda_override)
    return user

def require_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if current_user.rol != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requiere rol admin")
    return current_user


def get_barista_actor(
    x_barista_id: int | None = Header(None, alias="X-Barista-Id"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> tuple[int | None, str | None]:
    """Barista REAL detrás de la operación. Dos modos, según el dispositivo:

    - Kiosko compartido (PC): el dispositivo es el usuario genérico "Kiosk"; la barista
      concreta llega por el header X-Barista-Id (selector "barista activa").
    - Login individual (celular): el usuario autenticado YA es la barista real, así que
      se usa directamente — sin necesidad de header.

    Así barista_id/barista_nombre queda SIEMPRE con el actor real, venga del PC o del celu.
    Devuelve (None, None) si no se puede determinar — nunca rompe el request."""
    if x_barista_id is not None:
        barista = db.query(Usuario).filter(
            Usuario.id == x_barista_id, Usuario.activo == True
        ).first()
        return (x_barista_id, barista.nombre if barista else None)
    # Login individual: la barista real es el propio usuario (no el dispositivo kiosko).
    if current_user.rol == "barista" and not (current_user.email or "").startswith("kiosk@"):
        return current_user.id, current_user.nombre
    return None, None


def _barista_en_turno_activo(db: Session, tienda_id: int | None, barista_id: int | None) -> bool:
    """True si la barista está en el turno ABIERTO de la sede, sin salida marcada."""
    if not tienda_id or not barista_id:
        return False
    turno = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if not turno:
        return False
    return db.query(TurnoBarista).filter(
        TurnoBarista.turno_id == turno.id,
        TurnoBarista.usuario_id == barista_id,
        TurnoBarista.salida_at.is_(None),
    ).first() is not None


def require_barista_en_turno(
    x_barista_id: int | None = Header(None, alias="X-Barista-Id"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> tuple[int | None, str | None]:
    """Como get_barista_actor pero EXIGE que la barista esté en el turno actual.
    Para operaciones que MUEVEN inventario (merma, recepción, ajuste): en el kiosko
    compartido bloquea a quien no está en turno — evita que alguien ajeno al turno
    mueva cosas y queden atribuidas a otra persona.
    - Admin: exento (opera desde el panel, sin barista).
    - Celular (login individual): la barista es el usuario autenticado.
    - Kiosko: valida X-Barista-Id contra el turno abierto de la sede del dispositivo."""
    if current_user.rol == "admin":
        return (None, None)
    # Celular: la barista real es el propio usuario (no el dispositivo kiosko).
    if x_barista_id is None and current_user.rol == "barista" and not (current_user.email or "").startswith("kiosk@"):
        return (current_user.id, current_user.nombre)
    if x_barista_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Elegí la barista activa (del turno) para registrar esta operación.")
    barista = db.query(Usuario).filter(Usuario.id == x_barista_id, Usuario.activo == True).first()
    if not barista or not _barista_en_turno_activo(db, current_user.tienda_id, x_barista_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esa barista no está en el turno actual. Seleccioná una barista del turno para operar.")
    return (x_barista_id, barista.nombre)


def ensure_tienda_access(current_user: Usuario, tienda_id: int) -> int:
    if current_user.rol == "admin":
        return tienda_id
    if current_user.tienda_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario sin tienda asignada")
    if current_user.tienda_id != tienda_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta tienda")
    return tienda_id


def ensure_turno_access(db: Session, current_user: Usuario, turno_id: int) -> CajaTurno:
    turno = db.query(CajaTurno).filter(CajaTurno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turno no encontrado")
    ensure_tienda_access(current_user, turno.tienda_id)
    return turno
