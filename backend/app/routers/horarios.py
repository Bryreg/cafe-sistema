"""Router del módulo Horarios & Nómina.

Todo es admin salvo `/horarios/mi-horario`, que es lo que ve la barista desde el
kiosko o desde su celular: SUS turnos publicados y sus novedades, nada más.
"""
import io
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin
from app.core.tz import hoy_col
from app.database import get_db
from app.models.models import ContratoBarista, Festivo, Usuario
from app.services import festivos as fsvc
from app.services import horarios as hsvc
from app.services import nomina as nmsvc
from app.services import novedades_nomina as nsvc
from app.services import tasas_laborales as tsvc
from app.services.horas import lunes_de

router = APIRouter(prefix="/horarios", tags=["horarios"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class TurnoIn(BaseModel):
    tienda_id: int
    usuario_id: int
    fecha: date
    hora_inicio: str
    hora_fin: str
    nota: Optional[str] = None


class PublicarIn(BaseModel):
    tienda_id: int
    lunes: date


class CopiarIn(BaseModel):
    tienda_id: int
    lunes_origen: date
    lunes_destino: date


class NovedadIn(BaseModel):
    tienda_id: int
    usuario_id: int
    tipo: str
    fecha_desde: date
    fecha_hasta: date
    remunerada: Optional[bool] = None
    nota: Optional[str] = None
    soporte_url: Optional[str] = None


class NovedadPatch(BaseModel):
    tipo: Optional[str] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    remunerada: Optional[bool] = None
    nota: Optional[str] = None
    soporte_url: Optional[str] = None


class ContratoIn(BaseModel):
    salario_mensual: float = 0.0
    horas_semana_pactadas: Optional[float] = None
    fecha_ingreso: Optional[date] = None
    activo: bool = True
    nota: Optional[str] = None


class TasaPatch(BaseModel):
    jornada_max_semanal: Optional[float] = None
    hora_inicio_nocturna: Optional[int] = None
    hora_fin_nocturna: Optional[int] = None
    recargo_nocturno: Optional[float] = None
    recargo_dominical: Optional[float] = None
    recargo_dominical_nocturno: Optional[float] = None
    extra_diurna: Optional[float] = None
    extra_nocturna: Optional[float] = None
    divisor_hora_mensual: Optional[float] = None
    nota: Optional[str] = None
    confirmar_contador: Optional[bool] = None


class TasaIn(BaseModel):
    vigente_desde: date
    jornada_max_semanal: Optional[float] = None
    hora_inicio_nocturna: Optional[int] = None
    hora_fin_nocturna: Optional[int] = None
    recargo_nocturno: Optional[float] = None
    recargo_dominical: Optional[float] = None
    recargo_dominical_nocturno: Optional[float] = None
    extra_diurna: Optional[float] = None
    extra_nocturna: Optional[float] = None
    divisor_hora_mensual: Optional[float] = None
    nota: Optional[str] = None


class FestivoIn(BaseModel):
    fecha: date
    nombre: str
    es_festivo: bool = True
    nota: Optional[str] = None


# ─── Horario semanal (admin) ────────────────────────────────────────────────

@router.get("/semana")
def semana(tienda_id: int = Query(..., ge=1), lunes: Optional[date] = Query(None),
           db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    """Grilla barista × día de una semana, con el total de cada una contra la
    jornada máxima vigente. Sin `lunes` devuelve la semana en curso."""
    return hsvc.semana(db, tienda_id, lunes or lunes_de(hoy_col()))


@router.post("/turno")
def guardar_turno(body: TurnoIn, db: Session = Depends(get_db),
                  admin: Usuario = Depends(require_admin)):
    tp = hsvc.guardar_turno(db, body.tienda_id, body.usuario_id, body.fecha,
                            body.hora_inicio, body.hora_fin,
                            creado_por_id=admin.id, nota=body.nota)
    return hsvc.serializar(tp)


@router.delete("/turno/{turno_id}")
def borrar_turno(turno_id: int, db: Session = Depends(get_db),
                 admin: Usuario = Depends(require_admin)):
    if not hsvc.borrar_turno(db, turno_id):
        raise HTTPException(status_code=404, detail="Ese turno no existe.")
    return {"ok": True}


@router.post("/publicar")
def publicar(body: PublicarIn, db: Session = Depends(get_db),
             admin: Usuario = Depends(require_admin)):
    """Envía la semana: los borradores pasan a publicado y a cada barista le
    llega SU horario por campana y push."""
    return hsvc.publicar_semana(db, body.tienda_id, lunes_de(body.lunes), admin.id)


@router.post("/copiar")
def copiar(body: CopiarIn, db: Session = Depends(get_db),
           admin: Usuario = Depends(require_admin)):
    creados = hsvc.copiar_semana(db, body.tienda_id, lunes_de(body.lunes_origen),
                                 lunes_de(body.lunes_destino), admin.id)
    return {"creados": creados}


# ─── Lo que ve la barista ───────────────────────────────────────────────────

@router.get("/mi-horario")
def mi_horario(desde: Optional[date] = Query(None), hasta: Optional[date] = Query(None),
               usuario_id: Optional[int] = Query(None),
               db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Los turnos PUBLICADOS de una persona. Por defecto, dos semanas desde hoy.

    En el kiosko compartido el usuario autenticado es el dispositivo, no la
    persona: por eso se acepta `usuario_id` (la barista activa del selector).
    Un admin puede consultar el de cualquiera; una barista con login individual
    solo el suyo.
    """
    objetivo = usuario_id or user.id
    es_admin = getattr(user.rol, "value", user.rol) == "admin"
    if objetivo != user.id and not es_admin:
        # EL TOKEN DEL KIOSKO ES COMPARTIDO por todas las baristas de la sede (PIN
        # común) y vive años: aceptarlo como llave para cualquier `usuario_id` deja
        # leer la INCAPACIDAD MÉDICA de una compañera —con su nota y el link al
        # certificado— cambiando el selector de barista activa. La excepción del
        # kiosko se queda, pero acotada a alguien que de verdad pertenece a ESA
        # sede, que es el mismo criterio que el repo ya exige para mover
        # inventario (deps.require_barista_en_turno).
        if not (user.email or "").startswith("kiosk@"):
            raise HTTPException(status_code=403, detail="Solo podés ver tu propio horario.")
        destino = db.query(Usuario).filter(Usuario.id == objetivo).first()
        if destino is None or destino.tienda_id != user.tienda_id:
            raise HTTPException(
                status_code=403,
                detail="Desde el kiosko solo se puede ver el horario de las baristas de esta sede.")
    d = desde or hoy_col()
    h = hasta or (d + timedelta(days=13))
    # El horario se pide con la sede de quien consulta: `hsvc.mi_horario` filtraba
    # solo por usuario y estado, así que un id de la otra sede devolvía sus turnos.
    turnos = hsvc.mi_horario(db, objetivo, d, h,
                             tienda_id=None if es_admin else user.tienda_id)
    # Payload PÚBLICO: sin la nota libre ni el certificado. Ver a_dict_publico.
    novedades = [nsvc.a_dict_publico(n) for n in nsvc.listar(
        db, user.tienda_id, d, h, usuario_id=objetivo)] if user.tienda_id else []
    return {
        "usuario_id": objetivo,
        "desde": d.isoformat(), "hasta": h.isoformat(),
        "turnos": turnos,
        "novedades": novedades,
        "festivos": sorted(f.isoformat() for f in fsvc.fechas_festivas(db, d, h)),
    }


# ─── Novedades laborales ────────────────────────────────────────────────────

@router.get("/novedades/tipos")
def tipos_novedad(admin: Usuario = Depends(require_admin)):
    """Catálogo con la razón de cada tipo: qué implica antes de elegirlo."""
    return nsvc.catalogo()


@router.get("/novedades")
def listar_novedades(tienda_id: int = Query(..., ge=1),
                     desde: Optional[date] = Query(None), hasta: Optional[date] = Query(None),
                     usuario_id: Optional[int] = Query(None),
                     db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    hoy = hoy_col()
    d = desde or hoy.replace(day=1)
    h = hasta or (d + timedelta(days=45))
    return [nsvc.a_dict(n) for n in nsvc.listar(db, tienda_id, d, h, usuario_id)]


@router.post("/novedades", status_code=201)
def crear_novedad(body: NovedadIn, db: Session = Depends(get_db),
                  admin: Usuario = Depends(require_admin)):
    n = nsvc.crear(db, body.tienda_id, body.usuario_id, body.tipo,
                   body.fecha_desde, body.fecha_hasta, creado_por_id=admin.id,
                   remunerada=body.remunerada, nota=body.nota,
                   soporte_url=body.soporte_url)
    return nsvc.a_dict(n)


@router.patch("/novedades/{novedad_id}")
def editar_novedad(novedad_id: int, body: NovedadPatch, db: Session = Depends(get_db),
                   admin: Usuario = Depends(require_admin)):
    n = nsvc.actualizar(db, novedad_id, body.model_dump(exclude_unset=True))
    if n is None:
        raise HTTPException(status_code=404, detail="Esa novedad no existe.")
    return nsvc.a_dict(n)


@router.delete("/novedades/{novedad_id}")
def borrar_novedad(novedad_id: int, db: Session = Depends(get_db),
                   admin: Usuario = Depends(require_admin)):
    if not nsvc.borrar(db, novedad_id):
        raise HTTPException(status_code=404, detail="Esa novedad no existe.")
    return {"ok": True}


# ─── Resumen mensual ────────────────────────────────────────────────────────

@router.get("/resumen")
def resumen(tienda_id: int = Query(..., ge=1), anio: Optional[int] = Query(None),
            mes: Optional[int] = Query(None), db: Session = Depends(get_db),
            admin: Usuario = Depends(require_admin)):
    hoy = hoy_col()
    return nmsvc.resumen_mensual(db, tienda_id, anio or hoy.year, mes or hoy.month)


@router.get("/resumen.csv")
def resumen_csv(tienda_id: int = Query(..., ge=1), anio: Optional[int] = Query(None),
                mes: Optional[int] = Query(None), db: Session = Depends(get_db),
                admin: Usuario = Depends(require_admin)):
    hoy = hoy_col()
    a, m = anio or hoy.year, mes or hoy.month
    csv = nmsvc.csv_mensual(db, tienda_id, a, m)
    return StreamingResponse(
        io.StringIO("﻿" + csv),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="horas-{a}-{m:02d}.csv"'},
    )


# ─── Contratos (salario para el estimado) ───────────────────────────────────

@router.get("/contratos")
def listar_contratos(tienda_id: int = Query(..., ge=1), db: Session = Depends(get_db),
                     admin: Usuario = Depends(require_admin)):
    personas = hsvc.baristas_de(db, tienda_id)
    contratos = {c.usuario_id: c for c in db.query(ContratoBarista).filter(
        ContratoBarista.usuario_id.in_([u.id for u in personas] or [0])).all()}
    out = []
    for u in personas:
        c = contratos.get(u.id)
        out.append({
            "usuario_id": u.id, "nombre": u.nombre,
            "salario_mensual": float(c.salario_mensual) if c else 0.0,
            "horas_semana_pactadas": c.horas_semana_pactadas if c else None,
            "fecha_ingreso": c.fecha_ingreso.isoformat() if c and c.fecha_ingreso else None,
            "activo": bool(c.activo) if c else True,
            "nota": c.nota if c else None,
            "tiene_contrato": c is not None,
        })
    return out


@router.put("/contratos/{usuario_id}")
def guardar_contrato(usuario_id: int, body: ContratoIn, db: Session = Depends(get_db),
                     admin: Usuario = Depends(require_admin)):
    fila = db.query(ContratoBarista).filter(
        ContratoBarista.usuario_id == usuario_id).first()
    if fila is None:
        fila = ContratoBarista(usuario_id=usuario_id)
        db.add(fila)
    fila.salario_mensual = body.salario_mensual
    fila.horas_semana_pactadas = body.horas_semana_pactadas
    fila.fecha_ingreso = body.fecha_ingreso
    fila.activo = body.activo
    fila.nota = body.nota
    db.commit()
    db.refresh(fila)
    return {"usuario_id": usuario_id, "salario_mensual": float(fila.salario_mensual),
            "ok": True}


# ─── Tasas de ley ───────────────────────────────────────────────────────────

@router.get("/tasas")
def listar_tasas(db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    return [tsvc.a_dict(t) for t in tsvc.listar(db)]


@router.post("/tasas", status_code=201)
def crear_tasa(body: TasaIn, db: Session = Depends(get_db),
               admin: Usuario = Depends(require_admin)):
    datos = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    datos["vigente_desde"] = body.vigente_desde
    return tsvc.a_dict(tsvc.crear(db, datos))


@router.patch("/tasas/{tasa_id}")
def editar_tasa(tasa_id: int, body: TasaPatch, db: Session = Depends(get_db),
                admin: Usuario = Depends(require_admin)):
    fila = tsvc.actualizar(db, tasa_id, body.model_dump(exclude_unset=True))
    if fila is None:
        raise HTTPException(status_code=404, detail="Esa tasa no existe.")
    return tsvc.a_dict(fila)


# ─── Festivos ───────────────────────────────────────────────────────────────

@router.get("/festivos")
def listar_festivos(anio: Optional[int] = Query(None), db: Session = Depends(get_db),
                    admin: Usuario = Depends(require_admin)):
    return fsvc.calendario(db, anio or hoy_col().year)


@router.post("/festivos")
def guardar_festivo(body: FestivoIn, db: Session = Depends(get_db),
                    admin: Usuario = Depends(require_admin)):
    """Agrega un festivo que el código no calcula, o quita uno que sí calcula
    (`es_festivo=false`)."""
    fila = db.query(Festivo).filter(Festivo.fecha == body.fecha).first()
    if fila is None:
        fila = Festivo(fecha=body.fecha)
        db.add(fila)
    fila.nombre = body.nombre
    fila.es_festivo = body.es_festivo
    fila.nota = body.nota
    db.commit()
    return {"fecha": body.fecha.isoformat(), "es_festivo": body.es_festivo, "ok": True}


@router.delete("/festivos/{fecha}")
def borrar_festivo(fecha: date, db: Session = Depends(get_db),
                   admin: Usuario = Depends(require_admin)):
    """Borra el OVERRIDE: el día vuelve a lo que dice el cálculo."""
    fila = db.query(Festivo).filter(Festivo.fecha == fecha).first()
    if fila is None:
        raise HTTPException(status_code=404, detail="No hay override para esa fecha.")
    db.delete(fila)
    db.commit()
    return {"ok": True}
