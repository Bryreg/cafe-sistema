"""El LIBRO del banco sobre HTTP: una fila por día, con la fórmula de la hoja.

Todo es admin. El saldo del banco no es información de turno: la barista no lo
necesita para operar y verlo no la ayuda a nada.

═══════════════════════════════════════════════════════════════════════════════
DIVISIÓN DE TRABAJO CON `services/banco.py`
═══════════════════════════════════════════════════════════════════════════════
La REGLA vive en el servicio; acá solo se traduce a HTTP. El servicio levanta
ValueError con un texto escrito PARA EL DUEÑO ("el monto va en positivo: el
signo lo decide si es entrada o salida"), así que ese mensaje viaja TAL CUAL
dentro del 400. Reemplazarlo por un "datos inválidos" genérico lo dejaría sin
saber qué corregir, que es justo lo que el mensaje del servicio ya resuelve.

Lo único que se valida acá y no allá son los guardrails de TECLEO que dependen
del transporte o de la columna: un `Infinity` que solo puede llegar por JSON, un
monto que no cabe en Numeric(12,2), un mes 13 que reventaría `date()`. Ninguno
de esos es una regla del negocio — son formas de que un 500 no se disfrace de
dato guardado.
"""
import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.tz import hoy_col

# Piso de fecha para TODO el libro: el ancla y los movimientos. Una fecha
# anterior es siempre un tecleo (el año con dos dígitos, un dígito de más), y
# en el ANCLA pesa más que en cualquier movimiento: es la raíz de la cadena, y
# con una fecha absurdamente vieja todos los días de toda la historia quedan
# marcados con saldo confiable y el cartel que explica desde cuándo se conoce
# el saldo desaparece.
LIBRO_DESDE = date(2000, 1, 1)
from app.database import get_db
from app.models.models import Obligacion, Usuario
from app.services import banco
from app.services import costos as costos_svc

router = APIRouter(prefix="/banco", tags=["banco"])


# Cota de tecleo del año. `date(anio, mes, 1)` revienta con ValueError fuera del
# rango legal y `serie_mensual` recorre doce meses: un cero de más en el año
# convertiría un error de tipeo en un 500 sin mensaje.
ANIO_MIN, ANIO_MAX = 2000, 2100

# Lo máximo que entra en `MovimientoBanco.monto`, que es Numeric(12, 2): diez
# dígitos enteros. Más que esto lo rechaza Postgres con un error de rango —o sea
# un 500— cuando en realidad es un cero de más al teclear.
MONTO_MAX = 9_999_999_999.99


def _anio_mes(anio: Optional[int], mes: Optional[int]) -> tuple[int, int]:
    """El mes que se pide, o el de hoy en Colombia. Con 400 en vez de 500."""
    hoy = hoy_col()
    a = hoy.year if anio is None else int(anio)
    m = hoy.month if mes is None else int(mes)
    if not 1 <= m <= 12:
        raise HTTPException(400, "Mes inválido (tiene que ser 1 a 12).")
    if not ANIO_MIN <= a <= ANIO_MAX:
        raise HTTPException(400, f"Año inválido (tiene que ser {ANIO_MIN} a {ANIO_MAX}).")
    return a, m


def _anio(anio: Optional[int]) -> int:
    return _anio_mes(anio, 1)[0]


class MovimientoIn(BaseModel):
    """Un movimiento del banco, tecleado por el dueño.

    NO expone `automatico`: esa bandera marca lo que el SISTEMA sugirió solo
    (GMF, comisión del datáfono) y existe para poder distinguirlo de lo que él
    escribió a mano. Si el cliente pudiera prenderla, la distinción dejaría de
    significar nada — un movimiento que llega por este endpoint es, por
    definición, tecleado.
    """
    # Las cotas de fecha y de largo NO van acá sino en el handler, como
    # HTTPException(400). Pydantic rechaza con 422 y un `detail` que es una
    # LISTA de objetos, y el cliente solo sabe leer `detail` cuando es texto
    # (frontend/.../banco.ts): el mensaje bien escrito no llegaba nunca y el
    # dueño leía «Reintentá», que lo invita a repetir algo que va a fallar
    # siempre igual. Cambiar un 500 por un 422 mudo no es arreglarlo.
    fecha: date
    cuenta_id: int
    tipo: str                      # 'entrada' | 'salida' — lo valida el servicio
    monto: float                   # SIEMPRE positivo; el signo lo pone el tipo
    concepto: str
    # Si el movimiento paga una obligación ya cargada, se enlaza: así el
    # calendario puede tachar ese vencimiento en vez de mostrarlo pendiente.
    obligacion_id: Optional[int] = None
    # La categoría del movimiento (cualquier ámbito: café, personal, banco).
    # Opcional: un movimiento sin clasificar es válido, no un error.
    categoria_id: Optional[int] = None
    nota: Optional[str] = None


class AnclaIn(BaseModel):
    """El saldo del extracto: con cuánta plata ARRANCA ese día.

    Sin restricciones de pydantic a propósito, por el mismo motivo que
    `SaldoBancoRequest` (schemas/costos.py): un valor rechazado por el schema
    vuelve DENTRO del cuerpo del 422 y un `inf` no es serializable a JSON — la
    respuesta de error revienta antes de llegar. La validación va en el handler
    y contesta 400 con un texto que se entiende.
    """
    saldo: float
    fecha: Optional[date] = None   # None = hoy


@router.get("/libro")
def libro_del_mes(
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Una fila por día del mes: arranca, entra, sale, queda.

    Van TODOS los días, también los que no tuvieron movimiento: son los que
    dejan ver que el saldo se quedó abajo cuatro días seguidos.

    LA CADENA SE DECIDE POR DÍA. Cada fila trae su `cadena`: en false el día es
    anterior al ancla, no se sabe cuánta plata había y `inicial`/`final` van en
    null. `cadena_completa` significa «TODOS los días del rango tienen saldo» y
    con el ancla a mitad de mes —el caso normal— es false aunque del ancla en
    adelante el saldo sea exacto: la pantalla NO puede decidir con esa bandera.
    Para decir la verdad parcial están `dias_con_saldo` y `primer_dia_con_saldo`.
    """
    a, m = _anio_mes(anio, mes)
    desde, hasta = banco.dias_del_mes(a, m)
    return banco.libro(db, desde, hasta)


@router.get("/por-categoria")
def por_categoria(
    anio: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Cuánto se está yendo en cada cosa, mes a mes: las salidas del libro
    agrupadas por categoría, los doce meses del año. Lo sin categoría viaja
    como «Sin clasificar» — dicho, no escondido."""
    a, _ = _anio_mes(anio, None)
    return banco.por_categoria_anual(db, a)


@router.get("/consignaciones-preview")
def preview_consignaciones(
    desde: date = Query(...),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Qué cambiaría si las consignaciones entraran solas al libro desde esa
    fecha: cuántas son y cuánta plata, y qué entradas de Occidente ya tecleadas
    en ese rango quedarían contadas DOS veces. Es la vista previa con la que se
    decide la activación — nunca un interruptor a ciegas."""
    if desde < LIBRO_DESDE:
        raise HTTPException(400, "Esa fecha es anterior al año 2000: revisá lo "
                                 "que tecleaste.")
    return banco.preview_consignaciones(db, desde)


class ConsignacionesDesdeIn(BaseModel):
    desde: date


@router.post("/consignaciones-desde")
def activar_consignaciones(
    data: ConsignacionesDesdeIn,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Activa el régimen: desde `desde`, cada consignación entra al libro en SU
    día, como entrada de Occidente, sin que nadie la teclee. Se fija UNA vez."""
    if data.desde < LIBRO_DESDE:
        raise HTTPException(400, "Esa fecha es anterior al año 2000: revisá lo "
                                 "que tecleaste.")
    try:
        return banco.activar_consignaciones(db, data.desde)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/serie")
def serie_del_anio(
    anio: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Los doce meses: cuánto entró, cuánto salió y con cuánto cerró cada uno.

    `cierre` en null es la declaración honesta de que la cadena no llega hasta
    ese mes (falta el saldo del extracto): no es un cierre de cero.
    """
    return banco.serie_mensual(db, _anio(anio))


@router.get("/cuentas")
def listar_cuentas(
    solo_activas: bool = Query(True),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Los rieles por donde entra y sale la plata (Occidente, Bold).

    NO siembra: las cuentas las crea el arranque de la app (`main.py`). Sembrar
    de forma perezosa adentro de un GET hace que dos cargas simultáneas de la
    pantalla intenten crear la misma cuenta y una reviente con IntegrityError —
    el mismo motivo por el que los parámetros tributarios se siembran al boot.

    Misma forma que `cuentas` dentro del libro: una sola forma para la pantalla.
    """
    return [{"id": c.id, "nombre": c.nombre, "activa": bool(c.activa),
             "nota": c.nota} for c in banco.cuentas(db, solo_activas=solo_activas)]


@router.post("/movimientos")
def crear_movimiento(
    data: MovimientoIn,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Carga un movimiento. Devuelve el movimiento creado, NO el saldo del día.

    Y no lo devuelve a propósito: un movimiento mueve el saldo de TODOS los días
    siguientes del mes (la cadena se deriva, no se guarda). Contestar con el día
    tocado invitaría a parchear esa fila en pantalla y dejar el resto del mes
    mostrando saldos viejos. La pantalla tiene que recargar el mes.
    """
    if not math.isfinite(data.monto):
        raise HTTPException(400, "El monto tiene que ser un número válido.")
    # Solo el lado positivo: un monto negativo lo rechaza el servicio con el
    # mensaje que corresponde ("el monto va en positivo"), que es más útil que
    # mandarlo a contar ceros.
    if data.monto > MONTO_MAX:
        raise HTTPException(400, "Ese monto es demasiado grande: revisá los ceros.")
    # LA FECHA, ACOTADA ACÁ Y CON TEXTO. Sin cota, 9999-12-31 se guardaba y
    # reventaba AL RELEERLA: el libro recorre día por día y `d += timedelta(1)`
    # desborda `date.max`. Y el tope superior es HOY porque este libro es plata
    # que YA SE MOVIÓ —es lo que la propia pantalla promete— mientras que un
    # débito futuro que se sabe va en Obligaciones, que es lo único que el
    # punto de quiebre mira. Aceptándolo acá, bajaba el saldo del libro y NO
    # bajaba la proyección: dos números para la misma pregunta, con el
    # optimista en la pestaña que se mira primero.
    if data.fecha < LIBRO_DESDE:
        raise HTTPException(400, "Esa fecha es anterior al año 2000: revisá lo "
                                 "que tecleaste.")
    if data.fecha > hoy_col():
        raise HTTPException(400, "El libro es de plata que YA se movió, así que "
                                 "no acepta fechas futuras. Un débito que ya "
                                 "sabés que viene va en Obligaciones, que es lo "
                                 "que mira la proyección.")
    if len(data.concepto or "") > 160:
        raise HTTPException(400, "El concepto no puede pasar de 160 caracteres.")
    if len(data.nota or "") > 300:
        raise HTTPException(400, "La nota no puede pasar de 300 caracteres.")
    if data.obligacion_id is not None and db.query(Obligacion).filter(
            Obligacion.id == data.obligacion_id).first() is None:
        raise HTTPException(400, "Esa obligación no existe.")
    try:
        mov = banco.registrar(
            db, data.fecha, data.cuenta_id, data.tipo, data.monto, data.concepto,
            usuario_id=admin.id, obligacion_id=data.obligacion_id, nota=data.nota,
            categoria_id=data.categoria_id)
    except ValueError as e:
        # El texto del servicio ya está escrito para que lo lea el dueño.
        raise HTTPException(400, str(e))

    # Se relee por el libro de ESE día en vez de armar el dict acá: así el
    # movimiento que devuelve el POST tiene exactamente la misma forma que los
    # que vienen adentro de `dias[].movimientos`, y la pantalla no necesita
    # aprender dos formas del mismo objeto.
    fila = banco.libro(db, mov.fecha, mov.fecha)["dias"][0]
    out = next(m for m in fila["movimientos"] if m["id"] == mov.id)
    # Bajo el régimen de consignaciones-al-libro, una entrada de Occidente
    # tecleada puede ser la MISMA plata que una consignación ya proyectada.
    # No se bloquea (una transferencia recibida es legítima) pero se dice, con
    # la clave aditiva que el bundle viejo ignora.
    corte = banco.consignaciones_desde(db)
    if (corte is not None and data.tipo == "entrada" and data.fecha >= corte
            and out.get("cuenta") == "Occidente"):
        out["advertencia"] = (
            "Ojo: desde el " + corte.isoformat() + " las consignaciones entran "
            "solas al libro. Si esta entrada es una consignación, ya está "
            "contada y quedaría dos veces — borrala si es el caso.")
    return out


@router.delete("/movimientos/{movimiento_id}")
def borrar_movimiento(
    movimiento_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Se borra de verdad y el saldo se reacomoda solo (está derivado).

    No hay "anulado" en este libro: un movimiento anulado que siguiera sumando
    sería un saldo mentiroso, y uno que no sumara es idéntico a no existir.
    """
    if not banco.borrar(db, movimiento_id):
        raise HTTPException(404, "Ese movimiento no existe.")
    return {"ok": True}


@router.put("/ancla")
def declarar_ancla(
    data: AnclaIn,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """El saldo del extracto, que es de dónde arranca toda la cadena.

    Es un dato del dueño: el sistema registra consignaciones, nunca un saldo
    bancario, así que no puede derivarlo. Sin él NINGÚN día del libro tiene
    saldo (`dias_con_saldo` en 0), y con él lo tienen los días de esa fecha en
    adelante — los anteriores siguen en null, que es lo honesto.

    ESCRIBE LAS MISMAS DOS CLAVES que `POST /costos/saldo-banco`
    (`saldo_banco` y `saldo_banco_fecha` en `configuracion`), y lo hace llamando
    al MISMO servicio: dos escritores con reglas distintas sobre la misma fila
    darían dos verdades según por qué pantalla se entró. Por eso las
    validaciones de abajo son las de aquel handler, no unas nuevas.
    """
    if not math.isfinite(data.saldo):
        raise HTTPException(400, "El saldo del banco tiene que ser un número válido.")
    if data.saldo < 0:
        raise HTTPException(400, "El saldo del banco no puede ser negativo.")
    if data.saldo > costos_svc.SALDO_BANCO_MAX:
        raise HTTPException(400, "El saldo del banco es demasiado grande.")
    fecha = data.fecha or hoy_col()
    if fecha < LIBRO_DESDE:
        raise HTTPException(400, "La fecha del extracto es anterior al año 2000: "
                                     "revisá lo que tecleaste.")
    if fecha > hoy_col():
        raise HTTPException(400, "La fecha del saldo no puede ser futura.")

    costos_svc.guardar_saldo_banco(db, data.saldo, fecha, admin.id)

    # Se relee del ancla (no se devuelve lo que llegó): lo que la pantalla
    # muestre tiene que ser lo que quedó guardado, no lo que se pidió guardar.
    saldo, guardada = banco.ancla(db)
    return {
        "saldo": saldo,
        "fecha": guardada.isoformat() if guardada else None,
        # Cuántos días hace que se miró ese extracto. Es el dato que deja decir
        # "saldo del viernes" en vez de hacerlo pasar por el de hoy.
        "dias_desde": (hoy_col() - guardada).days if guardada else None,
        "desactualizado": (guardada is None
                           or (hoy_col() - guardada).days
                           > costos_svc.DIAS_SALDO_BANCO_VIGENTE),
    }
