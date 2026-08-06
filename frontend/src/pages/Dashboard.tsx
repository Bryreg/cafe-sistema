import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import {
  BarChart3, TrendingUp, TrendingDown, ShoppingCart, Package,
  AlertTriangle, Download, RefreshCw, Layers, Store, Banknote,
  Wallet, Check, ChevronRight, Inbox, Sparkles, Cake, AlertCircle,
} from 'lucide-react'
// Hora LOCAL (Colombia): toISOString es UTC y despues de las 19:00 devuelve manana,
// haciendo que el panel consulte un dia futuro y muestre todo en cero.
import { hoyLocal as today, haceDiasLocal as daysAgo, inicioMesLocal as primerDiaDelMes } from '../utils/fechaLocal'
import { novedadesParaRol, TipoNovedad } from '../constants/novedades'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

// ─── Types ────────────────────────────────────────────────────────────────────

interface Sede { id: number; nombre: string }

interface Resumen {
  total_ventas: number
  n_tickets: number
  ticket_promedio: number
  total_efectivo: number
  total_tarjeta: number
  n_items: number
}

interface VentaHora {
  hora: number
  total: number
  n_tickets: number
}

interface ProductoTop {
  nombre_producto: string
  unidades: number
  total: number
}

interface VentaSede {
  tienda_id: number
  tienda: string
  total: number
  n_tickets: number
}

interface ImpulsoSede { lote_id: number; producto_nombre: string; cantidad_restante: number; dias_en_inventario: number; urgente: boolean; sede: string }
interface RutinaHoy { clave: string; nombre: string; status: 'ok' | 'warn' | 'alert' | null; hechas: number }
interface LimpiezaSede { tienda: string; rutinas: RutinaHoy[]; aseoHechas: number; aseoTotal: number; ultimaActividad: string | null }

interface VentaCategoria {
  categoria: string
  total: number
  unidades: number
}

interface InvValorizado {
  total: number
  nota: string
  por_sede: { tienda_id: number; tienda: string; valor: number }[]
  por_categoria: { categoria: string; valor: number }[]
}

interface DashCompras {
  total_facturado: number
  total_pagado: number
  total_pendiente: number
  por_proveedor: { proveedor: string; facturado: number; pagado: number; n: number }[]
}

// Forma unificada: get_alertas + campos opcionales de la variante consolidada.
interface AlertaStock {
  producto_id: number
  producto: string
  unidad?: string
  stock_actual: number
  stock_minimo: number
  stock_critico?: number
  stock_ideal?: number
  nivel?: 'agotado' | 'bajo'
  estado: 'agotado' | 'critico' | 'bajo'
  cantidad_sugerida?: number
  tienda_id?: number
  tienda_nombre?: string
}

interface LoteVencer {
  producto: string
  cantidad_restante: number
  fecha_vencimiento: string
  tienda: string
}

interface MermaItem {
  producto: string
  cantidad: number
  tipo: string
}

interface DescuadresResumen {
  con_diferencia: number
  n_turnos: number
}

interface ConsignPend {
  n: number
  monto: number
}

interface ConsignTurno {
  turno_id: number
  tienda_nombre?: string
  esperado_consignar: number
  total_consignado: number
  diferencia: number
}

interface TurnoActivo {
  id: number
  fecha_apertura: string
}

// ─── Período ────────────────────────────────────────────────────────────────────

type Periodo = 'hoy' | 'semana' | 'mes' | '3meses'

const PERIODOS: { key: Periodo; label: string }[] = [
  { key: 'hoy', label: 'Hoy' },
  { key: 'semana', label: '7 días' },
  { key: 'mes', label: '30 días' },
  { key: '3meses', label: '90 días' },
]

function periodoRango(p: Periodo): { desde: string; hasta: string } {
  const hasta = today()
  const desde = p === 'hoy'
    ? today()
    : p === 'semana'
    ? daysAgo(7)
    : p === 'mes'
    ? daysAgo(30)
    : daysAgo(90)
  return { desde, hasta }
}

const catColores: Record<string, string> = {
  bebida: '#5c7a4e',
  pasteleria: '#c08a3e',
  insumo: '#7a6a55',
}

// Badges de novedad (estilo inline para matchear el dashboard; el modal usa Tailwind).
const TIPO_NOV: Record<TipoNovedad, { label: string; fg: string; bg: string }> = {
  nuevo:  { label: 'Nuevo',  fg: '#15803d', bg: '#dcfce7' },
  mejora: { label: 'Mejora', fg: '#1d4ed8', bg: '#dbeafe' },
  cambio: { label: 'Cambio', fg: '#b45309', bg: '#fef3c7' },
}
// Parseo manual de YYYY-MM-DD para evitar el corrimiento UTC de new Date(iso).
function fmtFechaNov(f: string): string {
  const [a, m, d] = f.split('-').map(Number)
  return new Date(a, (m || 1) - 1, d || 1)
    .toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })
}

// ─── Componentes auxiliares ───────────────────────────────────────────────────

function KpiCard({
  label, value, sub, color, children,
}: {
  label: string; value: string; sub?: string; color?: string; children?: React.ReactNode
}) {
  return (
    <div style={{
      background: '#fff',
      border: '1px solid #e8e3db',
      borderRadius: 14,
      padding: '14px 16px',
    }}>
      <p style={{ fontSize: 11, fontWeight: 600, color: '#8b7d6b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
        {label}
      </p>
      <p style={{ fontSize: 22, fontWeight: 700, color: color ?? '#1a1512', lineHeight: 1.1 }}>
        {value}
      </p>
      {sub && <p style={{ fontSize: 12, color: '#8b7d6b', marginTop: 3 }}>{sub}</p>}
      {children}
    </div>
  )
}

function SectionTitle({ icon: Icon, label }: { icon: React.ElementType; label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 10 }}>
      <Icon size={15} style={{ color: '#5c7a4e' }} />
      <h2 style={{ fontSize: 13, fontWeight: 700, color: '#2d1f0f', letterSpacing: '0.01em' }}>{label}</h2>
    </div>
  )
}

// Etiqueta de banda (nivel superior a SectionTitle).
function BandLabel({ label }: { label: string }) {
  return (
    <p style={{ margin: '0 4px 12px', fontSize: 10, fontWeight: 700, color: '#8b7d6b', letterSpacing: '.1em', textTransform: 'uppercase' }}>
      {label}
    </p>
  )
}

function BarHorizontal({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ fontSize: 12, color: '#4a3728', fontWeight: 500, maxWidth: '60%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
        <span style={{ fontSize: 12, color: '#4a3728', fontWeight: 600 }}>{fmt(value)}</span>
      </div>
      <div style={{ height: 6, background: '#f0ebe4', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 4, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

// Tarjeta accionable de la Banda 2 (severidad por color).
type Severity = 'danger' | 'warning' | 'neutral'

function AlertCard({
  icon: Icon, primary, label, severity, ctaLabel, to,
}: {
  icon: React.ElementType
  primary: string
  label: string
  severity: Severity
  ctaLabel: string
  to: string
}) {
  const navigate = useNavigate()
  const c = severity === 'danger'
    ? { fg: '#b91c1c', border: '#f2cccc', bg: '#fdf4f4' }
    : severity === 'warning'
    ? { fg: '#b45309', border: '#f4d9a3', bg: '#fffaef' }
    : { fg: '#556072', border: '#ddd5c8', bg: '#f8f5f0' }
  return (
    <div
      role="button"
      onClick={() => navigate(to)}
      style={{
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: 14,
        padding: '13px 15px',
        display: 'flex',
        flexDirection: 'column',
        gap: 5,
        cursor: 'pointer',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <Icon size={17} style={{ color: c.fg, flexShrink: 0 }} />
        <span style={{ fontSize: 20, fontWeight: 700, color: c.fg, lineHeight: 1.1 }}>{primary}</span>
      </div>
      <p style={{ margin: 0, fontSize: 12.5, color: c.fg, lineHeight: 1.3 }}>{label}</p>
      <span style={{ marginTop: 3, display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 12, fontWeight: 700, color: c.fg }}>
        {ctaLabel} <ChevronRight size={13} />
      </span>
    </div>
  )
}

// ─── Dashboard (merged) ──────────────────────────────────────────────────────

/**
 * Dashboard admin unificado: una sola página scrolleable con 3 bandas.
 * Banda 1 "Pulso de hoy" → siempre hoy (no usa el período).
 * Banda 2 "Requiere tu atención" → siempre "ahora"; respeta el filtro de sede.
 * Banda 3 "Análisis" → gobernada por el filtro de período + sede.
 */
export default function Dashboard() {
  const [sedes, setSedes] = useState<Sede[]>([])
  const [sedeId, setSedeId] = useState<number | null>(null)   // null = Todas
  const [periodo, setPeriodo] = useState<Periodo>('hoy')       // solo Banda 3
  const [loading, setLoading] = useState(false)

  // ── Banda 1 ──
  const [hoy, setHoy] = useState<Resumen | null>(null)
  const [ayer, setAyer] = useState<Resumen | null>(null)
  const [ventasSedeHoy, setVentasSedeHoy] = useState<VentaSede[]>([])
  const [turnosPorSede, setTurnosPorSede] = useState<Record<number, boolean>>({})

  // ── Banda 2 ──
  const [alertas, setAlertas] = useState<AlertaStock[]>([])
  const [consignPend, setConsignPend] = useState<ConsignPend | null>(null)
  const [comprasPend, setComprasPend] = useState<DashCompras | null>(null)
  const [descuadres, setDescuadres] = useState<DescuadresResumen | null>(null)
  const [lotesVencer, setLotesVencer] = useState<LoteVencer[]>([])
  const [solicitudesPend, setSolicitudesPend] = useState(0)
  // Flujo proyectado: el día en que se acaba la plata. Solo se muestra si EXISTE
  // (null = la proyección nunca cruza cero, y entonces no hay nada que atender).
  const [quiebre, setQuiebre] = useState<{ fecha: string; dias: number } | null>(null)
  // Y lo que la proyección NO sabe. Sin esto, la AUSENCIA de quiebre se leería
  // como "estás bien" cuando en realidad puede ser "nadie cargó los pagos".
  const [faltaFlujo, setFaltaFlujo] = useState<string[]>([])

  // ── Banda 3 ──
  const [resumen, setResumen] = useState<Resumen | null>(null)
  const [ventasPorHora, setVentasPorHora] = useState<VentaHora[]>([])
  const [topProductos, setTopProductos] = useState<ProductoTop[]>([])
  const [ventasPorSede, setVentasPorSede] = useState<VentaSede[]>([])
  const [ventasPorCategoria, setVentasPorCategoria] = useState<VentaCategoria[]>([])
  const [invValorizado, setInvValorizado] = useState<InvValorizado | null>(null)
  const [comprasPeriodo, setComprasPeriodo] = useState<DashCompras | null>(null)
  const [mermas, setMermas] = useState<MermaItem[]>([])
  // Pastelería por impulsar + Limpieza de hoy — de TODAS las sedes (no respetan el filtro de sede).
  const [impulso, setImpulso] = useState<ImpulsoSede[]>([])
  const [limpiezaSedes, setLimpiezaSedes] = useState<LimpiezaSede[]>([])

  // ── Cargar sedes ──
  useEffect(() => {
    api.get('/auth/tiendas').then(r => setSedes(r.data ?? [])).catch(() => {})
  }, [])

  // ── Banda 1: pulso de hoy (deps: sedeId) ──
  const cargarPulso = useCallback(() => {
    const t = today()
    const paramsSede = sedeId !== null ? { tienda_id: sedeId } : {}

    api.get('/pos/analytics/resumen', { params: { fecha_desde: t, fecha_hasta: t, ...paramsSede } })
      .then(r => setHoy(r.data)).catch(() => setHoy(null))
    const ay = daysAgo(1)
    api.get('/pos/analytics/resumen', { params: { fecha_desde: ay, fecha_hasta: ay, ...paramsSede } })
      .then(r => setAyer(r.data)).catch(() => setAyer(null))
    // Split por sede: SIEMPRE todas las sedes (no respeta el filtro de sede).
    api.get('/dashboard-ejecutivo/ventas-por-sede', { params: { fecha_desde: t, fecha_hasta: t } })
      .then(r => setVentasSedeHoy(r.data ?? [])).catch(() => setVentasSedeHoy([]))
  }, [sedeId])

  // Turnos abiertos por sede — depende de la lista de sedes.
  useEffect(() => {
    if (sedes.length === 0) return
    let cancel = false
    Promise.all(
      sedes.map(s =>
        api.get(`/caja/activo/${s.id}`)
          .then(r => ({ id: s.id, abierto: !!(r.data as TurnoActivo | null) }))
          .catch(() => ({ id: s.id, abierto: false }))
      )
    ).then(res => {
      if (cancel) return
      const map: Record<number, boolean> = {}
      res.forEach(x => { map[x.id] = x.abierto })
      setTurnosPorSede(map)
    })
    return () => { cancel = true }
  }, [sedes])

  // Pastelería por impulsar (lotes 3+ días) de TODAS las sedes, combinada.
  useEffect(() => {
    if (sedes.length === 0) return
    let cancel = false
    Promise.all(
      sedes.map(s =>
        api.get(`/inventario/pasteleria-impulso/${s.id}`)
          .then(r => (r.data ?? []).map((it: any) => ({ ...it, sede: s.nombre })))
          .catch(() => [])
      )
    ).then(res => {
      if (cancel) return
      const all = (res.flat() as ImpulsoSede[])
        .sort((a, b) => (b.urgente ? 1 : 0) - (a.urgente ? 1 : 0) || b.dias_en_inventario - a.dias_en_inventario)
      setImpulso(all)
    })
    return () => { cancel = true }
  }, [sedes])

  // Limpieza por sede: rutinas por hora (estado) + aseo profundo de la semana + última actividad.
  useEffect(() => {
    if (sedes.length === 0) return
    let cancel = false
    const hoyStr = today()                       // YYYY-MM-DD local
    const [aa, mm, dd] = hoyStr.split('-').map(Number)
    const semanaHoy = Math.min(Math.floor((dd - 1) / 7) + 1, 4)
    Promise.all(
      sedes.map(s =>
        Promise.all([
          api.get('/rutinas/cumplimiento-dia', { params: { tienda_id: s.id } }).then(r => r.data).catch(() => null),
          api.get(`/limpieza/${s.id}/tareas`).then(r => r.data).catch(() => []),
          api.get(`/limpieza/${s.id}/semanal`, { params: { mes: mm, anio: aa } }).then(r => r.data).catch(() => []),
        ]).then(([cd, tareas, regs]: [any, any[], any[]]) => {
          const activas = (tareas ?? []).filter((t: any) => t.activa)
          const regSem = new Set((regs ?? []).filter((r: any) => Math.min(r.semana || 1, 4) === semanaHoy).map((r: any) => r.tarea_key))
          const rutinas = (cd?.rutinas ?? []).map((x: any) => ({ clave: x.clave, nombre: x.nombre, status: x.status, hechas: x.hechas }))
          // Última actividad de rutinas (hora del evento más reciente de hoy).
          const ultimos = (cd?.rutinas ?? []).map((x: any) => x.ultimo).filter(Boolean).sort()
          return {
            tienda: s.nombre,
            rutinas,
            aseoHechas: activas.filter((t: any) => regSem.has(t.key)).length,
            aseoTotal: activas.length,
            ultimaActividad: ultimos.length ? ultimos[ultimos.length - 1] : null,
          }
        })
      )
    ).then(res => { if (!cancel) setLimpiezaSedes(res) })
    return () => { cancel = true }
  }, [sedes])

  // ── Banda 2: requiere tu atención (deps: sedeId) ──
  const cargarAtencion = useCallback(() => {
    const paramsSede = sedeId !== null ? { tienda_id: sedeId } : {}

    // Stock consolidado (endpoint nuevo).
    api.get('/inventario/alertas', { params: paramsSede })
      .then(r => setAlertas(r.data ?? [])).catch(() => setAlertas([]))

    // Consignaciones: única fuente de verdad.
    api.get('/consignaciones/resumen-admin', { params: paramsSede })
      .then(r => {
        const filas: ConsignTurno[] = Array.isArray(r.data) ? r.data : []
        const pendientes = filas.filter(f => f.total_consignado < f.esperado_consignar)
        const monto = pendientes.reduce((acc, f) => acc + Math.max(0, f.esperado_consignar - f.total_consignado), 0)
        setConsignPend({ n: pendientes.length, monto })
      })
      .catch(() => setConsignPend(null))

    // Solicitudes de baristas pendientes (pedido + sencilla) → Bandeja.
    Promise.all([
      api.get('/solicitudes/pedido/todas'),
      api.get('/solicitudes/sencilla/todas'),
    ])
      .then(([p, s]) => {
        const pend = (arr: any[]) => (arr ?? []).filter(x =>
          x.estado === 'pendiente' && (sedeId === null || x.tienda_id === sedeId)).length
        setSolicitudesPend(pend(p.data) + pend(s.data))
      })
      .catch(() => setSolicitudesPend(0))

    // Pagos proveedores: pendiente vigente (sin rango de fechas), scoped por sede.
    api.get('/facturas/dashboard', { params: paramsSede })
      .then(r => setComprasPend({
        total_facturado: r.data?.totales?.facturado ?? 0,
        total_pagado: r.data?.totales?.pagado ?? 0,
        total_pendiente: r.data?.totales?.pendiente ?? 0,
        por_proveedor: r.data?.por_proveedor ?? [],
      }))
      .catch(() => setComprasPend(null))

    // Descuadres del mes: /informes/turnos requiere tienda_id → loop cuando es "Todas".
    const desde = primerDiaDelMes()
    const hasta = today()
    const objetivo = sedeId !== null ? [{ id: sedeId }] : sedes.map(s => ({ id: s.id }))
    if (objetivo.length === 0) {
      setDescuadres(null)
    } else {
      Promise.all(
        objetivo.map(o =>
          api.get('/informes/turnos', { params: { tienda_id: o.id, fecha_desde: desde, fecha_hasta: hasta } })
            .then(r => ({
              con_diferencia: r.data?.totales?.con_diferencia ?? 0,
              n_turnos: r.data?.totales?.n_turnos ?? 0,
            }))
            .catch(() => ({ con_diferencia: 0, n_turnos: 0 }))
        )
      ).then(res => {
        setDescuadres({
          con_diferencia: res.reduce((a, x) => a + x.con_diferencia, 0),
          n_turnos: res.reduce((a, x) => a + x.n_turnos, 0),
        })
      })
    }

    // Lotes por vencer.
    api.get('/inventario/lotes-trazabilidad', { params: { estado: 'por_vencer', ...paramsSede } })
      .then(r => setLotesVencer((r.data ?? []).slice(0, 10))).catch(() => setLotesVencer([]))

    // Punto de quiebre del flujo proyectado — el único dato del panel que habla
    // del futuro. Sin quiebre no se muestra la tarjeta roja: no hay nada que
    // atender. Pero si a la proyección le faltan datos, eso SÍ hay que atenderlo:
    // un panel silencioso equivale a decir "todo bien", y nadie lo verificó.
    api.get('/costos/flujo', { params: { dias: 30, ...paramsSede } })
      .then(r => {
        const f = r.data?.punto_de_quiebre
        setQuiebre(f ? { fecha: f, dias: r.data?.dias_hasta_quiebre ?? 0 } : null)
        const a = r.data?.advertencias
        const falta: string[] = []
        if (a?.sin_salidas_cargadas) falta.push('no hay pagos cargados')
        if (a?.sin_historia_ventas) falta.push('no hay ventas para estimar lo que entra')
        if (a?.excluye_corporativas) falta.push('esta sede no incluye los gastos corporativos')
        if (a?.saldo_banco_desactualizado) falta.push(
          r.data?.caja_hoy?.saldo_banco_fecha
            ? 'el saldo del banco está viejo'
            : 'falta el saldo del banco')
        setFaltaFlujo(falta)
      })
      .catch(() => { setQuiebre(null); setFaltaFlujo([]) })
  }, [sedeId, sedes])

  // ── Banda 3: análisis (deps: periodo, sedeId) ──
  const cargarAnalisis = useCallback(() => {
    const { desde, hasta } = periodoRango(periodo)
    const params: Record<string, string | number> = { fecha_desde: desde, fecha_hasta: hasta }
    if (sedeId !== null) params['tienda_id'] = sedeId

    api.get('/pos/analytics/resumen', { params }).then(r => setResumen(r.data)).catch(() => setResumen(null))
    api.get('/pos/analytics/ventas-por-hora', { params }).then(r => setVentasPorHora(r.data ?? [])).catch(() => setVentasPorHora([]))
    // FIX top-productos: pasar tienda_id (via params) cuando hay sede seleccionada.
    api.get('/pos/analytics/productos-top', { params: { ...params, limite: 10 } }).then(r => setTopProductos(r.data ?? [])).catch(() => setTopProductos([]))
    // ventas-por-sede: el endpoint SOLO acepta fechas → filtramos client-side por sede.
    api.get('/dashboard-ejecutivo/ventas-por-sede', { params: { fecha_desde: desde, fecha_hasta: hasta } })
      .then(r => setVentasPorSede(r.data ?? [])).catch(() => setVentasPorSede([]))
    api.get('/dashboard-ejecutivo/ventas-por-categoria', { params }).then(r => setVentasPorCategoria(r.data ?? [])).catch(() => setVentasPorCategoria([]))
    api.get('/dashboard-ejecutivo/inventario-valorizado', { params: sedeId !== null ? { tienda_id: sedeId } : {} }).then(r => setInvValorizado(r.data)).catch(() => setInvValorizado(null))
    api.get('/facturas/dashboard', { params: sedeId !== null ? { tienda_id: sedeId, desde, hasta } : { desde, hasta } })
      .then(r => setComprasPeriodo({
        total_facturado: r.data?.totales?.facturado ?? 0,
        total_pagado: r.data?.totales?.pagado ?? 0,
        total_pendiente: r.data?.totales?.pendiente ?? 0,
        por_proveedor: r.data?.por_proveedor ?? [],
      }))
      .catch(() => setComprasPeriodo(null))
    // Mermas: /informes/mermas requiere tienda_id → solo con sede seleccionada.
    if (sedeId !== null) {
      api.get('/informes/mermas', { params })
        .then(r => setMermas(((r.data?.filas ?? []) as any[])
          .map(f => ({ producto: f.producto, cantidad: f.total_cantidad ?? 0, tipo: f.unidad ?? '' }))
          .slice(0, 8)))
        .catch(() => setMermas([]))
    } else {
      setMermas([])
    }
  }, [periodo, sedeId, sedes])

  // Un solo cargar() dispara las 3 bandas; Actualizar lo re-ejecuta.
  const cargar = useCallback(() => {
    setLoading(true)
    Promise.all([
      Promise.resolve(cargarPulso()),
      Promise.resolve(cargarAtencion()),
      Promise.resolve(cargarAnalisis()),
    ]).finally(() => setLoading(false))
  }, [cargarPulso, cargarAtencion, cargarAnalisis])

  useEffect(() => { cargarPulso() }, [cargarPulso])
  useEffect(() => { cargarAtencion() }, [cargarAtencion])
  useEffect(() => { cargarAnalisis() }, [cargarAnalisis])

  // ── Export CSV ──
  function exportarCSV() {
    const { desde, hasta } = periodoRango(periodo)
    const agot = alertas.filter(a => a.estado === 'agotado').length
    const crit = alertas.filter(a => a.estado === 'critico').length
    const lines: string[] = [
      `Dashboard — Análisis ${desde} a ${hasta}`,
      '',
      'KPIs período',
      'Ventas totales,N° tickets,Ticket promedio,Efectivo,Tarjeta',
      [
        resumen?.total_ventas ?? 0,
        resumen?.n_tickets ?? 0,
        resumen?.ticket_promedio ?? 0,
        resumen?.total_efectivo ?? 0,
        resumen?.total_tarjeta ?? 0,
      ].join(','),
      '',
      'Ventas por sede',
      'Sede,Total,Tickets',
      ...ventasPorSedeFiltradas.map(s => `${s.tienda},${s.total},${s.n_tickets}`),
      '',
      'Ventas por categoría',
      'Categoría,Total,Unidades',
      ...ventasPorCategoria.map(c => `${c.categoria},${c.total},${c.unidades}`),
      '',
      'Top productos',
      'Producto,Unidades,Total',
      ...topProductos.slice(0, 10).map(p => `${p.nombre_producto},${p.unidades},${p.total}`),
      '',
      'Requiere atención (ahora)',
      'Indicador,Valor',
      `Stock agotados,${agot}`,
      `Stock críticos,${crit}`,
      `Lotes por vencer,${lotesVencer.length}`,
      `Pagos proveedores pendiente,${comprasPend?.total_pendiente ?? 0}`,
      `Descuadres de caja (mes),${descuadres ? `${descuadres.con_diferencia} de ${descuadres.n_turnos}` : '—'}`,
      `Consignaciones sin consignar,${consignPend ? `${consignPend.n} turnos (${consignPend.monto})` : '—'}`,
      '',
      'Mermas del período (unidades)',
      'Producto,Unidades',
      ...mermas.map(m => `${m.producto},${Math.round(m.cantidad)}`),
    ]
    const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `dashboard-${desde}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ─── Derived — Banda 1 ──
  const ventasHoy = hoy?.total_ventas ?? 0
  const ventasAyer = ayer?.total_ventas ?? 0
  const delta = ventasHoy - ventasAyer
  const deltaPct = ventasAyer > 0 ? (delta / ventasAyer) * 100 : 0
  const positive = delta >= 0
  const efectPct = ventasHoy > 0 ? Math.round(((hoy?.total_efectivo ?? 0) / ventasHoy) * 100) : 0
  const tarjPct = ventasHoy > 0 ? Math.round(((hoy?.total_tarjeta ?? 0) / ventasHoy) * 100) : 0

  // ─── Derived — Banda 2 ──
  const agotadosN = alertas.filter(a => a.estado === 'agotado').length
  const criticosN = alertas.filter(a => a.estado === 'critico').length
  const hayStock = agotadosN + criticosN > 0
  const hayConsign = (consignPend?.n ?? 0) > 0
  const hayPagos = (comprasPend?.total_pendiente ?? 0) > 0
  const haySolicitudes = solicitudesPend > 0
  const hayDescuadres = (descuadres?.con_diferencia ?? 0) > 0
  const hayLotes = lotesVencer.length > 0
  const hayQuiebre = quiebre !== null
  const faltaInfoFlujo = faltaFlujo.length > 0
  const hayAlgo = hayStock || hayConsign || hayPagos || hayDescuadres || hayLotes
    || hayQuiebre || faltaInfoFlujo

  // ─── Derived — Banda 3 ──
  const ventasPorSedeFiltradas = sedeId === null
    ? ventasPorSede
    : ventasPorSede.filter(s => s.tienda_id === sedeId)

  const maxVentaHora = ventasPorHora.length > 0 ? Math.max(...ventasPorHora.map(h => h.total)) : 1
  const maxVentaSede = ventasPorSedeFiltradas.length > 0 ? Math.max(...ventasPorSedeFiltradas.map(s => s.total)) : 1
  const maxVentaCat  = ventasPorCategoria.length > 0 ? Math.max(...ventasPorCategoria.map(c => c.total)) : 1
  const maxTopProd   = topProductos.length > 0 ? Math.max(...topProductos.map(p => p.total)) : 1

  // ─── Render ───────────────────────────────────────────────────────────────────
  return (
    <div style={{ fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif', padding: '4px 0 40px', maxWidth: 1100 }}>

      {/* ── TOP BAR ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 16, marginTop: 14 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1a1512', display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
            <BarChart3 size={20} style={{ color: '#5c7a4e' }} />
            Dashboard
          </h1>
          <p style={{ fontSize: 13, color: '#8b7d6b', margin: '3px 0 0' }}>
            Pulso del día · alertas accionables · análisis del negocio
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={cargar}
            style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#f5f0e8', border: '1px solid #e0d9cc', borderRadius: 10, padding: '7px 12px', fontSize: 13, color: '#4a3728', cursor: 'pointer', fontWeight: 500 }}
          >
            <RefreshCw size={13} style={{ opacity: loading ? 0.4 : 1 }} />
            {loading ? 'Cargando…' : 'Actualizar'}
          </button>
          <button
            onClick={exportarCSV}
            style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#5c7a4e', border: 'none', borderRadius: 10, padding: '7px 14px', fontSize: 13, color: '#fff', cursor: 'pointer', fontWeight: 600 }}
          >
            <Download size={13} />
            CSV
          </button>
        </div>
      </div>

      {/* ── Filtros ── */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 18, alignItems: 'center' }}>
        {/* Sede */}
        {sedes.length > 1 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button
              onClick={() => setSedeId(null)}
              style={{
                padding: '6px 14px', borderRadius: 20, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                border: sedeId === null ? 'none' : '1px solid #e0d9cc',
                background: sedeId === null ? '#2d5a3f' : '#fff',
                color: sedeId === null ? '#fff' : '#4a3728',
              }}
            >
              Todas
            </button>
            {sedes.map(s => (
              <button
                key={s.id}
                onClick={() => setSedeId(s.id)}
                style={{
                  padding: '6px 14px', borderRadius: 20, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                  border: sedeId === s.id ? 'none' : '1px solid #e0d9cc',
                  background: sedeId === s.id ? '#2d5a3f' : '#fff',
                  color: sedeId === s.id ? '#fff' : '#4a3728',
                }}
              >
                {s.nombre}
              </button>
            ))}
          </div>
        )}

      </div>

      {/* ══ BANDA 1 · Pulso de hoy ══ */}
      <BandLabel label="Pulso de hoy" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 12 }}>
        {/* Ventas de hoy — tile enfatizado forest-green + delta */}
        <div style={{
          background: 'linear-gradient(165deg, #1a6b3a 0%, #14512c 100%)',
          borderRadius: 14, padding: '14px 16px', color: '#fff',
          boxShadow: '0 10px 26px -18px rgba(28,55,42,.7)',
        }}>
          <p style={{ fontSize: 11, fontWeight: 600, color: 'oklch(85% 0.05 155)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
            Ventas de hoy
          </p>
          <p style={{ fontSize: 24, fontWeight: 700, color: '#fff', lineHeight: 1.05 }}>{fmt(ventasHoy)}</p>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 6,
            padding: '3px 9px', borderRadius: 999,
            background: ventasAyer === 0 ? 'rgba(255,255,255,.12)' : positive ? 'rgba(120,220,150,.22)' : 'rgba(240,150,120,.22)',
          }}>
            {ventasAyer > 0
              ? (positive ? <TrendingUp size={11} style={{ color: '#a7f3c9' }} /> : <TrendingDown size={11} style={{ color: '#f8b7a0' }} />)
              : null}
            <span style={{ fontSize: 11, fontWeight: 700, color: '#fff' }}>
              {ventasAyer > 0
                ? `${positive ? '+' : ''}${deltaPct.toFixed(1)}% vs. ayer`
                : 'Sin datos de ayer'}
            </span>
          </div>
        </div>

        <KpiCard
          label="Tickets"
          value={`${hoy?.n_tickets ?? 0}`}
          sub={`Ticket prom. ${fmt(hoy?.ticket_promedio ?? 0)}`}
        />
        <KpiCard
          label="Efectivo"
          value={fmt(hoy?.total_efectivo ?? 0)}
          sub={`${efectPct}% del total`}
        />
        <KpiCard
          label="Tarjeta"
          value={fmt(hoy?.total_tarjeta ?? 0)}
          sub={`${tarjPct}% del total`}
        />
      </div>

      {/* Split por sede + indicador de turno abierto */}
      {ventasSedeHoy.length > 0 && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16,
          background: '#fff', border: '1px solid #e8e3db', borderRadius: 14,
          padding: '11px 16px', marginBottom: 22,
        }}>
          {ventasSedeHoy.map((s, i) => (
            <div key={s.tienda_id} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <span style={{
                width: 7, height: 7, borderRadius: 999, flexShrink: 0,
                background: turnosPorSede[s.tienda_id] ? '#2d8a5f' : '#c8c0b4',
                boxShadow: turnosPorSede[s.tienda_id] ? '0 0 0 3px rgba(45,138,95,.18)' : 'none',
              }} />
              <span style={{ fontSize: 13, color: '#4a3728', fontWeight: 500 }}>{s.tienda}</span>
              <span style={{ fontSize: 13, color: '#1a6b3a', fontWeight: 700 }}>{fmt(s.total)}</span>
              <span style={{ fontSize: 11, color: '#8b7d6b' }}>
                {s.n_tickets} tk · prom {fmt(s.n_tickets > 0 ? s.total / s.n_tickets : 0)}
              </span>
              {i < ventasSedeHoy.length - 1 && <span style={{ color: '#d6cec2', marginLeft: 6 }}>·</span>}
            </div>
          ))}
        </div>
      )}

      {/* ══ BANDA 2 · Requiere tu atención ══ */}
      <BandLabel label="Requiere tu atención" />
      {hayAlgo ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(178px, 1fr))', gap: 10, marginBottom: 22 }}>
          {/* Va primero: es lo único que avisa ANTES de que pase. */}
          {hayQuiebre && (
            <AlertCard
              icon={TrendingDown}
              primary={`${quiebre!.dias} día${quiebre!.dias !== 1 ? 's' : ''}`}
              label={`hasta quedarte sin plata · ${new Date(quiebre!.fecha + 'T00:00:00')
                .toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })}`}
              severity="danger"
              ctaLabel="Ver flujo"
              to="/plata#calendario"
            />
          )}
          {/* El silencio no es un all-clear: si a la proyección le faltan datos, se
              dice qué falta en vez de dejar que el panel vacío hable por ella. */}
          {faltaInfoFlujo && (
            <AlertCard
              icon={AlertCircle}
              primary="Falta info"
              label={`para proyectar la plata: ${faltaFlujo.join(' · ')}`}
              severity="warning"
              ctaLabel="Completar"
              to="/plata#calendario"
            />
          )}
          {hayStock && (
            <AlertCard
              icon={AlertTriangle}
              primary={`${agotadosN}`}
              label={`agotados · ${criticosN} críticos`}
              severity="danger"
              ctaLabel="Pedir"
              /* Al inventario, no a /pedidos-admin: es la misma sugerencia (las dos
                 pantallas consumen /pedidos/sugerencia) pero ahí se ve junto al
                 stock, los días que alcanza y cuánto pedir. Pedidos salió del nav. */
              to="/control-inventario"
            />
          )}
          {hayConsign && (
            <AlertCard
              icon={Banknote}
              primary={fmt(consignPend!.monto)}
              label={`sin consignar · ${consignPend!.n} turno${consignPend!.n !== 1 ? 's' : ''}`}
              severity="warning"
              ctaLabel="Ver"
              to="/consignaciones"
            />
          )}
          {hayPagos && (
            <AlertCard
              icon={ShoppingCart}
              primary={fmt(comprasPend!.total_pendiente)}
              label="pagos a proveedores"
              severity="warning"
              ctaLabel="Pagar"
              to="/plata#calendario"
            />
          )}
          {haySolicitudes && (
            <AlertCard
              icon={Inbox}
              primary={`${solicitudesPend}`}
              label={`solicitud${solicitudesPend !== 1 ? 'es' : ''} de baristas pendiente${solicitudesPend !== 1 ? 's' : ''}`}
              severity="warning"
              ctaLabel="Revisar"
              to="/bandeja"
            />
          )}
          {hayDescuadres && (
            <AlertCard
              icon={Wallet}
              primary={`${descuadres!.con_diferencia}`}
              label="descuadres de caja · mes en curso"
              severity="neutral"
              ctaLabel="Revisar"
              to="/cuadre-turnos"
            />
          )}
          {hayLotes && (
            <AlertCard
              icon={Package}
              primary={`${lotesVencer.length}`}
              label={`lote${lotesVencer.length !== 1 ? 's' : ''} por vencer`}
              severity="neutral"
              ctaLabel="Ver"
              to="/lotes"
            />
          )}
        </div>
      ) : (
        <div className="bg-success-50 border border-success-200 flex items-center gap-[9px]"
          style={{ padding: '10px 14px', marginBottom: 22, borderRadius: 14 }}>
          <span className="bg-success-200 flex items-center justify-center flex-shrink-0"
            style={{ width: 22, height: 22, borderRadius: 8 }}>
            <Check size={11} className="text-success-700" />
          </span>
          <span className="text-success-700" style={{ flex: 1, fontSize: 12.5, fontWeight: 600 }}>
            Todo en orden — sin alertas activas
          </span>
        </div>
      )}

      {/* ══ BANDA 3 · Análisis ══ */}
      <BandLabel label="Análisis" />
      {/* Selector de período — ahora pegado al Análisis que controla (antes flotaba arriba) */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        {PERIODOS.map(p => (
          <button key={p.key} onClick={() => setPeriodo(p.key)}
            style={{
              padding: '5px 13px', borderRadius: 20, fontSize: 12, fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
              border: periodo === p.key ? 'none' : '1px solid #e0d9cc',
              background: periodo === p.key ? '#5c7a4e' : '#fff',
              color: periodo === p.key ? '#fff' : '#4a3728',
            }}>
            {p.label}
          </button>
        ))}
      </div>
      {/* Resumen del período en UNA línea — sin repetir el "Pulso de hoy" (antes eran 5 KPIs iguales) */}
      <p style={{ margin: '0 0 16px', fontSize: 12.5, color: '#8b7d6b' }}>
        <strong style={{ color: '#1a6b3a' }}>{fmt(resumen?.total_ventas ?? 0)}</strong> en ventas · {resumen?.n_tickets ?? 0} tickets · prom {fmt(resumen?.ticket_promedio ?? 0)} · efectivo {fmt(resumen?.total_efectivo ?? 0)} · tarjeta {fmt(resumen?.total_tarjeta ?? 0)}
      </p>

      {/* Grid principal de widgets */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16, marginBottom: 16 }}>

        {/* Ventas por hora */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={TrendingUp} label="Ventas por hora" />
          {ventasPorHora.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Sin datos en el período</p>
          ) : (
            <div>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 120 }}>
                {ventasPorHora.map(h => {
                  const pct = maxVentaHora > 0 ? (h.total / maxVentaHora) : 0
                  const isPico = pct >= 0.8
                  return (
                    <div key={h.hora} style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'flex-end', height: '100%' }}>
                      <div
                        title={`${h.hora}h — ${fmt(h.total)}`}
                        style={{
                          width: '100%', maxWidth: 13,
                          height: `${Math.max(pct * 100, h.total > 0 ? 4 : 1)}%`,
                          background: isPico ? '#1a6b3a' : '#63b98c',
                          borderRadius: '3px 3px 0 0',
                        }}
                      />
                    </div>
                  )
                })}
              </div>
              <div style={{ display: 'flex', gap: 3, marginTop: 5 }}>
                {ventasPorHora.map(h => (
                  <span key={h.hora} style={{ flex: 1, textAlign: 'center', fontSize: 9, color: '#8b7d6b', whiteSpace: 'nowrap' }}>
                    {[6, 9, 12, 15, 18, 21].includes(h.hora) ? `${h.hora}h` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Pastelería por impulsar — lotes con días en inventario, ambas sedes */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={Cake} label="Pastelería por impulsar" />
          {impulso.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Nada urgente por impulsar</p>
          ) : (
            impulso.slice(0, 7).map(it => (
              <div key={`${it.sede}-${it.lote_id}`} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 7 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 12.5, color: '#2d1f0f', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.producto_nombre}</p>
                  <p style={{ margin: 0, fontSize: 10.5, color: '#8b7d6b' }}>{sedes.length > 1 ? `${it.sede} · ` : ''}{it.cantidad_restante} {it.cantidad_restante === 1 ? 'unidad' : 'u.'}</p>
                </div>
                <span style={{ fontSize: 10.5, fontWeight: 700, padding: '2px 8px', borderRadius: 999, flexShrink: 0,
                  background: it.urgente ? '#fde8e8' : '#fef3c7', color: it.urgente ? '#b42318' : '#b45309' }}>
                  {it.urgente ? '¡Último día!' : `${it.dias_en_inventario}d`}
                </span>
              </div>
            ))
          )}
        </div>

        {/* Limpieza — rutinas por hora + aseo profundo semanal, por sede */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={Sparkles} label="Limpieza y aseo" />
          {limpiezaSedes.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Cargando…</p>
          ) : (
            limpiezaSedes.map(s => {
              const venc = s.rutinas.filter(r => r.status === 'alert').length
              const aseoPct = s.aseoTotal ? Math.round((s.aseoHechas / s.aseoTotal) * 100) : 0
              const aseoOk = s.aseoTotal > 0 && s.aseoHechas === s.aseoTotal
              return (
                <div key={s.tienda} style={{ marginBottom: 13 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#4a3728' }}>{s.tienda}</span>
                    <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 7px', borderRadius: 999,
                      background: venc > 0 ? '#fde8e8' : '#dcfce7', color: venc > 0 ? '#b42318' : '#15803d' }}>
                      {venc > 0 ? `${venc} rutina${venc > 1 ? 's' : ''} vencida${venc > 1 ? 's' : ''}` : 'rutinas al día'}
                    </span>
                  </div>
                  {/* Rutinas por hora: dots por rutina */}
                  <div style={{ display: 'flex', gap: 12, marginBottom: 7 }}>
                    {s.rutinas.map(r => {
                      const c = r.status === 'ok' ? '#16a34a' : r.status === 'warn' ? '#d97706' : r.status === 'alert' ? '#dc2626' : '#c8c0b4'
                      const nom = r.nombre.replace('Limpieza General', 'Limpieza').replace('Revisión Vitrina', 'Vitrina')
                      return (
                        <span key={r.clave} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10.5, color: '#6b5d4b' }} title={`${r.nombre}: ${r.hechas} hoy`}>
                          <span style={{ width: 7, height: 7, borderRadius: 999, background: c, flexShrink: 0 }} />
                          {nom} <strong style={{ color: '#4a3728' }}>{r.hechas}</strong>
                        </span>
                      )
                    })}
                    {s.rutinas.length === 0 && <span style={{ fontSize: 10.5, color: '#8b7d6b' }}>sin rutinas hoy</span>}
                  </div>
                  {/* Aseo profundo semanal */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
                    <span style={{ fontSize: 11, color: '#6b5d4b' }}>Aseo profundo · semana</span>
                    <span style={{ fontSize: 11.5, fontWeight: 700, color: aseoOk ? '#15803d' : '#4a3728' }}>{s.aseoHechas}/{s.aseoTotal}{aseoOk ? ' ✓' : ''}</span>
                  </div>
                  <div style={{ height: 5, background: '#f0ebe4', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${aseoPct}%`, background: aseoOk ? '#16a34a' : aseoPct > 0 ? '#c08a3e' : '#f0ebe4', borderRadius: 3 }} />
                  </div>
                </div>
              )
            })
          )}
        </div>

      </div>

      {/* Fila: Top productos (izq) + Novedades del sistema (der, horizontal) */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 16 }}>

        {/* Top productos */}
        <div style={{ flex: '1 1 280px', minWidth: 0, background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={TrendingUp} label="Top productos" />
          {topProductos.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Sin ventas en el período</p>
          ) : (
            <div>
              {topProductos.slice(0, 8).map((p, idx) => (
                <div key={p.nombre_producto} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 7 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#c08a3e', width: 16, textAlign: 'center' }}>
                    {idx + 1}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                      <span style={{ fontSize: 12, color: '#2d1f0f', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '65%' }}>{p.nombre_producto}</span>
                      <span style={{ fontSize: 12, color: '#1a6b3a', fontWeight: 600 }}>{fmt(p.total)}</span>
                    </div>
                    <div style={{ height: 4, background: '#f0ebe4', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${Math.round((p.total / maxTopProd) * 100)}%`, background: '#c8dbbf', borderRadius: 2 }} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Novedades del sistema — horizontal, ocupa el ancho a la derecha de Top productos */}
        <div style={{ flex: '2 1 460px', minWidth: 0, background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={Sparkles} label="Novedades del sistema" />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))', gap: 10 }}>
            {novedadesParaRol('admin').slice(0, 6).map((n, idx) => (
              <div key={idx} style={{ border: '1px solid #f0ebe4', borderRadius: 10, padding: '8px 10px', background: '#fcfbf9' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 999, color: TIPO_NOV[n.tipo].fg, background: TIPO_NOV[n.tipo].bg }}>{TIPO_NOV[n.tipo].label}</span>
                  <span style={{ fontSize: 10, color: '#8b7d6b' }}>{fmtFechaNov(n.fecha)}</span>
                </div>
                <p style={{ margin: 0, fontSize: 12, fontWeight: 600, color: '#2d1f0f' }}>{n.titulo}</p>
                <p style={{ margin: '2px 0 0', fontSize: 11, color: '#6b5d4b', lineHeight: 1.35, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{n.detalle}</p>
              </div>
            ))}
          </div>
        </div>

      </div>

      {/* Fila inferior: Inventario + Compras + Mermas */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>

        {/* Inventario valorizado */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={Package} label="Inventario valorizado" />
          {invValorizado ? (
            <>
              <p style={{ fontSize: 11, color: '#8b7d6b', marginBottom: 10 }}>
                {invValorizado.nota}
              </p>
              <div style={{ marginBottom: 12 }}>
                <p style={{ fontSize: 10, fontWeight: 700, color: '#8b7d6b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>Por sede</p>
                {invValorizado.por_sede.map(s => (
                  <BarHorizontal key={s.tienda_id} label={s.tienda} value={s.valor} max={Math.max(...invValorizado.por_sede.map(x => x.valor), 1)} color="#2d5a9a" />
                ))}
              </div>
              <div>
                <p style={{ fontSize: 10, fontWeight: 700, color: '#8b7d6b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>Por categoría</p>
                {invValorizado.por_categoria.map(c => (
                  <BarHorizontal key={c.categoria} label={c.categoria} value={c.valor} max={Math.max(...invValorizado.por_categoria.map(x => x.valor), 1)} color={catColores[c.categoria] ?? '#7a6a55'} />
                ))}
              </div>
            </>
          ) : (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Cargando…</p>
          )}
        </div>

        {/* Compras a proveedores (período) */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={ShoppingCart} label="Compras a proveedores" />
          {comprasPeriodo ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
                <div style={{ background: '#f0faf4', border: '1px solid #c8dbbf', borderRadius: 10, padding: '10px 12px' }}>
                  <p style={{ fontSize: 10, color: '#5c7a4e', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 2 }}>Pagado</p>
                  <p style={{ fontSize: 16, fontWeight: 700, color: '#1a6b3a' }}>{fmt(comprasPeriodo.total_pagado)}</p>
                </div>
                <div style={{ background: (comprasPeriodo.total_pendiente > 0) ? '#fff7ed' : '#f5f0e8', border: `1px solid ${comprasPeriodo.total_pendiente > 0 ? '#fbbf24' : '#e0d9cc'}`, borderRadius: 10, padding: '10px 12px' }}>
                  <p style={{ fontSize: 10, color: comprasPeriodo.total_pendiente > 0 ? '#b45309' : '#8b7d6b', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 2 }}>Pendiente</p>
                  <p style={{ fontSize: 16, fontWeight: 700, color: comprasPeriodo.total_pendiente > 0 ? '#b45309' : '#4a3728' }}>{fmt(comprasPeriodo.total_pendiente)}</p>
                </div>
              </div>
              {comprasPeriodo.por_proveedor && comprasPeriodo.por_proveedor.length > 0 && (
                <div>
                  <p style={{ fontSize: 10, fontWeight: 700, color: '#8b7d6b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>Por proveedor</p>
                  {comprasPeriodo.por_proveedor.slice(0, 5).map(p => (
                    <div key={p.proveedor} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, alignItems: 'center' }}>
                      <span style={{ fontSize: 12, color: '#4a3728', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>{p.proveedor}</span>
                      <div style={{ textAlign: 'right' }}>
                        <span style={{ fontSize: 11, color: '#1a6b3a', fontWeight: 600 }}>{fmt(p.pagado)}</span>
                        <span style={{ fontSize: 10, color: '#8b7d6b' }}> / {fmt(p.facturado)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Cargando…</p>
          )}
        </div>

        {/* Mermas del período */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={AlertTriangle} label="Mermas del período" />
          {sedeId === null ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Elegí una sede para ver mermas</p>
          ) : mermas.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Sin mermas registradas</p>
          ) : (
            mermas.slice(0, 8).map((m, idx) => (
              <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                <span style={{ fontSize: 12, color: '#4a3728', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '65%' }}>{m.producto}</span>
                <span style={{ fontSize: 12, color: '#b45309', fontWeight: 600 }}>{Math.round(m.cantidad)} u.</span>
              </div>
            ))
          )}
        </div>

        {/* Ventas por categoría */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={Layers} label="Ventas por categoría" />
          {ventasPorCategoria.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Sin datos en el período</p>
          ) : (
            <div>
              {ventasPorCategoria.map(c => (
                <BarHorizontal
                  key={c.categoria}
                  label={c.categoria.charAt(0).toUpperCase() + c.categoria.slice(1)}
                  value={c.total}
                  max={maxVentaCat}
                  color={catColores[c.categoria] ?? '#7a6a55'}
                />
              ))}
            </div>
          )}
        </div>

        {/* Ventas por sede (client-filtered por sedeId) */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={Store} label="Ventas por sede" />
          {ventasPorSedeFiltradas.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Sin sedes activas</p>
          ) : (
            <div>
              {ventasPorSedeFiltradas.map(s => {
                const prom = s.n_tickets > 0 ? s.total / s.n_tickets : 0
                return (
                  <div key={s.tienda_id} style={{ marginBottom: 11 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 3 }}>
                      <span style={{ fontSize: 12.5, color: '#2d1f0f', fontWeight: 600 }}>{s.tienda}</span>
                      <span style={{ fontSize: 12.5, color: '#1a6b3a', fontWeight: 700 }}>{fmt(s.total)}</span>
                    </div>
                    <div style={{ height: 5, background: '#f0ebe4', borderRadius: 3, overflow: 'hidden', marginBottom: 3 }}>
                      <div style={{ height: '100%', width: `${Math.round((s.total / maxVentaSede) * 100)}%`, background: '#5c7a4e', borderRadius: 3 }} />
                    </div>
                    <div style={{ display: 'flex', gap: 7, fontSize: 10.5, color: '#8b7d6b' }}>
                      <span>{s.n_tickets} tickets</span>
                      <span>·</span>
                      <span>ticket prom. {fmt(prom)}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
