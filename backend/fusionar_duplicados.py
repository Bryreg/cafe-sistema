"""Fusiona duplicados de catálogo (nivel 1: mismo producto escrito distinto —
acentos, orden de palabras, 'de', unidades). Conserva UNO por grupo y le pasa
TODO el historial de los demás, luego los borra.

Regla del que QUEDA (keeper):
  1) el que tenga precio POS (precio_venta > 0);
  2) si ninguno tiene precio, el que tenga más stock;
  3) desempate: menor id.

El stock del/los eliminados se SUMA al que queda (por sede). Umbrales (mínimo/
ideal/crítico) toman el máximo. Todo el historial (ventas, movimientos, mermas,
facturas, conteos, lotes, etc.) se reasigna al que queda.

Uso (Render Shell):
    cd /opt/render/project/src/backend
    python fusionar_duplicados.py           # DRY-RUN: muestra el plan, NO cambia nada
    python fusionar_duplicados.py --si      # aplica la fusión
"""
import os, sys, re, unicodedata
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine
from sqlalchemy import text
from app.models.models import Producto, Inventario

GO = "--si" in sys.argv

STOP  = {"de", "la", "el", "los", "las", "con", "y", "x", "und", "unidad", "unidades", "para", "o", "a", "botella"}
UNITS = {"oz", "onz", "onza", "onzas", "gr", "g", "gramos", "ml", "cc", "lt", "litro", "litros", "kg"}

# Tablas que referencian productos.id y se reasignan con UPDATE simple (sin unique en producto).
FK_TABLES = [
    "movimientos_inventario", "lotes_inventario", "conteos_fisicos_items", "mermas",
    "solicitudes_pedido_items", "pasteleria_diaria", "auditorias_inventario_items",
    "recetas_ingredientes", "facturas_compra_items", "conteos_compras_items",
    "ticket_items", "recepcion_items", "notas_credito_items", "inventarios_mensuales_items",
]


def _sa(s): return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
def strongkey(s):
    s = _sa(s)
    s = re.sub(r"(\d)\s*([a-z])", r"\1 \2", s)   # 9oz -> 9 oz ; 2500g -> 2500 g
    s = re.sub(r"([a-z])\s*(\d)", r"\1 \2", s)   # x2500 -> x 2500
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    out = []
    for t in s.split():
        if t in STOP or t in UNITS: continue
        if t.endswith("s") and len(t) > 4: t = t[:-1]   # plural -> singular
        if t.isdigit(): t = str(int(t))                 # 04 -> 4
        if t and t not in STOP and t not in UNITS:
            out.append(t)
    return " ".join(sorted(out))


db = SessionLocal()
try:
    prods = db.query(Producto).all()
    inv_rows = db.query(Inventario).all()
    stock_sum = defaultdict(float)
    for i in inv_rows:
        stock_sum[i.producto_id] += (i.stock_actual or 0)

    # nº de movimientos (para marcar los que "tienen movimientos")
    def _cnt(tabla, pid):
        return db.execute(text(f"SELECT COUNT(*) FROM {tabla} WHERE producto_id=:p"), {"p": pid}).scalar() or 0
    def movs(pid):
        return _cnt("ticket_items", pid) + _cnt("movimientos_inventario", pid) + _cnt("mermas", pid)

    groups = defaultdict(list)
    for p in prods:
        groups[strongkey(p.nombre)].append(p)
    dups = {k: v for k, v in groups.items() if len(v) > 1}

    def keeper_de(group):
        con_precio = [p for p in group if (p.precio_venta or 0) > 0]
        cands = con_precio or group
        return sorted(cands, key=lambda p: (-stock_sum[p.id], p.id))[0]

    def cat(p): return p.categoria.value if hasattr(p.categoria, "value") else str(p.categoria)

    print("=" * 66)
    print(f"  FUSIÓN DE DUPLICADOS  —  {len(dups)} grupo(s)  —  modo: {'APLICAR' if GO else 'DRY-RUN'}")
    print("=" * 66)

    plan = []
    for k in sorted(dups):
        group = dups[k]
        keeper = keeper_de(group)
        losers = [p for p in group if p.id != keeper.id]
        plan.append((keeper, losers))
        stock_final = stock_sum[keeper.id] + sum(stock_sum[l.id] for l in losers)
        print(f"\n~ [{k}]  ({cat(keeper)})")
        print(f"   QUEDA  id={keeper.id:<4} '{keeper.nombre}' | ${keeper.precio_venta or 0:.0f} | "
              f"conteo:{'SI' if keeper.incluir_en_conteo else 'no'} | stock:{stock_sum[keeper.id]:g} | movs:{movs(keeper.id)}")
        for l in losers:
            print(f"   borra  id={l.id:<4} '{l.nombre}' | ${l.precio_venta or 0:.0f} | "
                  f"conteo:{'SI' if l.incluir_en_conteo else 'no'} | stock:{stock_sum[l.id]:g} | movs:{movs(l.id)}")
        print(f"   -> stock final del que queda: {stock_final:g}")

    if not GO:
        print("\n\nDRY-RUN: no se cambió nada. Ejecutá con  --si  para aplicar.")
        sys.exit(0)

    # ── APLICAR (todo en UNA transacción; si algo falla, no cambia nada) ──────
    aplicados = 0
    with engine.begin() as conn:
        for keeper, losers in plan:
            kid = keeper.id
            for loser in losers:
                lid = loser.id
                # 1) inventario: sumar stock por sede (unique producto+tienda)
                k_rows = {r[0]: r for r in conn.execute(text(
                    "SELECT tienda_id, stock_actual, stock_minimo, stock_ideal, stock_critico "
                    "FROM inventario WHERE producto_id=:k"), {"k": kid}).fetchall()}
                for lr in conn.execute(text(
                        "SELECT id, tienda_id, stock_actual, stock_minimo, stock_ideal, stock_critico "
                        "FROM inventario WHERE producto_id=:l"), {"l": lid}).fetchall():
                    lid_inv, lt, ls, lmin, lide, lcri = lr
                    if lt in k_rows:
                        _, ks, kmin, kide, kcri = k_rows[lt]
                        conn.execute(text(
                            "UPDATE inventario SET stock_actual=:s, stock_minimo=:mn, stock_ideal=:idl, "
                            "stock_critico=:cr WHERE producto_id=:k AND tienda_id=:t"),
                            {"s": (ks or 0) + (ls or 0), "mn": max(kmin or 0, lmin or 0),
                             "idl": max(kide or 0, lide or 0), "cr": max(kcri or 0, lcri or 0),
                             "k": kid, "t": lt})
                        conn.execute(text("DELETE FROM inventario WHERE id=:i"), {"i": lid_inv})
                    else:
                        conn.execute(text("UPDATE inventario SET producto_id=:k WHERE id=:i"),
                                     {"k": kid, "i": lid_inv})
                # 2) resto de tablas: reasignar historial al que queda
                for t in FK_TABLES:
                    conn.execute(text(f"UPDATE {t} SET producto_id=:k WHERE producto_id=:l"),
                                 {"k": kid, "l": lid})
                # 3) borrar el producto duplicado
                conn.execute(text("DELETE FROM productos WHERE id=:l"), {"l": lid})
                aplicados += 1

    print(f"\n\n[OK] Fusión aplicada: {aplicados} duplicado(s) eliminados, historial reasignado.")
finally:
    db.close()
