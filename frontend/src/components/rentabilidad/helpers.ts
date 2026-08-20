// Shared types and derived-data helpers for the Rentabilidad cockpit views.

import { Dato, datoListo, datoSinBase } from '../../api/dato'

export interface Bucket {
  /** Lo COBRADO: Σ Ticket.total. Es lo que entró al cajón y lo que cuadra contra
   *  caja — pero NO es todo plata del negocio (ver `impoconsumo`). */
  ventas: number
  // ── EL IMPOCONSUMO NO ES PLATA DEL NEGOCIO ─────────────────────────────────
  // El precio de la carta lo lleva ADENTRO: de una aromática de $5.900, $437 son
  // de la DIAN. El backend (services/parametros_tributarios.separar) parte lo
  // cobrado en estas dos mitades y TODOS los márgenes se calculan contra
  // `venta_neta`, no contra `ventas`.
  //
  // INVARIANTE que la pantalla puede usar: venta_neta + impoconsumo == ventas.
  // De ahí sale la escalera de PnLView: sin el escalón del impuesto en el medio,
  // Ventas − Compras − Costos NO da el margen neto y la resta se ve rota.
  //
  // Los dos llegan SIEMPRE (backend: `_cerrar` y el `resumen`), pero con tarifa
  // en 0 —o con un parámetro que dice que el precio no lleva el impuesto
  // adentro— `impoconsumo` vale 0 y `venta_neta` == `ventas`. Por eso lo que se
  // muestra se condiciona por el MONTO y nunca por la presencia del campo.
  venta_neta: number
  impoconsumo: number
  compras: number; gastos: number
  /** venta_neta − compras − gastos (NO ventas − …: ver arriba). */
  margen_neto: number
  /** margen_neto / venta_neta × 100. La base es la venta NETA: toda leyenda que
   *  lo muestre tiene que decirlo, y la pantalla tiene que mostrar esa base. */
  pct_margen_neto: number | null
}
export interface RentabilidadData {
  desde: string; hasta: string
  resumen: Bucket & {
    /** Tarifa del impoconsumo vigente al ARRANQUE del rango, como FRACCIÓN:
     *  0,08 = 8%. No es el % de lo cobrado — con el impuesto adentro del precio
     *  el impuesto es el 7,41% del precio final, no el 8%. Para mostrarla se
     *  usa `fmtTasa`, nunca `tasa * 100` a pelo. */
    tasa_impoconsumo: number
    /** true = la tarifa está cargada pero todavía sin confirmar con el contador,
     *  igual que las tasas laborales. Se muestra SOLO cuando de verdad está
     *  separando plata (`impoconsumo > 0`): con la tarifa en 0 esta bandera
     *  viene prendida por defecto y avisar de "la tarifa sin confirmar" hablaría
     *  de una tarifa que no existe — la misma trampa de siempre, prender un
     *  cartel por la FORMA del dato en vez de por el MONTO. */
    impoconsumo_confirmar_contador: boolean
    /** venta_neta − compras. Sobre la venta NETA, no sobre lo cobrado. */
    margen_bruto: number
    /** margen_bruto / venta_neta × 100. */
    pct_margen_bruto: number | null
    n_tickets: number; n_facturas: number
    cogs_teorico?: number
    // ── OJO: ESTE PAR NO USA LA MISMA BASE QUE EL MARGEN NETO ─────────────────
    // `margen_bruto_real` es `ventas − cogs_teorico` y su % es sobre `ventas`,
    // o sea sobre lo COBRADO, con el impoconsumo adentro (backend:
    // services/rentabilidad.py, `margen_bruto_real` / `pct_margen_bruto_real`).
    // El margen neto y `margen_bruto` en cambio salen de `venta_neta`. Las dos
    // cifras conviven en la misma pantalla, así que cada leyenda tiene que decir
    // su base o el dueño compara dos números que no miden lo mismo.
    margen_bruto_real?: number
    pct_margen_bruto_real?: number | null
    brecha_compras?: number
    pct_venta_costeada?: number | null
    // ── EL COSTO COMPLETO DE SERVIR, EMPAQUE INCLUIDO ────────────────────────
    // `cogs_teorico` es SOLO la receta. El vaso, la tapa y la servilleta viven
    // en `cogs_desechables` y se suman en `cogs_con_desechables`.
    //
    // POR QUÉ VIAJAN LOS DOS MÁRGENES Y NO UNO SOLO: `margen_bruto_real`
    // (ventas − receta) es el término al que se le resta la fuga medida por
    // conteo, y esa fuga YA se lleva los vasos consumidos —el desechable no
    // descuenta inventario al vender—, así que meterle el empaque adentro
    // contaría el mismo vaso dos veces en `margen_bruto_real_con_fuga`. Pero
    // ese argumento cubre ese número y NINGÚN otro: `margen_bruto_real` se
    // dibuja también en el mes en curso, donde no hay ningún cierre y no existe
    // término de fuga, y ahí el empaque no está en ninguna parte.
    // `margen_bruto_real_con_desechables` es el que la pantalla muestra como
    // «margen sobre lo vendido»: nunca le falta el vaso, haya conteo o no.
    cogs_desechables?: number
    cogs_con_desechables?: number
    /** Qué parte de la venta viene de productos con TODOS sus desechables
     *  costeados. En 0 = el margen de arriba no lleva un solo empaque adentro. */
    pct_venta_con_desechables?: number | null
    margen_bruto_real_con_desechables?: number
    pct_margen_bruto_real_con_desechables?: number | null
    // ── LA CONDICIÓN DEL DOBLE CONTEO, MEDIDA ────────────────────────────────
    // «El vaso ya está adentro de la fuga» es cierto SOLO si el barista contó
    // ese renglón en el cierre. `cerrar()` rellena `cantidad_real` con el
    // sistema para todo lo no contado, así que un empaque que nadie miró da
    // residuo 0 y desaparece del término de fuga sin que nada lo diga.
    // `desechables_en_la_fuga` / `desechables_producto_mes` son PRODUCTO-MES
    // (renglones de empaque × cierres), misma convención que
    // `fuga_cobertura_contados`. Cuando el numerador es menor, la banda de fuga
    // NO puede seguir diciendo que su residuo cubre el empaque.
    //
    // `desechables_con_costo` VA SIN `?`, y es el mismo candado que se le puso a
    // `alertas_costo` en esta misma tanda. `get_rentabilidad` lo escribe como
    // `len(desech_insumos_vendidos)` adentro del ÚNICO literal de `resumen`
    // (backend/app/services/rentabilidad.py), sin condición, así que no existe
    // la respuesta que no lo trae. Mientras fue opcional, el consumidor tenía que
    // escribir `?? 0` para compilar, y ese cero se IMPRIMÍA: «Los 0 renglones de
    // empaque con costo pasaron por el conteo», debajo del renglón que afirma que
    // el vaso ya está adentro del residuo. Un conteo fabricado sosteniendo una
    // afirmación tranquilizadora es la regla 1 de components/ui/README.md, y con
    // el campo obligatorio el `?? 0` deja de compilar en vez de depender de que
    // nadie lo vuelva a escribir.
    desechables_con_costo: number
    // Estos dos SÍ quedan opcionales a propósito: la pantalla los trata con
    // `!= null` y su ausencia apaga el aviso en vez de fabricar un cero, o sea
    // cae del lado que NO tranquiliza. No hay `?? 0` que puedan alimentar.
    desechables_en_la_fuga?: number
    desechables_producto_mes?: number
    // Cobertura de costos FIJOS del período (arriendo, nómina, servicios,
    // impuestos). Ya están DENTRO de `gastos` y `margen_neto`: se exponen aparte
    // para distinguir "el negocio no tiene costos fijos" de "nadie los cargó".
    // Sin esta distinción un semáforo verde afirmaría algo que nadie verificó.
    costos_fijos_devengados?: number
    n_costos_fijos?: number
    tiene_costos_fijos?: boolean
    // Costo laboral CALCULADO por services/nomina (horas marcadas × recargos de
    // ley), no digitado a mano. ADITIVO: ya está DENTRO de `gastos` y de
    // `margen_neto`; viaja aparte para poder decir de qué meses el número lo
    // sacó el sistema y de cuáles lo puso una persona.
    //
    // Un mes NO puede estar en las dos listas: el que tiene una obligación de
    // nómina cargada a mano usa esa y descarta el cálculo, o el sueldo se
    // contaría dos veces.
    nomina_calculada?: number
    nomina_meses_calculados?: string[]
    nomina_meses_manuales?: string[]
    /** Plata de esa nómina manual que cae DENTRO del período consultado. En 0
     *  con `nomina_meses_manuales` no vacío = el devengo quedó afuera. */
    nomina_manual_en_ventana?: number
    /** Lo mismo abierto POR MES. Hace falta porque una ventana multi-mes puede
     *  tener un mes cubierto y otro sin un peso adentro, y el total los tapa. */
    nomina_manual_por_mes?: Record<string, number>
    nomina_personas?: number
    nomina_horas?: number
    // Gente con horas en el período y SIN salario cargado en Contratos: sus
    // horas entran al margen valiendo $0. Es una instrucción de trabajo.
    nomina_sin_contrato?: number
    nomina_es_estimado?: boolean
    // Plata REGALADA en mostrador (Ticket.descuento). ADITIVA: `ventas` ya viene
    // neto, así que esto cuenta lo que se resignó, nunca lo vuelve a restar. Sin
    // el número, un descuento y una venta que no ocurrió se ven igual.
    descuentos?: number
    n_tickets_con_descuento?: number
    pct_descuento?: number | null   // medido sobre la venta BRUTA (venta + descuento)
    // Fuga de inventario MEDIDA por los cierres de mes del período: lo que el
    // conteo físico encontró de menos y que NINGUNA causa registrada explica,
    // valorizado.
    //
    // NO se resta de `margen_neto`: ese margen sale de `compras`, que es base de
    // RECEPCIÓN (la mercadería se gasta entera al recibirla), así que lo que se
    // compró y se fugó YA está descontado ahí adentro y volver a restarlo contaría
    // la misma plata dos veces. El término va contra `margen_bruto_real`
    // (ventas − cogs_teorico), que es base de CONSUMO y solo tiene el costo de lo
    // efectivamente VENDIDO.
    // `null` ≠ 0: cero significa "se contó y no falta nada"; null significa
    // "nadie cerró un conteo completo dentro de este rango, así que no se midió".
    fuga_inventario?: number | null
    tiene_fuga_medida?: boolean
    // Mismo eje que `margen_bruto_real`: parten de `ventas` (lo cobrado) y su %
    // también, así que este bloque entero se lee sobre lo COBRADO y no sobre la
    // venta neta. Se dice en la tarjeta.
    margen_bruto_real_con_fuga?: number | null
    pct_margen_bruto_real_con_fuga?: number | null
    periodos_con_fuga_medida?: { tienda_id: number; anio: number; mes: number
      valor_inexplicado: number; con_residuo: number; contados: number; productos: number }[]
    // De cuánto del inventario habla la fuga, cuánta de ella no se pudo poner en
    // pesos y cuánta se valorizó con el precio de VENTA: un total chico puede ser
    // un conteo chico, y uno grande puede ser precio de venta disfrazado de costo.
    //
    // La cobertura es PRODUCTO-MES, no productos: son las coberturas de cada
    // cierre sumadas a lo largo del rango, así que 3 cierres de 97 productos dan
    // 291 y ese local no tiene 291 productos. El ratio es correcto; el absoluto
    // solo se lee dividido por `fuga_cierres`, y por eso la pantalla dice
    // "producto-mes" y muestra la cantidad de cierres.
    fuga_cobertura_contados?: number
    fuga_cobertura_productos?: number
    fuga_cierres?: number
    // Estos DOS sí son productos DISTINTOS: son una instrucción de trabajo
    // ("cargá el costo de estos"), no una medida del período.
    fuga_sin_costo?: number
    fuga_estimados?: number
    // Los dos términos de `margen_bruto_real_con_fuga` NO miden el mismo tramo:
    // el margen es de TODO el rango y la fuga solo de los meses calendario
    // COMPLETOS ya cerrados que caen adentro. El sesgo es optimista (subdeclara
    // la fuga) y este par es lo que deja decirlo en pantalla.
    fuga_meses?: number
    fuga_meses_rango?: number
    // Y el tramo tiene DOS ejes. `fuga_sedes` son las sedes que cerraron al menos
    // un conteo adentro del rango; `fuga_sedes_rango`, las que vendieron. Con
    // "Todas las sedes" el margen suma las ventas y el COGS de todas y la fuga
    // solo de las que contaron: la sede que nunca cierra se cae de la resta sin
    // ninguna señal, con el mismo sesgo optimista que el eje de los meses.
    fuga_sedes?: number
    fuga_sedes_rango?: number
  }
  por_mes: ({ mes: string } & Bucket)[]
  // tienda_id null = gasto CORPORATIVO (arriendo, nómina): fila propia "Corporativo",
  // no se reparte entre sedes (si se repartiera, Σ por_sede dejaría de dar el global).
  por_sede: ({ tienda_id: number | null; tienda: string } & Bucket)[]
  gastos_detalle: { concepto: string; total: number; n: number }[]
  // PARTICIÓN de resumen.gastos por categoría de costo (Σ total == resumen.gastos).
  // `clave` es el slug estable del catálogo; 'sin_categorizar' es la bolsa de los
  // egresos de caja que todavía nadie adoptó, y su `grupo` es null a propósito.
  gastos_por_categoria?: { clave: string; nombre: string; grupo: string | null; total: number; n: number }[]
  nota: string
}

export interface ProdMargen {
  producto_id: number; nombre: string; categoria: string; tipo: string
  /** El precio de la CARTA, con el impoconsumo adentro. NO es la base del margen. */
  precio_venta: number
  // ── LA BASE DEL MARGEN POR PRODUCTO ES EL PRECIO NETO ──────────────────────
  // Misma corrección que en el P&L: `margen`, `pct_margen`,
  // `margen_con_desechables` y `pct_margen_con_desechables` ya vienen calculados
  // contra `precio_neto` (backend: get_rentabilidad_productos). Cualquier frase
  // que diga "margen sobre el precio de venta" quedó falsa, y cualquier cuenta
  // que la pantalla rehaga con `precio_venta` (el simulador lo hacía) muestra un
  // margen más alto que el de la tabla de al lado.
  //
  // `impoconsumo_unitario` en 0 significa que este precio no lleva impuesto
  // adentro y ahí `precio_neto == precio_venta`: por eso lo que se muestra se
  // condiciona por ese MONTO, producto por producto.
  precio_neto: number
  impoconsumo_unitario: number
  costo: number | null; costo_completo: boolean
  insumos_sin_costo: string[]; margen: number | null; pct_margen: number | null
  costo_desechables: number | null; costo_con_desechables: number | null
  desechables_sin_costo: string[]; margen_con_desechables: number | null
  pct_margen_con_desechables: number | null
  unidades_30d: number
  /** Plata VENDIDA en 30d (Σ TicketItem.subtotal): lo cobrado, con impuesto. */
  venta_30d: number
}
export interface AlertaCosto {
  insumo_id: number; nombre: string; unidad_medida: string | null
  /**
   * Quién la subió, tal como está escrito en la factura que fijó el precio
   * nuevo (no el proveedor más grande ni el último que facturó cualquier cosa).
   * `null` —y SOLO `null`— cuando esa factura vino sin proveedor cargado.
   *
   * Sin `?`: `rentabilidad.alertas_de_costo` escribe la clave en cada alerta que
   * arma, sin condición. Dejarlo opcional metía un `undefined` que había que
   * distinguir de `null` y que en la práctica se leía igual, así que la pantalla
   * terminaba diciendo lo mismo para «la factura no tenía proveedor» que para
   * «no me llegó el campo». Son cosas distintas y una de las dos no existe.
   */
  proveedor: string | null
  fecha_ultimo: string | null
  /**
   * LOS TRES COSTOS VIENEN SIN REDONDEAR, y hay que imprimirlos con `fmtUnit`,
   * nunca con `fmt`. Un insumo de $0,004545/gr redondeado a peso entero imprime
   * "$0 → $0" al lado de un "+150%", y son la misma cifra contándose de dos
   * formas: la que se ve no explica la que se afirma.
   *
   * `costo_usado` es el promedio ponderado con el que HOY se costea (o el costo
   * oficial fijado a mano); `costo_ref` es el más barato que ese insumo tuvo en
   * los últimos `ref_meses` meses y es contra ESE que se mide `pct_suba`.
   */
  costo_usado: number; costo_ultimo: number; costo_ref: number
  /** De qué factura salió la referencia: el «+40%» queda verificable en el papel. */
  ref_proveedor: string | null
  ref_fecha: string | null
  ref_meses: number
  /**
   * `true` = el que cobraba la referencia y el que cobra ahora son el mismo.
   * DECIDE DE QUIÉN PUEDE SER SUJETO LA FRASE: con `false`, escribir «Andina
   * subió la leche +40%» le atribuye a Andina un precio que Andina nunca cobró.
   */
  mismo_proveedor: boolean
  /** Lo que movió el proveedor: último contra referencia, NO contra el promedio. */
  pct_suba: number
  /**
   * Qué parte de esa suba ya está adentro de `costo_usado` — o sea, qué parte
   * ya llegó al piso. `null` cuando `costo_usado` no cae entre la referencia y
   * el último (pasa con un costo fijado a mano) y por lo tanto no es fracción
   * de nada.
   */
  pct_absorbido: number | null
  productos_afectados: string[]; venta_30d_afectada: number
}
export interface PorProductoData {
  productos: ProdMargen[]
  /**
   * SIN `?` A PROPÓSITO — es el candado que evita el `?? []` de río abajo.
   *
   * `get_rentabilidad_productos` (backend/app/services/rentabilidad.py) mete
   * `alertas_costo` en el dict que devuelve SIEMPRE: la clave está en el
   * `return`, no adentro de un `if`, y la función que la llena devuelve lista
   * (vacía cuando no subió nada). O sea que acá `[]` significa una sola cosa:
   * se comparó y ningún insumo se está facturando más de un 10% arriba de lo más
   * barato que se le pagó en los últimos 12 meses.
   *
   * Mientras el campo fue opcional, el consumidor tenía que escribir
   * `alertas_costo ?? []` y esa expresión aplastaba «no se pudo preguntar»
   * contra «no subió nada» — regla 2 de components/ui/README.md. Que el tipo lo
   * exija hace que el compilador cierre esa puerta en vez de la disciplina de
   * quien edite dentro de seis meses.
   */
  alertas_costo: AlertaCosto[]
  facturas_pendientes_de_costos: number
  // Fase 2 del OCR: aliases proveedor→producto que el sistema aprendió.
  aliases_conocidos?: number
  nota: string
}

export interface PulsoData {
  mes_actual: { ventas: number; tickets: number; ticket_promedio: number | null; desde: string; hasta: string }
  mes_anterior: { ventas: number; tickets: number; ticket_promedio: number | null; desde: string; hasta: string }
  ventas_diarias: { dia: string; ventas: number }[]
  attach: { tickets_con_bebida: number; pct_bebida_con_pasteleria: number | null; pct_bebida_con_addon: number | null }
  top_pares: { a: string; a_id: number; a_cat: string; b: string; b_id: number; b_cat: string; veces: number }[]
  daypart: { hora: number; tickets: number; ventas: number }[]
  top_movers: {
    subiendo: { producto_id: number; nombre: string; unidades: number; unidades_prev: number; venta: number; venta_prev: number; delta_venta: number }[]
    bajando: { producto_id: number; nombre: string; unidades: number; unidades_prev: number; venta: number; venta_prev: number; delta_venta: number }[]
  }
  nota: string
}

export const fmt = (v: number) => '$' + Math.round(v || 0).toLocaleString('es-CO')
/**
 * PRECIO POR UNIDAD DE INSUMO — $/ml, $/gr, $/unidad.
 *
 * Existe porque `fmt` redondea a peso entero, y estos números viven abajo del
 * peso: la leche a $2,0727/ml y a $2,80/ml se imprimían las dos como "$2 → $3"
 * (una suba del 50% dibujada al lado de un "+40%" que decía otra cosa), y la
 * canela a $0,004545/gr imprimía "$0 → $0". Los decimales se estiran según la
 * magnitud para que dos precios distintos NUNCA se impriman iguales.
 */
export const fmtUnit = (v: number) => {
  const a = Math.abs(v || 0)
  const dec = a === 0 ? 0 : a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : a >= 0.01 ? 3 : 5
  return '$' + (v || 0).toLocaleString('es-CO',
    { minimumFractionDigits: dec, maximumFractionDigits: dec })
}
export const fmtK = (v: number) => {
  const a = Math.abs(v)
  if (a >= 1_000_000) return '$' + (v / 1_000_000).toFixed(1).replace('.', ',') + 'M'
  if (a >= 1_000) return '$' + Math.round(v / 1_000) + 'k'
  return fmt(v)
}
export const pctDelta = (actual: number, anterior: number): number | null =>
  anterior > 0 ? Math.round(((actual - anterior) / anterior) * 100) : null

/** Tasa que viaja como FRACCIÓN (0,08) → texto de porcentaje ("8%").
 *  Se redondea ANTES de formatear porque en coma flotante 0.08 * 100 da
 *  8.000000000000002, y ese ruido terminaría impreso en un cartel de impuestos.
 *  Existe para que ninguna vista escriba `tasa * 100` a mano. */
export const fmtTasa = (frac: number) =>
  (Math.round((frac || 0) * 10000) / 100).toLocaleString('es-CO', { maximumFractionDigits: 2 }) + '%'

// Utility contributed per month = unit margin × units sold (the real money maker).
export const prodUtil = (p: ProdMargen) => (p.margen ?? 0) * p.unidades_30d
export const costoFull = (p: ProdMargen) => p.costo_con_desechables ?? p.costo

// ── Kasavana-Smith quadrants ─────────────────────────────────────────────────
export type Quad = 'estrella' | 'caballo' | 'puzzle' | 'perro'
export interface MatrixInfo {
  prods: ProdMargen[]
  uThresh: number
  mThresh: number
  quadOf: (p: ProdMargen) => Quad
}
export function buildMatrix(all: ProdMargen[]): MatrixInfo {
  const prods = all.filter(p => p.unidades_30d > 0 && p.pct_margen != null && p.costo_completo)
  const uThresh = (prods.reduce((s, p) => s + p.unidades_30d, 0) / (prods.length || 1)) * 0.7
  const mThresh = prods.reduce((s, p) => s + (p.pct_margen || 0), 0) / (prods.length || 1)
  const quadOf = (p: ProdMargen): Quad => {
    const pop = p.unidades_30d >= uThresh, rent = (p.pct_margen || 0) >= mThresh
    return pop ? (rent ? 'estrella' : 'caballo') : (rent ? 'puzzle' : 'perro')
  }
  return { prods, uThresh, mThresh, quadOf }
}

// ── Data-health (detector de datos truchos) ──────────────────────────────────
//
// Estas dos devuelven `Dato<...>` y no un array pelado, y la razón es el bug que
// llegó a producción: un array vacío significaba a la vez «miré y está todo
// bien» y «no llegué a mirar nada», así que el banner pintaba el verde «todos
// coherentes con su categoría» sobre una medición que nunca corrió.
//
// En `computeOutliers` el caso es peor que «no llegaron productos». El algoritmo
// necesita CUATRO productos costeados en una misma categoría para comparar, y
// una desviación de al menos 4 puntos para que un z-score signifique algo. Con
// cien productos en pantalla repartidos en categorías de a dos, no se compara
// nada — y el resultado era `[]`, indistinguible del verde. Por eso la guarda no
// cuenta productos: cuenta CATEGORÍAS EFECTIVAMENTE COMPARADAS.
export interface Outlier { p: ProdMargen; mean: number; alto: boolean }
export function computeOutliers(all: ProdMargen[]): Dato<Outlier[]> {
  const sold = all.filter(p => p.unidades_30d > 0 && p.pct_margen != null && p.costo_completo)
  if (all.length === 0) return datoSinBase('No llegó ningún producto: no se comparó nada.')
  if (sold.length === 0) {
    return datoSinBase('Ningún producto tiene venta y costo completo: no hay con qué comparar.')
  }
  const byCat = new Map<string, ProdMargen[]>()
  for (const p of sold) {
    const k = p.categoria || 'otros'
    const arr = byCat.get(k)
    if (arr) arr.push(p); else byCat.set(k, [p])
  }
  const flags: Outlier[] = []
  let categoriasComparadas = 0
  byCat.forEach(arr => {
    if (arr.length < 4) return
    const ms = arr.map(p => p.pct_margen as number)
    const mean = ms.reduce((a, b) => a + b, 0) / ms.length
    const sd = Math.sqrt(ms.reduce((a, b) => a + (b - mean) ** 2, 0) / ms.length)
    if (sd < 4) return
    categoriasComparadas += 1
    for (const p of arr) {
      const z = ((p.pct_margen as number) - mean) / sd
      if (Math.abs(z) >= 2) flags.push({ p, mean: Math.round(mean), alto: z > 0 })
    }
  })
  if (categoriasComparadas === 0) {
    return datoSinBase(
      'Ninguna categoría junta 4 productos costeados con márgenes distintos: no se comparó nada.')
  }
  return datoListo(
    flags.sort((a, b) => Math.abs(b.p.pct_margen! - b.mean) - Math.abs(a.p.pct_margen! - a.mean)).slice(0, 8))
}

export interface InsumoSinCosto { nombre: string; n: number; venta: number }
export function computeInsumosSinCosto(all: ProdMargen[]): Dato<InsumoSinCosto[]> {
  // Acá alcanza con el largo: la función no tiene umbrales adentro, así que con
  // al menos un producto mirado el `[]` sí quiere decir «no falta ninguno».
  if (all.length === 0) return datoSinBase('No llegó ningún producto: no se revisó el costeo.')
  const m = new Map<string, { n: number; venta: number }>()
  for (const p of all) {
    for (const nm of (p.insumos_sin_costo ?? [])) {
      if (nm.startsWith('defin')) continue
      const e = m.get(nm) ?? { n: 0, venta: 0 }
      e.n += 1; e.venta += p.venta_30d || 0; m.set(nm, e)
    }
  }
  return datoListo([...m.entries()].map(([nombre, v]) => ({ nombre, ...v }))
    .sort((a, b) => b.venta - a.venta).slice(0, 12))
}

// ── Jugadas: single ranked list of actions (costo → combos → add-ons → daypart → precio) ──

// Core coffee drinks are NEVER price suggestions (clients already complain about them).
const CAFE_CORE = ['americano', 'cappuccino', 'capuchino', 'latte', 'tinto', 'espresso', 'cafe ', 'café ']
const esCafeCore = (nombre: string) => {
  const n = ' ' + nombre.toLowerCase()
  return CAFE_CORE.some(k => n.includes(' ' + k) || n.includes(k))
}

