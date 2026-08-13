"""Orden fijo del conteo: el recorrido físico con que se camina el local.

El dueño dictó una lista en tres bloques (las tres zonas que las baristas
recorren al contar). Este módulo la traduce a `Producto.orden_conteo`, que es
lo que las pantallas de conteo usan para ordenar las filas.

Por qué el matching es conservador
----------------------------------
La lista del dueño usa SUS nombres ("T CHOCOLATE", "VELINO MACADAMIA") y la
base usa los suyos ("Torta Chocolate", "SABORIZANTE MACADAMIA"). Un puente
flojo entre los dos —un `contiene`, un fuzzy— pondría "Salsa Chocolate" en la
fila de la torta, y la barista contaría el frasco creyendo que cuenta la
vitrina. Un conteo equivocado es peor que un conteo desordenado: el desorden se
ve, el error no.

Por eso solo hay dos formas de matchear, las dos declaradas a mano en
`data/orden_conteo.json`:
  1. igualdad del nombre NORMALIZADO contra una `variante` de la entrada;
  2. prefijo normalizado, cuando la entrada declara `prefijo` (una entrada de
     la lista que en el catálogo son varios productos: PULPAS, AROMATICAS).
Todo lo demás queda en NULL → se cuenta al final, alfabético.

Un producto reclamado por DOS entradas tampoco se asigna: dos posiciones
posibles es exactamente la duda que la regla manda no resolver sola.

Qué NO hace
-----------
No pisa una posición que ya tiene valor. La única forma de que el cargador
vuelva a sembrar un producto es devolverlo a NULL (el admin lo hace con
PATCH /inventario/productos/{id} mandando orden_conteo = -1). Detectar "esto lo
movió un humano" sin guardar un espejo de lo sembrado no se puede hacer barato
y honesto a la vez, así que el cargador no lo intenta: escribe únicamente sobre
NULL. El reporte sí muestra qué posiciones difieren de lo que sembraría hoy.

El arranque nunca se cae por este archivo: `sembrar()` atrapa todo. Un JSON
malformado deja el conteo en el orden que ya tenía, que es exactamente lo que
pasaba antes de esta feature.
"""
import json
import logging
import os

from app.models.models import Producto
# Una sola normalización de nombres en todo el sistema (la de los alias de
# facturas). Si esta se separa de aquella, "SALSA MARACUYA" y "Salsa Maracuyá"
# dejan de ser el mismo producto en la mitad del sistema y no en la otra.
from app.services.producto_alias import normalizar_alias as normalizar

logger = logging.getLogger(__name__)

RUTA_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "orden_conteo.json")

# Espacio entre entradas de un mismo bloque: deja 9 huecos para los productos
# que una entrada de prefijo expande (PULPAS → 4 pulpas) sin invadir la
# siguiente posición del recorrido.
PASO = 10
# Salto entre bloques: para poder intercalar una zona entera después sin
# renumerar el archivo completo.
SALTO_BLOQUE = 1000
# Cuántos productos puede absorber una entrada antes de empezar a empatar. Un
# empate NO desordena: el cliente ordena por (orden_conteo, nombre), así que los
# excedentes quedan alfabéticos entre ellos y siguen antes de la entrada que
# viene. Invadir la posición siguiente sí desordenaría.
_MAX_EXPANSION = PASO - 1


class OrdenConteoInvalido(Exception):
    """El archivo de datos no se puede leer o no dice lo que tiene que decir."""


def cargar_entradas(ruta: str | None = None) -> list[dict]:
    """Lee el JSON y devuelve las entradas del recorrido, en orden, con su
    posición base ya calculada.

    Levanta OrdenConteoInvalido ante cualquier problema — el que decide si eso
    tumba algo o no es el caller (`sembrar` no lo deja tumbar el arranque).
    """
    ruta = ruta or RUTA_JSON
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError) as e:
        raise OrdenConteoInvalido(f"No se pudo leer {ruta}: {e}") from e

    if not isinstance(datos, dict) or not isinstance(datos.get("bloques"), list):
        raise OrdenConteoInvalido("El archivo debe tener una lista 'bloques'")

    entradas: list[dict] = []
    for i_bloque, bloque in enumerate(datos["bloques"], start=1):
        if not isinstance(bloque, dict) or not isinstance(bloque.get("entradas"), list):
            raise OrdenConteoInvalido(f"Bloque {i_bloque} sin lista 'entradas'")
        numero = int(bloque.get("bloque", i_bloque))
        base = (numero - 1) * SALTO_BLOQUE
        for i_entrada, cruda in enumerate(bloque["entradas"], start=1):
            if not isinstance(cruda, dict) or not cruda.get("entrada"):
                raise OrdenConteoInvalido(f"Bloque {numero}: entrada #{i_entrada} sin nombre")
            variantes = cruda.get("variantes") or []
            prefijo = cruda.get("prefijo")
            if not variantes and not prefijo:
                raise OrdenConteoInvalido(
                    f"'{cruda['entrada']}': una entrada sin 'variantes' ni 'prefijo' no "
                    "puede matchear nada — declarala o sacala")
            entradas.append({
                "bloque": numero,
                "entrada": str(cruda["entrada"]),
                "nota": cruda.get("_nota"),
                # Se guardan normalizadas: la comparación es siempre normalizada.
                "variantes": [normalizar(v) for v in variantes],
                "prefijo": normalizar(prefijo) if prefijo else None,
                "orden_base": base + PASO * i_entrada,
            })

    ordenes = [e["orden_base"] for e in entradas]
    if len(ordenes) != len(set(ordenes)):
        raise OrdenConteoInvalido("Dos entradas cayeron en la misma posición")
    return entradas


def emparejar(entradas: list[dict], productos) -> dict:
    """Cruza el recorrido contra el catálogo. Función pura: no toca la DB.

    `productos`: iterable de (id, nombre).

    Devuelve:
      asignaciones — {producto_id: orden}, solo los matches CIERTOS
      por_entrada  — el recorrido con los productos que se quedó cada posición
      sin_match    — [(id, nombre)] de lo que va al final, alfabético
      ambiguos     — [(id, nombre, [entradas...])] reclamados por más de una
                     posición; no se asignan, se reportan
    """
    catalogo = [(pid, nombre or "", normalizar(nombre)) for pid, nombre in productos]

    # 1) Recolectar TODOS los reclamos antes de resolver ninguno: un producto que
    #    dos entradas se disputan no puede depender de cuál se evaluó primero.
    reclamos: dict[int, list[int]] = {}   # producto_id → índices de entrada
    for i, entrada in enumerate(entradas):
        variantes = set(entrada["variantes"])
        prefijo = entrada["prefijo"]
        for pid, _nombre, norm in catalogo:
            if not norm:
                continue
            if norm in variantes or (prefijo and norm.startswith(prefijo)):
                reclamos.setdefault(pid, []).append(i)

    # 2) Solo los reclamos únicos se convierten en posición.
    ganados: dict[int, list[tuple[str, int]]] = {}   # índice entrada → [(nombre, pid)]
    ambiguos = []
    por_id = {pid: (nombre, norm) for pid, nombre, norm in catalogo}
    for pid, indices in reclamos.items():
        nombre, _norm = por_id[pid]
        if len(indices) > 1:
            ambiguos.append((pid, nombre, [entradas[i]["entrada"] for i in indices]))
            continue
        ganados.setdefault(indices[0], []).append((nombre, pid))

    asignaciones: dict[int, int] = {}
    por_entrada = []
    for i, entrada in enumerate(entradas):
        # Alfabético NORMALIZADO entre los productos de una misma entrada: es el
        # orden que el dueño pidió para las pulpas y el único estable si mañana
        # aparece una pulpa nueva.
        suyos = sorted(ganados.get(i, []), key=lambda t: normalizar(t[0]))
        productos_entrada = []
        for k, (nombre, pid) in enumerate(suyos):
            orden = entrada["orden_base"] + min(k, _MAX_EXPANSION)
            asignaciones[pid] = orden
            productos_entrada.append({"id": pid, "nombre": nombre, "orden": orden})
        por_entrada.append({
            "bloque": entrada["bloque"],
            "entrada": entrada["entrada"],
            "nota": entrada["nota"],
            "orden_base": entrada["orden_base"],
            "productos": productos_entrada,
        })

    sin_match = sorted(
        [(pid, nombre) for pid, nombre, _n in catalogo if pid not in asignaciones],
        key=lambda t: normalizar(t[1]),
    )
    return {"asignaciones": asignaciones, "por_entrada": por_entrada,
            "sin_match": sin_match, "ambiguos": ambiguos}


def _productos_del_conteo(db):
    """El universo que ve la pantalla de conteo — el mismo filtro que
    services/inventario.get_inventario_tienda. Si esos dos se separan, el
    reporte habla de un catálogo distinto del que la barista cuenta."""
    return (db.query(Producto)
            .filter(Producto.incluir_en_conteo.isnot(False))
            .all())


def aplicar(db, ruta: str | None = None) -> dict:
    """Siembra el recorrido en `Producto.orden_conteo`. Idempotente.

    Escribe SOLO donde orden_conteo es NULL: una posición que ya tiene valor la
    puso alguien (este cargador en un arranque anterior, o una persona desde el
    hub) y no se pisa. Commitea — es una operación de arranque, no parte de una
    transacción mayor.

    Levanta OrdenConteoInvalido si el archivo está mal. Usá `sembrar` si el
    llamador no puede permitirse la excepción.
    """
    entradas = cargar_entradas(ruta)
    productos = db.query(Producto).all()
    res = emparejar(entradas, [(p.id, p.nombre) for p in productos])

    asignados = 0
    for p in productos:
        orden = res["asignaciones"].get(p.id)
        if orden is not None and p.orden_conteo is None:
            p.orden_conteo = orden
            asignados += 1
    if asignados:
        db.commit()
    else:
        # Nada que escribir: no dejar la sesión con cambios colgando.
        db.rollback()

    if res["ambiguos"]:
        for pid, nombre, entradas_en_disputa in res["ambiguos"]:
            logger.warning("orden_conteo: '%s' (id %s) lo reclaman %s — sin posición",
                           nombre, pid, entradas_en_disputa)
    logger.info("orden_conteo: %d posiciones sembradas, %d productos sin orden",
                asignados, len(res["sin_match"]))
    return {"asignados": asignados,
            "sin_orden": len(res["sin_match"]),
            "ambiguos": len(res["ambiguos"])}


def sembrar(db, ruta: str | None = None) -> dict:
    """`aplicar` a prueba de arranque: nunca levanta.

    Un archivo de datos jamás puede tumbar un deploy de una cafetería que está
    abierta. Si algo falla, el conteo queda en el orden que ya tenía —el mismo
    de antes de esta feature— y el error queda en el log.
    """
    try:
        return {"ok": True, **aplicar(db, ruta)}
    except Exception as e:   # noqa: BLE001 — a propósito: el arranque manda
        try:
            db.rollback()
        except Exception:    # noqa: BLE001
            pass
        logger.warning("orden_conteo: no se pudo sembrar el orden del conteo (%s). "
                       "El conteo sigue en el orden que ya tenía.", e)
        return {"ok": False, "error": str(e)}


def reporte(db, ruta: str | None = None) -> dict:
    """Qué matcheó con qué, contra el catálogo REAL de producción.

    Es la única forma de verificar este archivo: el catálogo de producción no se
    conoce entero desde acá. Tres preguntas que responde:
      · ¿qué entrada de la lista del dueño no encontró producto? (variante que falta)
      · ¿qué producto quedó sin posición? (se cuenta al final, alfabético)
      · ¿qué posición difiere de lo que el cargador sembraría hoy? (la movió alguien)
    """
    entradas = cargar_entradas(ruta)
    productos = _productos_del_conteo(db)
    res = emparejar(entradas, [(p.id, p.nombre) for p in productos])
    actual = {p.id: p.orden_conteo for p in productos}
    nombres = {p.id: p.nombre for p in productos}

    editados = [
        {"id": pid, "nombre": nombres[pid],
         "orden_actual": actual[pid], "orden_del_archivo": orden}
        for pid, orden in sorted(res["asignaciones"].items(), key=lambda t: t[1])
        if actual.get(pid) is not None and actual[pid] != orden
    ]
    sin_sembrar = [
        {"id": pid, "nombre": nombres[pid], "orden_del_archivo": orden}
        for pid, orden in sorted(res["asignaciones"].items(), key=lambda t: t[1])
        if actual.get(pid) is None
    ]
    sin_orden = sorted(
        [{"id": p.id, "nombre": p.nombre} for p in productos if p.orden_conteo is None],
        key=lambda d: normalizar(d["nombre"]),
    )
    return {
        "total_productos": len(productos),
        "con_orden": sum(1 for p in productos if p.orden_conteo is not None),
        "entradas": res["por_entrada"],
        "entradas_sin_producto": [e for e in res["por_entrada"] if not e["productos"]],
        "productos_sin_orden": sin_orden,
        # Ya tienen posición, pero distinta de la del archivo: alguien las movió.
        "editados_a_mano": editados,
        # Matchean, pero su posición sigue en NULL (el cargador no corrió, o
        # corrió antes de que el producto existiera). Se siembran al reiniciar.
        "pendientes_de_sembrar": sin_sembrar,
        "ambiguos": [{"id": pid, "nombre": nombre, "entradas": ents}
                     for pid, nombre, ents in res["ambiguos"]],
    }
