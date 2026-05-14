import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  Wrench, Bug, Search, Droplets, Zap, Settings2,
  Plus, X, ChevronDown, ChevronUp, Trash2, ImageIcon,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface Sede { id: number; nombre: string }

interface Mantenimiento {
  id: number
  tienda_id: number
  tipo: string
  titulo: string
  descripcion: string | null
  fecha_realizado: string
  costo: number | null
  tecnico: string | null
  imagen_url: string | null
  usuario_nombre: string | null
}

// ─── Config de tipos ──────────────────────────────────────────────────────────

const TIPO_CFG: Record<string, { label: string; icon: React.ReactNode; bg: string; text: string; border: string }> = {
  equipo:     { label: 'Equipo',     icon: <Wrench size={14} />,    bg: 'bg-blue-50',   text: 'text-blue-700',   border: 'border-blue-200'   },
  fumigacion: { label: 'Fumigación', icon: <Bug size={14} />,       bg: 'bg-green-50',  text: 'text-green-700',  border: 'border-green-200'  },
  sondeo:     { label: 'Sondeo',     icon: <Search size={14} />,    bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200' },
  plomeria:   { label: 'Plomería',   icon: <Droplets size={14} />,  bg: 'bg-cyan-50',   text: 'text-cyan-700',   border: 'border-cyan-200'   },
  electrico:  { label: 'Eléctrico',  icon: <Zap size={14} />,       bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200' },
  otro:       { label: 'Otro',       icon: <Settings2 size={14} />, bg: 'bg-gray-50',   text: 'text-gray-600',   border: 'border-gray-200'   },
}

const FILTROS_TIPO = [
  { key: '', label: 'Todos' },
  ...Object.entries(TIPO_CFG).map(([key, cfg]) => ({ key, label: cfg.label })),
]

function TipoBadge({ tipo }: { tipo: string }) {
  const cfg = TIPO_CFG[tipo] ?? TIPO_CFG.otro
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${cfg.bg} ${cfg.text}`}>
      {cfg.icon} {cfg.label}
    </span>
  )
}

const fmtFecha = (f: string) =>
  new Date(f.includes('T') ? f : f + 'T00:00:00').toLocaleDateString('es-CO', {
    day: 'numeric', month: 'short', year: 'numeric',
  })

const fmtCosto = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

// ─── Tarjeta ──────────────────────────────────────────────────────────────────

function CardMantenimiento({ m, onDelete }: { m: Mantenimiento; onDelete: (id: number) => void }) {
  const [abierto, setAbierto] = useState(false)
  const [imgOpen, setImgOpen] = useState(false)

  return (
    <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
      <button
        onClick={() => setAbierto(v => !v)}
        className="w-full flex items-start justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <TipoBadge tipo={m.tipo} />
          </div>
          <p className="font-semibold text-gray-800 text-sm truncate">{m.titulo}</p>
          <p className="text-xs text-gray-400 mt-0.5">{fmtFecha(m.fecha_realizado)}</p>
        </div>
        <div className="flex items-center gap-2 ml-2 flex-shrink-0">
          {m.costo !== null && (
            <span className="text-xs font-semibold text-gray-600 bg-gray-100 px-2 py-0.5 rounded-full">
              {fmtCosto(m.costo)}
            </span>
          )}
          {abierto ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
        </div>
      </button>

      {abierto && (
        <div className="px-4 pb-4 border-t border-gray-100 pt-3 space-y-2">
          {m.descripcion && (
            <p className="text-sm text-gray-600 leading-relaxed">{m.descripcion}</p>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
            {m.tecnico && <span>🔧 {m.tecnico}</span>}
            {m.usuario_nombre && <span>👤 Registrado por {m.usuario_nombre}</span>}
          </div>
          <div className="flex items-center gap-2 pt-1">
            {m.imagen_url && (
              <button
                onClick={() => setImgOpen(true)}
                className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 border border-blue-200 rounded-lg px-2.5 py-1"
              >
                <ImageIcon size={12} /> Ver foto
              </button>
            )}
            <button
              onClick={() => { if (confirm('¿Eliminar este registro?')) onDelete(m.id) }}
              className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600 border border-red-100 rounded-lg px-2.5 py-1 ml-auto"
            >
              <Trash2 size={12} /> Eliminar
            </button>
          </div>
        </div>
      )}

      {imgOpen && m.imagen_url && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          onClick={() => setImgOpen(false)}
        >
          <img src={m.imagen_url} className="max-w-full max-h-[90vh] rounded-xl shadow-2xl" alt="Soporte" />
          <button className="absolute top-4 right-4 text-white"><X size={24} /></button>
        </div>
      )}
    </div>
  )
}

// ─── Formulario ───────────────────────────────────────────────────────────────

function FormNuevo({ tiendaId, onCreado, onClose }: {
  tiendaId: number; onCreado: () => void; onClose: () => void
}) {
  const [tipo, setTipo] = useState('equipo')
  const [titulo, setTitulo] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [fechaRealizado, setFechaRealizado] = useState(new Date().toISOString().split('T')[0])
  const [costo, setCosto] = useState('')
  const [tecnico, setTecnico] = useState('')
  const [imagen, setImagen] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!titulo.trim()) { setError('El título es obligatorio'); return }
    setLoading(true); setError('')
    try {
      const fd = new FormData()
      fd.append('tienda_id', String(tiendaId))
      fd.append('tipo', tipo)
      fd.append('titulo', titulo.trim())
      fd.append('fecha_realizado', `${fechaRealizado}T12:00:00`)
      if (descripcion) fd.append('descripcion', descripcion)
      if (costo) fd.append('costo', costo)
      if (tecnico) fd.append('tecnico', tecnico)
      if (imagen) fd.append('imagen', imagen)
      await api.post('/mantenimientos/', fd)
      onCreado()
      onClose()
    } catch {
      setError('Error al registrar. Intenta de nuevo.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="bg-white w-full sm:max-w-lg rounded-t-2xl sm:rounded-2xl overflow-y-auto max-h-[92vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
          <h2 className="font-bold text-gray-800">Registrar mantenimiento</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>

        <form onSubmit={handleSubmit} className="px-5 py-4 space-y-4">
          {/* Tipo */}
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1.5">Tipo</label>
            <div className="grid grid-cols-3 gap-2">
              {Object.entries(TIPO_CFG).map(([key, cfg]) => (
                <button
                  key={key} type="button" onClick={() => setTipo(key)}
                  className={`flex flex-col items-center gap-1 py-2 px-1 rounded-xl border-2 text-xs font-medium transition-colors ${
                    tipo === key ? `${cfg.bg} ${cfg.text} ${cfg.border}` : 'border-gray-200 text-gray-400 hover:border-gray-300'
                  }`}
                >
                  {cfg.icon} {cfg.label}
                </button>
              ))}
            </div>
          </div>

          {/* Título */}
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
              Descripción del trabajo *
            </label>
            <input
              value={titulo} onChange={e => setTitulo(e.target.value)}
              placeholder="Ej: Mantenimiento preventivo cafetera La Marzocco"
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          </div>

          {/* Notas */}
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
              Notas adicionales
            </label>
            <textarea
              value={descripcion} onChange={e => setDescripcion(e.target.value)}
              placeholder="Detalles del trabajo realizado..."
              rows={2}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 resize-none"
            />
          </div>

          {/* Fecha */}
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
              Fecha realizado *
            </label>
            <input
              type="date" value={fechaRealizado} onChange={e => setFechaRealizado(e.target.value)} required
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          </div>

          {/* Técnico + Costo */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
                Técnico / Empresa
              </label>
              <input
                value={tecnico} onChange={e => setTecnico(e.target.value)}
                placeholder="Nombre o empresa"
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
                Costo (opcional)
              </label>
              <input
                type="number" min={0} value={costo} onChange={e => setCosto(e.target.value)}
                placeholder="0"
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
              />
            </div>
          </div>

          {/* Foto */}
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">
              Foto / Soporte (opcional)
            </label>
            <input
              type="file" accept="image/*" onChange={e => setImagen(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-gray-500 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-amber-50 file:text-amber-700 hover:file:bg-amber-100"
            />
          </div>

          {error && <p className="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2">{error}</p>}

          <button
            type="submit" disabled={loading}
            className="w-full bg-amber-500 hover:bg-amber-600 text-white font-bold py-3 rounded-xl transition-colors disabled:opacity-50"
          >
            {loading ? 'Guardando…' : 'Registrar mantenimiento'}
          </button>
        </form>
      </div>
    </div>
  )
}

// ─── Página principal ─────────────────────────────────────────────────────────

export default function MantenimientosAdmin() {
  const { user } = useAuth()
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)
  const [filtroTipo, setFiltroTipo] = useState('')
  const [historial, setHistorial] = useState<Mantenimiento[]>([])
  const [loading, setLoading] = useState(false)
  const [showForm, setShowForm] = useState(false)

  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (tiendaId === null && r.data.length > 0) setTiendaId(r.data[0].id)
    }).catch(() => {})
  }, [])

  const cargar = () => {
    if (!tiendaId) return
    setLoading(true)
    api.get('/mantenimientos/', { params: { tienda_id: tiendaId, tipo: filtroTipo || undefined } })
      .then(r => setHistorial(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { cargar() }, [tiendaId, filtroTipo])

  const handleDelete = (id: number) => {
    if (!tiendaId) return
    api.delete(`/mantenimientos/${id}`, { params: { tienda_id: tiendaId } })
      .then(cargar).catch(() => {})
  }

  return (
    <div className="space-y-4 pb-10">
      {/* Título + botón */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <Wrench size={20} className="text-amber-600" />
            Mantenimientos
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Equipos, fumigación, sondeos y reparaciones</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 text-white text-sm font-bold px-4 py-2 rounded-xl transition-colors shadow-sm"
        >
          <Plus size={16} /> Registrar
        </button>
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

      {/* Filtros por tipo */}
      <div className="flex gap-1.5 flex-wrap">
        {FILTROS_TIPO.map(f => (
          <button
            key={f.key} onClick={() => setFiltroTipo(f.key)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              filtroTipo === f.key
                ? 'bg-amber-500 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-gray-400 animate-pulse py-6 text-center">Cargando…</p>}

      {!loading && historial.length === 0 && (
        <div className="text-center py-12 text-gray-400">
          <Wrench size={32} className="mx-auto mb-2 opacity-30" />
          <p className="text-sm">Sin registros de mantenimiento</p>
        </div>
      )}

      {!loading && (
        <div className="space-y-2">
          {historial.map(m => (
            <CardMantenimiento key={m.id} m={m} onDelete={handleDelete} />
          ))}
        </div>
      )}

      {showForm && tiendaId && (
        <FormNuevo tiendaId={tiendaId} onCreado={cargar} onClose={() => setShowForm(false)} />
      )}
    </div>
  )
}
