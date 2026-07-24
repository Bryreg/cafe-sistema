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
  }
  por_mes: ({ mes: string } & Bucket)[]
  por_sede: ({ tienda_id: number; tienda: string } & Bucket)[]
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
export interface Jugada {
  id: string
  tipo: 'costo' | 'combo' | 'addon' | 'daypart' | 'precio'
  titulo: string
  detalle: string
  impacto: string          // human label, e.g. "+$121k/mes" or "afecta $393k/mes"
  simularProductoId?: number
  riesgo?: string
}

// Core coffee drinks are NEVER price suggestions (clients already complain about them).
const CAFE_CORE = ['americano', 'cappuccino', 'capuchino', 'latte', 'tinto', 'espresso', 'cafe ', 'café ']
const esCafeCore = (nombre: string) => {
  const n = ' ' + nombre.toLowerCase()
  return CAFE_CORE.some(k => n.includes(' ' + k) || n.includes(k))
}

export function computeJugadas(prodData: PorProductoData | null, pulso: PulsoData | null): Jugada[] {
  if (!prodData) return []
  const all = prodData.productos
  const sold = all.filter(p => p.unidades_30d > 0 && p.margen != null)
  const jugadas: Jugada[] = []
  const byName = new Map(all.map(p => [p.nombre, p]))

  // 1. COSTO — insumos subiendo de precio (señal temprana; palanca #1 de la estrategia).
  for (const a of (prodData.alertas_costo ?? []).slice(0, 3)) {
    const prodSim = a.productos_afectados.map(n => byName.get(n)).find(p => p && p.unidades_30d > 0)
    jugadas.push({
      id: `costo-${a.insumo_id}`, tipo: 'costo',
      titulo: `Renegociá ${a.nombre}: subió ${a.pct_suba}%`,
      detalle: `Última factura ${fmt(a.costo_ultimo)} vs ${fmt(a.costo_usado)} usado. Afecta: ${a.productos_afectados.slice(0, 3).join(', ')}${a.productos_afectados.length > 3 ? '…' : ''}`,
      impacto: `${fmtK(a.venta_30d_afectada)}/mes en juego`,
      simularProductoId: prodSim?.producto_id,
    })
  }

  // 2. COSTO — caballos: mucho volumen, margen flojo → bajar costo (proveedor/receta/desechables).
  const caballos = sold
    .filter(p => p.costo_completo && (p.pct_margen ?? 100) < 66 && p.costo != null)
    .sort((a, b) => b.venta_30d - a.venta_30d)
    .slice(0, 2)
  for (const p of caballos) {
    const ganancia10 = Math.round((p.costo as number) * 0.10 * p.unidades_30d)
    jugadas.push({
      id: `caballo-${p.producto_id}`, tipo: 'costo',
      titulo: `Bajá el costo de ${p.nombre}`,
      detalle: `${p.pct_margen}% de margen sobre ${fmtK(p.venta_30d)}/mes de venta. Palancas: proveedor, receta, desechables.`,
      impacto: `−10% de costo = +${fmtK(ganancia10)}/mes`,
      simularProductoId: p.producto_id,
    })
  }

  // 3. COMBOS — pares REALES por co-ocurrencia de tickets (no suposición).
  if (pulso?.top_pares?.length) {
    const mixto = pulso.top_pares.filter(par => par.a_cat !== par.b_cat).slice(0, 3)
    for (const par of mixto) {
      const a = all.find(p => p.producto_id === par.a_id)
      const b = all.find(p => p.producto_id === par.b_id)
      if (!a || !b || costoFull(a) == null || costoFull(b) == null) continue
      const suelto = a.precio_venta + b.precio_venta
      const combo = Math.round((suelto * 0.9) / 100) * 100
      const costo = (costoFull(a) ?? 0) + (costoFull(b) ?? 0)
      const margen = combo > 0 ? Math.round((1 - costo / combo) * 100) : 0
      if (margen < 50) continue
      jugadas.push({
        id: `combo-${par.a_id}-${par.b_id}`, tipo: 'combo',
        titulo: `Combo ${par.a} + ${par.b}`,
        detalle: `${par.veces} tickets ya los piden juntos (30d). Sueltos ${fmt(suelto)} → combo ${fmt(combo)} · ${margen}% de margen.`,
        impacto: `${par.veces} tickets/mes de base real`,
      })
    }
  }

  // 4. ADD-ONS — porciones dormidas de alto margen, con el attach actual como línea base.
  const dormidos = all
    .filter(p => p.categoria === 'porciones' && (p.pct_margen ?? 0) >= 75 && p.margen != null && p.precio_venta > 0)
    .sort((a, b) => (a.unidades_30d - b.unidades_30d) || ((b.pct_margen ?? 0) - (a.pct_margen ?? 0)))
  if (dormidos.length) {
    const base = pulso?.attach?.pct_bebida_con_addon
    const margenes = dormidos.map(d => d.pct_margen ?? 0)
    const minM = Math.min(...margenes), maxM = Math.max(...margenes)
    const ADDON_PRECIO = 2900  // precio sugerido del add-on (recomendación)
    const costoTipico = dormidos[0].costo ?? 0
    const margenAttach = Math.max(0, ADDON_PRECIO - costoTipico)
    jugadas.push({
      id: 'addons', tipo: 'addon',
      titulo: `Activá los add-ons dormidos (add-on sugerido +${fmt(ADDON_PRECIO)})`,
      detalle: `${dormidos.length} porciones con ${minM}-${maxM}% de margen casi sin ventas: ${dormidos.slice(0, 3).map(d => d.nombre.replace('Porcion ', '').replace('Porción ', '')).join(', ')}… ${base != null ? `Hoy solo ${base}% de las bebidas llevan add-on.` : ''}`,
      impacto: `~${fmtK(margenAttach)} de margen por add-on`,
    })
  }

  // 5. DAYPART — hora valle para ubicar promos donde rinden.
  if (pulso?.daypart?.length) {
    const abiertos = pulso.daypart.filter(d => d.tickets >= 5)
    if (abiertos.length >= 4) {
      const valle = [...abiertos].sort((a, b) => a.ventas - b.ventas)[0]
      const pico = [...abiertos].sort((a, b) => b.ventas - a.ventas)[0]
      jugadas.push({
        id: 'daypart', tipo: 'daypart',
        titulo: `Hora valle: ${valle.hora}:00 — empujá combos ahí`,
        detalle: `A las ${valle.hora}:00 vendés ${fmtK(valle.ventas)} en 30d vs ${fmtK(pico.ventas)} a las ${pico.hora}:00 (tu pico). Una promo de tarde (2da unidad −40%, nunca 2×1) llena la franja.`,
        impacto: `${Math.round(valle.ventas / Math.max(1, pico.ventas) * 100)}% del pico`,
      })
    }
  }

  // 6. PRECIO — al final y NUNCA café core (la queja de los clientes es el café diario).
  const TARGET = 0.62
  const ops = sold
    .filter(p => p.tipo !== 'reventa' && !esCafeCore(p.nombre) && p.costo_completo
      && p.pct_margen != null && p.pct_margen < 58 && p.costo != null)
    .map(p => {
      const sugerido = Math.round((p.costo! / (1 - TARGET)) / 100) * 100
      const suba = p.precio_venta > 0 ? (sugerido - p.precio_venta) / p.precio_venta : 0
      const ganancia = Math.max(0, (sugerido - p.precio_venta) * p.unidades_30d)
      return { p, sugerido, ganancia, suba }
    })
    .filter(x => x.suba > 0 && x.suba <= 0.20)
    .sort((a, b) => b.ganancia - a.ganancia)
    .slice(0, 2)
  for (const { p, sugerido, ganancia } of ops) {
    jugadas.push({
      id: `precio-${p.producto_id}`, tipo: 'precio',
      titulo: `Precio de ${p.nombre}: ${fmt(p.precio_venta)} → ${fmt(sugerido)}`,
      detalle: `Margen ${p.pct_margen}%. Antes de subir, probá bajar el costo (simulador). No es café del día a día.`,
      impacto: `+${fmtK(ganancia)}/mes`,
      simularProductoId: p.producto_id,
      riesgo: 'sensible a precio',
    })
  }

  return jugadas
}
