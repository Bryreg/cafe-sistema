import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  Bell, Plus, Trash2, ToggleLeft, ToggleRight,
  AlertTriangle, MessageSquare, Users, X as XIcon,
} from 'lucide-react'

interface Comunicado {
  id: number
  titulo: string | null
  mensaje: string
  tienda_id: number | null
  activo: boolean
  urgente: boolean
  fecha_creacion: string
  creado_por: string | null
  total_leidos: number
}

interface Tienda { id: number; nombre: string }

function rel(fecha: string) {
  const diff = (Date.now() - new Date(fecha).getTime()) / 1000
  if (diff < 60) return 'Hace un momento'
  if (diff < 3600) return `Hace ${Math.floor(diff / 60)} min`
  if (diff < 86400) return `Hace ${Math.floor(diff / 3600)} h`
  return `Hace ${Math.floor(diff / 86400)} d`
}

export default function Comunicados() {
  const { user } = useAuth()
  const [comunicados, setComunicados] = useState<Comunicado[]>([])
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(false)

  // Form state
  const [titulo, setTitulo] = useState('')
  const [mensaje, setMensaje] = useState('')
  const [tiendaId, setTiendaId] = useState<string>('todas')
  const [urgente, setUrgente] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    cargar()
    api.get('/auth/tiendas').then(r => setTiendas(r.data)).catch(() => null)
  }, [])

  const cargar = () => {
    api.get('/comunicados/admin').then(r => setComunicados(r.data)).catch(() => null)
  }

  const crear = async () => {
    if (!mensaje.trim()) { setError('El mensaje es obligatorio'); return }
    setLoading(true); setError('')
    try {
      await api.post('/comunicados/', {
        titulo: titulo.trim() || null,
        mensaje: mensaje.trim(),
        tienda_id: tiendaId === 'todas' ? null : parseInt(tiendaId),
        urgente,
      })
      setTitulo(''); setMensaje(''); setTiendaId('todas'); setUrgente(false)
      setShowForm(false)
      cargar()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al crear')
    } finally { setLoading(false) }
  }

  const toggleActivo = async (c: Comunicado) => {
    await api.patch(`/comunicados/${c.id}`, { activo: !c.activo })
    cargar()
  }

  const eliminar = async (id: number) => {
    if (!confirm('¿Eliminar este comunicado?')) return
    await api.delete(`/comunicados/${id}`)
    cargar()
  }

  const activos   = comunicados.filter(c => c.activo)
  const inactivos = comunicados.filter(c => !c.activo)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-warm-700 flex items-center gap-2">
            <Bell size={18} className="text-forest" /> Comunicados
          </h1>
          <p className="text-xs text-warm-400 mt-0.5">
            Mensajes que ven los baristas al entrar al sistema
          </p>
        </div>
        <button
          onClick={() => { setShowForm(true); setError('') }}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold text-white transition-colors"
          style={{ background: 'oklch(35% 0.05 155)' }}
        >
          <Plus size={14} /> Nuevo
        </button>
      </div>

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl w-full max-w-md shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-warm-100">
              <p className="font-bold text-warm-700">Nuevo comunicado</p>
              <button onClick={() => setShowForm(false)} className="text-warm-400 hover:text-warm-600">
                <XIcon size={18} />
              </button>
            </div>
            <div className="px-5 py-4 space-y-3">
              {error && <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</p>}

              <div>
                <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide">
                  Título (opcional)
                </label>
                <input
                  value={titulo}
                  onChange={e => setTitulo(e.target.value)}
                  placeholder="Ej: Cambio de turno especial"
                  className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-forest"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide">
                  Mensaje *
                </label>
                <textarea
                  value={mensaje}
                  onChange={e => setMensaje(e.target.value)}
                  placeholder="Escribe el mensaje para los baristas..."
                  rows={4}
                  className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-forest resize-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide">
                    Para
                  </label>
                  <select
                    value={tiendaId}
                    onChange={e => setTiendaId(e.target.value)}
                    className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-forest bg-white"
                  >
                    <option value="todas">Todas las tiendas</option>
                    {tiendas.map(t => (
                      <option key={t.id} value={String(t.id)}>{t.nombre}</option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-col justify-end">
                  <button
                    onClick={() => setUrgente(u => !u)}
                    className={`flex items-center gap-2 border-2 rounded-xl px-3 py-2.5 text-sm font-semibold transition-colors ${
                      urgente
                        ? 'border-red-400 bg-red-50 text-red-700'
                        : 'border-warm-200 text-warm-500'
                    }`}
                  >
                    <AlertTriangle size={14} />
                    {urgente ? 'Urgente ✓' : 'Urgente'}
                  </button>
                </div>
              </div>
            </div>

            <div className="px-5 pb-5 flex gap-2">
              <button
                onClick={() => setShowForm(false)}
                className="flex-1 py-3 rounded-xl border-2 border-warm-200 text-sm font-semibold text-warm-500"
              >
                Cancelar
              </button>
              <button
                onClick={crear}
                disabled={loading || !mensaje.trim()}
                className="flex-1 py-3 rounded-xl text-sm font-bold text-white disabled:opacity-40 transition-colors"
                style={{ background: 'oklch(35% 0.05 155)' }}
              >
                {loading ? 'Enviando...' : 'Publicar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Active */}
      <div>
        <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide mb-3">
          Activos ({activos.length})
        </p>
        {activos.length === 0 ? (
          <div className="bg-white border border-warm-200 rounded-2xl p-8 text-center">
            <MessageSquare size={28} className="text-warm-300 mx-auto mb-2" />
            <p className="text-sm text-warm-400">Sin comunicados activos</p>
            <p className="text-xs text-warm-300 mt-1">
              Crea uno para que los baristas lo vean al entrar
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {activos.map(c => (
              <ComunicadoCard
                key={c.id} c={c} tiendas={tiendas}
                onToggle={() => toggleActivo(c)}
                onDelete={() => eliminar(c.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Inactive */}
      {inactivos.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide mb-3">
            Inactivos ({inactivos.length})
          </p>
          <div className="space-y-2 opacity-60">
            {inactivos.map(c => (
              <ComunicadoCard
                key={c.id} c={c} tiendas={tiendas}
                onToggle={() => toggleActivo(c)}
                onDelete={() => eliminar(c.id)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ComunicadoCard({
  c, tiendas, onToggle, onDelete,
}: {
  c: Comunicado; tiendas: Tienda[]
  onToggle: () => void; onDelete: () => void
}) {
  const tiendaNombre = c.tienda_id
    ? tiendas.find(t => t.id === c.tienda_id)?.nombre ?? `Tienda ${c.tienda_id}`
    : 'Todas las tiendas'

  return (
    <div className={`bg-white rounded-2xl border p-4 ${
      c.urgente && c.activo ? 'border-red-200' : 'border-warm-200'
    }`}>
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
          c.urgente ? 'bg-red-100' : 'bg-forest-50'
        }`}>
          {c.urgente
            ? <AlertTriangle size={16} className="text-red-600" />
            : <Bell size={16} className="text-forest" />
          }
        </div>

        <div className="flex-1 min-w-0">
          {c.titulo && (
            <p className="text-sm font-bold text-warm-700">{c.titulo}</p>
          )}
          <p className="text-sm text-warm-600 mt-0.5 leading-snug">{c.mensaje}</p>

          <div className="flex items-center gap-3 mt-2 flex-wrap">
            <span className="flex items-center gap-1 text-xs text-warm-400">
              <Users size={11} /> {tiendaNombre}
            </span>
            <span className="text-xs text-warm-400">{rel(c.fecha_creacion)}</span>
            {c.total_leidos > 0 && (
              <span className="text-xs text-green-600 font-medium">
                ✓ {c.total_leidos} leído{c.total_leidos > 1 ? 's' : ''}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onToggle}
            title={c.activo ? 'Desactivar' : 'Activar'}
            className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors"
          >
            {c.activo
              ? <ToggleRight size={18} className="text-forest" />
              : <ToggleLeft size={18} />
            }
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 rounded-lg text-warm-400 hover:text-red-500 hover:bg-red-50 transition-colors"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}
