"""Lista (solo lectura) qué productos están marcados para conteo y cuáles no,
y detecta posibles DUPLICADOS por nombre. No modifica nada.

Ejecutar en Render Shell:
    cd /opt/render/project/src/backend && python listar_conteo.py
"""
import os, sys, re, unicodedata
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.models import Producto, Inventario, Tienda


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(s))
                  .encode("ascii", "ignore").decode()).strip().upper()


def cat(p) -> str:
    return p.categoria.value if hasattr(p.categoria, "value") else str(p.categoria)


db = SessionLocal()
try:
    prods = db.query(Producto).all()
    prods.sort(key=lambda p: (cat(p), p.nombre.lower()))

    # Stock de Vida (por si ayuda a decidir cuál duplicado conservar)
    vida = db.query(Tienda).filter(Tienda.nombre.ilike("vida")).first()
    stock = {}
    if vida:
        for inv in db.query(Inventario).filter(Inventario.tienda_id == vida.id).all():
            stock[inv.producto_id] = inv.stock_actual

    def sflag(p): return "SI" if p.incluir_en_conteo else "no"
    def aflag(p): return "activo" if getattr(p, "activo", True) else "INACTIVO"
    def stk(p):   return stock.get(p.id, 0)

    conteo   = [p for p in prods if p.incluir_en_conteo]
    nocont   = [p for p in prods if not p.incluir_en_conteo]

    print("=" * 60)
    print(f"  PRODUCTOS: {len(prods)}  |  se cuentan: {len(conteo)}  |  NO se cuentan: {len(nocont)}")
    print("=" * 60)

    # ── Duplicados por nombre normalizado ───────────────────────────────────
    groups = defaultdict(list)
    for p in prods:
        groups[norm(p.nombre)].append(p)
    dups = {k: v for k, v in groups.items() if len(v) > 1}

    print(f"\n### POSIBLES DUPLICADOS (mismo nombre): {len(dups)} grupo(s) ###")
    if not dups:
        print("  (ninguno)")
    for k in sorted(dups):
        print(f"\n  ~ {k}")
        for p in dups[k]:
            print(f"     id={p.id:<4} '{p.nombre}' | {cat(p)} | ${p.precio_venta or 0:.0f} | "
                  f"conteo:{sflag(p)} | {aflag(p)} | stockVida:{stk(p):g}")

    # ── Se cuentan ──────────────────────────────────────────────────────────
    print(f"\n\n### SE CUENTAN (incluir_en_conteo = SI): {len(conteo)} ###")
    ccat = defaultdict(list)
    for p in conteo:
        ccat[cat(p)].append(p)
    for c in sorted(ccat):
        print(f"\n  [{c}] ({len(ccat[c])})")
        for p in ccat[c]:
            marca = "" if getattr(p, "activo", True) else "  (INACTIVO)"
            print(f"     - {p.nombre}{marca}")

    # ── No se cuentan ───────────────────────────────────────────────────────
    print(f"\n\n### NO SE CUENTAN (incluir_en_conteo = no): {len(nocont)} ###")
    ncat = defaultdict(list)
    for p in nocont:
        ncat[cat(p)].append(p)
    for c in sorted(ncat):
        print(f"\n  [{c}] ({len(ncat[c])})")
        for p in ncat[c]:
            precio = f" | ${p.precio_venta:.0f}" if p.precio_venta else ""
            marca = "" if getattr(p, "activo", True) else "  (INACTIVO)"
            print(f"     - {p.nombre}{precio}{marca}")
finally:
    db.close()
