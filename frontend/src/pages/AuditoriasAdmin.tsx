import { useEffect, useState, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  ClipboardCheck, Package, Plus, X, ChevronDown, ChevronUp,
  Trash2, Search, CheckSquare, Square, ShieldCheck, Lock,
  AlertCircle, CheckCircle2, Clock,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface Sede { id: number; nombre: string }

interface AudInvItem {
  id: number
  producto_id: number
  producto_nombre: string
  unidad: string
  cantidad_sistema: number
  cantidad_real: number
  diferencia: number
  observacion: string | null
}

interface AudInv {
  id: number
  tienda_id: number
  fecha: string
  descripcion: string
  causa: string | null
  observaciones: string | null
  acciones_tomadas: string | null
  estado: 'abierta' | 'cerrada'
  usuario_nombre: string | null
  created_at: string
  items: AudInvItem[]
}

interface TareaLimp {
  tarea_key: string
  tarea_label: string
  realizado: boolean
  realizado_por: string | null
}

interface AudLimp {
  id: number
  tienda_id: number
  semana: string
  fecha_inicio: string
  observaciones: string | null
  vobo: boolean
  vobo_fecha: string | null
  vobo_por: string | null
  usuario_nombre: string | null
  completadas: number
  total_tareas: number
  items: TareaLimp[]
}

interface InvProd {
  producto_id: number
  nombre: string
  stock_actual: number
  unidad_medida: string
  categoria: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const CAUSAS: { value: string; label: string }[] = [
  { value: 'acceso_no_autorizado',    label: 'Acceso no autorizado' },
  { value: 'error_conteo',            label: 'Error de conteo' },
  { value: 'dano',                     label: 'Daño al producto' },
  { value: 'traslado_no_registrado',  label: 'Traslado no registrado' },
  { value: 'otro',                    label: 'Otro' },
]

function getISOWeek(date = new Date()): string {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
  const day = d.getUTCDay() || 7
  d.setUTCDate(d.getUTCDate() + 4 - day)
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
  const wk = Math.ceil((((d.getTime() - yearStart.getTime()) / 86400000) + 1) / 7)
  return `${d.getUTCFullYear()}-W${String(wk).padStart(2, '0')}`
}

function weekStartISO(semana: string): string {
  const [yr, wk] = semana.split('-W').map(Number)
  const jan4 = new Date(Date.UTC(yr, 0, 4))
  const day4 = jan4.getUTCDay() || 7
  const mon = new Date(jan4)
  mon.setUTCDate(jan4.getUTCDate() - day4 + 1 + (wk - 1) * 7)
  return mon.toISOString().split('T')[0]
}

const fmtFecha = (f: string) =>
  new Date(f.includes('T') ? f : f + 'T00:00:00').toLocaleDateString('es-CO', {
    day: 'numeric', month: 'short', year: 'numeric',
  })

const fmtNum = (n: number) =>
  n % 1 === 0 ? String(n) : n.toFixed(3).replace(/\.?0+$/, '')

// ─── ══════════════════════════════ INVENTARIO ══════════════════════════════ ─

// ── Formulario nueva auditoría ─────────────────────────────────────────────

function FormNuevaAudInv({ tiendaId, onCreada, onClose }: {
  tiendaId: number; onCreada: () => void; onClose: () => void
}) {
  const [productos, setProductos] = useState<InvProd[]>([])
  const [busqueda, setBusqueda] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [causa, setCausa] = useState('')
  const [observaciones, setObservaciones] = useState('')
  const [cantidades, setCantidades] = useState<Record<number, string>>({})
  const [observsProd, setObservsProd] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(false)
  const [loadingProds, setLoadingProds] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/inventario/', { params: { tienda_id: tiendaId } })
      .then(r => setProductos(r.data))
      .catch(() => {})
      .finally(() => setLoadingProds(false))
  }, [tiendaId])

  const prodsFiltrados = productos.filter(p =>
    p.nombre.toLowerCase().includes(busqueda.toLowerCase())
  )

  const itemsSeleccionados = Object.entries(cantidades)
    .filter(([, v]) => v !== '' && !isNaN(Number(v)))
    .map(([id]) => Number(id))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!descripcion.trim()) { setError('La descripción es obligatoria'); return }
    if (itemsSeleccionados.length === 0) { setError('Ingresa al menos una cantidad real'); return }
    setLoading(true); setError('')
    try {
      const items = itemsSeleccionados.map(pid => ({
        producto_id: pid,
        cantidad_real: Number(cantidades[pid]),
        observacion: observsProd[pid]?.trim() || null,
      }))
      await api.post('/auditorias/inventario', {
        tienda_id: tiendaId,
        fecha: new Date().toISOString(),
        descripcion: descripcion.trim(),
        causa: causa || null,
        observaciones: observaciones.trim() || null,
        items,
      })
      onCreada(); onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Error al crear la auditoría')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="bg-white w-full sm:max-w-2xl rounded-t-2xl sm:rounded-2xl flex flex-col max-h-[95vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 flex-shrink-0">
          <h2 className="font-bold text-gray-800 flex items-center gap-2">
            <Package size={18} className="text-amber-600" />
            Nueva auditoría de inventario
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col overflow-hidden flex-1">
          <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
            {/* Descripción */}
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
                Motivo / Descripción *
              </label>
              <input
                value={descripcion} onChange={e => setDescripcion(e.target.value)}
                placeholder="Ej: Conteo de apertura — sospecha de faltantes"
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Causa */}
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
                  Causa (opcional)
                </label>
                <select
                  value={causa} onChange={e => setCausa(e.target.value)}
                  className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white"
                >
                  <option value="">Sin especificar</option>
                  {CAUSAS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
              {/* Observaciones */}
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
                  Observaciones generales
                </label>
                <input
                  value={observaciones} onChange={e => setObservaciones(e.target.value)}
                  placeholder="Notas adicionales..."
                  className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
                />
              </div>
            </div>

            {/* Búsqueda de productos */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Conteo de productos
                </label>
                {itemsSeleccionados.length > 0 && (
                  <span className="text-xs bg-amber-100 text-amber-700 font-semibold px-2 py-0.5 rounded-full">
                    {itemsSeleccionados.length} productos ingresados
                  </span>
                )}
              </div>
              <div className="relative mb-2">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  value={busqueda} onChange={e => setBusqueda(e.target.value)}
                  placeholder="Buscar producto..."
                  className="w-full border border-gray-200 rounded-xl pl-8 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
                />
              </div>
              {loadingProds ? (
                <p className="text-sm text-gray-400 text-center py-3 animate-pulse">Cargando productos…</p>
              ) : (
                <div className="border border-gray-200 rounded-xl overflow-hidden max-h-64 overflow-y-auto">
                  {prodsFiltrados.length === 0 ? (
                    <p className="text-sm text-gray-400 text-center py-4">Sin resultados</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50 sticky top-0">
                        <tr>
                          <th className="text-left px-3 py-2 font-semibold text-gray-500">Producto</th>
                          <th className="text-right px-2 py-2 font-semibold text-gray-500 whitespace-nowrap">Sistema</th>
                          <th className="text-right px-3 py-2 font-semibold text-gray-500 whitespace-nowrap">Contado</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {prodsFiltrados.map(p => (
                          <tr key={p.producto_id} className={cantidades[p.producto_id] !== undefined && cantidades[p.producto_id] !== '' ? 'bg-amber-50' : ''}>
                            <td className="px-3 py-1.5">
                              <span className="font-medium text-gray-700">{p.nombre}</span>
                              <span className="text-gray-400 ml-1">{p.unidad_medida}</span>
                            </td>
                            <td className="px-2 py-1.5 text-right text-gray-500 whitespace-nowrap">
                              {fmtNum(p.stock_actual)}
                            </td>
                            <td className="px-3 py-1.5">
                              <input
                                type="number" min={0} step="0.001"
                                value={cantidades[p.producto_id] ?? ''}
                                onChange={e => setCantidades(prev => ({ ...prev, [p.producto_id]: e.target.value }))}
                                placeholder="—"
                                className="w-20 border border-gray-200 rounded-lg px-2 py-1 text-right focus:outline-none focus:ring-1 focus:ring-amber-400 text-xs"
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="px-5 pb-5 pt-3 border-t border-gray-100 flex-shrink-0 space-y-2">
            {error && <p className="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2">{error}</p>}
            <button
              type="submit" disabled={loading}
              className="w-full bg-amber-500 hover:bg-amber-600 text-white font-bold py-3 rounded-xl transition-colors disabled:opacity-50"
            >
              {loading ? 'Guardando…' : 'Crear auditoría'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal cerrar auditoría ─────────────────────────────────────────────────

function ModalCerrar({ audId, tiendaId, onCerrada, onClose }: {
  audId: number; tiendaId: number; onCerrada: () => void; onClose: () => void
}) {
  const [causa, setCausa] = useState('')
  const [acciones, setAcciones] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      await api.patch(`/auditorias/inventario/${audId}/cerrar`, {
        causa: causa || null,
        acciones_tomadas: acciones.trim() || null,
      }, { params: { tienda_id: tiendaId } })
      onCerrada(); onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Error al cerrar')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-white w-full max-w-md rounded-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h3 className="font-bold text-gray-800 flex items-center gap-2">
            <Lock size={16} className="text-gray-500" /> Cerrar auditoría
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-5 py-4 space-y-3">
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Causa</label>
            <select
              value={causa} onChange={e => setCausa(e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white"
            >
              <option value="">Sin especificar</option>
              {CAUSAS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Acciones tomadas</label>
            <textarea
              value={acciones} onChange={e => setAcciones(e.target.value)}
              placeholder="Describe las medidas tomadas..."
              rows={3}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 resize-none"
            />
          </div>
          {error && <p className="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2">{error}</p>}
          <button
            type="submit" disabled={loading}
            className="w-full bg-gray-800 hover:bg-gray-900 text-white font-bold py-3 rounded-xl transition-colors disabled:opacity-50"
          >
            {loading ? 'Cerrando…' : 'Confirmar cierre'}
          </button>
        </form>
      </div>
    </div>
  )
}

// ── Tarjeta auditoría inventario ──────────────────────────────────────────

function CardAudInv({ a, tiendaId, onRefresh }: {
  a: AudInv; tiendaId: number; onRefresh: () => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [showCerrar, setShowCerrar] = useState(false)

  const faltantes = a.items.filter(it => it.diferencia < 0).length
  const sobrantes = a.items.filter(it => it.diferencia > 0).length

  const estadoBadge = a.estado === 'abierta'
    ? 'bg-yellow-100 text-yellow-700'
    : 'bg-gray-100 text-gray-500'

  const handleDelete = async () => {
    if (!confirm('¿Eliminar esta auditoría?')) return
    try {
      await api.delete(`/auditorias/inventario/${a.id}`, { params: { tienda_id: tiendaId } })
      onRefresh()
    } catch { /* noop */ }
  }

  return (
    <>
      <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
        <button
          onClick={() => setAbierto(v => !v)}
          className="w-full flex items-start justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${estadoBadge}`}>
                {a.estado === 'abierta' ? 'Abierta' : 'Cerrada'}
              </span>
              {faltantes > 0 && (
                <span className="text-xs font-semibold text-red-600 bg-red-50 px-2 py-0.5 rounded-full">
                  {faltantes} faltante{faltantes !== 1 ? 's' : ''}
                </span>
              )}
              {sobrantes > 0 && (
                <span className="text-xs font-semibold text-green-600 bg-green-50 px-2 py-0.5 rounded-full">
                  {sobrantes} sobrante{sobrantes !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <p className="font-semibold text-gray-800 text-sm leading-tight">{a.descripcion}</p>
            <p className="text-xs text-gray-400 mt-0.5">
              {fmtFecha(a.fecha)} · {a.usuario_nombre ?? '—'} · {a.items.length} productos
            </p>
          </div>
          {abierto ? <ChevronUp size={16} className="text-gray-400 ml-2 flex-shrink-0 mt-1" /> : <ChevronDown size={16} className="text-gray-400 ml-2 flex-shrink-0 mt-1" />}
        </button>

        {abierto && (
          <div className="border-t border-gray-100">
            {/* Items table */}
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left px-4 py-2 font-semibold text-gray-500">Producto</th>
                    <th className="text-right px-3 py-2 font-semibold text-gray-500">Sistema</th>
                    <th className="text-right px-3 py-2 font-semibold text-gray-500">Real</th>
                    <th className="text-right px-3 py-2 font-semibold text-gray-500">Diferencia</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {a.items.map(it => (
                    <tr key={it.id} className={it.diferencia < 0 ? 'bg-red-50/60' : it.diferencia > 0 ? 'bg-green-50/60' : ''}>
                      <td className="px-4 py-2">
                        <span className="font-medium text-gray-700">{it.producto_nombre}</span>
                        <span className="text-gray-400 ml-1">{it.unidad}</span>
                        {it.observacion && <p className="text-gray-400 mt-0.5 italic">{it.observacion}</p>}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-500">{fmtNum(it.cantidad_sistema)}</td>
                      <td className="px-3 py-2 text-right text-gray-700 font-medium">{fmtNum(it.cantidad_real)}</td>
                      <td className={`px-3 py-2 text-right font-bold ${
                        it.diferencia < 0 ? 'text-red-600' : it.diferencia > 0 ? 'text-green-600' : 'text-gray-400'
                      }`}>
                        {it.diferencia > 0 ? '+' : ''}{fmtNum(it.diferencia)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Info adicional */}
            {(a.causa || a.observaciones || a.acciones_tomadas) && (
              <div className="px-4 py-3 bg-gray-50 border-t border-gray-100 space-y-1 text-xs text-gray-600">
                {a.causa && <p><span className="font-semibold">Causa:</span> {CAUSAS.find(c => c.value === a.causa)?.label ?? a.causa}</p>}
                {a.observaciones && <p><span className="font-semibold">Observaciones:</span> {a.observaciones}</p>}
                {a.acciones_tomadas && <p><span className="font-semibold">Acciones tomadas:</span> {a.acciones_tomadas}</p>}
              </div>
            )}

            {/* Acciones */}
            <div className="px-4 py-3 flex items-center gap-2 border-t border-gray-100">
              {a.estado === 'abierta' && (
                <button
                  onClick={() => setShowCerrar(true)}
                  className="flex items-center gap-1 text-xs text-gray-700 bg-gray-100 hover:bg-gray-200 border border-gray-200 rounded-lg px-3 py-1.5 font-semibold transition-colors"
                >
                  <Lock size={12} /> Cerrar auditoría
                </button>
              )}
              <button
                onClick={handleDelete}
                className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600 border border-red-100 rounded-lg px-2.5 py-1.5 ml-auto transition-colors"
              >
                <Trash2 size={12} /> Eliminar
              </button>
            </div>
          </div>
        )}
      </div>

      {showCerrar && (
        <ModalCerrar
          audId={a.id} tiendaId={tiendaId}
          onCerrada={onRefresh} onClose={() => setShowCerrar(false)}
        />
      )}
    </>
  )
}

// ── Panel Inventario ───────────────────────────────────────────────────────

function TabInventario({ tiendaId }: { tiendaId: number }) {
  const [auditorias, setAuditorias] = useState<AudInv[]>([])
  const [loading, setLoading] = useState(false)
  const [showForm, setShowForm] = useState(false)

  const cargar = useCallback(() => {
    setLoading(true)
    api.get('/auditorias/inventario', { params: { tienda_id: tiendaId } })
      .then(r => setAuditorias(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tiendaId])

  useEffect(() => { cargar() }, [cargar])

  return (
    <div className="space-y-3">
      {/* Acciones */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {auditorias.length > 0
            ? `${auditorias.filter(a => a.estado === 'abierta').length} abierta(s) · ${auditorias.filter(a => a.estado === 'cerrada').length} cerrada(s)`
            : 'Sin auditorías registradas'}
        </p>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 text-white text-sm font-bold px-4 py-2 rounded-xl transition-colors shadow-sm"
        >
          <Plus size={16} /> Nueva auditoría
        </button>
      </div>

      {loading && <p className="text-sm text-gray-400 animate-pulse py-8 text-center">Cargando…</p>}

      {!loading && auditorias.length === 0 && (
        <div className="text-center py-14 text-gray-400">
          <Package size={36} className="mx-auto mb-2 opacity-25" />
          <p className="text-sm font-medium">Sin auditorías de inventario</p>
          <p className="text-xs mt-1">Crea una cuando detectes diferencias en el stock</p>
        </div>
      )}

      {!loading && (
        <div className="space-y-2">
          {auditorias.map(a => (
            <CardAudInv key={a.id} a={a} tiendaId={tiendaId} onRefresh={cargar} />
          ))}
        </div>
      )}

      {showForm && (
        <FormNuevaAudInv tiendaId={tiendaId} onCreada={cargar} onClose={() => setShowForm(false)} />
      )}
    </div>
  )
}


// ─── ══════════════════════════════ LIMPIEZA ════════════════════════════════ ─

// ── Formulario nueva semana ────────────────────────────────────────────────

function FormNuevaSemana({ tiendaId, tareas, onCreada, onClose }: {
  tiendaId: number
  tareas: { key: string; label: string }[]
  onCreada: () => void
  onClose: () => void
}) {
  const semanaActual = getISOWeek()
  const [semana, setSemana] = useState(semanaActual)
  const [observaciones, setObservaciones] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      const fechaInicio = weekStartISO(semana) + 'T00:00:00'
      await api.post('/auditorias/limpieza', {
        tienda_id: tiendaId,
        semana,
        fecha_inicio: fechaInicio,
        observaciones: observaciones.trim() || null,
        items: tareas.map(t => ({ tarea_key: t.key, realizado: false, realizado_por: null })),
      })
      onCreada(); onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Error al crear')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-white w-full max-w-sm rounded-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h3 className="font-bold text-gray-800">Nueva semana de aseo</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-5 py-4 space-y-4">
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
              Semana (ISO)
            </label>
            <input
              value={semana} onChange={e => setSemana(e.target.value)}
              placeholder="2026-W20"
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 font-mono"
            />
            <p className="text-xs text-gray-400 mt-1">
              Lunes de esta semana: {semana ? weekStartISO(semana) : '—'}
            </p>
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
              Observaciones
            </label>
            <textarea
              value={observaciones} onChange={e => setObservaciones(e.target.value)}
              placeholder="Notas generales de la semana..."
              rows={2}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 resize-none"
            />
          </div>
          {error && <p className="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2">{error}</p>}
          <button
            type="submit" disabled={loading}
            className="w-full bg-amber-500 hover:bg-amber-600 text-white font-bold py-3 rounded-xl transition-colors disabled:opacity-50"
          >
            {loading ? 'Creando…' : 'Crear cronograma'}
          </button>
        </form>
      </div>
    </div>
  )
}

// ── Vista detalle semana ───────────────────────────────────────────────────

function DetalleSemana({ aud, tiendaId, onRefresh, onClose }: {
  aud: AudLimp; tiendaId: number; onRefresh: () => void; onClose: () => void
}) {
  const [items, setItems] = useState<TareaLimp[]>(aud.items.map(it => ({ ...it })))
  const [obs, setObs] = useState(aud.observaciones ?? '')
  const [saving, setSaving] = useState(false)
  const [voboLoading, setVoboLoading] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [error, setError] = useState('')

  const completadas = items.filter(it => it.realizado).length

  const toggleRealizado = (key: string) => {
    if (aud.vobo) return
    setItems(prev => prev.map(it =>
      it.tarea_key === key ? { ...it, realizado: !it.realizado } : it
    ))
  }

  const setRealizadoPor = (key: string, val: string) => {
    if (aud.vobo) return
    setItems(prev => prev.map(it =>
      it.tarea_key === key ? { ...it, realizado_por: val } : it
    ))
  }

  const handleSave = async () => {
    setSaving(true); setError(''); setSaveMsg('')
    try {
      await api.patch(`/auditorias/limpieza/${aud.id}`, {
        observaciones: obs.trim() || null,
        items: items.map(it => ({
          tarea_key: it.tarea_key,
          realizado: it.realizado,
          realizado_por: it.realizado_por?.trim() || null,
        })),
      }, { params: { tienda_id: tiendaId } })
      setSaveMsg('Guardado ✓')
      setTimeout(() => setSaveMsg(''), 2000)
      onRefresh()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Error al guardar')
    } finally { setSaving(false) }
  }

  const handleVobo = async () => {
    if (!confirm('¿Dar VoBo a esta auditoría de limpieza? Esta acción no puede revertirse.')) return
    setVoboLoading(true)
    try {
      await api.patch(`/auditorias/limpieza/${aud.id}/vobo`, null, { params: { tienda_id: tiendaId } })
      onRefresh(); onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Error al dar VoBo')
    } finally { setVoboLoading(false) }
  }

  const handleDelete = async () => {
    if (!confirm('¿Eliminar este cronograma de aseo?')) return
    try {
      await api.delete(`/auditorias/limpieza/${aud.id}`, { params: { tienda_id: tiendaId } })
      onRefresh(); onClose()
    } catch { /* noop */ }
  }

  const pct = Math.round((completadas / (aud.total_tareas || 1)) * 100)

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="bg-white w-full sm:max-w-xl rounded-t-2xl sm:rounded-2xl flex flex-col max-h-[95vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 flex-shrink-0">
          <div>
            <h3 className="font-bold text-gray-800">
              Cronograma de aseo
              {aud.vobo && <span className="ml-2 text-xs bg-green-100 text-green-700 font-semibold px-2 py-0.5 rounded-full">VoBo ✓</span>}
            </h3>
            <p className="text-xs text-gray-400 mt-0.5">
              Semana {aud.semana} · Inicia {fmtFecha(aud.fecha_inicio)}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>

        {/* Progress */}
        <div className="px-5 py-3 border-b border-gray-100 flex-shrink-0">
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span className="text-gray-500">{completadas} / {aud.total_tareas} tareas completadas</span>
            <span className={`font-bold ${pct === 100 ? 'text-green-600' : pct >= 50 ? 'text-amber-600' : 'text-gray-500'}`}>
              {pct}%
            </span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${pct === 100 ? 'bg-green-500' : 'bg-amber-500'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        {/* Tareas */}
        <div className="overflow-y-auto flex-1 divide-y divide-gray-100">
          {items.map((it) => (
            <div
              key={it.tarea_key}
              className={`px-5 py-3 flex items-start gap-3 ${it.realizado ? 'bg-green-50/50' : ''} ${!aud.vobo ? 'cursor-pointer hover:bg-gray-50' : ''}`}
              onClick={() => toggleRealizado(it.tarea_key)}
            >
              <div className="flex-shrink-0 mt-0.5">
                {it.realizado
                  ? <CheckSquare size={18} className="text-green-600" />
                  : <Square size={18} className="text-gray-300" />}
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm ${it.realizado ? 'text-gray-600' : 'text-gray-700 font-medium'}`}>
                  {it.tarea_label}
                </p>
                {it.realizado && (
                  <input
                    type="text"
                    value={it.realizado_por ?? ''}
                    onChange={e => { e.stopPropagation(); setRealizadoPor(it.tarea_key, e.target.value) }}
                    onClick={e => e.stopPropagation()}
                    placeholder="¿Quién lo hizo?"
                    disabled={aud.vobo}
                    className="mt-1 w-full text-xs border border-green-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-green-400 bg-white disabled:bg-transparent disabled:border-transparent disabled:text-gray-500"
                  />
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-gray-100 flex-shrink-0 space-y-3">
          {/* Observaciones */}
          {!aud.vobo && (
            <textarea
              value={obs} onChange={e => setObs(e.target.value)}
              placeholder="Observaciones generales de la semana..."
              rows={2}
              className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 resize-none"
            />
          )}
          {aud.observaciones && aud.vobo && (
            <p className="text-sm text-gray-600 italic bg-gray-50 rounded-xl px-3 py-2">{aud.observaciones}</p>
          )}

          {aud.vobo && aud.vobo_por && (
            <p className="text-xs text-green-700 bg-green-50 rounded-xl px-3 py-2">
              ✅ VoBo dado por <strong>{aud.vobo_por}</strong> el {fmtFecha(aud.vobo_fecha!)}
            </p>
          )}

          {error && <p className="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2">{error}</p>}
          {saveMsg && <p className="text-sm text-green-700 bg-green-50 rounded-xl px-3 py-2 text-center">{saveMsg}</p>}

          {!aud.vobo && (
            <div className="flex gap-2">
              <button
                onClick={handleSave} disabled={saving}
                className="flex-1 bg-amber-500 hover:bg-amber-600 text-white font-bold py-2.5 rounded-xl transition-colors disabled:opacity-50 text-sm"
              >
                {saving ? 'Guardando…' : 'Guardar cambios'}
              </button>
              {completadas === aud.total_tareas && (
                <button
                  onClick={handleVobo} disabled={voboLoading}
                  className="flex items-center gap-1.5 bg-green-600 hover:bg-green-700 text-white font-bold px-4 py-2.5 rounded-xl transition-colors disabled:opacity-50 text-sm"
                >
                  <ShieldCheck size={16} /> VoBo
                </button>
              )}
            </div>
          )}

          <button
            onClick={handleDelete}
            className="w-full flex items-center justify-center gap-1.5 text-xs text-red-400 hover:text-red-600 py-1.5 transition-colors"
          >
            <Trash2 size={12} /> Eliminar cronograma
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Panel Limpieza ────────────────────────────────────────────────────────

function TabLimpieza({ tiendaId }: { tiendaId: number }) {
  const [auditorias, setAuditorias] = useState<AudLimp[]>([])
  const [tareas, setTareas] = useState<{ key: string; label: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [seleccionada, setSeleccionada] = useState<AudLimp | null>(null)

  const cargar = useCallback(() => {
    setLoading(true)
    Promise.all([
      api.get('/auditorias/limpieza', { params: { tienda_id: tiendaId } }),
      api.get('/auditorias/limpieza/tareas'),
    ])
      .then(([rAud, rTareas]) => {
        setAuditorias(rAud.data)
        setTareas(rTareas.data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tiendaId])

  useEffect(() => { cargar() }, [cargar])

  // Refresh seleccionada cuando se recargue
  const handleRefresh = useCallback(() => {
    cargar()
    if (seleccionada) {
      api.get('/auditorias/limpieza', { params: { tienda_id: tiendaId } })
        .then(r => {
          const actualizada = (r.data as AudLimp[]).find(a => a.id === seleccionada.id)
          if (actualizada) setSeleccionada(actualizada)
        })
        .catch(() => {})
    }
  }, [cargar, seleccionada, tiendaId])

  const semanaActual = getISOWeek()
  const semanaExiste = auditorias.some(a => a.semana === semanaActual)

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {auditorias.length > 0
            ? `${auditorias.length} semana${auditorias.length !== 1 ? 's' : ''} registrada${auditorias.length !== 1 ? 's' : ''}`
            : 'Sin cronogramas registrados'}
        </p>
        {!semanaExiste && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 text-white text-sm font-bold px-4 py-2 rounded-xl transition-colors shadow-sm"
          >
            <Plus size={16} /> Esta semana
          </button>
        )}
      </div>

      {loading && <p className="text-sm text-gray-400 animate-pulse py-8 text-center">Cargando…</p>}

      {!loading && auditorias.length === 0 && (
        <div className="text-center py-14 text-gray-400">
          <CheckSquare size={36} className="mx-auto mb-2 opacity-25" />
          <p className="text-sm font-medium">Sin cronogramas de aseo</p>
          <p className="text-xs mt-1">Registra el cronograma de esta semana</p>
          <button
            onClick={() => setShowForm(true)}
            className="mt-4 flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 text-white text-sm font-bold px-5 py-2 rounded-xl transition-colors mx-auto"
          >
            <Plus size={16} /> Crear cronograma
          </button>
        </div>
      )}

      {!loading && (
        <div className="space-y-2">
          {auditorias.map(a => {
            const pct = Math.round((a.completadas / (a.total_tareas || 1)) * 100)
            const esActual = a.semana === semanaActual
            return (
              <button
                key={a.id}
                onClick={() => setSeleccionada(a)}
                className="w-full bg-white border border-gray-200 rounded-2xl px-4 py-3 text-left hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {esActual && (
                        <span className="text-xs bg-amber-100 text-amber-700 font-semibold px-2 py-0.5 rounded-full">
                          Esta semana
                        </span>
                      )}
                      {a.vobo && (
                        <span className="text-xs bg-green-100 text-green-700 font-semibold px-2 py-0.5 rounded-full">
                          VoBo ✓
                        </span>
                      )}
                    </div>
                    <p className="font-semibold text-gray-800 text-sm">
                      Semana {a.semana}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      Inicia {fmtFecha(a.fecha_inicio)}
                      {a.vobo_por && ` · VoBo: ${a.vobo_por}`}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1 flex-shrink-0">
                    <span className={`text-sm font-bold ${pct === 100 ? 'text-green-600' : pct >= 50 ? 'text-amber-600' : 'text-gray-400'}`}>
                      {pct}%
                    </span>
                    <span className="text-xs text-gray-400">{a.completadas}/{a.total_tareas}</span>
                  </div>
                </div>
                <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${pct === 100 ? 'bg-green-500' : 'bg-amber-400'}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </button>
            )
          })}
        </div>
      )}

      {showForm && (
        <FormNuevaSemana
          tiendaId={tiendaId} tareas={tareas}
          onCreada={() => { cargar(); setShowForm(false) }}
          onClose={() => setShowForm(false)}
        />
      )}

      {seleccionada && (
        <DetalleSemana
          aud={seleccionada} tiendaId={tiendaId}
          onRefresh={handleRefresh}
          onClose={() => { setSeleccionada(null); cargar() }}
        />
      )}
    </div>
  )
}


// ─── ════════════════════════════ PÁGINA PRINCIPAL ══════════════════════════ ─

type Tab = 'inventario' | 'limpieza'

export default function AuditoriasAdmin() {
  const { user } = useAuth()
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)
  const [tab, setTab] = useState<Tab>('inventario')

  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (tiendaId === null && r.data.length > 0) setTiendaId(r.data[0].id)
    }).catch(() => {})
  }, [])

  const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: 'inventario', label: 'Inventario', icon: <Package size={15} /> },
    { key: 'limpieza',   label: 'Limpieza',   icon: <CheckSquare size={15} /> },
  ]

  return (
    <div className="space-y-4 pb-10">
      {/* Título */}
      <div>
        <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
          <ClipboardCheck size={20} className="text-amber-600" />
          Auditorías
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">Control de inventario y cronograma de aseo</p>
      </div>

      {/* Selector de sede */}
      {sedes.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {sedes.map(s => (
            <button
              key={s.id} onClick={() => setTiendaId(s.id)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                tiendaId === s.id
                  ? 'bg-amber-500 text-white shadow-sm'
                  : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
              }`}
            >
              {s.nombre}
            </button>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex bg-gray-100 rounded-xl p-1 gap-1">
        {TABS.map(t => (
          <button
            key={t.key} onClick={() => setTab(t.key)}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-semibold transition-colors ${
              tab === t.key
                ? 'bg-white text-gray-800 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {/* Contenido del tab activo */}
      {tiendaId && tab === 'inventario' && <TabInventario tiendaId={tiendaId} />}
      {tiendaId && tab === 'limpieza' && <TabLimpieza tiendaId={tiendaId} />}
    </div>
  )
}
