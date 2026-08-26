"""Un proveedor, un nombre.

En producción llegamos a 41 nombres de proveedor para ~23 negocios reales:
«Galerías», «Galerias» y «Galeria» eran el mismo supermercado con 17 facturas
partidas en tres, y lo mismo pasaba con Maria Maria (3 grafías), Cafexcoop (3),
Calipulpas (3), KOS (3) y Wilenses (3). El nombre lo teclea —o lo lee de una
foto— quien registra la factura, y `FacturaCompra.proveedor` es texto libre sin
catálogo detrás, así que cada variante nace un proveedor nuevo. Con la lista
partida, «cuánto le compro a Galerías» y «qué me cobró la última vez» dan
números que no son.

Este módulo es la puerta: antes de guardar una factura, el nombre entrante se
compara contra los que YA existen y, si es el mismo negocio escrito distinto, se
guarda con la grafía que ya estaba. No inventa un catálogo nuevo ni obliga a
elegir de una lista: el historial ES el catálogo.

DOS REGLAS, Y LAS DOS SON CONSERVADORAS —fundir dos proveedores DISTINTOS es
peor que dejar una grafía suelta, porque mezcla plata de dos negocios—:

  1. MISMA CLAVE. La clave ignora mayúsculas, tildes, puntuación, espacios y las
     coletillas jurídicas y genéricas (s.a.s, ltda, «productos», «industria»,
     «almacenes», «pastelería»…). Así «Galerías» = «Galerias» = «Galeria», y
     «PRODUCTOS WILENSES» = «Wilenses».
  2. UNO CONTIENE AL OTRO, por el principio o por el final. «Calipulpas» está al
     final de «JUAN CARLOS PARRA/CALIPULPAS», y «Delitas» al final de
     «INDUALIMENTOS DELITAS S.A.S.». Se exige que el nombre conocido tenga al
     menos `_MIN_CONTENIDO` caracteres y que calce en un extremo: sin eso, un
     proveedor de nombre corto se tragaría a cualquiera que lo mencione.

Lo que NO hace: adivinar por parecido (distancia de edición). «Café Expreso
Coop» y «Cafexcoop» son el mismo negocio y este módulo NO los une — eso queda
para el escaneo, que ve la lista de conocidos y elige, y para el admin, que
puede corregir el nombre de la factura a mano. Preferimos una grafía de más
antes que dos negocios fundidos por error.
"""
import re
import unicodedata

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import FacturaCompra

# Palabras que no distinguen a un negocio de otro: formas jurídicas y genéricos
# del rubro. Salen de la clave para que «PRODUCTOS WILENSES» y «Wilenses»
# coincidan. OJO al agregar: cada palabra acá hace la clave MÁS permisiva.
_RUIDO = {
    "sa", "sas", "sa s", "ltda", "limitada", "eu", "cia", "y", "e",
    "productos", "producto", "industria", "industrias", "indualimentos",
    "almacenes", "almacen", "supermercados", "supermercado", "distribuidora",
    "comercializadora", "alimentos", "pasteleria", "panaderia",
}

# Largo mínimo del nombre conocido para que la regla de «uno contiene al otro»
# se anime a fundir. Con menos, un nombre corto (Paola, Mimos) se colaría dentro
# de cualquier razón social que lo mencione de pasada.
_MIN_CONTENIDO = 5


def clave(nombre: str | None) -> str:
    """Huella comparable de un nombre de proveedor: sin tildes, sin mayúsculas,
    sin puntuación, sin espacios y sin coletillas. Devuelve '' si no hay nombre.

    Los espacios se van al final (no antes) para que «Cafex coop» y «Cafexcoop»
    den la misma clave, pero las palabras de ruido se puedan quitar enteras.

    Ojo con las siglas punteadas: «S.A.S.» se parte en tres letras sueltas, y
    ninguna letra suelta está en `_RUIDO`, así que sin volver a pegarlas la
    coletilla sobrevivía como «sas» y «KOS COLOMBIA S.A.S» no coincidía con
    «KOS COLOMBIA». Por eso las corridas de letras sueltas se recomponen en una
    palabra ANTES de filtrar el ruido."""
    if not nombre:
        return ""
    s = unicodedata.normalize("NFD", nombre.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)

    # Recomponer siglas: s a s -> sas (dos o más letras sueltas seguidas).
    palabras, corrida = [], []
    for w in s.split():
        if len(w) == 1 and w.isalpha():
            corrida.append(w)
            continue
        if corrida:
            palabras.append("".join(corrida) if len(corrida) > 1 else corrida[0])
            corrida = []
        palabras.append(w)
    if corrida:
        palabras.append("".join(corrida) if len(corrida) > 1 else corrida[0])

    return "".join(p for p in palabras if p and p not in _RUIDO)


def conocidos(db: Session, tienda_id: int | None = None) -> list[str]:
    """Los proveedores que ya existen, de más facturas a menos.

    Una clave puede tener varias grafías (justo lo que este módulo viene a
    cerrar): gana la MÁS USADA, y a igual uso la primera alfabéticamente para
    que el resultado no dependa del orden del SELECT."""
    q = db.query(FacturaCompra.proveedor, func.count().label("n"))
    if tienda_id is not None:
        q = q.filter(FacturaCompra.tienda_id == tienda_id)
    filas = q.group_by(FacturaCompra.proveedor).all()

    mejor: dict[str, tuple[int, str]] = {}
    for nombre, n in filas:
        nombre = (nombre or "").strip()
        if not nombre:
            continue
        k = clave(nombre)
        if not k:
            continue
        actual = mejor.get(k)
        if actual is None or n > actual[0] or (n == actual[0] and nombre < actual[1]):
            mejor[k] = (n, nombre)
    return [nombre for _, (n, nombre) in sorted(mejor.items(), key=lambda kv: (-kv[1][0], kv[1][1]))]


def canonizar(db: Session, nombre: str | None, tienda_id: int | None = None) -> str | None:
    """El nombre con el que hay que guardar: la grafía YA EXISTENTE si es el
    mismo negocio, o el nombre limpio tal cual si es un proveedor nuevo.

    `tienda_id=None` (el default) compara contra las DOS sedes a propósito: el
    mismo proveedor le vende a las dos y no queremos que Vida y Palmetto
    escriban «Galerías» distinto."""
    limpio = (nombre or "").strip()
    if not limpio:
        return nombre
    k = clave(limpio)
    if not k:
        return limpio

    lista = conocidos(db, tienda_id)
    # Regla 1: misma clave. Es la que resuelve mayúsculas, tildes y coletillas.
    for existente in lista:
        if clave(existente) == k:
            return existente
    # Regla 2: uno contiene al otro por un extremo. Se exige el largo mínimo en
    # AMBOS lados —si no, un entrante corto («Coop») se pegaría al primer
    # conocido que lo termine— y se recorre en orden de uso, así el proveedor
    # más establecido gana cuando dos podrían calzar.
    if len(k) < _MIN_CONTENIDO:
        return limpio
    for existente in lista:
        ke = clave(existente)
        if len(ke) < _MIN_CONTENIDO:
            continue
        if k.startswith(ke) or k.endswith(ke) or ke.startswith(k) or ke.endswith(k):
            return existente
    return limpio
