"""Detecta duplicados de catálogo escritos DISTINTO (acentos, orden de palabras,
'de', unidades, abreviaturas). Solo lectura — no modifica nada.

Ejecutar en Render Shell:
    cd /opt/render/project/src/backend && python detectar_duplicados.py
"""
import os, sys, re, unicodedata
from difflib import SequenceMatcher
from itertools import combinations
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.models import Producto, Inventario, Tienda

STOP  = {"de", "la", "el", "los", "las", "con", "y", "x", "und", "unidad", "unidades", "para"}
UNITS = {"oz", "onz", "onza", "onzas", "gr", "g", "ml", "cc", "lt", "litro", "litros", "kg"}


def _sa(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()

def _tokens(s: str):
    s = re.sub(r"[^a-z0-9 ]", " ", _sa(s))
    return [t for t in s.split() if t and t not in STOP and t not in UNITS]

def strongkey(s: str) -> str:
    return " ".join(sorted(_tokens(s)))

def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _sa(a), _sa(b)).ratio()


db = SessionLocal()
try:
    prods = db.query(Producto).all()
    vida = db.query(Tienda).filter(Tienda.nombre.ilike("vida")).first()
    stock = {}
    if vida:
        for inv in db.query(Inventario).filter(Inventario.tienda_id == vida.id).all():
            stock[inv.producto_id] = inv.stock_actual

    def cat(p): return p.categoria.value if hasattr(p.categoria, "value") else str(p.categoria)
    def L(p):
        return (f"     id={p.id:<4} '{p.nombre}' | {cat(p)} | ${p.precio_venta or 0:.0f} | "
                f"conteo:{'SI' if p.incluir_en_conteo else 'no'} | "
                f"{'activo' if getattr(p,'activo',True) else 'INACTIVO'} | stockVida:{stock.get(p.id,0):g}")

    print("=" * 64)
    print(f"  DETECCIÓN DE DUPLICADOS — {len(prods)} productos")
    print("=" * 64)

    # ── Nivel 1: mismo nombre normalizado fuerte (acentos/orden/'de'/unidades) ──
    g1 = defaultdict(list)
    for p in prods:
        g1[strongkey(p.nombre)].append(p)
    dup1 = {k: v for k, v in g1.items() if len(v) > 1}
    print(f"\n### NIVEL 1 · MISMO producto (alta confianza): {len(dup1)} grupo(s) ###")
    print("    (acentos, mayúsculas, orden de palabras, 'de', unidades oz/gr/ml)")
    for k in sorted(dup1):
        print(f"\n  ~ [{k}]")
        for p in dup1[k]:
            print(L(p))

    ya = {p.id for g in dup1.values() for p in g}

    # ── Nivel 2: nombres muy parecidos (plural, typo, letra distinta) ──────────
    print(f"\n\n### NIVEL 2 · MUY PARECIDOS (revisar): similitud >= 85% ###")
    n2 = 0
    for a, b in combinations(prods, 2):
        if a.id in ya and b.id in ya:
            continue
        if strongkey(a.nombre) == strongkey(b.nombre):
            continue
        r = ratio(a.nombre, b.nombre)
        if r >= 0.85:
            n2 += 1
            print(f"\n  ~ {int(r*100)}% parecidos:")
            print(L(a)); print(L(b))
    if n2 == 0:
        print("  (ninguno)")

    # ── Nivel 3: uno contiene al otro (abreviatura, p.ej. 'Americano' vs 'Café Americano') ──
    print(f"\n\n### NIVEL 3 · UNO CONTIENE AL OTRO (posible, MÁS falsos positivos) ###")
    print("    (revisar con cuidado: 'Torta' vs 'Torta Chocolate' pueden ser distintos)")
    n3 = 0
    toks = {p.id: set(_tokens(p.nombre)) for p in prods}
    for a, b in combinations(prods, 2):
        if strongkey(a.nombre) == strongkey(b.nombre):
            continue
        ta, tb = toks[a.id], toks[b.id]
        if not ta or not tb:
            continue
        if (ta < tb or tb < ta):  # subconjunto estricto
            n3 += 1
            print("\n  ~ uno contiene al otro:")
            print(L(a)); print(L(b))
    if n3 == 0:
        print("  (ninguno)")

    print(f"\n\nRESUMEN: nivel1={len(dup1)} grupos | nivel2={n2} pares | nivel3={n3} pares")
finally:
    db.close()
