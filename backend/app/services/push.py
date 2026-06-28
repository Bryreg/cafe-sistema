"""Canal Web Push (PWA) con VAPID.

La clave PÚBLICA no es secreta: viaja al navegador para suscribir el dispositivo,
por eso lleva un default. La clave PRIVADA SÍ es secreta y NO tiene default: si
falta, el canal push queda deshabilitado silenciosamente (la campana sigue).
"""
import os
import json
import logging

from pywebpush import webpush, WebPushException

from app.models.models import PushSubscription

logger = logging.getLogger(__name__)

VAPID_PUBLIC = os.getenv(
    "VAPID_PUBLIC_KEY",
    "BCRlsQC39MijXm4YuFDU4QynY2ABJDLDOHHDIkyJXcRe1Sr7fGodm8CIgjIx8SCOfnjHmm8hx8l9UAYEf1s1I8o",
)
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY")  # secreta, sin default
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:bmgpersonal99@gmail.com")


def public_key() -> str:
    """Clave pública VAPID — la consume el frontend para suscribir el dispositivo."""
    return VAPID_PUBLIC


def guardar_subscription(db, tienda_id, usuario_id, sub: dict) -> PushSubscription:
    """Upsert de una suscripción por endpoint.

    `sub` = {"endpoint": str, "keys": {"p256dh": str, "auth": str}}.
    Si el endpoint ya existe, actualiza tienda/usuario/keys; si no, crea.
    """
    endpoint = sub["endpoint"]
    keys = sub.get("keys", {}) or {}
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")

    fila = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint
    ).first()
    if fila:
        fila.tienda_id = tienda_id
        fila.usuario_id = usuario_id
        fila.p256dh = p256dh
        fila.auth = auth
    else:
        fila = PushSubscription(
            tienda_id=tienda_id,
            usuario_id=usuario_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
        )
        db.add(fila)
    db.commit()
    db.refresh(fila)
    return fila


def borrar_subscription(db, endpoint: str) -> bool:
    """Borra una suscripción por endpoint. Devuelve True si borró algo."""
    fila = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint
    ).first()
    if not fila:
        return False
    db.delete(fila)
    db.commit()
    return True


def enviar(db, tienda_id, titulo: str, cuerpo: str, url: str = "/dashboard") -> int:
    """Envía un push a las suscripciones de la tienda (y a las globales con
    tienda_id NULL). Nunca lanza: cuenta y devuelve los envíos exitosos.

    Usa una SESIÓN PROPIA (aislada), no la del caller: el motor de notificaciones
    a veces corre a mitad de una transacción de venta, y un commit/rollback acá
    sobre esa sesión la corrompería. La sesión propia lee suscripciones ya
    commiteadas y limpia las expiradas (404/410) sin tocar la transacción de
    negocio. El parámetro `db` se ignora a propósito (compat de firma).
    """
    if VAPID_PRIVATE is None:
        return 0

    from app.database import SessionLocal
    enviados = 0
    s_db = SessionLocal()
    try:
        subs = s_db.query(PushSubscription).filter(
            (PushSubscription.tienda_id == tienda_id)
            | (PushSubscription.tienda_id.is_(None))
        ).all()
        payload = json.dumps({
            "title": titulo,
            "body": cuerpo,
            "url": url,
            "icon": "/icon-192.png",
        })
        for s in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": s.endpoint,
                        "keys": {"p256dh": s.p256dh, "auth": s.auth},
                    },
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE,
                    vapid_claims={"sub": VAPID_SUBJECT},
                )
                enviados += 1
            except WebPushException as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):
                    # Suscripción expirada: limpiar en la sesión propia.
                    try:
                        s_db.delete(s)
                        s_db.commit()
                    except Exception:
                        s_db.rollback()
                else:
                    logger.warning("WebPush fallo (status=%s): %s", status, e)
            except Exception as e:  # noqa: BLE001 — nunca romper el flujo de negocio
                logger.warning("WebPush error inesperado: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.warning("push.enviar fallo global: %s", e)
    finally:
        s_db.close()
    return enviados
