import { useEffect, useState, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { AlertTriangle, CheckCircle, Trash2, Pencil, Check, X } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface CodigoSinMapeo {
  codigo: string
  descripcion: string
}

interface Mapeo {
  id: number
  codigo_siigo: string
  descripcion_siigo: string
  producto_id: number
  producto_nombre: string
  factor_conversion: number
  activo: boolean
}

interface Producto {
  id: number
  nombre: string
  categoria: string
  unidad_medida: string
}

// ─── SiigoMapeo ───────────────────────────────────────────────────────────────

export default function SiigoMapeo() {
  const { user } = useAuth()
  const tiendaId = user?.tienda_id ?? 1

  // ── Data state ──────────────────────────────────────────────────────────────
  const [sinMapeo, setSinMapeo] = useState<CodigoSinMapeo[]>([])
  const [mapeos, setMapeos] = useState<Mapeo[]>([])
  const [productos, setProductos] = useState<Producto[]>([])

  // ── Loading / error ─────────────────────────────────────────────────────────
  const [loadingSin, setLoadingSin] = useState(true)
  const [loadingMapeos, setLoadingMapeos] = useState(true)
  const [error, setError] = useState('')

  // ── Inline map form ─────────────────────────────────────────────────────────
  const [mapeando, setMapeando] = useState<string | null>(null) // codigo_siigo being mapped
  const [formProductoId, setFormProductoId] = useState<number | ''>('')
  const [formFactor, setFormFactor] = useState('1')
  const [saving, setSaving] = useState(false)

  // ── Inline edit factor ──────────────────────────────────────────────────────
  const [editandoId, setEditandoId] = useState<number | null>(null)
  const [editFactor, setEditFactor] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)

  // ── Deleting ────────────────────────────────────────────────────────────────
  const [deletingId, setDeletingId] = useState<number | null>(null)

  // ─── Fetch ──────────────────────────────────────────────────────────────────

  const cargarSinMapeo = useCallback(async () => {
    setLoadingSin(true)
    try {
      const { data } = await api.get<CodigoSinMapeo[]>(
        `/inventario/siigo-mapeo/sin-mapeo?tienda_id=${tiendaId}`
      )
      setSinMapeo(data)
    } catch {
      setError('Error al cargar códigos sin mapear')
    } finally {
      setLoadingSin(false)
    }
  }, [tiendaId])

  const cargarMapeos = useCallback(async () => {
    setLoadingMapeos(true)
    try {
      const { data } = await api.get<Mapeo[]>('/inventario/siigo-mapeo')
      setMapeos(data)
    } catch {
      setError('Error al cargar mapeos')
    } finally {
      setLoadingMapeos(false)
    }
  }, [])

  const cargarProductos = useCallback(async () => {
    try {
      const { data } = await api.get<Producto[]>('/inventario/productos')
      setProductos(data)
    } catch { /* silencioso */ }
  }, [])

  useEffect(() => {
    cargarSinMapeo()
    cargarMapeos()
    cargarProductos()
  }, [cargarSinMapeo, cargarMapeos, cargarProductos])

  // ─── Handlers ───────────────────────────────────────────────────────────────

  const abrirFormMapeo = (codigo: string) => {
    setMapeando(codigo)
    setFormProductoId('')
    setFormFactor('1')
  }

  const cancelarMapeo = () => {
    setMapeando(null)
    setFormProductoId('')
    setFormFactor('1')
  }

  const crearMapeo = async (item: CodigoSinMapeo) => {
    if (!formProductoId) return
    setSaving(true)
    setError('')
    try {
      await api.post('/inventario/siigo-mapeo', {
        codigo_siigo: item.codigo,
        descripcion_siigo: item.descripcion,
        producto_id: formProductoId,
        factor_conversion: parseFloat(formFactor) || 1,
        activo: true,
      })
      cancelarMapeo()
      await cargarSinMapeo()
      await cargarMapeos()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al crear mapeo')
    } finally {
      setSaving(false)
    }
  }

  const toggleActivo = async (m: Mapeo) => {
    try {
      await api.put(`/inventario/siigo-mapeo/${m.id}`, { activo: !m.activo })
      await cargarMapeos()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al actualizar')
    }
  }

  const iniciarEditFactor = (m: Mapeo) => {
    setEditandoId(m.id)
    setEditFactor(String(m.factor_conversion))
  }

  const cancelarEditFactor = () => {
    setEditandoId(null)
    setEditFactor('')
  }

  const guardarEditFactor = async (id: number) => {
    setSavingEdit(true)
    setError('')
    try {
      await api.put(`/inventario/siigo-mapeo/${id}`, {
        factor_conversion: parseFloat(editFactor) || 1,
      })
      cancelarEditFactor()
      await cargarMapeos()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al actualizar factor')
    } finally {
      setSavingEdit(false)
    }
  }

  const eliminarMapeo = async (id: number) => {
    if (!window.confirm('¿Eliminar este mapeo?')) return
    setDeletingId(id)
    setError('')
    try {
      await api.delete(`/inventario/siigo-mapeo/${id}`)
      await cargarSinMapeo()
      await cargarMapeos()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al eliminar')
    } finally {
      setDeletingId(null)
    }
  }

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">

      <div>
        <h1 className="text-lg font-bold text-gray-800">Mapeo Siigo</h1>
        <p className="text-sm text-gray-400 mt-0.5">
          Vincula los códigos de Siigo con los productos del inventario local.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-600 rounded-xl px-4 py-3 text-sm">
          <AlertTriangle size={14} className="shrink-0" /> {error}
        </div>
      )}

      {/* ── Sección 1: Códigos sin mapear ── */}
      <section className="space-y-3">
        <h2 className="text-sm font-bold text-gray-500 uppercase tracking-wide">
          Códigos sin mapear
        </h2>

        {loadingSin && (
          <p className="text-sm text-gray-400 animate-pulse py-4 text-center">Cargando...</p>
        )}

        {!loadingSin && sinMapeo.length === 0 && (
          <div className="bg-white border border-gray-200 rounded-2xl px-4 py-8 text-center">
            <CheckCircle size={28} className="text-green-400 mx-auto mb-2" />
            <p className="text-sm text-gray-500">Todos los códigos Siigo están mapeados</p>
          </div>
        )}

        {!loadingSin && sinMapeo.map(item => (
          <div key={item.codigo} className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
            {/* Row */}
            <div className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-gray-800">{item.codigo}</p>
                <p className="text-xs text-gray-400">{item.descripcion}</p>
              </div>
              {mapeando === item.codigo ? (
                <button
                  onClick={cancelarMapeo}
                  className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1"
                >
                  Cancelar
                </button>
              ) : (
                <button
                  onClick={() => abrirFormMapeo(item.codigo)}
                  className="px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold rounded-lg transition-colors"
                >
                  Mapear
                </button>
              )}
            </div>

            {/* Inline form */}
            {mapeando === item.codigo && (
              <div className="border-t border-gray-100 px-4 py-3 bg-gray-50 space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-500 mb-1">
                    Producto local
                  </label>
                  <select
                    value={formProductoId}
                    onChange={e => setFormProductoId(Number(e.target.value))}
                    className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-amber-500"
                  >
                    <option value="">Seleccionar producto...</option>
                    {productos.map(p => (
                      <option key={p.id} value={p.id}>
                        {p.nombre} ({p.unidad_medida})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-500 mb-1">
                    Factor de conversión
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    value={formFactor}
                    onChange={e => setFormFactor(e.target.value)}
                    className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-amber-500"
                    placeholder="1.0"
                  />
                  <p className="text-xs text-gray-400 mt-1">
                    Ej: 0.018 significa 1 unidad Siigo = 0.018 unidades locales
                  </p>
                </div>

                <button
                  onClick={() => crearMapeo(item)}
                  disabled={saving || !formProductoId}
                  className="w-full bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white font-bold py-2.5 rounded-xl text-sm transition-colors"
                >
                  {saving ? 'Guardando...' : 'Guardar mapeo'}
                </button>
              </div>
            )}
          </div>
        ))}
      </section>

      {/* ── Sección 2: Mapeos activos ── */}
      <section className="space-y-3">
        <h2 className="text-sm font-bold text-gray-500 uppercase tracking-wide">
          Mapeos activos
        </h2>

        {loadingMapeos && (
          <p className="text-sm text-gray-400 animate-pulse py-4 text-center">Cargando...</p>
        )}

        {!loadingMapeos && mapeos.length === 0 && (
          <div className="bg-white border border-gray-200 rounded-2xl px-4 py-8 text-center">
            <p className="text-sm text-gray-500">No hay mapeos configurados aún</p>
          </div>
        )}

        {!loadingMapeos && mapeos.length > 0 && (
          <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
            <div className="overflow-x-auto">
            {/* Table header */}
            <div className="grid grid-cols-[1fr_1fr_80px_64px_80px] bg-gray-50 border-b border-gray-100 px-4 py-2 min-w-[480px]">
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wide">Código Siigo</span>
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wide">Producto local</span>
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wide text-center">Factor</span>
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wide text-center">Activo</span>
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wide text-center">Acciones</span>
            </div>

            <div className="divide-y divide-gray-50">
              {mapeos.map(m => (
                <div
                  key={m.id}
                  className={`grid grid-cols-[1fr_1fr_80px_64px_80px] items-center px-4 py-3 min-w-[480px] ${
                    !m.activo ? 'opacity-50' : ''
                  }`}
                >
                  {/* Código + descripción */}
                  <div>
                    <p className="text-sm font-semibold text-gray-800">{m.codigo_siigo}</p>
                    <p className="text-xs text-gray-400 truncate max-w-[140px]">{m.descripcion_siigo}</p>
                  </div>

                  {/* Producto local */}
                  <p className="text-sm text-gray-700 truncate pr-2">{m.producto_nombre}</p>

                  {/* Factor — inline editable */}
                  <div className="text-center">
                    {editandoId === m.id ? (
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          step="0.001"
                          min="0"
                          value={editFactor}
                          onChange={e => setEditFactor(e.target.value)}
                          className="w-14 border border-amber-400 rounded-lg px-1.5 py-0.5 text-xs text-center focus:outline-none"
                          autoFocus
                        />
                        <button
                          onClick={() => guardarEditFactor(m.id)}
                          disabled={savingEdit}
                          className="p-0.5 text-green-600 hover:text-green-700 disabled:opacity-40"
                        >
                          <Check size={13} />
                        </button>
                        <button
                          onClick={cancelarEditFactor}
                          className="p-0.5 text-gray-400 hover:text-gray-600"
                        >
                          <X size={13} />
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => iniciarEditFactor(m)}
                        className="flex items-center gap-1 mx-auto text-sm text-gray-600 hover:text-amber-700 transition-colors group"
                        title="Editar factor"
                      >
                        <span className="font-mono">×{m.factor_conversion}</span>
                        <Pencil size={10} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                      </button>
                    )}
                  </div>

                  {/* Toggle activo */}
                  <div className="flex justify-center">
                    <button
                      onClick={() => toggleActivo(m)}
                      className={`relative w-9 h-5 rounded-full transition-colors ${
                        m.activo ? 'bg-green-500' : 'bg-gray-300'
                      }`}
                      title={m.activo ? 'Desactivar' : 'Activar'}
                    >
                      <span
                        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                          m.activo ? 'translate-x-4' : 'translate-x-0'
                        }`}
                      />
                    </button>
                  </div>

                  {/* Acciones */}
                  <div className="flex justify-center">
                    <button
                      onClick={() => eliminarMapeo(m.id)}
                      disabled={deletingId === m.id}
                      className="p-1.5 text-gray-400 hover:text-red-500 disabled:opacity-40 transition-colors"
                      title="Eliminar mapeo"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
            </div>{/* /overflow-x-auto */}
          </div>
        )}
      </section>

    </div>
  )
}
