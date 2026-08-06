// Shared types and derived-data helpers for the Rentabilidad cockpit views.

export interface Bucket {
  ventas: number; compras: number; gastos: number
  margen_neto: number; pct_margen_neto: number | null
}
export interface RentabilidadData {
  desde: string; hasta: string
  resumen: Bucket & {
    margen_bruto: number
    pct_margen_bruto: number | null
    n_tickets: number; n_facturas: number
    cogs_teorico?: number
    margen_bruto_real?: number
    pct_margen_bruto_real?: number | null
    brecha_compras?: number
    pct_venta_costeada?: number | null
    // Cobertura de costos FIJOS del período (arriendo, nómina, servicios,
    // impuestos). Ya están DENTRO de `gastos` y `margen_neto`: se exponen aparte
    // para distinguir "el negocio no tiene costos fijos" de "nadie los cargó".
    // Sin esta distinción un semáforo verde afirmaría algo que nadie verificó.
    costos_fijos_devengados?: number
    n_costos_fijos?: number
    tiene_costos_fijos?: boolean
  }
  por_mes: ({ mes: string } & Bucket)[]
  // tienda_id null = gasto CORPORATIVO (arriendo, nómina): fila propia "Corporativo",
  // no se reparte entre sedes (si se repartiera, Σ por_sede dejaría de dar el global).
  por_sede: ({ tienda_id: number | null; tienda: string } & Bucket)[]
  gastos_detalle: { concepto: string; total: number; n: number }[]
  nota: string
}

export interface ProdMargen {
  producto_id: number; nombre: string; categoria: string; tipo: string
  precio_venta: number; costo: number | null; costo_completo: boolean
  insumos_sin_costo: string[]; margen: number | null; pct_margen: number | null
  costo_desechables: number | null; costo_con_desechables: number | null
  desechables_sin_costo: string[]; margen_con_desechables: number | null
  pct_margen_con_desechables: number | null
  unidades_30d: number; venta_30d: number
}
export interface AlertaCosto {
  insumo_id: number; nombre: string; unidad_medida: string | null
  costo_usado: number; costo_ultimo: number; pct_suba: number
  productos_afectados: string[]; venta_30d_afectada: number
}
export interface PorProductoData {
  productos: ProdMargen[]
  alertas_costo?: AlertaCosto[]
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
export const fmtK = (v: number) => {
  const a = Math.abs(v)
  if (a >= 1_000_000) return '$' + (v / 1_000_000).toFixed(1).replace('.', ',') + 'M'
  if (a >= 1_000) return '$' + Math.round(v / 1_000) + 'k'
  return fmt(v)
}
export const pctDelta = (actual: number, anterior: number): number | null =>
  anterior > 0 ? Math.round(((actual - anterior) / anterior) * 100) : null

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
export interface Outlier { p: ProdMargen; mean: number; alto: boolean }
export function computeOutliers(all: ProdMargen[]): Outlier[] {
  const sold = all.filter(p => p.unidades_30d > 0 && p.pct_margen != null && p.costo_completo)
  const byCat = new Map<string, ProdMargen[]>()
  for (const p of sold) {
    const k = p.categoria || 'otros'
    const arr = byCat.get(k)
    if (arr) arr.push(p); else byCat.set(k, [p])
  }
  const flags: Outlier[] = []
  byCat.forEach(arr => {
    if (arr.length < 4) return
    const ms = arr.map(p => p.pct_margen as number)
    const mean = ms.reduce((a, b) => a + b, 0) / ms.length
    const sd = Math.sqrt(ms.reduce((a, b) => a + (b - mean) ** 2, 0) / ms.length)
    if (sd < 4) return
    for (const p of arr) {
      const z = ((p.pct_margen as number) - mean) / sd
      if (Math.abs(z) >= 2) flags.push({ p, mean: Math.round(mean), alto: z > 0 })
    }
  })
  return flags.sort((a, b) => Math.abs(b.p.pct_margen! - b.mean) - Math.abs(a.p.pct_margen! - a.mean)).slice(0, 8)
}

export interface InsumoSinCosto { nombre: string; n: number; venta: number }
export function computeInsumosSinCosto(all: ProdMargen[]): InsumoSinCosto[] {
  const m = new Map<string, { n: number; venta: number }>()
  for (const p of all) {
    for (const nm of (p.insumos_sin_costo ?? [])) {
      if (nm.startsWith('defin')) continue
      const e = m.get(nm) ?? { n: 0, venta: 0 }
      e.n += 1; e.venta += p.venta_30d || 0; m.set(nm, e)
    }
  }
  return [...m.entries()].map(([nombre, v]) => ({ nombre, ...v }))
    .sort((a, b) => b.venta - a.venta).slice(0, 12)
}

// ── Jugadas: single ranked list of actions (costo → combos → add-ons → daypart → precio) ──

// Core coffee drinks are NEVER price suggestions (clients already complain about them).
const CAFE_CORE = ['americano', 'cappuccino', 'capuchino', 'latte', 'tinto', 'espresso', 'cafe ', 'café ']
const esCafeCore = (nombre: string) => {
  const n = ' ' + nombre.toLowerCase()
  return CAFE_CORE.some(k => n.includes(' ' + k) || n.includes(k))
}

