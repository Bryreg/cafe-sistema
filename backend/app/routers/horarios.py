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
from app.models.models import ContratoBarista, Festivo, ParametroNomina, Usuario
from app.services import festivos as fsvc
from app.services import horarios as hsvc
from app.services import nomina as nmsvc
from app.services import novedades_nomina as nsvc
from app.services import parametros_nomina as pnsvc
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
    # Almuerzo del turno. Los dos en None = sin almuerzo, que es el default y lo
    # que mandan los clientes viejos: el turno se liquida entero, como siempre.
    almuerzo_inicio: Optional[str] = None
    almuerzo_minutos: Optional[int] = None
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
    # Sueldo EN SMMLV (1.0 = "gana el mínimo"). Manda sobre `salario_mensual`.
    # Tres estados y los tres significan cosas distintas, por eso el endpoint
    # mira `model_fields_set` y no el valor:
    #   ausente  → no se toca lo que haya (ver `guardar_contrato`)
    #   null     → vuelve a pesos fijos
    #   > 0      → queda atado al mínimo vigente de cada fecha liquidada
    salario_en_smmlv: Optional[float] = None
    horas_semana_pactadas: Optional[float] = None
    fecha_ingreso: Optional[date] = None
    activo: bool = True
    nota: Optional[str] = None


class AjustarAlMinimoIn(BaseModel):
    tienda_id: int


class ParametroNominaPatch(BaseModel):
    """Edición de una vigencia de nómina desde la pantalla.

    `vigente_desde` se declara SOLO para poder rechazarlo con un mensaje que se
    entienda. Si no estuviera en el schema, Pydantic lo descartaría en silencio,
    devolvería 200 y el dueño se iría convencido de que movió la fecha.

    `confirmar_contador` es el cartel de "esto todavía no lo validó nadie". Se
    puede mandar solo (revisé y está bien, bajá el cartel), pero escribir
    cualquier OTRO campo ya lo baja solo: ver `editar_parametro_nomina`.
    """
    vigente_desde: Optional[date] = None
    smmlv: Optional[float] = None
    auxilio_transporte: Optional[float] = None
    dias_base_auxilio: Optional[int] = None
    tope_auxilio_smmlv: Optional[float] = None
    salud_empleado: Optional[float] = None
    pension_empleado: Optional[float] = None
    fsp_desde_smmlv: Optional[float] = None
    fsp_tarifa: Optional[float] = None
    salud_empleador: Optional[float] = None
    pension_empleador: Optional[float] = None
    arl: Optional[float] = None
    caja_compensacion: Optional[float] = None
    sena: Optional[float] = None
    icbf: Optional[float] = None
    exonerado_114_1: Optional[bool] = None
    prima: Optional[float] = None
    cesantias: Optional[float] = None
    intereses_cesantias: Optional[float] = None
    vacaciones: Optional[float] = None
    nota: Optional[str] = None
    confirmar_contador: Optional[bool] = None


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
                            creado_por_id=admin.id, nota=body.nota,
                            almuerzo_inicio=body.almuerzo_inicio,
                            almuerzo_minutos=body.almuerzo_minutos)
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

# Guardrail de tecleo, NO un valor de nómina: nadie en una cafetería gana veinte
# mínimos, así que un número más grande que esto es un cero de más. El valor del
# mínimo en pesos no aparece por ningún lado acá — sale de `parametros_nomina`.
MAX_SALARIO_EN_SMMLV = 20.0


def _validar_salario_en_smmlv(valor: Optional[float]) -> Optional[float]:
    """Normaliza el múltiplo de SMMLV que llega de la pantalla.

    Devuelve lo que hay que GUARDAR: None significa "sueldo en pesos fijos".
    El 0 se guarda como None a propósito y no como 0.0, porque
    `parametros_nomina.salario_del_contrato` trata el 0 como falsy y cae a los
    pesos fijos igual: dejar el 0.0 en la base sería un valor que dice una cosa
    y hace otra, y el día que alguien lea la fila va a creer que la persona está
    atada al mínimo y gana cero.
    """
    if valor is None:
        return None
    valor = float(valor)
    if valor < 0:
        raise HTTPException(
            status_code=400,
            detail="El salario en SMMLV no puede ser negativo.")
    if valor > MAX_SALARIO_EN_SMMLV:
        raise HTTPException(
            status_code=400,
            detail=(f"{valor:g} SMMLV es un salario imposible para una barista "
                    f"(el máximo que acepta la pantalla son {MAX_SALARIO_EN_SMMLV:g}). "
                    "Si querés un sueldo en pesos, dejá el campo en blanco y usá "
                    "el salario mensual."))
    return valor or None


def _fila_contrato(c: Optional[ContratoBarista], u: Usuario,
                   params: Optional[pnsvc.Parametros]) -> dict:
    """Un contrato como lo ve la pantalla, con el sueldo YA RESUELTO.

    El resuelto viaja calculado desde acá y no se deriva en el cliente porque
    la regla de resolución (el múltiplo de SMMLV manda sobre los pesos fijos, y
    el mínimo depende de la FECHA) tiene que existir en un solo lugar. Un
    segundo cálculo en JavaScript es un segundo lugar donde equivocarse, y
    encima uno que nadie testea.
    """
    return {
        "usuario_id": u.id, "nombre": u.nombre,
        "salario_mensual": float(c.salario_mensual) if c else 0.0,
        "salario_en_smmlv": (float(c.salario_en_smmlv)
                             if c and c.salario_en_smmlv else None),
        # Lo que gana HOY, ya con el múltiplo aplicado sobre el mínimo vigente.
        "salario_resuelto": pnsvc.salario_del_contrato(c, params) if c else 0.0,
        # Va en cada fila —y no una sola vez arriba— para no romper la forma de
        # este endpoint, que hoy devuelve una LISTA y así la consume la pantalla.
        "smmlv_vigente": float(params.smmlv) if params else None,
        "horas_semana_pactadas": c.horas_semana_pactadas if c else None,
        "fecha_ingreso": c.fecha_ingreso.isoformat() if c and c.fecha_ingreso else None,
        "activo": bool(c.activo) if c else True,
        "nota": c.nota if c else None,
        "tiene_contrato": c is not None,
    }


@router.get("/contratos")
def listar_contratos(tienda_id: int = Query(..., ge=1), db: Session = Depends(get_db),
                     admin: Usuario = Depends(require_admin)):
    personas = hsvc.baristas_de(db, tienda_id)
    contratos = {c.usuario_id: c for c in db.query(ContratoBarista).filter(
        ContratoBarista.usuario_id.in_([u.id for u in personas] or [0])).all()}
    params = pnsvc.para(db, hoy_col())
    return [_fila_contrato(contratos.get(u.id), u, params) for u in personas]


@router.put("/contratos/{usuario_id}")
def guardar_contrato(usuario_id: int, body: ContratoIn, db: Session = Depends(get_db),
                     admin: Usuario = Depends(require_admin)):
    fila = db.query(ContratoBarista).filter(
        ContratoBarista.usuario_id == usuario_id).first()
    if fila is None:
        fila = ContratoBarista(usuario_id=usuario_id)
        db.add(fila)
    fila.salario_mensual = body.salario_mensual
    # El múltiplo de SMMLV solo se toca si el cliente lo MANDÓ. Es la única
    # excepción al reemplazo total de este PUT, y es a propósito: un formulario
    # viejo —o cualquier cliente que no conozca el campo— manda el contrato sin
    # él, y con reemplazo total desataría del mínimo a una persona que el dueño
    # acababa de ajustar, en silencio y sin tocar esa pantalla. Para volver a
    # pesos fijos hay que mandar `salario_en_smmlv: null` explícitamente.
    if "salario_en_smmlv" in body.model_fields_set:
        fila.salario_en_smmlv = _validar_salario_en_smmlv(body.salario_en_smmlv)
    fila.horas_semana_pactadas = body.horas_semana_pactadas
    fila.fecha_ingreso = body.fecha_ingreso
    fila.activo = body.activo
    fila.nota = body.nota
    db.commit()
    db.refresh(fila)
    params = pnsvc.para(db, hoy_col())
    return {
        "usuario_id": usuario_id,
        "salario_mensual": float(fila.salario_mensual),
        "salario_en_smmlv": (float(fila.salario_en_smmlv)
                             if fila.salario_en_smmlv else None),
        "salario_resuelto": pnsvc.salario_del_contrato(fila, params),
        "smmlv_vigente": float(params.smmlv) if params else None,
        "ok": True,
    }


@router.post("/contratos/ajustar-al-minimo")
def ajustar_contratos_al_minimo(body: Optional[AjustarAlMinimoIn] = None,
                                tienda_id: Optional[int] = Query(None, ge=1),
                                db: Session = Depends(get_db),
                                admin: Usuario = Depends(require_admin)):
    """Pone a TODAS las baristas activas de la sede en 1 SMMLV, de una.

    Existe como operación masiva y no como "andá contrato por contrato" porque
    el pedido real es "que ganen el mínimo", y hacerlo de a una garantiza que
    algún mes quede una sin ajustar — que es justo el error que nadie ve hasta
    que la persona reclama. Además deja a todas atadas al MÚLTIPLO y no a un
    número en pesos: en enero, cuando salga el decreto, los sueldos suben solos.

    NO toca a las inactivas: una barista que ya no trabaja acá conserva su
    contrato apagado para que sus meses viejos sigan liquidando igual, y
    reactivarle el sueldo desde acá le cambiaría el histórico.

    La sede se acepta por QUERY o por body, las dos. No es indecisión: la
    pantalla lo manda como query (`?tienda_id=`) con el body vacío, y exigir
    solo body dejaba el botón contestando 422 para siempre — un error que no se
    ve en ningún test de backend porque los dos lados están bien por separado.
    """
    sede = tienda_id if tienda_id is not None else (body.tienda_id if body else None)
    if sede is None:
        raise HTTPException(
            status_code=422,
            detail="Falta `tienda_id` (por query o en el cuerpo) para saber qué sede ajustar.")

    params = pnsvc.para(db, hoy_col())
    if params is None or not params.smmlv:
        # Sin parámetros no hay mínimo que aplicar. Preferimos no escribir nada
        # antes que atar a todo el mundo a un múltiplo que resuelve a cero.
        raise HTTPException(
            status_code=400,
            detail=("No hay parámetros de nómina cargados, así que no se sabe cuánto "
                    "vale el salario mínimo. Revisá la pantalla de parámetros."))

    personas = hsvc.baristas_de(db, sede)
    contratos = {c.usuario_id: c for c in db.query(ContratoBarista).filter(
        ContratoBarista.usuario_id.in_([u.id for u in personas] or [0])).all()}

    ajustadas, ya_estaban, omitidas = [], [], []
    for u in personas:
        c = contratos.get(u.id)
        if c is not None and not c.activo:
            omitidas.append({"usuario_id": u.id, "nombre": u.nombre,
                             "razon": "El contrato está inactivo."})
            continue
        # UN MÚLTIPLO EXPLÍCITO DISTINTO DE 1 NO SE PISA. Una supervisora
        # guardada en 1,5 SMMLV no está «sin ajustar»: está ganando por encima
        # del mínimo a propósito. Bajarla a 1.0 desde un botón masivo es un
        # RECORTE de sueldo —$875.453 al mes en ese caso— disfrazado de ajuste,
        # y el botón no avisaba nada porque contaba «tiene múltiplo cargado»
        # en vez de «tiene múltiplo 1». Se saltea y se dice por qué.
        multiplo = float(c.salario_en_smmlv or 0.0) if c is not None else 0.0
        if multiplo > 0 and multiplo != 1.0:
            omitidas.append({
                "usuario_id": u.id, "nombre": u.nombre,
                "razon": (f"Gana {multiplo:g} SMMLV a propósito: bajarla a 1 sería "
                          "un recorte de sueldo. Cambialo en su fila si querés."),
            })
            continue
        anterior = pnsvc.salario_del_contrato(c, params) if c is not None else 0.0
        if c is None:
            # Sin contrato es exactamente la que se olvidaría de a una.
            c = ContratoBarista(usuario_id=u.id, salario_mensual=0.0, activo=True)
            db.add(c)
        cambio = float(c.salario_en_smmlv or 0.0) != 1.0
        # `salario_mensual` se deja como estaba: pasa a ser referencia
        # informativa (lo que ganaba antes), porque el múltiplo manda.
        c.salario_en_smmlv = 1.0
        destino = ajustadas if cambio else ya_estaban
        destino.append({"usuario_id": u.id, "nombre": u.nombre,
                        "salario_anterior": anterior,
                        "salario_nuevo": round(float(params.smmlv), 2)})
    db.commit()

    return {
        "tienda_id": sede,
        "smmlv_vigente": float(params.smmlv),
        "vigencia_parametros": params.vigente_desde.isoformat(),
        "salario_resultante": round(float(params.smmlv), 2),
        "ajustadas": len(ajustadas),
        "ya_estaban": len(ya_estaban),
        # Las dos listas juntas son "cuáles quedaron en el mínimo".
        "baristas": ajustadas + ya_estaban,
        "detalle_ajustadas": ajustadas,
        "omitidas": omitidas,
        # El efecto que no se ve y hay que decir: el múltiplo se resuelve contra
        # el mínimo de la FECHA LIQUIDADA, así que un mes ya cerrado deja de
        # liquidarse con el número en pesos que tenía y pasa a usar el mínimo de
        # su año. Para quien ya ganaba el mínimo no cambia nada; para quien
        # tenía otro número, sí, y el P&L de esos meses se mueve.
        "reinterpreta_meses_cerrados": any(
            a["salario_anterior"] > 0
            and abs(a["salario_anterior"] - float(params.smmlv)) > 1
            for a in ajustadas),
    }


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


# ─── Parámetros de nómina (mínimo, auxilio y aportes de ley) ────────────────

# Lo de acá abajo son GUARDRAILS DE TECLEO, no valores de ley: esta lista no
# decide cuánto vale nada, solo rechaza lo que no puede ser un número válido.
# La plata y los porcentajes viven todos en `parametros_nomina`.

# Van en TANTO POR UNO: 0.04 es el 4%. El error que ataja el rango 0–1 es el
# clásico "escribí 4 donde iba 0,04", que multiplica por cien el aporte de todo
# el mes y recién se nota cuando el costo de nómina no cierra contra el banco.
PARAMS_PORCENTAJE = (
    "salud_empleado", "pension_empleado", "fsp_tarifa",
    "salud_empleador", "pension_empleador", "arl", "caja_compensacion",
    "sena", "icbf", "prima", "cesantias", "intereses_cesantias", "vacaciones",
)
# Estos NO son porcentajes: están EN SMMLV (el tope del auxilio son 2 mínimos,
# el fondo de solidaridad arranca en 4). Meterlos en la bolsa de arriba los
# haría rebotar siempre por "fuera de 0 a 1", y el tope del auxilio quedaría
# imposible de corregir desde la pantalla para siempre.
PARAMS_EN_SMMLV = ("tope_auxilio_smmlv", "fsp_desde_smmlv")
MAX_PARAM_EN_SMMLV = 50.0
# Pesos decretados cada diciembre: positivos y punto. Un cero de más o de menos
# en el mínimo desfigura la nómina entera, así que ni el cero pasa.
PARAMS_EN_PESOS = ("smmlv", "auxilio_transporte")

CAMPOS_EDITABLES_PARAMS = (
    PARAMS_EN_PESOS + PARAMS_EN_SMMLV + PARAMS_PORCENTAJE
    + ("dias_base_auxilio", "exonerado_114_1", "nota")
)


def _validar_parametros_nomina(cambios: dict) -> None:
    """Rechaza los valores que no pueden ser. Ninguna columna es nullable, así
    que un `null` explícito también rebota: mandarlo tumbaría la liquidación
    entera con un error de base de datos en vez de con un mensaje."""
    for campo in PARAMS_EN_PESOS:
        if campo in cambios:
            v = cambios[campo]
            if v is None or float(v) <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"«{campo}» es un valor en pesos y tiene que ser mayor que cero.")
    for campo in PARAMS_PORCENTAJE:
        if campo in cambios:
            v = cambios[campo]
            if v is None or not (0.0 <= float(v) <= 1.0):
                raise HTTPException(
                    status_code=400,
                    detail=(f"«{campo}» se escribe en tanto por uno, entre 0 y 1: "
                            "el 4% se carga como 0.04, no como 4."))
    for campo in PARAMS_EN_SMMLV:
        if campo in cambios:
            v = cambios[campo]
            if v is None or not (0.0 < float(v) <= MAX_PARAM_EN_SMMLV):
                raise HTTPException(
                    status_code=400,
                    detail=(f"«{campo}» se expresa en salarios mínimos (2 = dos SMMLV) "
                            f"y tiene que estar entre 0 y {MAX_PARAM_EN_SMMLV:g}."))
    if "dias_base_auxilio" in cambios:
        v = cambios["dias_base_auxilio"]
        if v is None or not (1 <= int(v) <= 31):
            raise HTTPException(
                status_code=400,
                detail=("«dias_base_auxilio» es el divisor del auxilio por día "
                        "(30 por ley) y tiene que estar entre 1 y 31."))


@router.get("/parametros-nomina")
def listar_parametros_nomina(db: Session = Depends(get_db),
                             admin: Usuario = Depends(require_admin)):
    """Las vigencias del mínimo, el auxilio y los aportes, de la más vieja a la
    más nueva. Siembra antes de listar, igual que `/tasas`: una base donde nunca
    corrió el seed devolvería una lista vacía y la pantalla diría que no hay
    parámetros, cuando lo que falta es escribirlos."""
    pnsvc.sembrar(db)
    return [pnsvc.a_dict(p) for p in pnsvc.listar(db)]


@router.put("/parametros-nomina/{param_id}")
def editar_parametro_nomina(param_id: int, body: ParametroNominaPatch,
                            db: Session = Depends(get_db),
                            admin: Usuario = Depends(require_admin)):
    """Corrige una vigencia. La fecha NO se toca.

    Es la misma regla que `tasas_laborales.actualizar()`: mover `vigente_desde`
    reescribe hacia atrás meses ya liquidados, porque cada período se resuelve
    con la vigencia de SU fecha. Allá la fecha simplemente no está en la lista
    de campos editables; acá además se contesta 400, porque este endpoint es un
    PUT que recibe la fila entera y descartar la fecha en silencio le haría
    creer al dueño que la movió.
    """
    cambios = body.model_dump(exclude_unset=True)
    if "vigente_desde" in cambios:
        raise HTTPException(
            status_code=400,
            detail=("La fecha de una vigencia no se puede mover: cada mes se liquida "
                    "con los parámetros de SU fecha, así que correrla recalcularía "
                    "nóminas que ya se pagaron. Si la fecha está mal, creá otra "
                    "vigencia con la fecha correcta."))

    fila = db.query(ParametroNomina).filter(ParametroNomina.id == param_id).first()
    if fila is None:
        raise HTTPException(status_code=404, detail="Esa vigencia de nómina no existe.")

    _validar_parametros_nomina(cambios)
    escritos = 0
    for campo in CAMPOS_EDITABLES_PARAMS:
        if campo in cambios:
            setattr(fila, campo, cambios[campo])
            escritos += 1

    if escritos:
        # Tocar un número ES la revisión: el cartel de "confirmar con el
        # contador" marca los valores que sembró el sistema y que nadie miró
        # todavía, así que en cuanto el dueño escribe encima deja de aplicar.
        fila.confirmar_contador = False
    elif "confirmar_contador" in cambios:
        # Sin cambios de valor, el único envío que tiene sentido es bajar (o
        # volver a subir) el cartel: "lo revisé y está bien como está".
        fila.confirmar_contador = bool(cambios["confirmar_contador"])

    db.commit()
    db.refresh(fila)
    return pnsvc.a_dict(fila)


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
