import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Activity, ChevronDown, ChevronRight, Search } from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface Sede { id: number; nombre: string }

interface LogEntry {
  id: number
  fecha: string
  accion: string
  tabla_afectada: string
  registro_id: number | null
  usuario_id: number | null
  usuario: string | null
  datos_antes: string | null
  datos_despues: string | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const ACCION_CFG: Record<string, { label: string; color: string }> = {
  apertura_caja:      { label: 'Apertura caja',    color: 'bg-green-100 text-green-700'  },
  cierre_caja:        { label: 'Cierre caja',       color: 'bg-blue-100 text-blue-700'   },
  registro_venta:     { label: 'Venta',             color: 'bg-emerald-100 text-emerald-700' },
  ajuste_inventario:  { label: 'Inventario',        color: 'bg-amber-100 text-amber-700' },
  registro_merma:     { label: 'Merma',             color: 'bg-orange-100 text-orange-700' },
  registro_factura:   { label: 'Factura',           color: 'bg-purple-100 text-purple-700' },
  registro_compra:    { label: 'Compra',            color: 'bg-violet-100 text-violet-700' },
  entrega_turno:      { label: 'Entrega',           color: 'bg-cyan-100 text-cyan-700'   },
  cuadre_llegada:     { label: 'Cuadre llegada',    color: 'bg-teal-100 text-teal-700'   },
}

function AccionBadge({ accion }: { accion: string }) {
  const cfg = ACCION_CFG[accion] ?? { label: accion, color: 'bg-gray-100 text-gray-600' }
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${cfg.color}`}>
      {cfg.label}
    </span>
  )
}

function fmtFecha(iso: string) {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' })
    + ' ' + d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}

function JsonViewer({ raw, label }: { raw: string | null; label: string }) {
  if (!raw) return null
  let parsed: unknown
  try { parsed = JSON.parse(raw) } catch { return <span className="text-xs text-warm-400">{raw}</span> }
  return (
    <div className="mt-1">
      <p className="text-xs text-warm-400 font-medium uppercase tracking-wide mb-0.5">{label}</p>
      <pre className="text-xs bg-gray-50 rounded-lg p-2 overflow-x-auto text-gray-700 max-h-32 overflow-y-auto">
        {JSON.stringify(parsed, null, 2)}
      </pre>
    </div>
  )
}

// ─── Fila expandible ─────────────────────────────────────────────────────────

function FilaLog({ entry }: { entry: LogEntry }) {
  const [open, setOpen] = useState(false)
  const tieneDatos = entry.datos_antes || entry.datos_despues

  return (
    <>
      <tr
        className={`border-b border-gray-100 last:border-0 ${tieneDatos ? 'cursor-pointer hover:bg-warm-50' : ''} transition-colors`}
        onClick={() => tieneDatos && setOpen(v => !v)}
      >
        <td className="py-2.5 pl-3 pr-2 text-xs text-warm-500 whitespace-nowrap">
          {fmtFecha(entry.fecha)}
        </td>
        <td className="py-2.5 px-2">
          <AccionBadge accion={entry.accion} />
        </td>
        <td className="py-2.5 px-2 text-sm text-warm-700 font-medium">
          {entry.usuario ?? <span className="text-warm-300">—</span>}
        </td>
        <td className="py-2.5 px-2 text-xs text-warm-400 hidden sm:table-cell">
          {entry.tabla_afectada}
          {entry.registro_id && <span className="ml-1 text-warm-300">#{entry.registro_id}</span>}
        </td>
        <td className="py-2.5 pr-3 text-right">
          {tieneDatos && (
            open ? <ChevronDown size={14} className="text-warm-400 inline" />
                 : <ChevronRight size={14} className="text-warm-300 inline" />
          )}
        </td>
      </tr>
      {open && tieneDatos && (
        <tr className="bg-warm-50">
          <td colSpan={5} className="px-4 pb-3 pt-1">
            <JsonViewer raw={entry.datos_antes}   label="Antes" />
            <JsonViewer raw={entry.datos_despues} label="Después" />
          </td>
        </tr>
      )}
    </>
  )
}

// ─── Página principal ─────────────────────────────────────────────────────────

export default function AuditLog() {
  const { user } = useAuth()
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(false)

  // Filtros
  const [fechaDesde, setFechaDesde] = useState('')
  const [fechaHasta, setFechaHasta] = useState('')
  const [usuarioId, setUsuarioId] = useState('')
  const [accion, setAccion] = useState('')

  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (tiendaId === null && r.data.length > 0) setTiendaId(r.data[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (tiendaId === null) return
    setLoading(true)
    const params: Record<string, string> = {}
    if (fechaDesde) params.fecha_desde = fechaDesde
    if (fechaHasta) params.fecha_hasta = fechaHasta
    if (usuarioId)  params.usuario_id  = usuarioId
    if (accion)     params.accion      = accion
    api.get(`/audit-log/${tiendaId}`, { params })
      .then(r => setLogs(r.data))
      .catch(() => setLogs([]))
      .finally(() => setLoading(false))
  }, [tiendaId, fechaDesde, fechaHasta, usuarioId, accion])

  const ACCIONES = Object.keys(ACCION_CFG)

  return (
    <div className="space-y-4 pb-10">
      {/* Título */}
      <div>
        <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
          <Activity size={20} className="text-amber-600" />
          Historial de acciones
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Registro de todas las operaciones del sistema
        </p>
      </div>

      {/* Selector sede */}
      {sedes.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {sedes.map(s => (
            <button key={s.id} onClick={() => setTiendaId(s.id)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                tiendaId === s.id
                  ? 'bg-amber-500 text-white shadow-sm'
                  : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
              }`}
            >{s.nombre}</button>
          ))}
        </div>
      )}

      {/* Filtros */}
      <div className="bg-white rounded-2xl border border-warm-200 p-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-warm-500 font-medium block mb-1">Desde</label>
            <input type="date" value={fechaDesde} onChange={e => setFechaDesde(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          </div>
          <div>
            <label className="text-xs text-warm-500 font-medium block mb-1">Hasta</label>
            <input type="date" value={fechaHasta} onChange={e => setFechaHasta(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          </div>
          <div>
            <label className="text-xs text-warm-500 font-medium block mb-1">Acción</label>
            <select value={accion} onChange={e => setAccion(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            >
              <option value="">Todas</option>
              {ACCIONES.map(a => (
                <option key={a} value={a}>{ACCION_CFG[a].label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-warm-500 font-medium block mb-1">ID usuario</label>
            <input type="number" value={usuarioId} onChange={e => setUsuarioId(e.target.value)}
              placeholder="Todos"
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          </div>
        </div>
        {(fechaDesde || fechaHasta || usuarioId || accion) && (
          <button
            onClick={() => { setFechaDesde(''); setFechaHasta(''); setUsuarioId(''); setAccion('') }}
            className="mt-3 text-xs text-warm-400 hover:text-warm-600 underline"
          >
            Limpiar filtros
          </button>
        )}
      </div>

      {/* Tabla */}
      {loading ? (
        <p className="text-sm text-gray-400 animate-pulse py-8 text-center">Cargando historial…</p>
      ) : logs.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-warm-400">
          <Search size={32} className="opacity-30" />
          <p className="text-sm">No hay registros para los filtros seleccionados</p>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-warm-100 flex items-center justify-between">
            <p className="text-xs text-warm-500 font-medium">
              {logs.length} registro{logs.length !== 1 ? 's' : ''} (últimos 100)
            </p>
            <p className="text-xs text-warm-400 hidden sm:block">
              Haz clic en una fila para ver los datos detallados
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs text-warm-400 uppercase border-b border-warm-100">
                  <th className="py-2 pl-3 pr-2 text-left font-medium">Fecha</th>
                  <th className="py-2 px-2 text-left font-medium">Acción</th>
                  <th className="py-2 px-2 text-left font-medium">Usuario</th>
                  <th className="py-2 px-2 text-left font-medium hidden sm:table-cell">Tabla / ID</th>
                  <th className="py-2 pr-3" />
                </tr>
              </thead>
              <tbody>
                {logs.map(e => <FilaLog key={e.id} entry={e} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
