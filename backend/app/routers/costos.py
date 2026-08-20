import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_barista_actor, require_admin
from app.core.tz import hoy_col
from app.database import get_db
from app.models.models import Usuario
from app.schemas.costos import (AdopcionEgresoRequest, ArmarMesRequest,
                                CategoriaCreate, CategoriaUpdate,
                                ComisionDatafonoRequest,
                                ImpoconsumoAgendarRequest,
                                ImpoconsumoDeclaradoRequest,
                                NominaAgendarRequest, ObligacionCreate,
                                ObligacionUpdate, PagoCreate,
                                ReservaMinimaRequest, SaldoBancoRequest)
from app.services import costos as svc

router = APIRouter(prefix="/costos", tags=["costos"])


@router.get("/categorias")
def listar_categorias(
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Catálogo de categorías activas (clave estable + nombre editable).

    Devuelve una LISTA pelada y así se queda: es la forma que consume la
    pantalla de Plata. Lo que hacía falta agregar —la explicación de los
    grupos— vive en `/categorias/grupos` justamente para no cambiarla.
    """
    return svc.listar_categorias(db)


# Declarado ANTES del PATCH de `/categorias/{categoria_id}` por prolijidad de
# lectura; no compiten (uno es GET y el otro PATCH), pero la regla del router es
# que la ruta literal va arriba de la paramétrica.
@router.get("/categorias/grupos")
def listar_grupos_categoria(
    admin: Usuario = Depends(require_admin),
):
    """Qué significa «fijo» y qué significa «variable», en el idioma del dueño.

    La copia sale del backend y no del formulario porque es la MISMA regla que
    decide `costos_fijos_devengados`: el grupo fijo es el que arma el piso de
    venta del mes. Definición y número tienen que salir del mismo archivo o se
    separan sin que nadie lo note. `advertencia` viene con texto solo en
    «variable», que es la elección que hay que explicar.
    """
    return svc.catalogo_grupos()


@router.post("/categorias")
def crear_categoria(
    data: CategoriaCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Crea una categoría de costo. Sin `grupo`, queda FIJA.

    Hasta acá el catálogo eran seis filas sembradas al arrancar, así que
    publicidad, internet, domicilios, seguros y el contador terminaban todos en
    «Otros»: cinco costos distintos en una sola línea del P&L.

    La respuesta trae `advertencia` con texto cuando la categoría quedó
    variable, para que la pantalla pueda decir por qué eso cambia el piso del
    mes en vez de guardar en silencio.
    """
    return svc.crear_categoria(db, data.nombre, data.grupo, admin.id)


@router.patch("/categorias/{categoria_id}")
def editar_categoria(
    categoria_id: int,
    data: CategoriaUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Corrige el nombre o el grupo de una categoría. La clave no se toca.

    Mover una categoría de variable a fijo le cambia el piso a TODO el
    histórico, no solo a lo que venga: el P&L agrupa por grupo cada vez que se
    abre. Es lo que se busca —así se arregla una mala clasificación vieja— y por
    eso queda auditado con el antes y el después.
    """
    return svc.editar_categoria(db, categoria_id,
                                data.model_dump(exclude_unset=True), admin.id)


@router.get("/agenda")
def agenda(
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    tienda_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Qué hay que pagar y cuándo: facturas de proveedor y costos fijos en UNA
    lista. Es la unión de dos consultas —la deuda con proveedores sigue viviendo
    solo en facturas_compra—, con el SALDO de cada ítem, no su total."""
    return svc.get_agenda(db, desde=desde, hasta=hasta, tienda_id=tienda_id)


@router.get("/flujo")
def flujo_proyectado(
    dias: Optional[int] = Query(None, ge=1, le=svc.HORIZONTE_MAX),
    tienda_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """El día en que se acaba la plata, ANTES de que pase.

    Serie diaria de saldo proyectado = efectivo en caja + saldo del banco
    declarado, más la venta esperada (MEDIANA por día de semana) y menos lo que
    hay que pagar. `punto_de_quiebre` es el primer día en negativo, o null.

    SIN `dias` el horizonte llega hasta FIN DE MES y no a 30 días fijos: el
    colchón que sale de esta serie tiene que mirar la misma ventana que el piso
    de venta (`/costos/piso`), o son dos respuestas a preguntas distintas puestas
    una al lado de la otra. `dias_hasta_fin_de_mes` y `horizonte_es_fin_de_mes`
    viajan en la respuesta para que la pantalla pueda decir cuál está mirando.

    Con `tienda_id` la proyección es SOLO de esa sede: el saldo del banco (que es
    de la empresa) no suma y las obligaciones corporativas quedan fuera, declaradas
    en `advertencias`. `advertencias` también dice cuándo faltan datos para que la
    respuesta signifique algo — un null en `punto_de_quiebre` no es un all-clear si
    nadie cargó las salidas."""
    return svc.get_flujo_proyectado(db, dias=dias, tienda_id=tienda_id)


@router.get("/piso")
def piso_de_venta(
    anio: int = Query(..., ge=2000, le=2100),
    mes: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """CUÁNTO HAY QUE VENDER ESTE MES PARA NO PERDER, y cuánto por día.

        piso del mes = costos fijos del mes completo / margen de contribución
        falta        = piso del mes − lo vendido en el mes a la fecha
        piso de hoy  = falta / los días que QUEDAN por abrir

    Los costos fijos se piden por el MES ENTERO y no "del 1 a hoy": el arriendo y
    la nómina se devengan a fin de mes, y con la ventana recortada el piso salía
    ridículamente bajo a principios de mes, que es cuando más se mira.

    El margen se MIDE sobre la venta real del mes —impuesto, costo de mercadería
    y comisión del datáfono como cocientes— y no se supone de las tarifas.

    CONTESTA 200 SIEMPRE. Las cuatro puertas de honestidad viajan en `puerta`, no
    como errores: sin costos fijos cargados no hay piso de resultado pero sí
    puede haber piso de caja, sin venta en el mes se usan las razones del mes
    anterior rotuladas, y un margen que no da positivo es un veredicto («cada
    venta pierde plata») y no un dato que falta. En todos los demás casos el
    número se publica rotulado «al menos», con `sesgos` diciendo cuáles de los
    cuatro están vivos — los cuatro empujan el piso hacia ABAJO.

    Los rangos de `anio`/`mes` van en Query y no en el servicio porque son
    límites de FORMA: un mes 13 no es una decisión de negocio mal tomada, es un
    parámetro que no existe, y ahí el 422 de FastAPI dice exactamente eso."""
    return svc.get_piso(db, anio, mes)


@router.get("/palancas")
def palancas_del_piso(
    anio: int = Query(..., ge=2000, le=2100),
    mes: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """QUIÉN SUBIÓ QUÉ, Y CUÁNTO LE MUEVE EL PISO POR DÍA.

    La línea que el dueño se lleva a la reunión: «Lácteos Andina subió la leche
    14%, toca $4.200.000 de venta al mes, y si ese precio se queda el piso me
    sube $180.000 por día». Las partes salen de la misma lectura para que no se
    puedan contradecir.

    EL PORCENTAJE ES CONTRA LA REFERENCIA —lo más barato que se le facturó a ese
    insumo en los últimos meses— y no contra el promedio con el que se costea:
    es el número que el proveedor puede verificar en su propia factura, y el
    único que no se apaga solo a medida que se compra al precio nuevo.

    Y LA PLATA SON DOS CIFRAS, NO UNA: «lo que todavía va a subir si el precio
    nuevo se queda» y «lo que baja hoy si el proveedor vuelve atrás» no son la
    misma plata mirada de dos formas. Ver `costos.get_palancas`.

    ES UN ENDPOINT APARTE DE `/piso` A PROPÓSITO. `/piso` lo pide también el
    bloque del año, DOCE veces seguidas, y el reparto del costo por insumo no
    tiene por qué correr doce veces para dibujar doce barras. Adentro llama a
    `get_piso` una vez y mide la suba CONTRA ESE piso: no hay una segunda cuenta
    del número, hay una diferencia contra el que ya se publicó.

    CONTESTA 200 SIEMPRE, con las mismas puertas del piso. Una suba que no se
    pudo traducir a pesos viaja igual con `sin_impacto_porque`: sacarla de la
    lista la volvería invisible justo para el que iba a ir a negociarla."""
    return svc.get_palancas(db, anio, mes)


@router.post("/comision-datafono")
def declarar_comision_datafono(
    data: ComisionDatafonoRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Lo que cobra el datáfono de cada venta con tarjeta.

    Sin este dato el piso de venta sale CORTO: la comisión se paga de cada venta
    y hoy no la descuenta nadie. Es uno de los cuatro sesgos que el propio piso
    declara, y el único que se apaga escribiendo un número.

    Se recibe en PORCENTAJE (2.5 = 2,5%) porque es como viene en el contrato del
    adquirente, y se guarda como fracción. El tope de 20% no es burocracia: una
    comisión más alta que eso es casi siempre un porcentaje tecleado como
    fracción o al revés, y guardarlo silenciosamente desfigura el piso.
    """
    p = data.porcentaje
    if not isinstance(p, (int, float)) or not math.isfinite(p):
        raise HTTPException(400, "La comisión tiene que ser un número.")
    if p < 0:
        raise HTTPException(400, "La comisión no puede ser negativa.")
    if p > 20:
        raise HTTPException(
            400, "Esa comisión es demasiado alta: se escribe en porcentaje "
                 "(por ejemplo 2.5 para 2,5%).")
    return svc.guardar_comision_datafono(db, p / 100.0, admin.id)


@router.post("/reserva-minima")
def declarar_reserva_minima(
    data: ReservaMinimaRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """La plata con la que el negocio no puede quedarse sin.

    Es lo que convierte «cuánto puedo gastar» en una decisión de negocio en vez
    de «cuánto puedo gastar hasta quedar en cero». El colchón del flujo se mide
    contra este número; el default es 0 y la respuesta del flujo lo dice
    (`reserva_es_default`), para que un cero sin decidir no pase por una decisión.

    La validación va acá y NO en el schema, mismo patrón que `/saldo-banco`: con
    Field(ge=..) el valor rechazado vuelve dentro del cuerpo del 422, un `inf` no
    es serializable a JSON y la respuesta de error revienta. Además el `detail`
    de un 422 es una LISTA y el cliente solo sabe leer strings."""
    if not math.isfinite(data.reserva):
        raise HTTPException(400, "La reserva debe ser un número válido")
    if data.reserva < 0:
        raise HTTPException(400, "La reserva no puede ser negativa")
    if data.reserva > svc.SALDO_BANCO_MAX:
        raise HTTPException(400, "La reserva es demasiado grande")
    return svc.guardar_reserva_minima_caja(db, data.reserva, admin.id)


@router.post("/saldo-banco")
def declarar_saldo_banco(
    data: SaldoBancoRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Declara cuánta plata hay en el banco. Es un dato del dueño: el sistema
    registra consignaciones, nunca un saldo bancario, así que no puede derivarlo.

    La validación va acá y NO en el schema (mismo patrón que la meta de ventas en
    routers/auth.py): con Field(ge=..) el valor rechazado vuelve dentro del cuerpo
    del 422 y un `inf` no es serializable a JSON — la respuesta de error revienta.
    El saldo además se persiste como TEXTO: un inf/NaN guardado rompería toda
    lectura futura, no solo esta escritura.
    """
    if not math.isfinite(data.saldo):
        raise HTTPException(400, "El saldo del banco debe ser un número válido")
    if data.saldo < 0:
        raise HTTPException(400, "El saldo del banco no puede ser negativo")
    if data.saldo > svc.SALDO_BANCO_MAX:
        raise HTTPException(400, "El saldo del banco es demasiado grande")
    fecha = data.fecha or hoy_col()
    if fecha > hoy_col():
        raise HTTPException(400, "La fecha del saldo no puede ser futura")
    return svc.guardar_saldo_banco(db, data.saldo, fecha, admin.id)


@router.get("/obligaciones")
def listar_obligaciones(
    tienda_id: Optional[int] = Query(None, ge=1),
    solo_corporativas: bool = Query(False),
    categoria: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    campo_fecha: str = Query("devengo"),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Lo que le cuesta el negocio, con su saldo. Sin `tienda_id` trae TODO —las
    corporativas incluidas—; con `tienda_id` trae solo esa sede."""
    return svc.listar_obligaciones(
        db, tienda_id=tienda_id, solo_corporativas=solo_corporativas,
        categoria=categoria, estado=estado, desde=desde, hasta=hasta,
        campo_fecha=campo_fecha)


@router.post("/obligaciones")
def crear_obligacion(
    data: ObligacionCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Registra un costo. `tienda_id` en null = gasto CORPORATIVO (sin sede)."""
    return svc.crear_obligacion(db, data, admin.id,
                                barista_id=barista[0], barista_nombre=barista[1])


@router.patch("/obligaciones/{obligacion_id}")
def editar_obligacion(
    obligacion_id: int,
    data: ObligacionUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    return svc.editar_obligacion(db, obligacion_id, data, admin.id)


# Ruta LITERAL antes de la paramétrica `/obligaciones/{obligacion_id}`. Acá SÍ
# competirían si estuviera abajo: `armar-mes` no parsea como int, así que
# FastAPI devolvería un 422 confuso en vez de esta ruta.
@router.post("/obligaciones/armar-mes")
def armar_el_mes(
    data: ArmarMesRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Copia TODAS las series mensuales a un mes, en un viaje y un solo commit.

    `confirmar: false` es la VISTA PREVIA: no escribe nada y devuelve
    `van_a_crearse` con concepto, monto y las dos fechas de cada una, más el
    `total` que le va a agregar al mes. `confirmar: true` las crea todas o
    ninguna.

    Es el reemplazo de hacer N veces `POST /obligaciones/{id}/repetir` desde la
    pantalla. Aquel endpoint sigue existiendo y sigue siendo la unidad de a una;
    lo que arregla este es el corte a la mitad: con catorce requests sueltas, una
    tablet que pierde señal en la séptima deja el mes armado por la mitad y
    ninguna pantalla lo dice.

    Idempotente igual que `repetir`: las series que ya tienen su copia de ese mes
    vuelven en `ya_estaban` y no se tocan. Las que NO se pueden copiar (categoría
    desactivada, o la vieja 'proveedores') vuelven en `no_se_pueden` con el
    porqué y no abortan el lote: una fila legacy no puede dejar el mes sin armar.

    LOS DOS CEROS VUELVEN SEPARADOS. `van_a_crearse: []` no dice por qué está
    vacío, y las dos razones son opuestas: «las series ya tienen su copia» (el
    mes está armado) o «no hay NINGUNA serie marcada como repetible» (el mes
    arranca sin un peso de costos fijos). `series_repetibles` las distingue, y
    `candidatas` trae las cuentas vivas que todavía no son serie —con su plata y
    su concepto— para que el dueño elija cuáles van. Lo que elige vuelve en
    `incluir` y se copia por el mismo camino; de ahí en más ya son serie.

    Los rangos de `anio`/`mes` los valida el handler con un 400 mostrable, no
    pydantic: el `detail` de un 422 es una lista y el cliente solo lee strings.
    Que un id de `incluir` SEA una cuenta elegible se valida en el servicio, que
    es donde está la base — y también con un 400 mostrable, nunca ignorándolo:
    tildar seis y que se creen cinco es el error que este módulo persigue."""
    if not (2000 <= data.anio <= 2100):
        raise HTTPException(400, "Año fuera de rango")
    if not (1 <= data.mes <= 12):
        raise HTTPException(400, "El mes va de 1 a 12")
    if any(i <= 0 for i in data.incluir):
        raise HTTPException(400, "Hay una cuenta elegida con un id inválido — "
                                 "recargá la pantalla y volvé a elegir")
    return svc.armar_mes(db, data.anio, data.mes, confirmar=data.confirmar,
                         usuario_id=admin.id, incluir=data.incluir,
                         barista_id=barista[0], barista_nombre=barista[1])


@router.get("/impoconsumo")
def declaracion_impoconsumo(
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """LA DECLARACIÓN DEL IMPOCONSUMO DEL BIMESTRE CERRADO.

    El único gasto grande que el sistema tenía bien contado y no mostraba nunca
    como plata a pagar: 7,41% de cada peso facturado se ve como menos venta todos
    los días y después aparece de golpe cada dos meses.

    Devuelve el bimestre a declarar, el mes en que la DIAN lo pide (el día exacto
    depende del NIT y el sistema no lo sabe: no se inventa), y el impoconsumo
    MEDIDO cobrado en ese bimestre — o `sin_monto_porque` en castellano cuando no
    se puede medir. Es LECTURA PURA: no crea ninguna obligación. La crea
    `POST /costos/impoconsumo/agendar`, con el monto a la vista, y `agendada`
    dice si ya existe.

    CONTESTA 200 SIEMPRE. Que no haya nada que declarar es una respuesta
    (`hay_que_declarar: false`), no un error."""
    return svc.get_impoconsumo(db)


@router.post("/impoconsumo/agendar")
def agendar_impoconsumo(
    data: ImpoconsumoAgendarRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Mete la declaración del bimestre en la agenda y en el flujo proyectado.

    Es el mismo movimiento que `POST /costos/nomina/agendar` le hizo al costo
    laboral: hasta acá el impoconsumo era un cálculo y un recordatorio, pero no
    plata que hay que pagar en una fecha — no estaba en la agenda, no bajaba la
    proyección y no tenía botón [Pagar]. Con $155,6M facturados en un bimestre son
    $11,5M que la caja no veía venir.

    LA OBLIGACIÓN NO ENTRA AL P&L NI AL PISO: va a una categoría dedicada que
    `rentabilidad._obligaciones_del_periodo` excluye por clave, igual que a la de
    proveedores. El margen ya se mide sobre la venta NETA de este impuesto, así
    que contarla otra vez como gasto sería la misma plata dos veces.

    `monto` es opcional: sin él manda lo MEDIDO sobre la venta real del bimestre,
    con él manda el dueño (la declaración la arma el contador).

    Idempotente por bimestre: si ya hay una obligación viva devuelve la que hay
    con `ya_existia: true`. 400 si el bimestre no cerró o si no hay monto medido
    ni escrito — una fila en $0 se leería como una cuenta ya resuelta— y también
    si el `monto` escrito queda muy por DEBAJO del medido: crear la fila apaga el
    aviso de cobertura de la caja, así que la cifra que lo apaga tiene que poder
    ser la declaración de ese bimestre. Escribir de MÁS no rebota."""
    return svc.agendar_impoconsumo(db, data.anio, data.bimestre, admin.id,
                                   monto=data.monto,
                                   barista_id=barista[0], barista_nombre=barista[1])


@router.post("/impoconsumo/declarado")
def marcar_impoconsumo(
    data: ImpoconsumoDeclaradoRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """«Esa ya la declaré»: el interruptor del recordatorio.

    Sin esto el aviso no se puede apagar nunca, y una advertencia que no se puede
    corregir se aprende a ignorar — el mismo motivo por el que existe
    `POST /costos/comision-datafono`.

    Marca el bimestre y todos los anteriores. Rechaza con 400 un bimestre que
    todavía no cerró: apagar por adelantado un aviso sobre plata que ni siquiera
    terminó de cobrarse apagaría de paso todos los de atrás."""
    return svc.marcar_impoconsumo_declarado(db, data.anio, data.bimestre, admin.id)


@router.post("/obligaciones/{obligacion_id}/repetir")
def repetir_obligacion(
    obligacion_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Crea la copia del MES SIGUIENTE de este costo (devengo y vencimiento +1 mes,
    con el día recortado al último real del mes). No es un scheduler: lo dispara
    el dueño y la copia queda editable.

    Idempotente por serie y mes: repetir dos veces devuelve la misma obligación
    con `ya_existia: true` en vez de cobrar el arriendo dos veces."""
    return svc.repetir_obligacion(db, obligacion_id, admin.id,
                                  barista_id=barista[0], barista_nombre=barista[1])


@router.post("/obligaciones/{obligacion_id}/no-repetir")
def dejar_de_repetir(
    obligacion_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """DESHACE que esta cuenta sea serie: deja de copiarse sola al mes siguiente.

    Es la vuelta de `repetir` y del tilde de «elegir qué va al mes que viene».
    Sin esto, tildar una vez la reparación del molino la convertía en un costo
    fijo mensual para siempre —está medido que anular una copia no alcanza y que
    anular la cabeza tampoco—, y el piso subía todos los meses por una plata que
    se pagó una sola vez.

    NO BORRA NI ANULA NADA: las obligaciones ya creadas siguen ahí con su plata y
    sus pagos, porque se deben igual. Lo único que cambia es que el mes que viene
    no se copian solas — vuelven a la lista de «elegir cuáles van».

    Idempotente: si ya no era serie contesta `ya_estaba: true` y no toca nada. No
    es un 400, porque no es un error del dueño: es el estado que él quería."""
    return svc.dejar_de_repetir(db, obligacion_id, admin.id,
                                barista_nombre=barista[1])


# Ruta literal ANTES de la paramétrica `/obligaciones/{obligacion_id}`, aunque
# no compitan: es la regla de lectura del router.
@router.post("/nomina/agendar")
def agendar_nomina(
    data: NominaAgendarRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Convierte la nómina de un mes en una obligación CORPORATIVA de verdad.

    Hasta acá el costo laboral era un cálculo y una pantalla, pero no plata que
    hay que pagar: no estaba en la agenda, no bajaba el flujo proyectado y no
    tenía botón [Pagar]. El gasto más grande del negocio faltaba en todas las
    cuentas que deciden si alcanza.

    El mes de DEVENGO decide de qué fuente sale el número —mes terminado, de las
    horas trabajadas; mes en curso o futuro, del contrato— y la fecha de
    VENCIMIENTO decide en qué día del flujo se dibuja. Con el pago a fin de mes
    coinciden, y por eso hay que escribirlo.

    `monto` es opcional: sin él manda el cálculo, con él manda el dueño.

    Idempotente por mes de devengo: si ya hay una obligación viva de nómina de
    ese mes devuelve la que hay con `ya_existia: true` y no crea nada.
    """
    return svc.agendar_nomina(db, data.anio, data.mes, admin.id,
                              monto=data.monto,
                              barista_id=barista[0], barista_nombre=barista[1])


@router.delete("/obligaciones/{obligacion_id}")
def anular_obligacion(
    obligacion_id: int,
    motivo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Baja LÓGICA: la saca de listados y totales sin borrar sus pagos."""
    return svc.anular_obligacion(db, obligacion_id, admin.id, motivo)


@router.get("/pagos")
def listar_pagos(
    obligacion_id: Optional[int] = Query(None, ge=1),
    factura_id: Optional[int] = Query(None, ge=1),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Qué plata salió y qué día — por fecha_pago, no por fecha de registro."""
    return svc.listar_pagos(db, obligacion_id=obligacion_id, factura_id=factura_id,
                            desde=desde, hasta=hasta)


@router.post("/pagos")
def registrar_pago(
    data: PagoCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Un pago apunta a una obligación O a una factura, nunca a las dos.
    `fecha_pago` es obligatoria: es EL DÍA QUE SALIÓ LA PLATA."""
    return svc.registrar_pago(db, data, admin.id,
                              barista_id=barista[0], barista_nombre=barista[1])


@router.get("/egresos-sin-adoptar")
def listar_egresos_sin_adoptar(
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    tienda_id: Optional[int] = Query(None, ge=1),
    limite: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Egresos de caja que el P&L todavía muestra como texto libre. Solo lectura:
    no modifica nada, solo dice qué hay para categorizar. Sin `desde` toma los
    últimos 90 días."""
    return svc.listar_egresos_sin_adoptar(db, desde=desde, hasta=hasta,
                                          tienda_id=tienda_id, limite=limite)


@router.post("/egresos/{movimiento_id}/adoptar")
def adoptar_egreso(
    movimiento_id: int,
    data: AdopcionEgresoRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Convierte un egreso suelto en obligación devengada + pago espejo. El
    MovimientoCaja NO se toca: el turno cuadra igual y el total de gastos del
    período no se mueve — la plata solo cambia de bolsa.

    400 si el egreso es un pago a proveedor (ya está contado en Compras),
    409 si ya fue adoptado."""
    return svc.adoptar_egreso(db, movimiento_id, data.categoria_id, admin.id,
                              fecha_devengo=data.fecha_devengo,
                              concepto=data.concepto,
                              beneficiario=data.beneficiario, nota=data.nota,
                              barista_id=barista[0], barista_nombre=barista[1])


@router.delete("/pagos/{pago_id}")
def anular_pago(
    pago_id: int,
    motivo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Baja lógica del pago: la obligación vuelve sola al estado que corresponda."""
    return svc.anular_pago(db, pago_id, admin.id, motivo)
