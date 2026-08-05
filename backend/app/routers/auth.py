from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta
import secrets
from app.database import get_db
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UsuarioPublic, UsuarioAdmin, ActualizarUsuario, SetPasswordRequest, KioskPinRequest, MetaVentasRequest
from app.models.models import Usuario, Tienda, RolEnum, Configuracion
from app.core.security import verify_password, hash_password, create_access_token
from app.core.deps import require_admin, get_current_user, ensure_tienda_access
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_kiosk_pin(db: Session) -> str:
    """PIN de kiosko vigente: la fila en `configuracion` manda; si no existe, cae al env var KIOSK_PIN."""
    row = db.query(Configuracion).filter(Configuracion.clave == "kiosk_pin").first()
    if row and row.valor:
        return row.valor
    return settings.KIOSK_PIN or ""


@router.post("/seleccionar-sede", response_model=TokenResponse)
def seleccionar_sede(tienda_id: int, db: Session = Depends(get_db),
                     user: Usuario = Depends(get_current_user)):
    """Emite un nuevo token con la sede seleccionada embebida, para que el backend la use en lugar de la DB."""
    tienda = db.query(Tienda).filter(Tienda.id == tienda_id, Tienda.activa == True).first()
    if not tienda:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    token = create_access_token({"sub": str(user.id), "tienda_id": tienda_id})
    return TokenResponse(
        access_token=token, rol=user.rol.value,
        nombre=user.nombre, tienda_id=tienda_id, user_id=user.id
    )


@router.get("/tiendas")
def listar_tiendas(db: Session = Depends(get_db)):
    """Lista pública de sedes activas para selección al iniciar turno."""
    return [{"id": t.id, "nombre": t.nombre} for t in db.query(Tienda).filter(Tienda.activa == True).all()]


@router.get("/usuarios", response_model=List[UsuarioPublic])
def listar_usuarios(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Lista de usuarios activos — SOLO admin (antes era pública: filtraba el roster + user_id)."""
    return db.query(Usuario).filter(Usuario.activo == True).all()


@router.get("/baristas", response_model=List[UsuarioPublic])
def listar_baristas(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Baristas activas para elegir quiénes entran al turno.

    Las baristas ROTAN entre sedes, así que se listan TODAS las activas (no se filtra por
    la sede del kiosko). Excluye el usuario kiosko/dispositivo (que no es una barista real).
    Reemplaza el uso público de /auth/usuarios."""
    return db.query(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol == RolEnum.barista,
        ~Usuario.email.like("kiosk@%"),
    ).order_by(Usuario.nombre).all()


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == data.email, Usuario.activo == True).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    user.ultimo_acceso = datetime.utcnow()
    db.commit()
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token, rol=user.rol.value,
        nombre=user.nombre, tienda_id=user.tienda_id, user_id=user.id
    )


@router.post("/logout")
def logout():
    """Stateless logout — client must discard the token from storage."""
    return {"message": "Logged out"}


@router.get("/me")
def me(user: Usuario = Depends(get_current_user)):
    """Etapa 9: Verifica sesión activa y retorna datos del usuario."""
    return {
        "id": user.id, "nombre": user.nombre, "email": user.email,
        "rol": user.rol.value, "tienda_id": user.tienda_id,
        "ultimo_acceso": user.ultimo_acceso,
    }


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    if db.query(Usuario).filter(Usuario.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email ya registrado")
    user = Usuario(
        nombre=data.nombre, email=data.email,
        password_hash=hash_password(data.password),
        rol=data.rol, tienda_id=data.tienda_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "nombre": user.nombre, "email": user.email}


@router.get("/admin/usuarios", response_model=List[UsuarioAdmin])
def listar_usuarios_admin(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Lista completa de usuarios para el panel admin."""
    usuarios = db.query(Usuario).order_by(Usuario.activo.desc(), Usuario.nombre).all()
    result = []
    for u in usuarios:
        tienda = db.query(Tienda).filter(Tienda.id == u.tienda_id).first() if u.tienda_id else None
        result.append(UsuarioAdmin(
            id=u.id, nombre=u.nombre, email=u.email, rol=u.rol.value,
            tienda_id=u.tienda_id, tienda_nombre=tienda.nombre if tienda else None,
            activo=u.activo,
            ultimo_acceso=u.ultimo_acceso.isoformat() if u.ultimo_acceso else None,
        ))
    return result


@router.patch("/usuarios/{user_id}")
def actualizar_usuario(user_id: int, data: ActualizarUsuario, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Actualiza nombre, rol, sede o estado activo de un usuario."""
    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if data.nombre is not None:
        user.nombre = data.nombre
    if data.rol is not None:
        user.rol = data.rol
    if data.tienda_id is not None:
        user.tienda_id = data.tienda_id
    if data.activo is not None:
        user.activo = data.activo
    db.commit()
    db.refresh(user)
    return {"id": user.id, "nombre": user.nombre, "activo": user.activo}


@router.post("/usuarios/{user_id}/set-password")
def set_password(user_id: int, data: SetPasswordRequest, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Establece o resetea la contraseña de un usuario (típicamente un admin)."""
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres")
    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.password_hash = hash_password(data.password)
    db.commit()
    return {"ok": True}


@router.get("/config/kiosk-pin")
def get_kiosk_pin(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """PIN de kiosko vigente, para que el admin lo consulte/comparta. Solo admin."""
    return {"pin": _get_kiosk_pin(db)}


@router.put("/config/kiosk-pin")
def set_kiosk_pin(data: KioskPinRequest, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Cambia el PIN de kiosko (se guarda en la DB; pisa al env var). Solo admin."""
    pin = data.pin.strip()
    if len(pin) < 4:
        raise HTTPException(status_code=400, detail="El PIN debe tener al menos 4 caracteres")
    row = db.query(Configuracion).filter(Configuracion.clave == "kiosk_pin").first()
    if row:
        row.valor = pin
    else:
        db.add(Configuracion(clave="kiosk_pin", valor=pin))
    db.commit()
    return {"ok": True}


@router.get("/config/meta-ventas/{tienda_id}")
def get_meta_ventas(tienda_id: int, db: Session = Depends(get_db),
                    user: Usuario = Depends(get_current_user)):
    """Meta de ventas mensual de la sede. La barista consulta la de SU tienda
    (para el contador del turno); el admin, la de cualquiera. 0 = sin meta."""
    ensure_tienda_access(user, tienda_id)
    row = db.query(Configuracion).filter(
        Configuracion.clave == f"meta_ventas_mes_{tienda_id}").first()
    meta = 0.0
    if row and row.valor:
        try:
            meta = float(row.valor)
        except ValueError:
            meta = 0.0
    return {"tienda_id": tienda_id, "meta": meta}


@router.put("/config/meta-ventas/{tienda_id}")
def set_meta_ventas(tienda_id: int, data: MetaVentasRequest, db: Session = Depends(get_db),
                    _: Usuario = Depends(require_admin)):
    """Define la meta de ventas mensual de la sede (se guarda en la DB, clave
    meta_ventas_mes_{tienda_id}). Solo admin; meta=0 significa "sin meta"."""
    if data.meta < 0:
        raise HTTPException(status_code=400, detail="La meta no puede ser negativa")
    clave = f"meta_ventas_mes_{tienda_id}"
    row = db.query(Configuracion).filter(Configuracion.clave == clave).first()
    if row:
        row.valor = str(data.meta)
    else:
        db.add(Configuracion(clave=clave, valor=str(data.meta)))
    db.commit()
    return {"tienda_id": tienda_id, "meta": data.meta}


@router.post("/kiosk-init", response_model=TokenResponse)
def kiosk_init(tienda_id: int, kiosk_pin: str, db: Session = Depends(get_db)):
    """Activa modo kiosco para un dispositivo. El PIN sale de `configuracion` (o del env var de respaldo)."""
    pin_vigente = _get_kiosk_pin(db)
    if not pin_vigente or kiosk_pin != pin_vigente:
        raise HTTPException(status_code=401, detail="PIN de kiosco incorrecto")
    tienda = db.query(Tienda).filter(Tienda.id == tienda_id, Tienda.activa == True).first()
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    kiosk_email = f"kiosk@tienda{tienda_id}.device"
    kiosk_user = db.query(Usuario).filter(Usuario.email == kiosk_email).first()
    if not kiosk_user:
        kiosk_user = Usuario(
            nombre="Kiosk", email=kiosk_email,
            password_hash=hash_password(secrets.token_hex(32)),
            rol=RolEnum.barista, tienda_id=tienda_id, activo=True,
        )
        db.add(kiosk_user)
        db.commit()
        db.refresh(kiosk_user)
    token = create_access_token(
        {"sub": str(kiosk_user.id), "tienda_id": tienda_id, "kiosk": True},
        expires_delta=timedelta(days=365 * 10),
    )
    return TokenResponse(
        access_token=token, rol="barista", nombre="Kiosk",
        tienda_id=tienda_id, user_id=kiosk_user.id, kiosk=True,
    )


@router.post("/usuarios")
def crear_usuario(data: RegisterRequest, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)):
    """Crea un usuario. El admin inicia sesión → requiere email + contraseña.
    La barista es solo un perfil del roster (no inicia sesión): alcanza con el nombre;
    el email y la contraseña se generan internos."""
    nombre = (data.nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    email = (data.email or "").strip().lower()

    if data.rol == "admin":
        if not email or not data.password:
            raise HTTPException(status_code=400, detail="Un admin necesita email y contraseña")
        if db.query(Usuario).filter(Usuario.email == email).first():
            raise HTTPException(status_code=400, detail="Email ya registrado")
        password = data.password
    else:
        # Barista: email interno único (no se usa para login) + clave aleatoria.
        if email and db.query(Usuario).filter(Usuario.email == email).first():
            raise HTTPException(status_code=400, detail="Email ya registrado")
        if not email:
            slug = "".join(ch for ch in nombre.lower() if ch.isalnum()) or "barista"
            email = f"{slug}@barista.local"
            n = 1
            while db.query(Usuario).filter(Usuario.email == email).first():
                n += 1
                email = f"{slug}{n}@barista.local"
        password = secrets.token_hex(16)

    user = Usuario(
        nombre=nombre, email=email,
        password_hash=hash_password(password),
        rol=data.rol, tienda_id=data.tienda_id, activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "nombre": user.nombre, "email": user.email}
