// ─── La forma EXACTA de `GET /costos/piso` ───────────────────────────────────
//
// Misma regla que `components/plata/tipos.ts`: no hay un tipo «de pantalla»
// distinto del tipo «de la API». Cada traducción es un lugar donde se recalcula
// plata con otra regla, y este endpoint existe justamente para que la plata se
// calcule UNA vez, allá.
//
// ═════════════════════════════════════════════════════════════════════════════
// LOS `| null` DE ACÁ NO SON DESCUIDO: SON LAS PUERTAS
// ═════════════════════════════════════════════════════════════════════════════
// El backend contesta 200 SIEMPRE y dice en `puerta` por qué no pudo calcular
// algo. Los campos que ese estado deja sin calcular vienen en `null`, y están
// tipados `number | null` para que ninguna pantalla pueda imprimirlos sin
// escribir antes qué se ve cuando no están. Es el mismo candado que `Dato<T>`
// pone un nivel más arriba: allá «no se pudo preguntar», acá «se preguntó y la
// respuesta es que todavía no se puede decir».
//
// Los dos casos se dibujan DISTINTO a propósito. Un fetch caído se arregla
// reintentando; una puerta se arregla cargando el arriendo.

/** Las cinco puertas. Las decide el BACKEND: la pantalla dibuja, no clasifica. */
export type PuertaPiso =
  | 'ok'
  | 'sin_costos_fijos'
  | 'sin_razones'
  | 'margen_no_positivo'
  | 'razones_del_mes_anterior'

export interface CategoriaCosto {
  clave: string
  nombre: string
  monto: number
  n: number
}

/** EL NUMERADOR: lo que hay que pagar venda lo que venda, del MES COMPLETO. */
export interface CostosFijosPiso {
  total: number
  n: number
  hay: boolean
  /**
   * La ventana del numerador, explícita y auditable — y DISTINTA de la de
   * `razones`. El arriendo y la nómina se devengan a fin de mes: con la ventana
   * recortada a «del 1 a hoy» el piso salía ridículamente bajo justo a
   * principios de mes, que es cuando más se mira. Que las dos fechas viajen por
   * separado es lo que deja mostrar en pantalla que la diferencia es a propósito.
   */
  desde: string
  hasta: string
  nomina_calculada: number
  nomina_manual_en_ventana: number
  nomina_sin_contrato: number
  por_categoria: CategoriaCosto[]
}

/** EL DENOMINADOR: de cada $100 cobrados, cuánto queda. Todo MEDIDO, no supuesto. */
export interface RazonesPiso {
  /** `mes_anterior` = las razones son PRESTADAS y la pantalla tiene que decirlo. */
  de: 'mes_pedido' | 'mes_anterior'
  desde: string
  hasta: string
  ventas_medidas: number
  /** MEDIDO (impoconsumo/ventas), no la tarifa ni tasa/(1+tasa). */
  impoconsumo: number
  /**
   * La mercadería de lo vendido, CON los desechables adentro. El vaso, la tapa
   * y la servilleta son costo de la bebida: dejarlos afuera era uno de los
   * cuatro sesgos declarados de este piso, y meterlos lo SUBE.
   */
  cogs: number
  /** ADITIVOS, ya adentro de `cogs`. Se abren para poder nombrar el empaque sin
   *  volver a restarlo: `cogs = cogs_sin_desechables + cogs_desechables`. */
  cogs_desechables: number
  cogs_sin_desechables: number
  comision: number
  tasa_comision: number
  pct_tarjeta: number
  /**
   * Qué parte de la venta tiene costo cargado, 0..100.
   *
   * Decide las PALABRAS de la banda de sesgos, NUNCA si el número existe. Un
   * costeo del 40% no invalida el piso: lo deja corto, que es exactamente lo
   * que el rótulo «al menos» está diciendo.
   */
  pct_venta_costeada: number | null
  /**
   * Qué parte de la venta viene de productos CON desechables cargados, 0..100.
   *
   * Hermana de `pct_venta_costeada`: decide si el sesgo del empaque sigue vivo.
   * Con el 12% cargado, el vaso sigue casi todo afuera del costo aunque
   * `cogs_desechables` ya no sea cero.
   */
  pct_venta_con_desechables: number | null
}

export interface DiasPiso {
  /** Días que ABRE entre hoy y fin de mes, hoy incluido. Es el divisor. */
  quedan: number
  calendario: number
  /** 0 = lunes. Sin el 6 = cierra los domingos. */
  dias_semana: number[]
  /** false = no había historia y se contó el calendario pelado. */
  derivados: boolean
  incluye_hoy: boolean
}

/**
 * LA COLUMNA DE REPUESTO.
 *
 * No necesita costos de producto: sale de lo que hay en caja contra lo que hay
 * que pagar. Por eso sobrevive a la puerta `sin_costos_fijos`, que es justo
 * cuando el piso de resultado no se puede decir.
 */
export interface PisoCaja {
  por_dia: number | null
  del_mes: number | null
  /** Σ agenda con fecha <= fin de mes, VENCIDO incluido. */
  salidas_agendadas: number
  vencido: number
  reserva: number
  reserva_es_default: boolean
  caja_hoy: number
  /** Plata que se debe y que este piso todavía NO mira: sin fecha, no proyecta. */
  sin_fecha: number
}

/**
 * Uno de los cuatro sesgos. Los cuatro empujan para el MISMO lado —hacia abajo—
 * y por eso el backend puede rotular el número «al menos» sin mentir.
 *
 * `detalle` es un mapa laxo porque cada sesgo trae lo suyo (`venta_sin_costear`,
 * `pct_venta_costeada`, `productos_con_desechables`, `pct_tarjeta`,
 * `tasa_comision`). Se lee campo por campo y con guarda de tipo: un `detalle`
 * que cambie de forma allá no puede imprimir `undefined` acá.
 */
export interface SesgoPiso {
  clave: string
  activo: boolean
  texto: string
  detalle: Record<string, number | null>
}

export interface Piso {
  anio: number
  mes: number
  hoy: string
  desde: string
  hasta: string
  puerta: PuertaPiso
  costos_fijos: CostosFijosPiso
  /** null SOLO con puerta `sin_razones`. Con `margen_no_positivo` SÍ viene. */
  margen_contribucion: number | null
  razones: RazonesPiso | null
  /** Lo vendido en el MES PEDIDO. 0.0 si las razones son prestadas. */
  ventas_mes: number
  /** EN PESOS COBRADOS: el impoconsumo ya está adentro. */
  piso_mes: number | null
  piso_hoy: number | null
  /** Negativo = ya lo pasó. NO se recorta en cero: eso es una noticia. */
  falta: number | null
  cubierto: boolean
  /** LOS MISMOS DOS NÚMEROS de arriba, servidos juntos. No es un segundo cálculo. */
  titular: { falta: number | null; por_dia: number | null }
  dias: DiasPiso
  piso_caja: PisoCaja
  /** El MÁS ALTO de los dos `por_dia`: cubrir el más chico y creer que alcanza
   *  es exactamente el error que este módulo viene arrastrando. */
  manda: 'resultado' | 'caja' | null
  el_otro: 'resultado' | 'caja' | null
  /** [] con puerta `sin_razones`. Nunca `undefined`. */
  sesgos: SesgoPiso[]
  rotulo: 'al_menos'
}

// ─── La forma EXACTA de `GET /costos/palancas` ───────────────────────────────
//
// «Lácteos Andina subió la leche 14%, toca $4.200.000 de venta al mes, y con ese
// precio el piso me sube $180.000 por día». Las cuatro piezas de esa frase salen
// de la MISMA lectura para que no se puedan contradecir entre sí.

/** Una suba de precio, con nombre y traducida a pesos de piso por día. */
export interface Palanca {
  insumo_id: number
  nombre: string
  unidad_medida: string | null
  /**
   * Quién la subió, tal como está escrito en la factura que fijó el precio
   * nuevo. `null` solo si esa factura no tiene proveedor cargado.
   */
  proveedor: string | null
  fecha_ultimo: string | null
  /** Los tres SIN redondear (se imprimen con `fmtUnit`, nunca con `fmt`).
   *  `costo_usado` es con el que hoy se costea; `costo_ref` el más barato de los
   *  últimos `ref_meses` meses, que es contra el que se mide `pct_suba`. */
  costo_usado: number
  costo_ultimo: number
  costo_ref: number
  /** De qué factura salió la referencia: deja verificar el «+40%» en el papel. */
  ref_proveedor: string | null
  ref_fecha: string | null
  ref_meses: number
  /** `true` = el de la referencia y el de ahora son el mismo proveedor. Decide
   *  si la frase puede tener al proveedor de SUJETO. */
  mismo_proveedor: boolean
  /** Lo que movió el proveedor (último contra referencia), no contra el promedio. */
  pct_suba: number
  /** Qué parte de esa suba ya está adentro de `costo_usado`. `null` cuando
   *  `costo_usado` no cae entre los dos precios y no es fracción de nada. */
  pct_absorbido: number | null
  productos_afectados: string[]
  venta_30d_afectada: number
  /** Pesos de costo que este insumo explica en la ventana medida. `null` = no se
   *  pudo repartir (no se vendió nada que lo use, o el producto que lo usa tiene
   *  costo fijado a mano). */
  costo_en_la_venta: number | null
  ventana: { desde: string; hasta: string } | null
  /**
   * ═══ SON DOS NÚMEROS Y NO SE DEDUCEN UNO DEL OTRO ═══════════════════════
   *
   * `si_se_queda` = cuánto MÁS va a subir el piso si el precio nuevo se queda.
   * `si_vuelve`   = hasta cuánto BAJA el piso si el proveedor vuelve a
   *                 `costo_ref`.
   *
   * La pantalla publicaba solo el primero y escribía debajo «recuperar el viejo
   * es esa misma plata de vuelta». No lo es: medido sobre la leche del ejemplo,
   * el primero daba +$8.053/día y el segundo −$798/día. Prometía 10 veces lo que
   * la decisión devuelve, porque el costo con el que se costea es un promedio de
   * toda la historia y ya tenía la suba absorbida en un 9% (`pct_absorbido`).
   *
   * LOS DOS SON TOPES, NO SON «MAÑANA», y el verbo de la pantalla tiene que
   * decirlo. Los dos salen de mover `costo_usado` —el promedio ponderado de toda
   * la historia de compras— hasta el otro precio, y ese promedio no salta: se
   * arrastra factura a factura. MEDIDO con el proveedor aceptando volver a
   * $2,00: el día del acuerdo el piso baja $0,00; con 1 compra al precio nuevo
   * bajó $658,99 (8,3% del tope), con 20 el 64,5%, con 100 el 90,1%. Cada uno es
   * el LÍMITE al que se llega comprando, no lo que se ve mañana.
   *
   * EL SIGNO SALE DE LA CUENTA. Lo normal es `si_se_queda >= 0` y
   * `si_vuelve <= 0`, pero con un costo fijado a mano cualquiera de los dos
   * puede darse vuelta: la pantalla elige el verbo mirando el signo, no lo
   * asume.
   */
  piso_mes_si_se_queda: number | null
  piso_dia_si_se_queda: number | null
  piso_mes_si_vuelve: number | null
  piso_dia_si_vuelve: number | null
  /** La distancia entera entre los dos mundos: la plata que la negociación pone
   *  sobre la mesa. NO se muestra — es con lo que el backend ORDENA la lista, y
   *  viaja para que ese orden se pueda auditar desde la respuesta. Es el único
   *  de los tres que no se encoge solo a medida que la suba se absorbe. */
  piso_mes_en_juego: number | null
  piso_dia_en_juego: number | null
  margen_si_se_queda: number | null
  margen_si_vuelve: number | null
  /** En castellano y desde el backend. Cuando viene, los tres campos de arriba
   *  son `null` y la pantalla escribe ESTO en vez de un guion mudo. */
  sin_impacto_porque: string | null
}

export interface PalancasData {
  anio: number
  mes: number
  /** El piso CONTRA EL QUE se midió cada palanca. No es un segundo cálculo: son
   *  los mismos números de `GET /costos/piso` de ese mes. */
  piso: {
    puerta: PuertaPiso
    piso_mes: number | null
    piso_hoy: number | null
    margen_contribucion: number | null
    costos_fijos: number
    dias_quedan: number
  }
  palancas: Palanca[]
  n_alertas: number
}

// Los campos nuevos de `GET /costos/flujo` (`saldo_minimo`, `colchon`, el
// horizonte anclado a fin de mes) viven en `plata/tipos.ts`, adentro de `Flujo`:
// son campos del MISMO endpoint que ya usaban los banners, y un segundo tipo
// para la misma respuesta es el lugar donde después se cuela un campo que el
// backend ya no manda.

// ── La nómina abierta (`GET /horarios/nomina-consolidada`) ───────────────────

export interface LiquidacionNomina {
  devengado: number
  auxilio: { total: number }
  aportes_empleador: { total: number }
  prestaciones: { total: number }
  costo_empleador: number
  confirmar_contador: boolean
  es_estimado: boolean
}

export interface PersonaNomina {
  usuario_id: number
  nombre: string
  tiene_contrato: boolean
  tiene_sueldo: boolean
  salario_mensual: number
  liquidacion: LiquidacionNomina
}

export interface NominaConsolidada {
  anio: number
  mes: number
  desde: string
  hasta: string
  advertencias: string[]
  personas: PersonaNomina[]
  totales: {
    total_devengado: number
    total_auxilio: number
    total_costo_empleador: number
    sin_sueldo: number
  }
}


// ─── La forma EXACTA de `GET /costos/impoconsumo` ────────────────────────────
//
// EL ÚNICO GASTO GRANDE QUE NO SE VEÍA COMO GASTO. De cada peso facturado, 7,41
// centavos son de la DIAN. El sistema ya lo trata bien en todos lados —la venta
// neta lo descuenta, el margen de contribución lo resta, el piso lo tiene
// adentro— pero en ninguna pantalla aparecía como PLATA QUE HAY QUE PAGAR EN UNA
// FECHA: se ve como menos venta todos los días y después aparece de golpe cada
// dos meses.
//
// SÍ SE AGENDA, con `POST /costos/impoconsumo/agendar`, pero en una categoría
// DEDICADA que el P&L no mira. Cargarla en 'impuestos' sería doble conteo —ese
// grupo es FIJO y entraría al numerador del piso, cuyo denominador ya le restó el
// impoconsumo— y ponerla en un grupo 'variable' tampoco alcanza, porque el gasto
// del P&L suma todas las obligaciones sin mirar el grupo. La exclusión es por
// CLAVE. Medido: así agendada, el piso y el margen neto se mueven $0 y la
// proyección de caja pasa a ver la salida. El porqué está en `services/costos.py`.

export interface Impoconsumo {
  hoy: string
  bimestre: {
    anio: number
    /** 1..6 — ene-feb, mar-abr, may-jun, jul-ago, sep-oct, nov-dic. */
    numero: number
    /** «julio-agosto 2026», en el idioma del dueño. */
    nombre: string
    desde: string
    hasta: string
  }
  /**
   * El MES en que la DIAN lo pide. El DÍA depende del último dígito del NIT y
   * el sistema no lo conoce: `hasta` es el último día de ese mes, que es lo
   * único que se puede afirmar sin el NIT.
   */
  declara_en: { anio: number; mes: number; nombre: string; hasta: string }
  declarado: boolean
  declarado_hasta: { anio: number; bimestre: number; nombre: string } | null
  /** Pasó el mes ENTERO del plazo: tarde para cualquier NIT. */
  vencido: boolean
  hay_que_declarar: boolean
  /**
   * Lo que el sistema MIDIÓ cobrado de impoconsumo en ese bimestre — NO «lo que
   * hay que pagar»: la declaración la arma el contador. `null` cuando no se
   * puede medir, y entonces `sin_monto_porque` dice por qué EN CASTELLANO. Un
   * monto inventado en una pantalla de plata es peor que un recordatorio sin
   * monto, así que acá no va ningún `?? 0`.
   */
  monto_medido: number | null
  ventas: number | null
  sin_monto_porque: string | null
  tasa: number | null
  confirmar_contador: boolean
  /**
   * La obligación de este bimestre, si ya se agendó. `null` = todavía no está en
   * la agenda ni en el flujo.
   *
   * Se mira SIEMPRE, incluso con el bimestre ya marcado como declarado: marcar
   * «ya la declaré» apaga el recordatorio pero NO paga la obligación, y esa plata
   * sigue en la agenda.
   */
  agendada: {
    obligacion_id: number
    monto: number
    fecha_vencimiento: string | null
    concepto: string
  } | null
}

// ─── La forma EXACTA de `POST /costos/obligaciones/armar-mes` ────────────────
//
// Con `confirmar: false` es la VISTA PREVIA y no escribe nada. Las dos mitades
// calculan la misma lista con el mismo código a propósito: si la previa y el
// commit fueran dos caminos, el dueño aprobaría una lista y se le crearía otra.

export interface CuentaPorArmar {
  serie_id: number
  origen_id: number
  concepto: string
  beneficiario: string | null
  monto: number
  tienda_id: number | null
  tienda_nombre: string | null
  categoria_clave: string
  categoria_nombre: string
  categoria_grupo: string
  fecha_devengo: string
  fecha_vencimiento: string | null
  /** De qué mes salió el monto. Con un mes saltado NO es el mes anterior. */
  copiado_de: string
}

/**
 * Una cuenta VIVA que todavía nadie marcó como repetible, ofrecida para elegir.
 *
 * No se copia sola nunca. Viene con su plata, su sede y su categoría porque la
 * decisión es del dueño: el arriendo se repite, la reparación del molino no, y
 * ninguna regla del sistema puede distinguirlas (las dos son categoría de grupo
 * "fijo" y las dos entran al numerador del piso).
 */
export interface CuentaSuelta {
  obligacion_id: number
  concepto: string
  beneficiario: string | null
  monto: number
  tienda_id: number | null
  tienda_nombre: string | null
  categoria_clave: string
  categoria_nombre: string
  fecha_devengo: string
  fecha_vencimiento: string | null
  /**
   * LO QUE EL MES DESTINO YA TIENE Y SE LE PARECE, para avisar EN EL RENGLÓN.
   *
   * La cobertura del server matchea por concepto normalizado + sede, y eso es
   * una igualdad: «Arriendo Vida» y «Arriendo local Vida» no matchean, así que
   * la cuenta se ofrece igual y tildarla duplicaría el arriendo. Acá viene lo
   * que quedó sin emparejar con la misma sede y categoría, para que el aviso
   * esté ANTES del tilde y no después.
   *
   * OPCIONAL, y no porque el backend lo omita: es una PWA con service worker,
   * así que existe la ventana del deploy en la que la tablet tiene el bundle
   * NUEVO contra el backend VIEJO. Mismo criterio que `editable_a_mano`.
   */
  parecidas?: LaDelMesDestino[]
}

/** Una fila del MES DESTINO: la que tapa a una del origen, o la que se le parece. */
export interface LaDelMesDestino {
  obligacion_id: number
  concepto: string
  monto: number
  fecha_devengo: string
  categoria_nombre: string
  tienda_nombre: string | null
}

/**
 * Una cuenta que NO va al mes porque el mes YA LA TIENE, con las dos filas.
 *
 * Que el server decida no copiar algo, callado, se lee como «no había nada».
 * Van las dos —la del origen y la del destino, con plata y fecha— para que el
 * dueño pueda decir «esa no es la misma» si la llave se equivocó.
 */
export interface YaEnElMes {
  obligacion_id: number
  concepto: string
  monto: number
  tienda_nombre: string | null
  categoria_nombre: string
  fecha_devengo: string
  /** `true` = era una SERIE y se habría copiado sola, sin ningún tap de por medio. */
  automatica: boolean
  ya: LaDelMesDestino
}

export interface ArmadoDelMes {
  anio: number
  mes: number
  nombre_mes: string
  confirmado: boolean
  van_a_crearse: CuentaPorArmar[]
  /** La plata que le va a agregar al mes. */
  total: number
  ya_estaban: { serie_id: number; obligacion_id: number; concepto: string; monto: number; fecha_devengo: string }[]
  /** Las que no se pueden copiar, CON el porqué. No abortan el lote. */
  no_se_pueden: { serie_id: number; origen_id: number; concepto: string; porque: string }[]
  /**
   * CUÁNTAS SERIES REPETIBLES HAY, que es lo que separa los dos ceros.
   *
   * `van_a_crearse: []` tiene dos causas opuestas y hasta acá eran la misma:
   * «las series ya tienen su copia» (el mes está armado) y «no hay NINGUNA serie
   * marcada como repetible» (el mes arranca sin un peso de costos fijos). En
   * este negocio pasaba siempre la segunda y la pantalla afirmaba la primera.
   */
  series_repetibles: number
  /** Las cuentas sin serie que se ofrecen para elegir. Nunca se copian solas. */
  candidatas: CuentaSuelta[]
  /** De qué mes son las candidatas. Con un mes saltado NO es el mes anterior. */
  candidatas_de: string | null
  /**
   * LO QUE EL MES DESTINO YA TIENE. Los dos números sobre los que esta pantalla
   * venía afirmando sin haberlos pedido: decía «el mes que viene arrancaría sin
   * costos fijos y el piso en cero» con el mes destino ya cargado a mano.
   *
   * `n: 0` es «lo miré y está vacío», que NO es lo mismo que no haber mirado —
   * y es lo único que autoriza el aviso fuerte.
   *
   * OPCIONAL por la ventana del deploy (bundle nuevo, backend viejo), igual que
   * `parecidas`. Con `undefined` no se puede afirmar nada sobre el mes destino.
   */
  mes_destino?: {
    /** TODAS las cuentas vivas del mes: lo que la cobertura del server mira. */
    n: number
    total: number
    /**
     * SOLO LAS QUE ENTRAN AL NUMERADOR DEL PISO, y es el número que la pantalla
     * tiene que mostrar cuando habla del piso. Publicar `total` en su lugar
     * daba un número CERCA del correcto y del lado tranquilizador: una
     * declaración del impoconsumo sola hacía leer como cubierto un mes sin un
     * peso de costos fijos.
     *
     * NO incluye la nómina CALCULADA (el server solo mira obligaciones acá), y
     * esa diferencia va para el lado seguro: el mes se ve menos cubierto de lo
     * que está, así que el aviso suena de más y nunca de menos.
     */
    n_fijos: number
    fijos: number
  }
  /** Las que NO van al mes porque el mes ya las tiene. Nunca en silencio. */
  ya_en_el_mes?: YaEnElMes[]
  /** Cuántas de las elegidas quedan marcadas como serie con este lote. */
  n_elegidas: number
  n_creadas: number
}
