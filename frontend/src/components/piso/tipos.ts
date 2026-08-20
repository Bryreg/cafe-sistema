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
  cogs: number
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
