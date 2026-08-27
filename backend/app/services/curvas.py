"""La curva del saldo de cada insumo en un rango, y los conteos físicos encima.

La tabla de insumos dice CUÁNTO entró y cuánto salió; esto dice CUÁNDO, que es
otra pregunta. Un insumo que arranca lleno, baja parejo toda la semana y llega
justo a cero el día que llega el pedido está sano. Uno que se agota el miércoles
y pasa tres días en negativo está roto, y los dos totales de la tabla son
idénticos.

NADA ACÁ RECALCULA EL LIBRO. `conciliacion._saldos` ya devuelve el saldo DESPUÉS
de cada movimiento junto con si ese saldo es firme o estimado, con tres pasadas
pensadas justamente para el problema que tiene este dato: un movimiento de tipo
`ajuste` guarda el stock RESULTANTE y no el delta, así que hacia adelante es un
ancla perfecta y hacia atrás es un muro. Reusar esa función es lo que hace que la
curva y los totales de la fila no se puedan desincronizar — y es lo que hace que
la curva sea CORRECTA: reconstruirla a mano hacia atrás desde el stock de hoy,
que es lo primero que uno intenta, se rompe en cuanto hay un ajuste en el medio.
En producción sólo 1 de 123 insumos tiene el arranque estimado, y viaja marcado.

Lo que sí se agrega es el CONTEO FÍSICO, que el libro no conoce: la curva es lo
que el sistema CREE y el conteo es lo único que alguien vio de verdad en el
estante. La distancia entre los dos es la fuga, y es el dato más valioso de la
pantalla porque no sale de ninguna otra parte.

Los registros de conteo repetidos se colapsan: en producción el conteo de
apertura copia exacto el del cierre de la noche anterior en 119 de 120 casos —al
abrir no se vuelve a contar—, así que dibujar los dos diría que el estante se
revisó el doble de veces de lo que se revisó.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from app.core.tz import inicio_dia_col_utc, fin_dia_col_utc
from app.models.models import ConteoFisico, ConteoFisicoItem
from app.services import conciliacion as esc

# Puntos que se mandan por producto. La barra mide unos 500 px de ancho y el
# dibujo es escalonado: más de 64 escalones no agregan forma, agregan bytes, y
# esto viaja para los ~120 insumos de una sede a una tablet.
#
# El recorte NO deforma la silueta: sólo se ralean las SALIDAS, y una salida sólo
# puede bajar. Las entradas, los ajustes y las reversas —lo único que sube— se
# mandan todas, así que el techo de la sombra (el máximo que el stock alcanzó
# hasta cada momento) sale exacto aunque se hayan ralado mil ventas.
MUESTRAS = 64

EPS = 1e-6


def _iguales(a: dict, b: dict) -> bool:
    return (abs(a["sistema"] - b["sistema"]) < EPS
            and abs(a["real"] - b["real"]) < EPS)


def conteos_rango(db, tienda_id: int, desde: date, hasta: date,
                  producto_ids: list[int] | None = None) -> dict[int, list[dict]]:
    """Los conteos físicos del rango por producto, en orden y ya colapsados."""
    d_utc, h_utc = inicio_dia_col_utc(desde), fin_dia_col_utc(hasta)
    q = (db.query(ConteoFisico.id, ConteoFisico.fecha_registro, ConteoFisico.tipo,
                  ConteoFisico.es_atajo, ConteoFisico.fecha_aplicado,
                  ConteoFisicoItem.producto_id, ConteoFisicoItem.cantidad_sistema,
                  ConteoFisicoItem.cantidad_real)
         .join(ConteoFisicoItem, ConteoFisicoItem.conteo_id == ConteoFisico.id)
         .filter(ConteoFisico.tienda_id == tienda_id,
                 ConteoFisico.fecha_registro >= d_utc,
                 ConteoFisico.fecha_registro <= h_utc))
    if producto_ids is not None:
        q = q.filter(ConteoFisicoItem.producto_id.in_(producto_ids))

    crudo: dict[int, list[dict]] = defaultdict(list)
    for cid, fecha, tipo, atajo, aplicado, pid, sistema, real in q.order_by(
            ConteoFisico.fecha_registro.asc(), ConteoFisico.id.asc()).all():
        if fecha is None:
            continue
        crudo[pid].append({
            "conteo_id": cid, "fecha": fecha,
            "tipos": [getattr(tipo, "value", tipo)],
            "sistema": float(sistema or 0), "real": float(real or 0),
            "dif": round(float(real or 0) - float(sistema or 0), 3),
            # Un atajo («todo coincide con sistema») no es un conteo: es un eco
            # del stock. Dibujarlo como una mirada al estante sería mentir sobre
            # la evidencia que hay detrás de la fila.
            "es_atajo": bool(atajo),
            "aplicado": aplicado is not None,
            "registros": 1,
        })

    salida: dict[int, list[dict]] = {}
    for pid, obs in crudo.items():
        juntas: list[dict] = []
        for o in obs:
            if juntas and _iguales(juntas[-1], o):
                u = juntas[-1]
                u["registros"] += 1
                u["aplicado"] = u["aplicado"] or o["aplicado"]
                u["es_atajo"] = u["es_atajo"] and o["es_atajo"]
                if o["tipos"][0] not in u["tipos"]:
                    u["tipos"].append(o["tipos"][0])
            else:
                juntas.append(o)
        salida[pid] = juntas
    return salida


def _ralear(puntos: list[dict], muestras: int) -> list[dict]:
    """Deja alrededor de `muestras` puntos sin tocar la silueta.

    Se conservan siempre los extremos y todo lo que SUBE (entradas, ajustes,
    reversas); de las salidas se guarda la última de cada tramo, que es el nivel
    con el que ese tramo termina y contra el que sigue el escalón siguiente.

    `muestras` es un objetivo, no un tope duro: si un insumo tuviera más entradas
    que el cupo entero, se mandan todas igual. Recortar ahí achataría el techo de
    la sombra, que es justamente lo que la barra viene a mostrar.

    La cantidad de una salida se REESCRIBE contra el punto que quedó antes: si se
    tiraron cuatro ventas en el medio, el globo tiene que decir cuánto salió
    entre los dos puntos que se ven, no cuánto salió en la última de las cuatro.
    """
    if len(puntos) > muestras:
        fijos = {0, len(puntos) - 1}
        fijos.update(i for i, p in enumerate(puntos) if p["k"] != "salida")
        salidas = [i for i in range(len(puntos)) if i not in fijos]
        cupo = max(0, muestras - len(fijos))
        if cupo and salidas:
            paso = len(salidas) / cupo
            fijos.update(salidas[min(len(salidas) - 1, int((k + 1) * paso) - 1)]
                         for k in range(cupo))
        puntos = [puntos[i] for i in sorted(fijos)]
    for antes, p in zip(puntos, puntos[1:]):
        if p["k"] == "salida":
            p["c"] = round(antes["v"] - p["v"], 3)
    return puntos


def curva_producto(movs, saldos, d_utc: datetime, h_utc: datetime,
                   inicial: float, inicial_estimado: bool, final: float,
                   conteos: list[dict], muestras: int = MUESTRAS) -> dict:
    """La curva de un producto y sus conteos, listos para dibujar.

    `t` son segundos desde el arranque del rango, no una fecha ISO: son 26 bytes
    contra 5 por punto, y a 64 puntos por 123 insumos eso es la diferencia entre
    una respuesta de 200 KB y una de 40 KB en la tablet del local.
    """
    despues, previo, estimado, previo_est = saldos
    seg = lambda f: int((f - d_utc).total_seconds())

    puntos: list[dict] = [{"t": 0, "v": inicial, "k": "inicio"}]
    if inicial_estimado:
        puntos[0]["est"] = True
    anterior = inicial
    n_movs = 0
    for i, m in enumerate(movs):
        if m.fecha is None or m.fecha < d_utc or m.fecha > h_utc:
            continue
        n_movs += 1
        tipo = esc._tipo(m)
        nivel = round(despues[i], 3)
        p = {"t": seg(m.fecha), "v": nivel, "k": tipo,
             "causa": esc._bucket(tipo, m.motivo),
             # Un ajuste no tiene cantidad propia: `cantidad` guarda el saldo
             # resultante. Lo que movió es la diferencia contra el saldo anterior.
             "c": round(nivel - anterior if tipo == "ajuste"
                        else float(m.cantidad or 0), 3)}
        if estimado[i]:
            p["est"] = True
        puntos.append(p)
        anterior = nivel
    puntos.append({"t": seg(h_utc), "v": final, "k": "fin"})

    fuera = []
    for c in conteos:
        valor, est = esc._saldo_en(movs, despues, previo, estimado, previo_est, c["fecha"])
        fuera.append({
            "conteo_id": c["conteo_id"], "t": seg(c["fecha"]),
            "tipos": c["tipos"], "registros": c["registros"],
            "sistema": round(c["sistema"], 3), "real": round(c["real"], 3),
            "dif": c["dif"], "es_atajo": c["es_atajo"], "aplicado": c["aplicado"],
            # Contra el mismo nivel que se dibuja: si el punto se comparara con
            # otro número, el punto y la curva contarían historias distintas en
            # la misma fila.
            "curva": round(valor, 3),
        })

    return {
        "puntos": _ralear(puntos, muestras),
        "puntos_total": len(puntos),
        "conteos": fuera,
        "n_movs": n_movs,
        # De dónde salió la altura: del libro atado al stock vivo de hoy, o de
        # suponer que el producto arrancó en cero antes del ajuste más viejo.
        "ancla": "estimado" if inicial_estimado else "libro",
    }
