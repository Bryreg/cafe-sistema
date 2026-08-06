import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import { conMiles, soloDigitos } from '../utils/plata'
import {
  Calculator, Download, Printer, TrendingUp, TrendingDown,
  Wallet, CreditCard, Receipt, CalendarDays, Target, Pencil, Check, X,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface DiaContador {
  fecha: string
  efectivo: number; tarjeta: number; transferencia: number; otros: number
  total: number; acumulado: number; facturas: number; ticket_promedio: number
}
interface Contador {
  anio: number; mes: number
  dias: DiaContador[]
  total_mes: number; total_efectivo: number; total_tarjeta: number
  total_transferencia: number; total_otros: number; total_facturas: number
  dias_con_venta: number; dias_periodo: number; promedio_diario: number; promedio_venta_diaria: number; ticket_promedio_mes: number
  participacion: { efectivo: number; tarjeta: number }
  dia_max: { fecha: string; total: number } | null
  dia_min: { fecha: string; total: number } | null
}
interface Tienda { id: number; nombre: string }

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const fmt = (v: number) => '$' + Math.round(v || 0).toLocaleString('es-CO')
const fmtDia = (iso: string) => {
  const [, m, d] = iso.split('-')
  return `${d}/${m}`
}

// ─── KPI card ─────────────────────────────────────────────────────────────────
function Kpi({ label, value, sub, Icon, tint, delta }: {
  label: string; value: string; sub?: string; Icon: typeof Wallet; tint: string; delta?: number | null
}) {
  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4">
      <div className="flex items-center gap-2 mb-1.5">
        <Icon size={14} style={{ color: tint }} />
        <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400">{label}</p>
      </div>
      <div className="flex items-baseline gap-2 flex-wrap">
        <p className="text-xl font-bold text-gray-800 font-mono leading-none">{value}</p>
        {delta != null && isFinite(delta) && (
          <span className={`text-xs font-bold ${delta >= 0 ? 'text-green-600' : 'text-red-500'}`}>
            {delta >= 0 ? '▲' : '▼'} {Math.abs(delta)}%
          </span>
        )}
      </div>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

// ─── Página ───────────────────────────────────────────────────────────────────
export default function InformeContador() {
  const now = new Date()
  const [anio, setAnio] = useState(now.getFullYear())
  const [mes, setMes] = useState(now.getMonth() + 1)
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(null)
  const [data, setData] = useState<Contador | null>(null)
  const [dataPrev, setDataPrev] = useState<Contador | null>(null)
  const [loading, setLoading] = useState(false)
  // Meta de ventas de la sede (una por tienda, NO por mes): null = aún no cargó.
  const [meta, setMeta] = useState<number | null>(null)
  const [editandoMeta, setEditandoMeta] = useState(false)
  const [metaInput, setMetaInput] = useState('')
  const [savingMeta, setSavingMeta] = useState(false)

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas')
      .then(r => { setTiendas(r.data); setTiendaId(prev => prev ?? (r.data[0]?.id ?? null)) })
      .catch(() => {})
  }, [])

  // La meta depende solo de la sede: cambiar de mes NO la refetchea (el progreso
  // se recalcula contra el total_mes del mes seleccionado).
  useEffect(() => {
    setMeta(null)
    setEditandoMeta(false)
    if (!tiendaId) return
    api.get<{ tienda_id: number; meta: number }>(`/auth/config/meta-ventas/${tiendaId}`)
      .then(r => setMeta(r.data.meta ?? 0))
      .catch(() => setMeta(null))
  }, [tiendaId])

  useEffect(() => {
    if (!tiendaId) return
    setLoading(true)
    // Mes anterior para comparar (diciembre → año-1).
    const prevMes = mes === 1 ? 12 : mes - 1
    const prevAnio = mes === 1 ? anio - 1 : anio
    Promise.all([
      api.get<Contador>('/pos/analytics/contador', { params: { anio, mes, tienda_id: tiendaId } }),
      api.get<Contador>('/pos/analytics/contador', { params: { anio: prevAnio, mes: prevMes, tienda_id: tiendaId } }),
    ])
      .then(([cur, prev]) => { setData(cur.data); setDataPrev(prev.data) })
      .catch(() => { setData(null); setDataPrev(null) })
      .finally(() => setLoading(false))
  }, [anio, mes, tiendaId])

  // Delta % vs mes anterior (null si el mes anterior no tuvo venta → evita dividir por 0).
  const pctDelta = (cur: number, prev: number | undefined | null) =>
    prev && prev > 0 ? Math.round((cur - prev) / prev * 100) : null

  // Guarda la meta con update optimista: se pinta ya y se revierte si el PUT falla.
  const guardarMeta = async () => {
    if (!tiendaId) return
    const nueva = Number(metaInput) || 0
    const anterior = meta
    setMeta(nueva)
    setEditandoMeta(false)
    setSavingMeta(true)
    try {
      await api.put(`/auth/config/meta-ventas/${tiendaId}`, { meta: nueva })
    } catch {
      setMeta(anterior)
    } finally {
      setSavingMeta(false)
    }
  }

  const maxDia = useMemo(() => Math.max(1, ...(data?.dias.map(d => d.total) ?? [1])), [data])
  const maxAcum = useMemo(() => Math.max(1, ...(data?.dias.map(d => d.acumulado) ?? [1])), [data])

  // ── Export CSV (abre en Excel) ──
  const exportarCSV = () => {
    if (!data) return
    const head = ['Dia operativo', 'Efectivo', 'Tarjeta', 'Transferencia', 'Otros', 'Total Diario', 'Acumulado Mes', 'Facturas', 'Ticket Promedio']
    const filas = data.dias.map(d => [d.fecha, d.efectivo, d.tarjeta, d.transferencia, d.otros, d.total, d.acumulado, d.facturas, d.ticket_promedio])
    const totalRow = ['TOTAL', data.total_efectivo, data.total_tarjeta, data.total_transferencia, data.total_otros, data.total_mes, '', data.total_facturas, data.ticket_promedio_mes]
    const csv = [head, ...filas, totalRow].map(r => r.join(';')).join('\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `informe-contador-${anio}-${String(mes).padStart(2, '0')}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const tieneDatos = data && data.dias.length > 0

  return (
    <div className="space-y-4">
      {/* Header + selectores */}
      <div className="flex flex-wrap items-center gap-3 print:hidden">
        <div className="flex items-center gap-2">
          <Calculator size={20} className="text-forest" />
          <h1 className="text-lg font-bold text-gray-800">Informe Contador</h1>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select value={mes} onChange={e => setMes(Number(e.target.value))}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white">
            {MESES.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select value={anio} onChange={e => setAnio(Number(e.target.value))}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white">
            {Array.from({ length: 5 }, (_, i) => now.getFullYear() - i).map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <button onClick={exportarCSV} disabled={!tieneDatos}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white transition-colors">
            <Download size={14} /> Excel
          </button>
          <button onClick={() => window.print()} disabled={!tieneDatos}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-40 text-gray-600 transition-colors">
            <Printer size={14} /> PDF
          </button>
        </div>
      </div>

      {/* Selector de sede */}
      <div className="flex items-center gap-2 flex-wrap print:hidden">
        {tiendas.map(t => (
          <button key={t.id} onClick={() => setTiendaId(t.id)}
            className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${
              tiendaId === t.id ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'
            }`}>{t.nombre}</button>
        ))}
      </div>

      {/* Título impreso */}
      <div className="hidden print:block">
        <h1 className="text-lg font-bold">Informe Contador — {MESES[mes - 1]} {anio}</h1>
        {/* El eje importa para conciliar: el adquirente liquida el datáfono por
            fecha de calendario, y acá las ventas van al día operativo del turno.
            Difieren solo en las ventas hechas pasada la medianoche. */}
        <p className="text-[11px] text-gray-500">
          Agrupado por día operativo (el del turno y su cuadre), no por fecha de calendario.
          La columna Tarjeta puede no coincidir con la fecha de liquidación del datáfono.
        </p>
        <p className="text-sm text-gray-500">{tiendas.find(t => t.id === tiendaId)?.nombre}</p>
      </div>

      {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Calculando consolidado...</p>}

      {!loading && !tieneDatos && (
        <div className="bg-white border border-gray-200 rounded-2xl px-4 py-12 text-center">
          <CalendarDays size={28} className="text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No hay ventas en {MESES[mes - 1]} {anio} para esta sede</p>
        </div>
      )}

      {!loading && tieneDatos && data && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {/* Meta del mes: valor único por sede (no por mes) — el progreso se
                recalcula contra el total del mes seleccionado. */}
            {tiendaId != null && meta != null && (
              <div className="bg-white rounded-2xl border border-gray-200 p-4 col-span-2 lg:col-span-5">
                <div className="flex items-center gap-2 mb-1.5">
                  <Target size={14} style={{ color: '#2d5a3f' }} />
                  <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400">Meta del mes</p>
                  {meta > 0 && !editandoMeta && (
                    <button
                      onClick={() => { setMetaInput(String(Math.round(meta))); setEditandoMeta(true) }}
                      disabled={savingMeta}
                      className="ml-auto p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-40 print:hidden"
                      title="Editar meta">
                      <Pencil size={12} />
                    </button>
                  )}
                </div>
                {editandoMeta || meta === 0 ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    {meta === 0 && !editandoMeta && (
                      <p className="text-sm text-gray-500">Sin meta — definila acá:</p>
                    )}
                    <span className="text-sm text-gray-400">$</span>
                    <input
                      type="text"
                      inputMode="numeric"
                      value={conMiles(metaInput)}
                      onChange={e => setMetaInput(soloDigitos(e.target.value))}
                      placeholder="0"
                      disabled={savingMeta}
                      className="w-36 border border-gray-300 rounded-lg px-2 py-1.5 text-sm text-right font-semibold font-mono focus:outline-none focus:ring-2 focus:ring-green-600 disabled:opacity-40"
                      autoFocus={editandoMeta}
                      onKeyDown={e => { if (e.key === 'Enter') guardarMeta(); if (e.key === 'Escape') setEditandoMeta(false) }}
                    />
                    <button onClick={guardarMeta} disabled={savingMeta}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-semibold bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white transition-colors">
                      <Check size={13} /> Guardar
                    </button>
                    {editandoMeta && (
                      <button onClick={() => setEditandoMeta(false)} disabled={savingMeta}
                        className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 disabled:opacity-40">
                        <X size={13} />
                      </button>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="flex items-baseline gap-3 flex-wrap">
                      <p className="text-xl font-bold text-gray-800 font-mono leading-none">{fmt(meta)}</p>
                      <span className="text-xs font-bold text-gray-600">
                        {Math.round((data.total_mes / meta) * 100)}%
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-2">
                      <div className="flex-1 h-3 rounded-full bg-gray-100 overflow-hidden">
                        <div className="h-full bg-green-500" style={{ width: `${Math.min(100, (data.total_mes / meta) * 100)}%` }} />
                      </div>
                    </div>
                    <p className="text-xs text-gray-400 mt-1">
                      {fmt(data.total_mes)} de {fmt(meta)} en {MESES[mes - 1]}
                      {data.total_mes >= meta ? ' · meta cumplida' : ` · faltan ${fmt(meta - data.total_mes)}`}
                    </p>
                  </>
                )}
              </div>
            )}
            <Kpi label="Total del mes" value={fmt(data.total_mes)} sub={`${data.dias_con_venta} días con venta · vs ${MESES[(mes === 1 ? 12 : mes - 1) - 1]}`} Icon={Receipt} tint="#2d5a3f" delta={pctDelta(data.total_mes, dataPrev?.total_mes)} />
            <Kpi label="Venta diaria (mes)" value={fmt(data.promedio_venta_diaria)} sub={`${data.total_mes ? fmt(data.total_mes) : '$0'} ÷ ${data.dias_periodo} días`} Icon={TrendingUp} tint="#2d5a3f" delta={pctDelta(data.promedio_venta_diaria, dataPrev?.promedio_venta_diaria)} />
            <Kpi label="Promedio por día con venta" value={fmt(data.promedio_diario)} sub={`${data.dias_con_venta} días`} Icon={TrendingUp} tint="#5b8def" delta={pctDelta(data.promedio_diario, dataPrev?.promedio_diario)} />
            <Kpi label="Ticket promedio" value={fmt(data.ticket_promedio_mes)} sub={`${data.total_facturas} facturas`} Icon={Receipt} tint="#c08a3e" delta={pctDelta(data.ticket_promedio_mes, dataPrev?.ticket_promedio_mes)} />
            <Kpi label="Efectivo / Tarjeta" value={`${data.participacion.efectivo}% / ${data.participacion.tarjeta}%`} Icon={Wallet} tint="#2a8d8a" />
          </div>

          {/* Día mayor / menor + participación */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4 flex items-center gap-3">
              <TrendingUp size={20} className="text-green-600 shrink-0" />
              <div><p className="text-[11px] font-bold uppercase tracking-wide text-gray-400">Día de mayor venta</p>
                <p className="text-sm font-bold text-gray-800">{data.dia_max ? `${fmtDia(data.dia_max.fecha)} · ${fmt(data.dia_max.total)}` : '—'}</p></div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4 flex items-center gap-3">
              <TrendingDown size={20} className="text-red-500 shrink-0" />
              <div><p className="text-[11px] font-bold uppercase tracking-wide text-gray-400">Día de menor venta</p>
                <p className="text-sm font-bold text-gray-800">{data.dia_min ? `${fmtDia(data.dia_min.fecha)} · ${fmt(data.dia_min.total)}` : '—'}</p></div>
            </div>
            {/* Participación por medio de pago */}
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-2">Participación por medio</p>
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Wallet size={12} className="text-green-600 shrink-0" />
                  <div className="flex-1 h-3 rounded-full bg-gray-100 overflow-hidden">
                    <div className="h-full bg-green-500" style={{ width: `${data.participacion.efectivo}%` }} />
                  </div>
                  <span className="text-xs font-bold text-gray-600 w-10 text-right">{data.participacion.efectivo}%</span>
                </div>
                <div className="flex items-center gap-2">
                  <CreditCard size={12} className="text-blue-500 shrink-0" />
                  <div className="flex-1 h-3 rounded-full bg-gray-100 overflow-hidden">
                    <div className="h-full bg-blue-500" style={{ width: `${data.participacion.tarjeta}%` }} />
                  </div>
                  <span className="text-xs font-bold text-gray-600 w-10 text-right">{data.participacion.tarjeta}%</span>
                </div>
              </div>
            </div>
          </div>

          {/* Tendencia diaria (barras) + Evolución acumulada (línea) */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-3">Tendencia diaria</p>
              {/* La columna necesita h-full SÍ o SÍ. El contenedor trae items-end,
                  que anula el stretch por defecto: sin h-full la columna toma la
                  altura de su contenido (cero) y el height:% de la barra se calcula
                  contra un padre de altura auto — que en CSS no resuelve. Resultado:
                  TODAS las barras quedaban en el minHeight de 3px, con cualquier
                  dato. El gráfico se veía plano aunque las ventas no lo fueran. */}
              <div className="flex items-end gap-[3px] h-32">
                {data.dias.map(d => (
                  <div key={d.fecha} className="flex-1 h-full flex flex-col items-center justify-end group relative" title={`${fmtDia(d.fecha)} · ${fmt(d.total)}`}>
                    <div className="w-full rounded-t transition-opacity hover:opacity-80" style={{ height: `${(d.total / maxDia) * 100}%`, minHeight: 3, background: '#2d5a3f' }} />
                  </div>
                ))}
              </div>
              <div className="flex justify-between mt-1 text-[9px] text-gray-400">
                <span>{data.dias[0] && fmtDia(data.dias[0].fecha)}</span>
                <span>{data.dias.length > 0 && fmtDia(data.dias[data.dias.length - 1].fecha)}</span>
              </div>
            </div>

            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-3">Evolución acumulada</p>
              <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="w-full h-32">
                <polyline
                  fill="none" stroke="#2d5a3f" strokeWidth="0.8" strokeLinejoin="round"
                  points={data.dias.map((d, i) => `${(i / Math.max(1, data.dias.length - 1)) * 100},${40 - (d.acumulado / maxAcum) * 38}`).join(' ')}
                />
              </svg>
              <p className="text-xs text-gray-400 mt-1 text-right">Acumulado: <span className="font-bold text-gray-700">{fmt(data.total_mes)}</span></p>
            </div>
          </div>

          {/* Tabla diaria */}
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-[11px] uppercase tracking-wide text-gray-400">
                    <th className="text-left px-3 py-2 font-bold" title="Día operativo del turno, no fecha de calendario">Día operativo</th>
                    <th className="text-right px-3 py-2 font-bold">Efectivo</th>
                    <th className="text-right px-3 py-2 font-bold">Tarjeta</th>
                    <th className="text-right px-3 py-2 font-bold hidden sm:table-cell">Transf.</th>
                    <th className="text-right px-3 py-2 font-bold hidden sm:table-cell">Otros</th>
                    <th className="text-right px-3 py-2 font-bold">Total</th>
                    <th className="text-right px-3 py-2 font-bold hidden md:table-cell">Acumulado</th>
                    <th className="text-right px-3 py-2 font-bold">Fact.</th>
                    <th className="text-right px-3 py-2 font-bold hidden md:table-cell">Ticket prom.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 font-mono">
                  {data.dias.map(d => (
                    <tr key={d.fecha} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-sans font-medium text-gray-700">{fmtDia(d.fecha)}</td>
                      <td className="px-3 py-2 text-right text-green-700">{fmt(d.efectivo)}</td>
                      <td className="px-3 py-2 text-right text-blue-600">{fmt(d.tarjeta)}</td>
                      <td className="px-3 py-2 text-right text-gray-400 hidden sm:table-cell">{fmt(d.transferencia)}</td>
                      <td className="px-3 py-2 text-right text-gray-400 hidden sm:table-cell">{fmt(d.otros)}</td>
                      <td className="px-3 py-2 text-right font-bold text-gray-800">{fmt(d.total)}</td>
                      <td className="px-3 py-2 text-right text-gray-500 hidden md:table-cell">{fmt(d.acumulado)}</td>
                      <td className="px-3 py-2 text-right text-gray-500">{d.facturas}</td>
                      <td className="px-3 py-2 text-right text-gray-500 hidden md:table-cell">{fmt(d.ticket_promedio)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-gray-50 font-mono font-bold text-gray-800 border-t-2 border-gray-200">
                    <td className="px-3 py-2.5 font-sans">TOTAL</td>
                    <td className="px-3 py-2.5 text-right text-green-700">{fmt(data.total_efectivo)}</td>
                    <td className="px-3 py-2.5 text-right text-blue-600">{fmt(data.total_tarjeta)}</td>
                    <td className="px-3 py-2.5 text-right text-gray-400 hidden sm:table-cell">{fmt(data.total_transferencia)}</td>
                    <td className="px-3 py-2.5 text-right text-gray-400 hidden sm:table-cell">{fmt(data.total_otros)}</td>
                    <td className="px-3 py-2.5 text-right">{fmt(data.total_mes)}</td>
                    <td className="px-3 py-2.5 text-right hidden md:table-cell" />
                    <td className="px-3 py-2.5 text-right">{data.total_facturas}</td>
                    <td className="px-3 py-2.5 text-right hidden md:table-cell">{fmt(data.ticket_promedio_mes)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
