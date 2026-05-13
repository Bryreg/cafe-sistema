import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Trash2, AlertTriangle, Check, PackageCheck, ArrowRight } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface InvItem {
  producto_id: number; producto_nombre: string
  unidad_medida: string; stock_actual: number
}
interface Merma {
  id: number; producto_id: number; cantidad: number; motivo: string
  fecha_registro: string; tipo: string; tienda_destino_id?: number
  recibido: boolean; fecha_recibido?: string
}
interface Sede {
  id: number; nombre: string
}
interface TrasladoPendiente {
  id: number; producto_id: number; producto_nombre: string; unidad_medida: string
  cantidad: number; tienda_origen_id: number; tienda_origen_nombre: string
  fecha_registro: string; motivo: string
}

type Tipo = 'consumo' | 'traslado' | 'daño'

const TIPO_CONFIG: Record<Tipo, { label: string; color: string; activeBg: string; activeBorder: string; activeText: string }> = {
  consumo: { label: 'Consumo', color: 'orange', activeBg: 'oklch(96% 0.015 60)', activeBorder: 'oklch(65% 0.13 55)', activeText: 'oklch(40% 0.12 55)' },
  traslado: { label: 'Traslado', color: 'blue', activeBg: 'oklch(95% 0.015 245)', activeBorder: 'oklch(55% 0.14 245)', activeText: 'oklch(35% 0.12 245)' },
  daño:     { label: 'Daño',     color: 'red',  activeBg: 'oklch(96% 0.015 20)',  activeBorder: 'oklch(58% 0.18 25)',  activeText: 'oklch(38% 0.16 25)'  },
}

export default function Mermas() {
  const { user } = useAuth()
  const [items, setItems] = useState<InvItem[]>([])
  const [mermas, setMermas] = useState<Merma[]>([])
  const [sedes, setSedes] = useState<Sede[]>([])
  const [traslados, setTraslados] = useState<TrasladoPendiente[]>([])
  const [tipo, setTipo] = useState<Tipo>('consumo')
  const [productoId, setProductoId] = useState<number | null>(null)
  const [cantidad, setCantidad] = useState('')
  const [motivo, setMotivo] = useState('')
  const [sedeDestinoId, setSedeDestinoId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [recibiendoId, setRecibiendoId] = useState<number | null>(null)

  const load = async () => {
    if (!user?.tienda_id) return
    const [invRes, mermasRes, sedesRes, trasladosRes] = await Promise.all([
      api.get(`/inventario/tienda/${user.tienda_id}`),
      api.get(`/mermas/tienda/${user.tienda_id}`),
      api.get('/mermas/sedes'),
      api.get(`/mermas/traslados/pendientes/${user.tienda_id}`),
    ])
    setItems(invRes.data)
    setMermas(mermasRes.data)
    setSedes(sedesRes.data)
    setTraslados(trasladosRes.data)
  }

  useEffect(() => { load() }, [user])

  const selected = items.find(i => i.producto_id === productoId)
  const sedesDestino = sedes.filter(s => s.id !== user?.tienda_id)

  const autoMotivo = tipo === 'traslado' && sedeDestinoId
    ? `Traslado a ${sedes.find(s => s.id === sedeDestinoId)?.nombre || 'sede'}`
    : ''

  const motivoFinal = tipo === 'traslado' ? autoMotivo : motivo

  const registrar = async () => {
    setError(''); setSaving(true)
    try {
      await api.post('/mermas/', {
        tienda_id: user?.tienda_id,
        producto_id: productoId,
        cantidad: Number(cantidad),
        motivo: motivoFinal,
        tipo,
        tienda_destino_id: tipo === 'traslado' ? sedeDestinoId : null,
      })
      setProductoId(null); setCantidad(''); setMotivo(''); setSedeDestinoId(null)
      setSaved(true); setTimeout(() => setSaved(false), 2000)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
    finally { setSaving(false) }
  }

  const recibirTraslado = async (id: number) => {
    setRecibiendoId(id)
    try {
      await api.patch(`/mermas/${id}/recibir`)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error al confirmar') }
    finally { setRecibiendoId(null) }
  }

  const cfg = TIPO_CONFIG[tipo]
  const canSubmit = !!productoId && !!cantidad && Number(cantidad) > 0 &&
    Number(cantidad) <= (selected?.stock_actual ?? 0) &&
    (tipo !== 'traslado' || !!sedeDestinoId) &&
    (tipo === 'traslado' || !!motivo) && !saving

  return (
    <BaristaLayout title="Mermas">
      <div className="space-y-5">
        <h1 className="text-xl font-bold text-gray-900">Registrar merma</h1>

        {/* Traslados pendientes por recibir */}
        {traslados.length > 0 && (
          <div className="rounded-2xl border-2 overflow-hidden" style={{ borderColor: 'oklch(55% 0.14 245)' }}>
            <div className="px-4 py-2.5 flex items-center gap-2" style={{ background: 'oklch(95% 0.015 245)' }}>
              <PackageCheck size={15} style={{ color: 'oklch(35% 0.12 245)' }} />
              <p className="text-xs font-bold uppercase tracking-wide" style={{ color: 'oklch(35% 0.12 245)' }}>
                Traslados por recibir ({traslados.length})
              </p>
            </div>
            <div className="divide-y divide-gray-100 bg-white">
              {traslados.map(t => (
                <div key={t.id} className="px-4 py-3 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-800 truncate">{t.producto_nombre}</p>
                    <p className="text-xs text-gray-400 flex items-center gap-1 mt-0.5">
                      <span className="font-medium" style={{ color: 'oklch(35% 0.12 245)' }}>{t.tienda_origen_nombre}</span>
                      <ArrowRight size={10} />
                      <span>esta sede</span>
                      <span className="mx-1">·</span>
                      <span className="font-bold text-gray-700">{t.cantidad} {t.unidad_medida}</span>
                    </p>
                  </div>
                  <button
                    onClick={() => recibirTraslado(t.id)}
                    disabled={recibiendoId === t.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-white disabled:opacity-50 transition-opacity"
                    style={{ background: 'oklch(48% 0.12 155)' }}>
                    <Check size={12} />
                    {recibiendoId === t.id ? '...' : 'Recibido'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Mensajes */}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}
        {saved && (
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">
            <Check size={14} /> Merma registrada
          </div>
        )}

        {/* Selector tipo */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Tipo</p>
          <div className="grid grid-cols-3 gap-2">
            {(Object.keys(TIPO_CONFIG) as Tipo[]).map(t => {
              const c = TIPO_CONFIG[t]
              const active = tipo === t
              return (
                <button key={t}
                  onClick={() => { setTipo(t); setSedeDestinoId(null); setMotivo('') }}
                  className="py-2.5 rounded-xl border-2 text-sm font-bold transition-all"
                  style={active ? {
                    background: c.activeBg,
                    borderColor: c.activeBorder,
                    color: c.activeText,
                  } : {
                    background: 'white',
                    borderColor: 'oklch(88% 0.006 75)',
                    color: 'oklch(40% 0.01 60)',
                  }}>
                  {c.label}
                </button>
              )
            })}
          </div>
        </div>

        {/* Selector sede destino (solo traslado) */}
        {tipo === 'traslado' && (
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Sede destino</p>
            <div className="grid grid-cols-2 gap-2">
              {sedesDestino.map(s => (
                <button key={s.id}
                  onClick={() => setSedeDestinoId(s.id)}
                  className="px-4 py-3 rounded-2xl border-2 text-left transition-all"
                  style={sedeDestinoId === s.id ? {
                    background: 'oklch(95% 0.015 245)',
                    borderColor: 'oklch(55% 0.14 245)',
                  } : {
                    background: 'white',
                    borderColor: 'oklch(88% 0.006 75)',
                  }}>
                  <p className="text-sm font-semibold text-gray-800">{s.nombre}</p>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Selector de producto */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Producto</p>
          <div className="grid grid-cols-2 gap-2">
            {items.map(item => (
              <button key={item.producto_id}
                onClick={() => { setProductoId(item.producto_id); setCantidad(''); setError('') }}
                className="text-left px-4 py-3 rounded-2xl border-2 transition-all"
                style={productoId === item.producto_id ? {
                  background: cfg.activeBg,
                  borderColor: cfg.activeBorder,
                } : {
                  background: 'white',
                  borderColor: 'oklch(88% 0.006 75)',
                }}>
                <p className="text-sm font-semibold text-gray-800 leading-tight">{item.producto_nombre}</p>
                <p className="text-xs mt-0.5 font-medium" style={{ color: item.stock_actual === 0 ? 'oklch(50% 0.18 25)' : 'oklch(58% 0.01 60)' }}>
                  {Math.round(item.stock_actual)} {item.unidad_medida}
                </p>
              </button>
            ))}
          </div>
        </div>

        {/* Formulario */}
        {selected && (
          <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-bold text-gray-800">{selected.producto_nombre}</p>
              <span className="text-xs text-gray-400">Stock: {Math.round(selected.stock_actual)} {selected.unidad_medida}</span>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">
                Cantidad ({selected.unidad_medida})
              </label>
              <input
                type="number"
                value={cantidad}
                onChange={e => setCantidad(e.target.value)}
                placeholder="0"
                max={selected.stock_actual}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-2xl font-bold text-center focus:outline-none transition-colors font-mono"
                style={{ fontFamily: '"JetBrains Mono", monospace' }}
                autoFocus
              />
              {Number(cantidad) > selected.stock_actual && (
                <p className="text-xs text-red-500 mt-1">Supera el stock disponible</p>
              )}
            </div>

            {tipo !== 'traslado' && (
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Motivo</label>
                <input
                  value={motivo}
                  onChange={e => setMotivo(e.target.value)}
                  placeholder={tipo === 'consumo' ? 'Ej: vencido, sobrante...' : 'Ej: caída, mal manejo...'}
                  className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none transition-colors"
                  style={{ outline: 'none' }}
                  onFocus={e => e.target.style.borderColor = cfg.activeBorder}
                  onBlur={e => e.target.style.borderColor = 'oklch(88% 0.006 75)'}
                />
              </div>
            )}

            {tipo === 'traslado' && sedeDestinoId && (
              <div className="rounded-xl p-3 flex items-center gap-3" style={{ background: 'oklch(95% 0.015 245)' }}>
                <ArrowRight size={16} style={{ color: 'oklch(35% 0.12 245)' }} />
                <div>
                  <p className="text-xs font-bold" style={{ color: 'oklch(35% 0.12 245)' }}>Traslado a</p>
                  <p className="text-sm font-semibold text-gray-800">{sedes.find(s => s.id === sedeDestinoId)?.nombre}</p>
                </div>
              </div>
            )}

            <button
              onClick={registrar}
              disabled={!canSubmit}
              className="w-full disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-3.5 rounded-xl text-sm flex items-center justify-center gap-2 transition-opacity"
              style={{ background: canSubmit ? cfg.activeBorder : 'oklch(72% 0.008 60)' }}>
              <Trash2 size={16} />
              {saving ? 'Guardando...' : `Confirmar ${cfg.label.toLowerCase()}`}
            </button>
          </div>
        )}

        {/* Recientes */}
        {mermas.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Recientes</p>
            </div>
            <div className="divide-y divide-gray-50">
              {mermas.slice(0, 15).map(m => {
                const item = items.find(i => i.producto_id === m.producto_id)
                const tipoCfg = TIPO_CONFIG[m.tipo as Tipo] || TIPO_CONFIG.consumo
                const esTraslado = m.tipo === 'traslado'
                return (
                  <div key={m.id} className="px-4 py-3 flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium text-gray-800">
                          {item?.producto_nombre || `#${m.producto_id}`}
                          <span className="ml-2 font-bold" style={{ color: tipoCfg.activeText }}>
                            -{m.cantidad} {item?.unidad_medida}
                          </span>
                        </p>
                        <span className="text-xs px-1.5 py-0.5 rounded-md font-semibold"
                          style={{ background: tipoCfg.activeBg, color: tipoCfg.activeText }}>
                          {tipoCfg.label}
                        </span>
                        {esTraslado && (
                          <span className="text-xs px-1.5 py-0.5 rounded-md font-semibold"
                            style={m.recibido
                              ? { background: 'oklch(93% 0.015 155)', color: 'oklch(35% 0.10 155)' }
                              : { background: 'oklch(95% 0.015 60)', color: 'oklch(45% 0.10 60)' }}>
                            {m.recibido ? 'Recibido' : 'Pendiente'}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-400 mt-0.5 truncate">{m.motivo}</p>
                    </div>
                    <span className="text-xs text-gray-400 shrink-0">
                      {new Date(m.fecha_registro).toLocaleDateString('es-CO')}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </BaristaLayout>
  )
}
