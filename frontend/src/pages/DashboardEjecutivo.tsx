import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import {
  BarChart3, TrendingUp, ShoppingCart, Package,
  AlertTriangle, Download, RefreshCw, DollarSign,
  Layers, Store, ExternalLink,
} from 'lucide-react'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

function today() {
  return new Date().toISOString().slice(0, 10)
}
function daysAgo(n: number) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

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

interface AlertaStock {
  producto_id: number
  producto: string
  stock_actual: number
  stock_minimo: number
  estado: 'agotado' | 'critico' | 'bajo'
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

interface ConciliacionResumen {
  valor_neto: number
  valor_diferencia_total: number
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

// ─── Componentes auxiliares ───────────────────────────────────────────────────

function KpiCard({
  label, value, sub, color,
}: {
  label: string; value: string; sub?: string; color?: string
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

function ResumenCard({
  icon: Icon, label, value, hint, tone, to,
}: {
  icon: React.ElementType
  label: string
  value: string
  hint?: string
  tone: 'ok' | 'warn' | 'danger' | 'muted'
  to: string
}) {
  const navigate = useNavigate()
  const toneColor = tone === 'ok' ? '#1a6b3a' : tone === 'warn' ? '#b45309' : tone === 'danger' ? '#991b1b' : '#8b7d6b'
  const toneBorder = tone === 'ok' ? '#c8dbbf' : tone === 'warn' ? '#fcd34d' : tone === 'danger' ? '#fca5a5' : '#e0d9cc'
  const toneBg = tone === 'ok' ? '#f0faf4' : tone === 'warn' ? '#fffbeb' : tone === 'danger' ? '#fff5f5' : '#f5f0e8'
  return (
    <div
      style={{
        background: toneBg,
        border: `1px solid ${toneBorder}`,
        borderRadius: 14,
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        cursor: 'pointer',
        transition: 'box-shadow 0.15s',
      }}
      onClick={() => navigate(to)}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && navigate(to)}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Icon size={13} style={{ color: toneColor, flexShrink: 0 }} />
          <p style={{ fontSize: 10, fontWeight: 700, color: '#8b7d6b', textTransform: 'uppercase', letterSpacing: '0.04em', margin: 0 }}>{label}</p>
        </div>
        <ExternalLink size={11} style={{ color: '#c0b8ae', flexShrink: 0 }} />
      </div>
      <p style={{ fontSize: 20, fontWeight: 700, color: toneColor, lineHeight: 1.1, margin: 0 }}>{value}</p>
      {hint && <p style={{ fontSize: 11, color: '#8b7d6b', margin: 0 }}>{hint}</p>}
    </div>
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

// ─── DashboardEjecutivo ───────────────────────────────────────────────────────

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

export default function DashboardEjecutivo() {
  const [sedes, setSedes] = useState<Sede[]>([])
  const [sedeId, setSedeId] = useState<number | null>(null)
  const [periodo, setPeriodo] = useState<Periodo>('hoy')
  const [loading, setLoading] = useState(false)

  const [resumen, setResumen] = useState<Resumen | null>(null)
  const [ventasPorHora, setVentasPorHora] = useState<VentaHora[]>([])
  const [topProductos, setTopProductos] = useState<ProductoTop[]>([])
  const [ventasPorSede, setVentasPorSede] = useState<VentaSede[]>([])
  const [ventasPorCategoria, setVentasPorCategoria] = useState<VentaCategoria[]>([])
  const [invValorizado, setInvValorizado] = useState<InvValorizado | null>(null)
  const [compras, setCompras] = useState<DashCompras | null>(null)
  const [alertas, setAlertas] = useState<AlertaStock[]>([])
  const [lotesVencer, setLotesVencer] = useState<LoteVencer[]>([])
  const [mermas, setMermas] = useState<MermaItem[]>([])
  const [conciliacion, setConciliacion] = useState<ConciliacionResumen | null>(null)
  const [descuadres, setDescuadres] = useState<DescuadresResumen | null>(null)
  const [consignPend, setConsignPend] = useState<ConsignPend | null>(null)

  // Cargar sedes
  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
    }).catch(() => {})
  }, [])

  // Cargar datos
  const cargar = useCallback(() => {
    const { desde, hasta } = periodoRango(periodo)
    setLoading(true)

    const params: Record<string, string | number> = {
      fecha_desde: desde,
      fecha_hasta: hasta,
    }
    if (sedeId !== null) params['tienda_id'] = sedeId

    const mesActual = new Date()
    const anio = mesActual.getFullYear()
    const mes = mesActual.getMonth() + 1

    const calls = [
      api.get('/pos/analytics/resumen', { params }).then(r => setResumen(r.data)).catch(() => null),
      api.get('/pos/analytics/ventas-por-hora', { params }).then(r => setVentasPorHora(r.data ?? [])).catch(() => null),
      api.get('/pos/analytics/productos-top', { params: { ...params, limite: 10 } }).then(r => setTopProductos(r.data ?? [])).catch(() => null),
      api.get('/dashboard-ejecutivo/ventas-por-sede', { params: { fecha_desde: desde, fecha_hasta: hasta } }).then(r => setVentasPorSede(r.data ?? [])).catch(() => null),
      api.get('/dashboard-ejecutivo/ventas-por-categoria', { params }).then(r => setVentasPorCategoria(r.data ?? [])).catch(() => null),
      api.get('/dashboard-ejecutivo/inventario-valorizado', { params: sedeId !== null ? { tienda_id: sedeId } : {} }).then(r => setInvValorizado(r.data)).catch(() => null),
      api.get('/facturas/dashboard', { params: sedeId !== null ? { tienda_id: sedeId, desde, hasta } : { desde, hasta } }).then(r => setCompras({
        total_facturado: r.data?.totales?.facturado ?? 0,
        total_pagado: r.data?.totales?.pagado ?? 0,
        total_pendiente: r.data?.totales?.pendiente ?? 0,
        por_proveedor: r.data?.por_proveedor ?? [],
      })).catch(() => null),
      api.get('/inventario/lotes-trazabilidad', { params: { estado: 'por_vencer', ...(sedeId !== null ? { tienda_id: sedeId } : {}) } }).then(r => setLotesVencer((r.data ?? []).slice(0, 10))).catch(() => null),
      api.get('/informes/mermas', { params }).then(r => setMermas((r.data?.items ?? r.data ?? []).slice(0, 8))).catch(() => null),
    ]

    // Alertas stock: solo si hay sede seleccionada
    if (sedeId !== null) {
      calls.push(
        api.get(`/inventario/alertas/${sedeId}`).then(r => setAlertas(r.data ?? [])).catch(() => null)
      )
    } else {
      setAlertas([])
    }

    // Conciliación inventario: solo si hay sede seleccionada (requiere tienda_id)
    if (sedeId !== null) {
      calls.push(
        api.get('/inventario-mensual/conciliacion', { params: { tienda_id: sedeId, anio, mes } })
          .then(r => setConciliacion({
            valor_neto: r.data?.resumen?.valor_neto ?? 0,
            valor_diferencia_total: r.data?.valor_diferencia_total ?? 0,
          }))
          .catch(() => setConciliacion(null))
      )
    } else {
      setConciliacion(null)
    }

    // Descuadres de caja: solo si hay sede seleccionada
    if (sedeId !== null) {
      calls.push(
        api.get('/informes/turnos', { params: { tienda_id: sedeId, fecha_desde: desde, fecha_hasta: hasta } })
          .then(r => setDescuadres({
            con_diferencia: r.data?.totales?.con_diferencia ?? 0,
            n_turnos: r.data?.totales?.n_turnos ?? 0,
          }))
          .catch(() => setDescuadres(null))
      )
    } else {
      setDescuadres(null)
    }

    // Consignaciones pendientes (funciona con o sin sede)
    const consignParams = sedeId !== null ? { tienda_id: sedeId } : {}
    calls.push(
      api.get('/consignaciones/resumen-admin', { params: consignParams })
        .then(r => {
          const filas: ConsignTurno[] = Array.isArray(r.data) ? r.data : []
          const pendientes = filas.filter(f => f.total_consignado < f.esperado_consignar)
          const monto = pendientes.reduce((acc, f) => acc + Math.max(0, f.esperado_consignar - f.total_consignado), 0)
          setConsignPend({ n: pendientes.length, monto })
        })
        .catch(() => setConsignPend(null))
    )

    Promise.all(calls).finally(() => setLoading(false))
  }, [periodo, sedeId])

  useEffect(() => { cargar() }, [cargar])

  // ─── Export CSV ───────────────────────────────────────────────────────────────
  function exportarCSV() {
    const { desde, hasta } = periodoRango(periodo)
    const lines: string[] = [
      `Dashboard Ejecutivo — ${desde} a ${hasta}`,
      '',
      'KPIs',
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
      ...ventasPorSede.map(s => `${s.tienda},${s.total},${s.n_tickets}`),
      '',
      'Ventas por categoría',
      'Categoría,Total,Unidades',
      ...ventasPorCategoria.map(c => `${c.categoria},${c.total},${c.unidades}`),
      '',
      'Top productos',
      'Producto,Unidades,Total',
      ...topProductos.slice(0, 10).map(p => `${p.nombre_producto},${p.unidades},${p.total}`),
      '',
      'Resumen de alertas',
      'Indicador,Valor',
      `Alertas de stock crítico,${alertas.filter(a => a.estado === 'agotado' || a.estado === 'critico').length}`,
      `Lotes por vencer,${lotesVencer.length}`,
      `Compras pendientes,${compras?.total_pendiente ?? 0}`,
      `Conciliación inventario (valor neto),${conciliacion?.valor_neto ?? 'N/A (requiere sede)'}`,
      `Mermas período (unidades),${mermas.reduce((a, m) => a + (m.cantidad ?? 0), 0)}`,
      `Descuadres de caja,${descuadres ? `${descuadres.con_diferencia} de ${descuadres.n_turnos}` : 'N/A (requiere sede)'}`,
      `Consignaciones pendientes,${consignPend ? `${consignPend.n} (${consignPend.monto})` : 'Cargando'}`,
    ]
    const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `dashboard-ejecutivo-${desde}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ─── Derived ──────────────────────────────────────────────────────────────────
  const maxVentaHora = ventasPorHora.length > 0 ? Math.max(...ventasPorHora.map(h => h.total)) : 1
  const maxVentaSede = ventasPorSede.length > 0 ? Math.max(...ventasPorSede.map(s => s.total)) : 1
  const maxVentaCat  = ventasPorCategoria.length > 0 ? Math.max(...ventasPorCategoria.map(c => c.total)) : 1
  const maxTopProd   = topProductos.length > 0 ? Math.max(...topProductos.map(p => p.total)) : 1

  const agotados  = alertas.filter(a => a.estado === 'agotado')
  const criticos  = alertas.filter(a => a.estado === 'critico')

  const catColores: Record<string, string> = {
    bebida: '#5c7a4e',
    pasteleria: '#c08a3e',
    insumo: '#7a6a55',
  }

  // ─── Render ───────────────────────────────────────────────────────────────────
  return (
    <div style={{ fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif', padding: '4px 0 40px', maxWidth: 1100 }}>

      {/* Encabezado */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 16, marginTop: 14 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1a1512', display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
            <BarChart3 size={20} style={{ color: '#5c7a4e' }} />
            Dashboard Ejecutivo
          </h1>
          <p style={{ fontSize: 13, color: '#8b7d6b', margin: '3px 0 0' }}>
            Consolidado multi-sede · indicadores clave del negocio
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

      {/* Filtros */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 18, alignItems: 'center' }}>
        {/* Período */}
        <div style={{ display: 'flex', gap: 6 }}>
          {PERIODOS.map(p => (
            <button
              key={p.key}
              onClick={() => setPeriodo(p.key)}
              style={{
                padding: '6px 14px',
                borderRadius: 20,
                fontSize: 12,
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'all 0.15s',
                border: periodo === p.key ? 'none' : '1px solid #e0d9cc',
                background: periodo === p.key ? '#5c7a4e' : '#fff',
                color: periodo === p.key ? '#fff' : '#4a3728',
              }}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Separador */}
        {sedes.length > 1 && <div style={{ width: 1, height: 20, background: '#e0d9cc' }} />}

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

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 20 }}>
        <KpiCard
          label="Ventas período"
          value={fmt(resumen?.total_ventas ?? 0)}
          sub={`${resumen?.n_tickets ?? 0} tickets`}
          color="#1a6b3a"
        />
        <KpiCard
          label="Ticket promedio"
          value={fmt(resumen?.ticket_promedio ?? 0)}
        />
        <KpiCard
          label="Efectivo"
          value={fmt(resumen?.total_efectivo ?? 0)}
        />
        <KpiCard
          label="Tarjeta"
          value={fmt(resumen?.total_tarjeta ?? 0)}
        />
        <KpiCard
          label="Inventario valorizado"
          value={fmt(invValorizado?.total ?? 0)}
          sub="a costo de compra"
          color="#2d5a9a"
        />
        <KpiCard
          label="Compras pendientes"
          value={fmt(compras?.total_pendiente ?? 0)}
          sub={`de ${fmt(compras?.total_facturado ?? 0)} facturado`}
          color={((compras?.total_pendiente ?? 0) > 0) ? '#b45309' : undefined}
        />
      </div>

      {/* Tarjetas resumen con drill-down */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, marginBottom: 20 }}>
        <ResumenCard
          icon={AlertTriangle}
          label="Stock crítico"
          value={sedeId !== null ? `${agotados.length + criticos.length}` : '—'}
          hint={sedeId !== null ? (agotados.length + criticos.length > 0 ? `${agotados.length} agotados · ${criticos.length} críticos` : 'Sin alertas activas') : 'Elegí una sede'}
          tone={sedeId === null ? 'muted' : (agotados.length + criticos.length > 0 ? 'danger' : 'ok')}
          to="/control-inventario"
        />
        <ResumenCard
          icon={Package}
          label="Lotes por vencer"
          value={`${lotesVencer.length}`}
          hint={lotesVencer.length > 0 ? 'Próximos 30 días' : 'Sin vencimientos próximos'}
          tone={lotesVencer.length > 0 ? 'warn' : 'ok'}
          to="/lotes"
        />
        <ResumenCard
          icon={ShoppingCart}
          label="Pagos pendientes"
          value={compras ? fmt(compras.total_pendiente) : '…'}
          hint={compras ? `de ${fmt(compras.total_facturado)} facturado` : undefined}
          tone={(compras?.total_pendiente ?? 0) > 0 ? 'warn' : 'ok'}
          to="/pagos-proveedores"
        />
        <ResumenCard
          icon={Layers}
          label="Conciliación (mes)"
          value={sedeId !== null ? (conciliacion ? fmt(conciliacion.valor_neto) : '…') : '—'}
          hint={sedeId !== null ? (conciliacion ? (conciliacion.valor_neto === 0 ? 'Sin diferencias' : 'Diferencia neta') : undefined) : 'Elegí una sede'}
          tone={sedeId === null ? 'muted' : (conciliacion === null ? 'muted' : (conciliacion.valor_neto === 0 ? 'ok' : 'danger'))}
          to="/conciliacion-inventario"
        />
        <ResumenCard
          icon={DollarSign}
          label="Mermas período"
          value={`${Math.round(mermas.reduce((a, m) => a + (m.cantidad ?? 0), 0))} u.`}
          hint={mermas.length > 0 ? `${mermas.length} productos` : 'Sin mermas registradas'}
          tone={mermas.length > 0 ? 'warn' : 'ok'}
          to="/informes"
        />
        <ResumenCard
          icon={TrendingUp}
          label="Descuadres caja"
          value={sedeId !== null ? (descuadres ? `${descuadres.con_diferencia}` : '…') : '—'}
          hint={sedeId !== null ? (descuadres ? `de ${descuadres.n_turnos} turnos` : undefined) : 'Elegí una sede'}
          tone={sedeId === null ? 'muted' : (descuadres === null ? 'muted' : (descuadres.con_diferencia > 0 ? 'danger' : 'ok'))}
          to="/informes"
        />
        <ResumenCard
          icon={Store}
          label="Consignaciones pend."
          value={consignPend ? `${consignPend.n}` : '…'}
          hint={consignPend ? (consignPend.n > 0 ? `Faltante: ${fmt(consignPend.monto)}` : 'Al día') : undefined}
          tone={consignPend === null ? 'muted' : (consignPend.n > 0 ? 'warn' : 'ok')}
          to="/consignaciones"
        />
      </div>

      {/* Grid 2 columnas para secciones principales */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16, marginBottom: 16 }}>

        {/* Ventas por hora */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={TrendingUp} label="Ventas por hora" />
          {ventasPorHora.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Sin datos en el período</p>
          ) : (
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 80, paddingBottom: 4 }}>
              {ventasPorHora.map(h => {
                const pct = maxVentaHora > 0 ? (h.total / maxVentaHora) : 0
                const isPico = pct >= 0.8
                return (
                  <div key={h.hora} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                    <div
                      title={`${h.hora}h — ${fmt(h.total)}`}
                      style={{
                        width: '100%', height: `${Math.max(pct * 60, 2)}px`,
                        background: isPico ? '#5c7a4e' : '#c8dbbf',
                        borderRadius: '3px 3px 0 0',
                        minHeight: 2,
                      }}
                    />
                    {[6, 9, 12, 15, 18, 21].includes(h.hora) && (
                      <span style={{ fontSize: 9, color: '#8b7d6b', whiteSpace: 'nowrap' }}>{h.hora}h</span>
                    )}
                  </div>
                )
              })}
            </div>
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

        {/* Ventas por sede */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={Store} label="Ventas por sede" />
          {ventasPorSede.length === 0 ? (
            <p style={{ fontSize: 12, color: '#8b7d6b', textAlign: 'center', padding: '20px 0' }}>Sin sedes activas</p>
          ) : (
            <div>
              {ventasPorSede.map(s => (
                <BarHorizontal
                  key={s.tienda_id}
                  label={s.tienda}
                  value={s.total}
                  max={maxVentaSede}
                  color="#5c7a4e"
                />
              ))}
            </div>
          )}
        </div>

        {/* Top productos */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
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

      </div>

      {/* Fila inferior: Inventario + Compras + Alertas */}
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

        {/* Compras a proveedores */}
        <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
          <SectionTitle icon={ShoppingCart} label="Compras a proveedores" />
          {compras ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
                <div style={{ background: '#f0faf4', border: '1px solid #c8dbbf', borderRadius: 10, padding: '10px 12px' }}>
                  <p style={{ fontSize: 10, color: '#5c7a4e', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 2 }}>Pagado</p>
                  <p style={{ fontSize: 16, fontWeight: 700, color: '#1a6b3a' }}>{fmt(compras.total_pagado)}</p>
                </div>
                <div style={{ background: (compras.total_pendiente > 0) ? '#fff7ed' : '#f5f0e8', border: `1px solid ${compras.total_pendiente > 0 ? '#fbbf24' : '#e0d9cc'}`, borderRadius: 10, padding: '10px 12px' }}>
                  <p style={{ fontSize: 10, color: compras.total_pendiente > 0 ? '#b45309' : '#8b7d6b', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 2 }}>Pendiente</p>
                  <p style={{ fontSize: 16, fontWeight: 700, color: compras.total_pendiente > 0 ? '#b45309' : '#4a3728' }}>{fmt(compras.total_pendiente)}</p>
                </div>
              </div>
              {compras.por_proveedor && compras.por_proveedor.length > 0 && (
                <div>
                  <p style={{ fontSize: 10, fontWeight: 700, color: '#8b7d6b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>Por proveedor</p>
                  {compras.por_proveedor.slice(0, 5).map(p => (
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

        {/* Alertas stock + Lotes por vencer */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

          {/* Alertas stock — solo si hay sede seleccionada */}
          {sedeId !== null && (agotados.length > 0 || criticos.length > 0) && (
            <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
              <SectionTitle icon={AlertTriangle} label="Stock crítico" />
              {agotados.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <p style={{ fontSize: 10, fontWeight: 700, color: '#991b1b', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
                    Agotados ({agotados.length})
                  </p>
                  {agotados.slice(0, 5).map(a => (
                    <div key={a.producto_id} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                      <span style={{ fontSize: 12, color: '#7f1d1d', fontWeight: 500 }}>{a.producto}</span>
                      <span style={{ fontSize: 11, color: '#991b1b', fontWeight: 700 }}>0 / {a.stock_minimo}</span>
                    </div>
                  ))}
                </div>
              )}
              {criticos.length > 0 && (
                <div>
                  <p style={{ fontSize: 10, fontWeight: 700, color: '#b45309', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
                    Críticos ({criticos.length})
                  </p>
                  {criticos.slice(0, 5).map(a => (
                    <div key={a.producto_id} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                      <span style={{ fontSize: 12, color: '#7c2d12', fontWeight: 500 }}>{a.producto}</span>
                      <span style={{ fontSize: 11, color: '#b45309', fontWeight: 700 }}>{a.stock_actual} / {a.stock_minimo}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {sedeId === null && (
            <div style={{ background: '#f5f0e8', border: '1px solid #e0d9cc', borderRadius: 14, padding: '14px 16px' }}>
              <p style={{ fontSize: 12, color: '#8b7d6b', margin: 0 }}>
                Seleccioná una sede para ver alertas de stock en tiempo real.
              </p>
            </div>
          )}

          {/* Lotes por vencer */}
          {lotesVencer.length > 0 && (
            <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
              <SectionTitle icon={AlertTriangle} label="Lotes próximos a vencer" />
              {lotesVencer.slice(0, 6).map((l, idx) => (
                <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, alignItems: 'center' }}>
                  <div style={{ minWidth: 0 }}>
                    <p style={{ fontSize: 12, color: '#2d1f0f', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160, margin: 0 }}>{l.producto}</p>
                    <p style={{ fontSize: 10, color: '#8b7d6b', margin: 0 }}>{l.tienda}</p>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <p style={{ fontSize: 11, color: '#b45309', fontWeight: 600, margin: 0 }}>{l.fecha_vencimiento ? l.fecha_vencimiento.slice(0, 10) : '—'}</p>
                    <p style={{ fontSize: 10, color: '#8b7d6b', margin: 0 }}>{Math.round(l.cantidad_restante)} u.</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Mermas */}
          {mermas.length > 0 && (
            <div style={{ background: '#fff', border: '1px solid #e8e3db', borderRadius: 14, padding: '14px 16px' }}>
              <SectionTitle icon={DollarSign} label="Mermas del período" />
              {mermas.slice(0, 5).map((m, idx) => (
                <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                  <span style={{ fontSize: 12, color: '#4a3728', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '65%' }}>{m.producto}</span>
                  <span style={{ fontSize: 12, color: '#b45309', fontWeight: 600 }}>{Math.round(m.cantidad)} u.</span>
                </div>
              ))}
            </div>
          )}

        </div>

      </div>
    </div>
  )
}
