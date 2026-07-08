"""Etapa 7: Gestión de notificaciones operativas internas."""
import logging
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.models import Notificacion
from app.core.tz import hoy_col, inicio_dia_col_utc, fin_dia_col_utc

logger = logging.getLogger(__name__)


def crear(db: Session, tienda_id: int, tipo: str, mensaje: str,
          nivel: str = "info", referencia_id: int | None = None,
          leida: bool = False) -> Notificacion:
    """Crea una notificación. NO hace commit — el caller lo hace.

    `leida=True` la registra como ya-vista (no suma al badge de la campana): se
    usa para dejar rastro de dedupe/histórico cuando el canal campana está
    apagado pero igual hay que recordar que el evento ya disparó hoy."""
    notif = Notificacion(
        tienda_id=tienda_id,
        tipo=tipo,
        mensaje=mensaje,
        nivel=nivel,
        referencia_id=referencia_id,
        leida=leida,
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


# ---------------------------------------------------------------------------
# Motor de reglas: dispara por los canales configurados (campana / push)
# ---------------------------------------------------------------------------

def disparar(db: Session, tienda_id: int, tipo: str, mensaje: str, nivel: str,
             referencia_id: int | None = None,
             push_titulo: str | None = None, push_cuerpo: str | None = None) -> None:
    """Dispara una notificación respetando la regla del tipo.

    - Si no hay regla o está inactiva -> no hace nada.
    - SIEMPRE registra la fila (silenciosa con leida=True si la campana está
      apagada): así el dedupe diario es independiente del canal y un push con
      campana off NO se reenvía en cada venta.
    - canal_push -> envía push web (en sesión propia, aislado).

    TRANSACCIÓN-SAFE: NO hace commit ni rollback. La fila de campana se persiste
    con el commit del caller (queda atada al éxito de la operación de negocio —
    p.ej. la venta). Hacer commit/rollback acá corrompía la transacción en curso
    cuando se invoca a mitad de armar un ticket (registrar_movimiento commit=False).
    Nunca lanza: cualquier fallo se loggea pero no rompe el flujo de negocio.
    """
    # Imports locales para evitar import circular (push/notif_reglas pueden
    # importar models que importan esto).
    from app.services import notif_reglas, push
    try:
        regla = notif_reglas.get_regla_efectiva(db, tienda_id, tipo)
        if regla is None or not regla.activa:
            return
        # Registrar siempre (silenciosa si la campana está off) para el dedupe.
        crear(db, tienda_id, tipo, mensaje, nivel, referencia_id,
              leida=not regla.canal_bell)
        if regla.canal_push:
            # Fire-and-forget: NO bloquear la venta con los HTTP de webpush.
            push.enviar_async(tienda_id, push_titulo or "Sistema Café",
                              push_cuerpo or mensaje)
    except Exception as e:  # noqa: BLE001
        logger.warning("notificaciones.disparar fallo (tipo=%s): %s", tipo, e)


def _ya_disparo_hoy(db: Session, tienda_id: int, tipo: str,
                    referencia_id: int | None = None) -> bool:
    """True si ya existe una notificación de ese tipo HOY (dedupe diario).
    Si se pasa referencia_id, restringe a esa referencia."""
    inicio, fin = inicio_dia_col_utc(hoy_col()), fin_dia_col_utc(hoy_col())
    q = db.query(Notificacion).filter(
        Notificacion.tienda_id == tienda_id,
        Notificacion.tipo == tipo,
        Notificacion.fecha >= inicio,
        Notificacion.fecha <= fin,
    )
    if referencia_id is not None:
        q = q.filter(Notificacion.referencia_id == referencia_id)
    return db.query(q.exists()).scalar()


def evaluar_ventas_dia(db: Session, tienda_id: int, total_dia: float) -> None:
    """Dispara la meta de ventas del día si se alcanzó el umbral (una vez por día)."""
    from app.services import notif_reglas
    try:
        regla = notif_reglas.get_regla_efectiva(db, tienda_id, "ventas_dia")
        if not regla or not regla.activa:
            return
        if not regla.umbral or regla.umbral <= 0:
            return
        if total_dia < regla.umbral:
            return
        if _ya_disparo_hoy(db, tienda_id, "ventas_dia"):
            return
        msg = f"Las ventas del dia alcanzaron ${total_dia:,.0f}"
        disparar(
            db, tienda_id, "ventas_dia", msg, regla.nivel or "info",
            push_titulo="Meta de ventas", push_cuerpo=msg,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("evaluar_ventas_dia fallo: %s", e)


def evaluar_venta_sin_descuento(db: Session, tienda_id: int, producto_id: int,
                                producto_nombre: str) -> None:
    """Se vendió un producto sin receta y sin stock propio: la plata entra pero el
    inventario no baja (fuga #3 de la auditoría). Una vez por día y por producto."""
    try:
        if _ya_disparo_hoy(db, tienda_id, "venta_sin_descuento", referencia_id=producto_id):
            return
        msg = f"{producto_nombre} se vende pero no descuenta ningún insumo (sin receta)"
        disparar(
            db, tienda_id, "venta_sin_descuento", msg, "advertencia",
            referencia_id=producto_id,
            push_titulo="Venta sin descuento", push_cuerpo=msg,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("evaluar_venta_sin_descuento fallo: %s", e)


def evaluar_stock(db: Session, tienda_id: int, producto_id: int,
                  producto_nombre: str, estado: str) -> None:
    """Dispara alerta de stock para estado 'critico' o 'agotado'
    (una vez por día y por producto)."""
    if estado not in ("critico", "agotado"):
        return
    tipo = "stock_" + estado
    try:
        if _ya_disparo_hoy(db, tienda_id, tipo, referencia_id=producto_id):
            return
        nombre = producto_nombre or f"#{producto_id}"
        msg = f"Producto {nombre} en nivel {estado}"
        nivel = "critico" if estado == "agotado" else "advertencia"
        disparar(
            db, tienda_id, tipo, msg, nivel, referencia_id=producto_id,
            push_titulo="Alerta de stock", push_cuerpo=msg,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("evaluar_stock fallo: %s", e)
