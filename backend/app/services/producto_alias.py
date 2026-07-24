"""Aliases proveedor→producto: el ENTRENAMIENTO real del escaneo de facturas.

Un alias es el texto con el que un proveedor nombra un producto del inventario
("CAFE ALTA TOSTION X KG" → Café alta tostión). Se aprende solo, de tres vías:
  - "correccion": un humano asignó/cambió el producto en el form de Ingresos —
    la verdad más fuerte, es la única que puede PISAR un alias existente.
  - "escaneo": la barista registró la factura confirmando lo que el escaneo
    sugirió sin cambiarlo.
  - "bootstrap": el backfill de costos leyó una foto vieja y el renglón matcheó
    de forma confiable un item ya registrado.

El escaneo en vivo consulta estos aliases PRIMERO (determinístico y gratis),
antes del producto_id de la IA y del fuzzy por nombre.

Regla de upsert (racional: humano manda):
  - alias nuevo                         → se crea (veces_visto=1)
  - ya existe → MISMO producto          → refuerzo (veces_visto+1)
  - ya existe → OTRO producto           → solo "correccion" lo repunta;
                                          escaneo/bootstrap no tocan y se loguea.

OJO con el privilegio de "correccion": el `origen` que recibe upsert_alias ya
viene DERIVADO server-side (ver services/facturas.py::_origen_alias_derivado) —
la etiqueta origen_match que manda el cliente es solo metadata informativa y
nunca autoriza sobrescribir por sí misma.

Ninguna función commitea: la transacción es del caller (y el caller debe
garantizar que un fallo acá nunca tumbe el guardado principal).
"""
import logging
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.models import ProductoAlias

logger = logging.getLogger(__name__)

ORIGENES_VALIDOS = {"bootstrap", "correccion", "escaneo"}

# Largo de las columnas alias_normalizado / alias_original.
_MAX_LARGO_ALIAS = 200


def normalizar_alias(texto) -> str:
    """La MISMA normalización de nombres que cargar_menu_venta.norm:
    NFKD → ascii (chau tildes y ñ) → espacios colapsados → strip → MAYÚSCULAS.
    SYNC: si cambia esta normalización, actualizar la otra copia:
    backend/cargar_menu_venta.py (norm)."""
    if texto is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def clave_alias(texto) -> str:
    """CLAVE canónica de alias: normalización + truncado al largo de la columna.
    TODO acceso por alias_normalizado (guardar en upsert_alias, buscar en
    mapear_items/_aliases_para_items o cualquier lookup) debe pasar por acá:
    truncar solo al GUARDAR hacía que una descripción >_MAX_LARGO_ALIAS chars
    se guardara recortada pero se buscara completa — y nunca matcheara."""
    return normalizar_alias(texto)[:_MAX_LARGO_ALIAS]


def _existente_por_clave(db, clave):
    """SELECT del alias por su clave canónica (separado para poder simular la
    ventana de carrera del upsert en tests)."""
    return (db.query(ProductoAlias)
            .filter(ProductoAlias.alias_normalizado == clave)
            .first())


def upsert_alias(db, texto_original, producto_id, origen,
                 barista_id=None, barista_nombre=None) -> ProductoAlias | None:
    """Aprende (o refuerza) un alias. Devuelve la fila tocada, o None si no se
    escribió nada (texto vacío, origen inválido o conflicto que no gana).
    NO commitea — eso es del caller.

    `origen` es un input ya DERIVADO por el servidor: el privilegio de pisar un
    alias existente ("correccion") lo decide services/facturas.py comparando el
    alias conocido contra el producto que el humano guardó — nunca la etiqueta
    origen_match del payload del cliente.

    barista_id/barista_nombre: autoría plana (patrón X-Barista-Id) de quién
    enseñó el alias. Se fija al crear y se actualiza al repuntar por corrección;
    un refuerzo no cambia la autoría original.

    Carrera del upsert: si otro request inserta la misma clave entre el SELECT
    y el INSERT, el UNIQUE dispara IntegrityError DENTRO de un SAVEPOINT
    (begin_nested) — se revierte solo este INSERT (la transacción del caller
    sigue viva), se re-consulta y se trata como refuerzo: la señal no se pierde."""
    if origen not in ORIGENES_VALIDOS:
        logger.warning("Alias con origen inválido %r — ignorado", origen)
        return None
    if not producto_id:
        return None
    norm = clave_alias(texto_original)
    if not norm:
        return None
    snapshot = str(texto_original).strip()[:_MAX_LARGO_ALIAS]

    # Con autoflush=False, un alias agregado en ESTA misma transacción (dos
    # renglones iguales en un lote) sería invisible para el query y el segundo
    # upsert duplicaría el INSERT → UNIQUE violation. El flush lo hace visible.
    db.flush()
    existente = _existente_por_clave(db, norm)
    if existente is None:
        alias = ProductoAlias(alias_normalizado=norm, alias_original=snapshot,
                              producto_id=producto_id, origen=origen, veces_visto=1,
                              barista_id=barista_id, barista_nombre=barista_nombre)
        try:
            with db.begin_nested():
                db.add(alias)
                db.flush()
            return alias
        except IntegrityError:
            # Carrera: otro request ganó el INSERT de esta clave entre el
            # SELECT y el flush. El SAVEPOINT revirtió SOLO este INSERT; se
            # re-consulta y se cae al flujo refuerzo/conflicto de abajo para
            # no perder la señal.
            existente = _existente_por_clave(db, norm)
            if existente is None:
                logger.warning(
                    "Alias %r: IntegrityError en el upsert y la re-consulta no "
                    "ve la fila (producto %s, origen %s) — señal descartada",
                    norm, producto_id, origen)
                return None

    if existente.producto_id == producto_id:
        # Refuerzo: el mismo texto volvió a confirmar el mismo producto.
        existente.veces_visto = int(existente.veces_visto or 0) + 1
        return existente

    # Conflicto: el alias apunta a OTRO producto. Solo el humano (correccion)
    # puede pisarlo; un escaneo/bootstrap automático no toca verdad previa.
    if origen == "correccion":
        logger.info("Alias %r repuntado por corrección humana: producto %s → %s",
                    norm, existente.producto_id, producto_id)
        existente.producto_id = producto_id
        existente.origen = "correccion"
        existente.alias_original = snapshot
        existente.veces_visto = 1   # verdad nueva: el historial anterior no cuenta
        # Autoría nueva: quien corrige es quien enseña la verdad vigente.
        existente.barista_id = barista_id
        existente.barista_nombre = barista_nombre
        return existente

    logger.warning("Alias %r ya apunta al producto %s (origen %s) — upsert %s "
                   "hacia el producto %s ignorado",
                   norm, existente.producto_id, existente.origen, origen, producto_id)
    return None


def contar_aliases(db) -> int:
    """Cuántos aliases conoce el sistema (para 'Salud de datos')."""
    return db.query(ProductoAlias).count()


def listar_aliases(db) -> list[dict]:
    """Administración mínima (solo la usa el router admin): qué aprendió el
    sistema y quién lo enseñó — un alias equivocado se auto-refuerza en
    silencio con cada escaneo, así que tiene que poder VERSE y borrarse."""
    filas = (db.query(ProductoAlias)
             .order_by(ProductoAlias.actualizado_en.desc(), ProductoAlias.id.desc())
             .all())
    return [
        {
            "id": f.id,
            "alias_original": f.alias_original,
            "alias_normalizado": f.alias_normalizado,
            "producto_id": f.producto_id,
            "producto_nombre": f.producto.nombre if f.producto else "",
            "origen": f.origen,
            "veces_visto": f.veces_visto,
            "actualizado_en": f.actualizado_en,
            "barista_id": f.barista_id,
            "barista_nombre": f.barista_nombre,
        }
        for f in filas
    ]


def eliminar_alias(db, alias_id: int) -> dict:
    """Borra un alias malo por id (solo admin). Sí commitea: es una operación
    administrativa puntual, no parte de una transacción mayor."""
    fila = db.get(ProductoAlias, alias_id)
    if fila is None:
        raise HTTPException(404, "Alias no encontrado")
    db.delete(fila)
    db.commit()
    return {"ok": True, "id": alias_id}
