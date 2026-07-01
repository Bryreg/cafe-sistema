"""Corrige una factura de proveedor que se marcó CONTADO pero en realidad fue BANCOS.
Cambia la factura a transferencia (bancos) y ELIMINA el egreso de caja que había
creado, para que deje de descontarse del efectivo pendiente por consignar.

Uso (Render Shell):
    cd /opt/render/project/src/backend
    python corregir_pago_bancos.py                # lista facturas pagadas en contado (con su id)
    python corregir_pago_bancos.py <factura_id>   # DRY-RUN: muestra el cambio y el egreso a borrar
    python corregir_pago_bancos.py <factura_id> --si   # aplica la corrección
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.models import FacturaCompra, MovimientoCaja, CajaTurno, Tienda, TipoPagoEnum

args = [a for a in sys.argv[1:] if not a.startswith("-")]
GO = "--si" in sys.argv
fid = int(args[0]) if args else None

db = SessionLocal()
try:
    def tienda_nombre(tid):
        t = db.query(Tienda).filter_by(id=tid).first()
        return t.nombre if t else f"tienda {tid}"

    # ── Modo lista: mostrar facturas pagadas en contado/efectivo ────────────
    if fid is None:
        print("Facturas registradas como CONTADO/EFECTIVO (posibles a corregir):\n")
        fs = (db.query(FacturaCompra)
              .filter((FacturaCompra.tipo_pago == TipoPagoEnum.contado) |
                      (FacturaCompra.forma_pago_real.in_(["contado", "efectivo", "Efectivo", "Contado"])))
              .order_by(FacturaCompra.id.desc()).limit(20).all())
        if not fs:
            print("  (ninguna)")
        for f in fs:
            print(f"  id={f.id:<4} {f.proveedor} | {tienda_nombre(f.tienda_id)} | "
                  f"${f.valor_total:.0f} | {f.tipo_pago.value} | forma:{f.forma_pago_real} | "
                  f"factura:{f.numero_factura or '-'} | {f.fecha_recibido or f.fecha_registro}")
        print("\nCorré:  python corregir_pago_bancos.py <id>   para ver el detalle de una.")
        sys.exit(0)

    # ── Modo factura específica ─────────────────────────────────────────────
    f = db.query(FacturaCompra).filter_by(id=fid).first()
    if not f:
        print(f"No existe factura id={fid}"); sys.exit(1)

    turnos_ids = [t.id for t in db.query(CajaTurno).filter(CajaTurno.tienda_id == f.tienda_id).all()]
    egresos = db.query(MovimientoCaja).filter(
        MovimientoCaja.tipo == "egreso",
        MovimientoCaja.caja_turno_id.in_(turnos_ids or [-1]),
        MovimientoCaja.valor == f.valor_total,
        MovimientoCaja.concepto.like(f"%{f.proveedor}%"),
    ).all()

    print("=" * 60)
    print(f"  FACTURA id={f.id} — {f.proveedor} — {tienda_nombre(f.tienda_id)}")
    print("=" * 60)
    print(f"  valor: ${f.valor_total:.0f} | tipo_pago actual: {f.tipo_pago.value} | forma: {f.forma_pago_real}")
    print(f"\n  CAMBIO: tipo_pago -> transferencia (bancos), forma_pago_real -> 'transferencia'")
    print(f"\n  Egreso(s) de caja que se ELIMINARÍAN (dejan de restar del pendiente por consignar):")
    if not egresos:
        print("    (ninguno encontrado — solo se corrige la factura)")
    for m in egresos:
        print(f"    mov id={m.id} | turno={m.caja_turno_id} | ${m.valor:.0f} | '{m.concepto}' | {m.fecha}")

    if not GO:
        print("\n\nDRY-RUN: no se cambió nada. Ejecutá con  --si  para aplicar.")
        sys.exit(0)

    f.tipo_pago = TipoPagoEnum.transferencia
    f.forma_pago_real = "transferencia"
    for m in egresos:
        db.delete(m)
    db.commit()
    print(f"\n\n[OK] Factura {f.id} -> bancos (transferencia). Egresos eliminados: {len(egresos)}.")
    print("      El efectivo de ese día vuelve a contar como pendiente por consignar.")
finally:
    db.close()
