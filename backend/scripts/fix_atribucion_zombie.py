"""
Backfill de ATRIBUCIÓN de ventas cobradas sobre un turno ZOMBIE.

Un turno que quedó abierto de un día anterior seguía recibiendo ventas (el índice
uq_one_turno_abierto impide abrir otro mientras tanto), y esas ventas quedaban
atribuidas al día operativo del turno viejo: el Informe Contador las mostraba días
antes de haberse cobrado. Desde el fix, cada ticket sella su propio día al cobrarse
(tickets.dia_operativo_id). Este script repara los tickets ANTERIORES al fix.

Qué hace, por cada ticket cuyo día Colombia difiere del día operativo de su turno:
  - busca (o crea) el DiaOperativo de la sede del ticket para SU propio día Colombia
    — creado como 'cerrado' y con nota de que se reconstruyó desde las ventas;
  - le escribe ese día en tickets.dia_operativo_id.
No toca ventas ni turnos: solo la columna de atribución.

Idempotente: un ticket ya sellado con el día correcto se cuenta como "ok" y no se
vuelve a escribir. Correrlo dos veces no cambia nada la segunda vez.

Correr DESPUÉS de desplegar: las columnas nuevas las crean las migraciones inline
del arranque de la app (app/main.py). Si faltan, el script avisa y no hace nada.

Uso:
    cd backend
    # dev:
    set ENV_FILE=.env.dev && python scripts/fix_atribucion_zombie.py
    # producción: con las variables de entorno de prod cargadas
    python scripts/fix_atribucion_zombie.py

    python scripts/fix_atribucion_zombie.py            # DRY-RUN (default): solo informa
    python scripts/fix_atribucion_zombie.py --apply    # escribe los cambios
"""
import sys, os
from collections import defaultdict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.core.tz import dia_col
from app.services.caja import es_venta_de_turno_zombie
from app.models import models  # noqa
from app.models.models import CajaTurno, DiaOperativo, EstadoDiaEnum, Ticket

NOTA_RECONSTRUIDO = ("Día reconstruido por fix_atribucion_zombie: no existía y se creó para "
                     "atribuir ventas cobradas sobre un turno de otro día.")


def _dia_del_turno(turno):
    """Día-negocio del turno: el de su DiaOperativo o, sin él, el día Colombia de
    su apertura (misma derivación que services/caja.py)."""
    if turno is None:
        return None
    if turno.dia_operativo_id and turno.dia:
        return turno.dia.fecha_operativa
    return dia_col(turno.fecha_apertura) if turno.fecha_apertura else None


def _verificar_esquema(db):
    """Las columnas nuevas las crea el arranque de la app, no este script: sin ellas
    el ORM revienta con un stack trace ilegible. Mejor decir qué falta."""
    for tabla, columna in (("tickets", "dia_operativo_id"),
                           ("caja_turnos", "cerrado_sin_conteo")):
        try:
            db.execute(text(f"SELECT {columna} FROM {tabla} LIMIT 1"))
        except Exception:
            db.rollback()
            raise SystemExit(
                f"[ABORTA] La columna {tabla}.{columna} no existe todavía. "
                "Desplegá/arrancá la app una vez (aplica las migraciones inline) y volvé a correr."
            )


def run(apply: bool = False, db=None):
    """db=None → sesión propia contra la DB configurada.
    Con `db` explícito (tests) usa esa sesión y no toca el engine global."""
    own_session = db is None
    if own_session:
        from app.database import SessionLocal
        db = SessionLocal()
    try:
        _verificar_esquema(db)
        turnos = {t.id: t for t in db.query(CajaTurno).all()}
        # Índice (tienda, fecha) -> DiaOperativo, para no consultar por cada ticket.
        dias_idx = {(d.tienda_id, d.fecha_operativa): d
                    for d in db.query(DiaOperativo).all()}

        tickets = db.query(Ticket).order_by(Ticket.fecha).all()
        a_corregir = []      # (ticket, dia_ticket, dia_turno)
        ya_ok = 0
        sin_datos = 0

        for t in tickets:
            if t.fecha is None:
                sin_datos += 1
                continue
            dia_ticket = dia_col(t.fecha)
            dia_turno = _dia_del_turno(turnos.get(t.caja_turno_id))
            if dia_turno is None:
                # Sin turno o sin apertura no hay contra qué comparar: el informe ya
                # lo resuelve por calendario, que es exactamente el día del ticket.
                sin_datos += 1
                continue
            # MISMO criterio que crear_ticket (caja.es_venta_de_turno_zombie): un
            # cierre que sigue cobrando pasada la medianoche NO está mal atribuido —
            # esa venta entra en el cierre que la barista firmó esa madrugada, y
            # moverla al día siguiente la sacaría de lo firmado. Solo se corrigen
            # las ventas de un turno realmente zombie.
            if not es_venta_de_turno_zombie(dia_turno, t.fecha):
                continue
            sellado = dias_idx.get((t.tienda_id, dia_ticket))
            if sellado is not None and t.dia_operativo_id == sellado.id:
                ya_ok += 1        # ya reparado en una corrida anterior
                continue
            a_corregir.append((t, dia_ticket, dia_turno))

        print(f"Tickets revisados        : {len(tickets)}")
        print(f"Ya atribuidos a su día   : {ya_ok}")
        print(f"Sin turno/fecha utilizable: {sin_datos}")
        print(f"A corregir               : {len(a_corregir)}")

        if a_corregir:
            # Resumen legible: qué día se les está sacando y a cuál se les pone.
            resumen = defaultdict(lambda: {"n": 0, "total": 0.0})
            for t, dia_ticket, dia_turno in a_corregir:
                r = resumen[(t.tienda_id, dia_turno, dia_ticket)]
                r["n"] += 1
                r["total"] += float(t.total or 0)
            print("\n  tienda  día del turno -> día real   tickets      monto")
            for (tienda_id, dia_turno, dia_ticket), r in sorted(resumen.items(), key=lambda kv: str(kv[0])):
                print(f"  {tienda_id:>6}  {dia_turno} -> {dia_ticket}   {r['n']:>7}  {r['total']:>9,.0f}")

        creados_dias = 0
        for t, dia_ticket, _ in a_corregir:
            dia = dias_idx.get((t.tienda_id, dia_ticket))
            if dia is None:
                dia = DiaOperativo(
                    tienda_id=t.tienda_id, fecha_operativa=dia_ticket,
                    # Cerrado: es un día pasado que se reconstruye, no uno en curso.
                    estado=EstadoDiaEnum.cerrado, abierto_por_id=t.usuario_id,
                    notas=NOTA_RECONSTRUIDO,
                )
                db.add(dia)
                db.flush()
                dias_idx[(t.tienda_id, dia_ticket)] = dia
                creados_dias += 1
            t.dia_operativo_id = dia.id

        print(f"\nDías operativos creados  : {creados_dias}")

        if apply:
            db.commit()
            print(f"[OK] {len(a_corregir)} tickets reatribuidos.")
        else:
            db.rollback()
            print("[DRY-RUN] nada escrito. Volvé a correr con --apply para aplicarlo.")

        return {"revisados": len(tickets), "corregidos": len(a_corregir),
                "ya_ok": ya_ok, "sin_datos": sin_datos, "dias_creados": creados_dias}

    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
