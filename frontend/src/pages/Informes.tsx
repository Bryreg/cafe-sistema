import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { BarChart2, Trash2, Package, ChevronDown, ChevronUp, UserCheck, Clock, AlertTriangle, Users, Download } from 'lucide-react'
import DifferenceBadge from '../components/DifferenceBadge'

interface Sede { id: number; nombre: string }

// ─── Exportar Excel (lazy-load SheetJS) ──────────────────────────────────────
async function exportarExcel(nombre: string, cabeceras: string[], filas: (string | number | null)[][]) {
  const XLSX = await import('xlsx')
  const ws = XLSX.utils.aoa_to_sheet([cabeceras, ...filas])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Datos')
  XLSX.writeFile(wb, `${nombre}.xlsx`)
}

function BtnExcel({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white transition-colors"
      style={{ background: 'oklch(48% 0.15 155)' }}
      title="Descargar Excel"
    >
      <Download size={14} /> Excel
    </button>
  )
}

type Tab = 'ventas' | 'mermas' | 'inventario' | 'cuadres' | 'turnos' | 'rotacion' | 'baristas'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
const fmtN = (v: number, dec = 2) => v.toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec })

function hoy() {
  return new Date().toISOString().slice(0, 10)
}
function inicioMes() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

// ─── Ventas ──────────────────────────────────────────────────────────────────
interface FilaVenta { fecha: string; venta_total: number; nota_credito: number; vales: number; tarjetas: number; efectivo: number; n_registros: number }
interface TotalesVenta { venta_total: number; nota_credito: number; vales: number; tarjetas: number; efectivo: number; n_registros: number }

function TabVentas({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaVenta[]>([])
  const [totales, setTotales] = useState<TotalesVenta | null>(null)
  const [loading, setLoading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/ventas', { params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta } })
      setFilas(data.filas)
      setTotales(data.totales)
    } finally { setLoading(false) }
  }

  const exportar = () => exportarExcel(
    `ventas_${desde}_${hasta}`,
    ['Fecha', 'Venta Total', 'Nota Crédito', 'Vales', 'Tarjetas', 'Efectivo', 'Registros'],
    [
      ...filas.map(f => [f.fecha, f.venta_total, f.nota_credito, f.vales, f.tarjetas, f.efectivo, f.n_registros]),
      ...(totales ? [['TOTAL', totales.venta_total, totales.nota_credito, totales.vales, totales.tarjetas, totales.efectivo, totales.n_registros]] : []),
    ]
  )

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {filas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Fecha</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Venta total</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">N. crédito</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Vales</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Tarjetas</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Efectivo</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filas.map(f => (
                  <tr key={f.fecha} className="hover:bg-gray-50">
                    <td className="px-4 py-2.5 font-medium text-gray-700">{f.fecha}</td>
                    <td className="px-4 py-2.5 text-right font-bold text-gray-800">{fmt(f.venta_total)}</td>
                    <td className="px-4 py-2.5 text-right text-red-600">{f.nota_credito > 0 ? fmt(f.nota_credito) : '—'}</td>
                    <td className="px-4 py-2.5 text-right text-orange-600">{f.vales > 0 ? fmt(f.vales) : '—'}</td>
                    <td className="px-4 py-2.5 text-right text-blue-600">{f.tarjetas > 0 ? fmt(f.tarjetas) : '—'}</td>
                    <td className="px-4 py-2.5 text-right text-green-700 font-semibold">{fmt(f.efectivo)}</td>
                  </tr>
                ))}
              </tbody>
              {totales && (
                <tfoot>
                  <tr className="bg-amber-50 border-t-2 border-amber-200 font-bold">
                    <td className="px-4 py-2.5 text-xs text-amber-700 uppercase">Total ({totales.n_registros} registros)</td>
                    <td className="px-4 py-2.5 text-right text-amber-800">{fmt(totales.venta_total)}</td>
                    <td className="px-4 py-2.5 text-right text-red-700">{fmt(totales.nota_credito)}</td>
                    <td className="px-4 py-2.5 text-right text-orange-700">{fmt(totales.vales)}</td>
                    <td className="px-4 py-2.5 text-right text-blue-700">{fmt(totales.tarjetas)}</td>
                    <td className="px-4 py-2.5 text-right text-green-800">{fmt(totales.efectivo)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}

      {filas.length === 0 && totales && (
        <p className="text-sm text-gray-400 text-center py-6">Sin registros en el período seleccionado.</p>
      )}
    </div>
  )
}

// ─── Mermas ──────────────────────────────────────────────────────────────────
interface DetalleItem { fecha: string; cantidad: number; motivo: string }
interface FilaMerma { producto_id: number; producto: string; unidad: string; total_cantidad: number; n_registros: number; detalle: DetalleItem[] }

function TabMermas({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaMerma[] | null>(null)
  const [kpi, setKpi] = useState<KpiMermas | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const cargar = async () => {
    setLoading(true)
    try {
      const params = { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta }
      const [detRes, kpiRes] = await Promise.all([
        api.get('/informes/mermas', { params }),
        api.get('/informes/kpi-mermas', { params }),
      ])
      setFilas(detRes.data.filas ?? [])
      setKpi(kpiRes.data)
      setExpanded(new Set())
    } finally { setLoading(false) }
  }

  const toggle = (id: number) => setExpanded(prev => {
    const s = new Set(prev)
    s.has(id) ? s.delete(id) : s.add(id)
    return s
  })

  const exportar = () => {
    if (!filas) return
    const rows: (string | number | null)[][] = []
    for (const f of filas) {
      rows.push([f.producto, f.unidad, f.total_cantidad, f.n_registros, '', ''])
      for (const d of f.detalle) rows.push(['', '', '', '', d.fecha, d.cantidad, d.motivo])
    }
    exportarExcel(`mermas_${desde}_${hasta}`,
      ['Producto', 'Unidad', 'Total cantidad', 'Registros', 'Fecha detalle', 'Cantidad detalle', 'Motivo'],
      rows)
  }

  return (
    <div className="space-y-4">
      {/* Filtro de fechas */}
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas && filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {/* KPIs */}
      {kpi && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-400 mb-1">Registros de merma</p>
              <p className="text-2xl font-bold font-mono text-gray-800">{kpi.total_registros}</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-400 mb-1">Ventas del período</p>
              <p className="text-xl font-bold font-mono text-gray-800">{fmt(kpi.total_ventas)}</p>
            </div>
          </div>

          {Object.keys(kpi.por_tipo).length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Por tipo</p>
              <div className="space-y-2">
                {Object.entries(kpi.por_tipo).map(([tipo, v]) => (
                  <div key={tipo} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full" style={{ background: TIPO_COLOR[tipo] || '#6b7280' }} />
                      <span className="text-sm font-medium text-gray-700">{TIPO_LABEL[tipo] || tipo}</span>
                    </div>
                    <div className="flex items-center gap-4 text-sm">
                      <span className="text-gray-400">{v.n_productos} prod.</span>
                      <span className="font-bold text-gray-800">{v.n} registros</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {kpi.top_productos.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-100">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Top productos con más mermas</p>
              </div>
              <div className="divide-y divide-gray-50">
                {kpi.top_productos.map((p, i) => (
                  <div key={i} className="px-4 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-300 font-mono w-4">{i + 1}</span>
                      <div>
                        <p className="text-sm font-medium text-gray-800">{p.nombre}</p>
                        <span className="text-xs px-1.5 py-0.5 rounded font-medium"
                          style={{ background: TIPO_COLOR[p.tipo] + '22', color: TIPO_COLOR[p.tipo] }}>
                          {TIPO_LABEL[p.tipo] || p.tipo}
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-bold text-gray-800 font-mono">{fmtN(p.cantidad, 0)} {p.unidad}</p>
                      <p className="text-xs text-gray-400">{p.n} {p.n === 1 ? 'registro' : 'registros'}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Detalle por producto */}
      {filas !== null && filas.length > 0 && (
        <>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Detalle por producto</p>
          <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
            {filas.map(f => (
              <div key={f.producto_id}>
                <button onClick={() => toggle(f.producto_id)}
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 text-left">
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-gray-800">{f.producto}</p>
                    <p className="text-xs text-gray-400">{f.n_registros} {f.n_registros === 1 ? 'registro' : 'registros'}</p>
                  </div>
                  <span className="text-sm font-bold text-red-600">{fmtN(f.total_cantidad, 0)} {f.unidad}</span>
                  {expanded.has(f.producto_id) ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                </button>
                {expanded.has(f.producto_id) && (
                  <div className="bg-gray-50 border-t border-gray-100 divide-y divide-gray-100">
                    {f.detalle.map((d, i) => (
                      <div key={i} className="flex items-center gap-3 px-6 py-2">
                        <p className="text-xs text-gray-400 w-36 shrink-0">{d.fecha}</p>
                        <p className="text-xs font-semibold text-gray-700 w-20 shrink-0">{fmtN(d.cantidad, 0)} {f.unidad}</p>
                        <p className="text-xs text-gray-500 truncate">{d.motivo}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {filas !== null && filas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin mermas en el período.</p>
      )}
    </div>
  )
}

// ─── Inventario consumido ─────────────────────────────────────────────────────
interface FilaConsumo { producto_id: number; producto: string; unidad: string; total_salida: number; n_movimientos: number; detalle: DetalleItem[] }

function TabInventario({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaConsumo[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/inventario-consumido', { params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta } })
      setFilas(data.filas ?? [])
      setExpanded(new Set())
    } finally { setLoading(false) }
  }

  const toggle = (id: number) => setExpanded(prev => {
    const s = new Set(prev)
    s.has(id) ? s.delete(id) : s.add(id)
    return s
  })

  const exportar = () => {
    if (!filas) return
    const rows: (string | number | null)[][] = []
    for (const f of filas) {
      rows.push([f.producto, f.unidad, f.total_salida, f.n_movimientos, '', '', ''])
      for (const d of f.detalle) rows.push(['', '', '', '', d.fecha, d.cantidad, d.motivo || ''])
    }
    exportarExcel(`inventario_consumido_${desde}_${hasta}`,
      ['Producto', 'Unidad', 'Total salida', 'Movimientos', 'Fecha detalle', 'Cantidad detalle', 'Motivo'],
      rows)
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas && filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {filas !== null && filas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {filas.map(f => (
            <div key={f.producto_id}>
              <button onClick={() => toggle(f.producto_id)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 text-left">
                <div className="flex-1">
                  <p className="text-sm font-semibold text-gray-800">{f.producto}</p>
                  <p className="text-xs text-gray-400">{f.n_movimientos} {f.n_movimientos === 1 ? 'movimiento' : 'movimientos'}</p>
                </div>
                <span className="text-sm font-bold text-blue-600">{fmtN(f.total_salida)} {f.unidad}</span>
                {expanded.has(f.producto_id) ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
              </button>
              {expanded.has(f.producto_id) && (
                <div className="bg-gray-50 border-t border-gray-100 divide-y divide-gray-100">
                  {f.detalle.map((d, i) => (
                    <div key={i} className="flex items-center gap-3 px-6 py-2">
                      <p className="text-xs text-gray-400 w-36 shrink-0">{d.fecha}</p>
                      <p className="text-xs font-semibold text-gray-700 w-20 shrink-0">{fmtN(d.cantidad)} {f.unidad}</p>
                      <p className="text-xs text-gray-500 truncate">{d.motivo || '—'}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {filas !== null && filas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin movimientos en el período.</p>
      )}
    </div>
  )
}

// ─── Cuadres de llegada ───────────────────────────────────────────────────────
interface FilaEntrega {
  id: number; fecha_hora: string; usuario: string
  efectivo_esperado: number; efectivo_real: number; diferencia_efectivo: number
  ventas_tarjeta_bold: number; diferencia_tarjeta: number; imagen_url: string | null
}
interface TotalesEntrega { n_entregas: number; con_diferencia_efectivo: number; con_diferencia_tarjeta: number }

function TabCuadres({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaEntrega[] | null>(null)
  const [totales, setTotales] = useState<TotalesEntrega | null>(null)
  const [loading, setLoading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/entregas', { params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta } })
      setFilas(data.filas)
      setTotales(data.totales)
    } finally { setLoading(false) }
  }

  const exportar = () => {
    if (!filas) return
    exportarExcel(`cuadres_llegada_${desde}_${hasta}`,
      ['Fecha/Hora', 'Barista', 'Efectivo esperado', 'Efectivo real', 'Diferencia efectivo', 'Total Bold', 'Diferencia Bold'],
      filas.map(f => [f.fecha_hora, f.usuario, f.efectivo_esperado, f.efectivo_real, f.diferencia_efectivo, f.ventas_tarjeta_bold, f.diferencia_tarjeta]))
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas && filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {totales && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Total cuadres</p>
            <p className="text-lg font-bold text-gray-800">{totales.n_entregas}</p>
          </div>
          <div className={`border rounded-xl p-3 text-center ${totales.con_diferencia_efectivo > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
            <p className="text-xs text-gray-400">Diff. efectivo</p>
            <p className={`text-lg font-bold ${totales.con_diferencia_efectivo > 0 ? 'text-red-700' : 'text-green-700'}`}>{totales.con_diferencia_efectivo}</p>
          </div>
          <div className={`border rounded-xl p-3 text-center ${totales.con_diferencia_tarjeta > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
            <p className="text-xs text-gray-400">Diff. Bold</p>
            <p className={`text-lg font-bold ${totales.con_diferencia_tarjeta > 0 ? 'text-red-700' : 'text-green-700'}`}>{totales.con_diferencia_tarjeta}</p>
          </div>
        </div>
      )}

      {filas !== null && filas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="divide-y divide-gray-50">
            {filas.map(f => (
              <div key={f.id} className="px-4 py-3 flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-400">{f.fecha_hora}</p>
                  <p className="text-sm font-semibold text-gray-700">{f.usuario}</p>
                  <p className="text-xs text-gray-500">
                    Real: <span className="font-semibold text-gray-800">{fmt(f.efectivo_real)}</span>
                    {' '}· esp: {fmt(f.efectivo_esperado)}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <DifferenceBadge diferencia={f.diferencia_efectivo} />
                  {f.diferencia_tarjeta !== 0 && (
                    <span className="text-xs text-red-600 font-semibold">
                      Bold Δ{f.diferencia_tarjeta > 0 ? '+' : ''}{fmt(f.diferencia_tarjeta)}
                    </span>
                  )}
                  {f.imagen_url && (
                    <a href={f.imagen_url} target="_blank" rel="noreferrer"
                      className="text-xs text-blue-500 hover:underline">foto</a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {filas !== null && filas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin cuadres de llegada en el período.</p>
      )}
    </div>
  )
}

// ─── Turnos ───────────────────────────────────────────────────────────────────
interface FilaTurno {
  id: number; fecha_apertura: string; fecha_cierre: string
  usuario_apertura: string; usuario_cierre: string
  base_real: number; total_ventas: number; total_efectivo: number; total_tarjeta: number
  diferencia_cierre: number; diferencia_tarjeta: number; justificacion_cierre: string | null
}
interface TotalesTornos {
  n_turnos: number; total_ventas: number; total_efectivo: number; total_tarjeta: number; con_diferencia: number
}

function TabTurnos({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaTurno[] | null>(null)
  const [totales, setTotales] = useState<TotalesTornos | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/turnos', { params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta } })
      setFilas(data.filas)
      setTotales(data.totales)
      setExpanded(new Set())
    } finally { setLoading(false) }
  }

  const toggle = (id: number) => setExpanded(prev => {
    const s = new Set(prev)
    s.has(id) ? s.delete(id) : s.add(id)
    return s
  })

  const exportar = () => {
    if (!filas) return
    exportarExcel(`turnos_${desde}_${hasta}`,
      ['Apertura', 'Cierre', 'Abrió', 'Cerró', 'Base real', 'Total ventas', 'Efectivo', 'Tarjeta', 'Diff. cierre', 'Diff. Bold', 'Justificación'],
      filas.map(f => [f.fecha_apertura, f.fecha_cierre, f.usuario_apertura, f.usuario_cierre,
        f.base_real, f.total_ventas, f.total_efectivo, f.total_tarjeta,
        f.diferencia_cierre, f.diferencia_tarjeta, f.justificacion_cierre ?? '']))
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas && filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {totales && totales.n_turnos > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Turnos</p>
            <p className="text-lg font-bold text-gray-800">{totales.n_turnos}</p>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Ventas totales</p>
            <p className="text-base font-bold text-gray-800">{fmt(totales.total_ventas)}</p>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Efectivo</p>
            <p className="text-base font-bold text-green-700">{fmt(totales.total_efectivo)}</p>
          </div>
          <div className={`border rounded-xl p-3 text-center ${totales.con_diferencia > 0 ? 'bg-red-50 border-red-200' : 'bg-white border-gray-200'}`}>
            <p className="text-xs text-gray-400">Con diferencia</p>
            <p className={`text-lg font-bold ${totales.con_diferencia > 0 ? 'text-red-700' : 'text-green-700'}`}>{totales.con_diferencia}</p>
          </div>
        </div>
      )}

      {filas !== null && filas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {filas.map(f => (
            <div key={f.id}>
              <button onClick={() => toggle(f.id)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 text-left">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-400">{f.fecha_apertura} → {f.fecha_cierre}</p>
                  <p className="text-sm font-semibold text-gray-700 truncate">{f.usuario_apertura}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-sm font-bold text-gray-800">{fmt(f.total_ventas)}</span>
                  {f.diferencia_cierre !== 0
                    ? <span className="text-xs font-bold text-red-600">Δ{fmt(f.diferencia_cierre)}</span>
                    : <span className="text-xs font-bold text-green-600">✓</span>
                  }
                  {expanded.has(f.id) ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                </div>
              </button>
              {expanded.has(f.id) && (
                <div className="bg-gray-50 border-t border-gray-100 px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                  <div><span className="text-gray-400">Base real:</span> <span className="font-semibold">{fmt(f.base_real)}</span></div>
                  <div><span className="text-gray-400">Efectivo:</span> <span className="font-semibold text-green-700">{fmt(f.total_efectivo)}</span></div>
                  <div><span className="text-gray-400">Tarjeta:</span> <span className="font-semibold text-blue-700">{fmt(f.total_tarjeta)}</span></div>
                  <div><span className="text-gray-400">Diff. Bold:</span> <span className={`font-semibold ${f.diferencia_tarjeta !== 0 ? 'text-red-600' : 'text-green-600'}`}>{f.diferencia_tarjeta !== 0 ? fmt(f.diferencia_tarjeta) : '✓'}</span></div>
                  <div><span className="text-gray-400">Cierre:</span> <span className="font-semibold">{f.usuario_cierre}</span></div>
                  {f.justificacion_cierre && (
                    <div className="col-span-2"><span className="text-gray-400">Justif.:</span> <span className="italic text-gray-600">{f.justificacion_cierre}</span></div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {filas !== null && filas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin turnos cerrados en el período.</p>
      )}
    </div>
  )
}

// ─── KPI Mermas (tipos y colores, usados en TabMermas) ────────────────────────
interface KpiMermas {
  total_registros: number; total_ventas: number; tiene_ventas: boolean
  por_tipo: Record<string, { n: number; n_productos: number }>
  top_productos: { nombre: string; unidad: string; n: number; cantidad: number; tipo: string }[]
}

const TIPO_COLOR: Record<string, string> = { consumo: '#ea580c', traslado: '#2563eb', daño: '#dc2626' }
const TIPO_LABEL: Record<string, string> = { consumo: 'Consumo', traslado: 'Traslado', daño: 'Daño' }

// ─── Rotación ─────────────────────────────────────────────────────────────────
interface FilaRotacion {
  producto_id: number; producto: string; categoria: string; unidad: string
  stock_actual: number; stock_minimo: number; entradas: number; salidas: number
  rotacion: number | null; estado: string; alerta_min: boolean
}
interface ResumenRotacion { activos: number; estancados: number; sin_movimiento: number; agotados: number; bajo_minimo: number }

const ESTADO_CFG: Record<string, { label: string; bg: string; text: string }> = {
  activo:          { label: 'Activo',         bg: 'oklch(93% 0.015 155)', text: 'oklch(30% 0.10 155)' },
  estancado:       { label: 'Estancado',       bg: 'oklch(95% 0.015 60)',  text: 'oklch(38% 0.12 55)'  },
  agotado:         { label: 'Agotado',         bg: 'oklch(96% 0.015 20)',  text: 'oklch(38% 0.16 25)'  },
  sin_movimiento:  { label: 'Sin movimiento',  bg: 'oklch(95% 0.005 60)',  text: 'oklch(55% 0.01 60)'  },
}

function TabRotacion({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaRotacion[] | null>(null)
  const [resumen, setResumen] = useState<ResumenRotacion | null>(null)
  const [filtroEstado, setFiltroEstado] = useState<string>('todos')
  const [loading, setLoading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/rotacion', { params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta } })
      setFilas(data.filas)
      setResumen(data.resumen)
    } finally { setLoading(false) }
  }

  const filasFiltradas = filas?.filter(f => filtroEstado === 'todos' || f.estado === filtroEstado) ?? []

  const exportar = () => {
    if (!filas) return
    exportarExcel(`rotacion_${desde}_${hasta}`,
      ['Producto', 'Categoría', 'Unidad', 'Stock actual', 'Stock mínimo', 'Entradas', 'Salidas', 'Rotación', 'Estado'],
      filas.map(f => [f.producto, f.categoria, f.unidad, f.stock_actual, f.stock_minimo,
        f.entradas, f.salidas, f.rotacion ?? '', f.estado]))
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50"
          style={{ background: 'oklch(48% 0.12 155)' }}>
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas && filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {resumen && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { key: 'activos',        label: 'Activos',        val: resumen.activos,        color: 'text-green-700' },
            { key: 'estancados',     label: 'Estancados',     val: resumen.estancados,     color: resumen.estancados > 0 ? 'text-orange-600' : 'text-gray-800' },
            { key: 'sin_movimiento', label: 'Sin movimiento', val: resumen.sin_movimiento, color: 'text-gray-500' },
            { key: 'bajo_minimo',    label: 'Bajo mínimo',    val: resumen.bajo_minimo,    color: resumen.bajo_minimo > 0 ? 'text-red-600' : 'text-gray-800' },
          ].map(({ key, label, val, color }) => (
            <button key={key}
              onClick={() => setFiltroEstado(filtroEstado === key ? 'todos' : key)}
              className={`bg-white border rounded-xl p-3 text-center transition-all ${filtroEstado === key ? 'border-gray-400' : 'border-gray-200'}`}>
              <p className="text-xs text-gray-400">{label}</p>
              <p className={`text-lg font-bold font-mono ${color}`}>{val}</p>
            </button>
          ))}
        </div>
      )}

      {filas !== null && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-400 uppercase">Producto</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Stock</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Entradas</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Salidas</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Rotación</th>
                  <th className="px-3 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filasFiltradas.length === 0 && (
                  <tr><td colSpan={6} className="text-center text-sm text-gray-400 py-6">Sin productos con este filtro.</td></tr>
                )}
                {filasFiltradas.map(f => {
                  const cfg = ESTADO_CFG[f.estado] || ESTADO_CFG.sin_movimiento
                  return (
                    <tr key={f.producto_id} className="hover:bg-gray-50">
                      <td className="px-4 py-2.5">
                        <p className="font-medium text-gray-800 text-sm">{f.producto}</p>
                        <p className="text-xs text-gray-400">{f.unidad}</p>
                      </td>
                      <td className={`px-3 py-2.5 text-right font-mono font-bold text-sm ${f.alerta_min ? 'text-red-600' : 'text-gray-700'}`}>
                        {fmtN(f.stock_actual, 0)}
                        {f.alerta_min && <AlertTriangle size={10} className="inline ml-1 text-red-500" />}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-sm text-green-700">{fmtN(f.entradas, 0)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-sm text-blue-700">{fmtN(f.salidas, 0)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-sm text-gray-600">
                        {f.rotacion !== null ? `${f.rotacion}x` : '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="text-xs px-1.5 py-0.5 rounded-md font-semibold whitespace-nowrap"
                          style={{ background: cfg.bg, color: cfg.text }}>
                          {cfg.label}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Baristas ─────────────────────────────────────────────────────────────────
interface FilaBarista {
  usuario_id: number; nombre: string
  n_recibos: number; n_cierres: number
  n_diff_efectivo: number; n_diff_tarjeta: number
  suma_diff_efectivo: number; peor_diferencia: number
  ultimo_cuadre: string | null
}
interface TotalesBaristas { n_baristas: number; total_cuadres: number; con_diferencia: number }

function TabBaristas({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaBarista[] | null>(null)
  const [totales, setTotales] = useState<TotalesBaristas | null>(null)
  const [loading, setLoading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/baristas', { params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta } })
      setFilas(data.filas)
      setTotales(data.totales)
    } finally { setLoading(false) }
  }

  const exportar = () => {
    if (!filas) return
    exportarExcel(`baristas_${desde}_${hasta}`,
      ['Barista', 'Llegadas', 'Cierres', 'Total cuadres', 'Cuadres c/diff', '% con diff', 'Suma diferencias', 'Peor diferencia', 'Diff Bold', 'Último cuadre'],
      filas.map(f => {
        const total = f.n_recibos + f.n_cierres
        const pct = total > 0 ? Math.round((f.n_diff_efectivo / total) * 100) : 0
        return [f.nombre, f.n_recibos, f.n_cierres, total, f.n_diff_efectivo, pct,
          f.suma_diff_efectivo, f.peor_diferencia, f.n_diff_tarjeta, f.ultimo_cuadre ?? '']
      }))
  }

  const totalCuadres = (f: FilaBarista) => f.n_recibos + f.n_cierres
  const pctDiff = (f: FilaBarista) => totalCuadres(f) > 0
    ? Math.round((f.n_diff_efectivo / totalCuadres(f)) * 100)
    : 0

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas && filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {totales && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Baristas</p>
            <p className="text-lg font-bold text-gray-800">{totales.n_baristas}</p>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Total cuadres</p>
            <p className="text-lg font-bold text-gray-800">{totales.total_cuadres}</p>
          </div>
          <div className={`border rounded-xl p-3 text-center ${totales.con_diferencia > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
            <p className="text-xs text-gray-400">Con diferencias</p>
            <p className={`text-lg font-bold ${totales.con_diferencia > 0 ? 'text-red-700' : 'text-green-700'}`}>{totales.con_diferencia}</p>
          </div>
        </div>
      )}

      {filas !== null && filas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {filas.map((f, i) => (
            <div key={f.usuario_id} className="px-4 py-3 flex items-center gap-3">
              <span className="text-sm font-mono text-gray-300 w-5 shrink-0">{i + 1}</span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-800">{f.nombre}</p>
                <p className="text-xs text-gray-400">
                  {f.n_recibos} llegadas · {f.n_cierres} cierres
                  {f.ultimo_cuadre && <span> · último {f.ultimo_cuadre}</span>}
                </p>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                {f.n_diff_efectivo === 0 ? (
                  <span className="text-xs font-bold text-green-600 bg-green-50 px-2 py-0.5 rounded-full">Sin diferencias</span>
                ) : (
                  <>
                    <span className="text-xs font-bold text-red-600 bg-red-50 px-2 py-0.5 rounded-full">
                      {f.n_diff_efectivo} diff · {pctDiff(f)}%
                    </span>
                    <span className="text-xs text-gray-500">
                      Σ {fmt(f.suma_diff_efectivo)} · peor {fmt(f.peor_diferencia)}
                    </span>
                  </>
                )}
                {f.n_diff_tarjeta > 0 && (
                  <span className="text-xs text-blue-500">{f.n_diff_tarjeta} diff Bold</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {filas !== null && filas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin cuadres registrados en el período.</p>
      )}
    </div>
  )
}


// ─── Página principal ─────────────────────────────────────────────────────────
export default function Informes() {
  const { user } = useAuth()
  const isAdmin = user?.rol === 'admin'
  const [tab, setTab] = useState<Tab>('ventas')
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)

  useEffect(() => {
    if (isAdmin) {
      api.get('/auth/tiendas').then(({ data }) => {
        setSedes(data)
        if (!tiendaId && data.length > 0) setTiendaId(data[0].id)
      }).catch(() => {})
    }
  }, [isAdmin])

  if (!tiendaId) return (
    <div className="text-center py-12 text-sm text-gray-400">Cargando sedes…</div>
  )

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'ventas',    label: 'Ventas',         icon: <BarChart2 size={14} /> },
    { id: 'baristas',  label: 'Baristas',       icon: <Users size={14} /> },
    { id: 'turnos',    label: 'Turnos',         icon: <Clock size={14} /> },
    { id: 'cuadres',   label: 'Cuadres',        icon: <UserCheck size={14} /> },
    { id: 'mermas',    label: 'Mermas',         icon: <Trash2 size={14} /> },
    { id: 'rotacion',  label: 'Rotación',       icon: <Package size={14} /> },
    { id: 'inventario',label: 'Inv. consumido', icon: <Package size={14} /> },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-base font-bold text-gray-800">Informes</h1>

        {/* Selector de sede (solo admin) */}
        {isAdmin && sedes.length > 1 && (
          <div className="flex gap-1.5">
            {sedes.map(s => (
              <button key={s.id} onClick={() => setTiendaId(s.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                  tiendaId === s.id
                    ? 'bg-amber-600 text-white border-amber-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-amber-400'
                }`}>
                {s.nombre}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              tab === t.id ? 'border-amber-500 text-amber-700' : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === 'ventas'     && <TabVentas    tiendaId={tiendaId} />}
      {tab === 'baristas'   && <TabBaristas  tiendaId={tiendaId} />}
      {tab === 'turnos'     && <TabTurnos    tiendaId={tiendaId} />}
      {tab === 'cuadres'    && <TabCuadres   tiendaId={tiendaId} />}
      {tab === 'mermas'     && <TabMermas    tiendaId={tiendaId} />}
      {tab === 'rotacion'   && <TabRotacion  tiendaId={tiendaId} />}
      {tab === 'inventario' && <TabInventario tiendaId={tiendaId} />}
    </div>
  )
}
