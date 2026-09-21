import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  Trash2, AlertTriangle, Check, PackageCheck, ArrowRight, Search,
  Coffee, ArrowLeftRight, HeartCrack, ChevronLeft, X, User, Undo2,
} from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface ProductoCat {
  id: number; nombre: string; categoria: string; unidad_medida: string
}
interface Merma {
  id: number; producto_id: number; cantidad: number; motivo: string
  fecha_registro: string; tipo: string; tienda_destino_id?: number
  recibido: boolean; fecha_recibido?: string; quien?: string | null
  producto_nombre?: string | null; unidad_medida?: string | null
  barista_nombre?: string | null
}
interface Sede { id: number; nombre: string }
interface TrasladoPendiente {
  id: number; producto_id: number; producto_nombre: string; unidad_medida: string
  cantidad: number; tienda_origen_id: number; tienda_origen_nombre: string
  fecha_registro: string; motivo: string
}
interface ItemSeleccionado {
  producto: ProductoCat
  cantidad: string
}

type Tipo = 'consumo' | 'traslado' | 'daño'

const TIPOS: { key: Tipo; label: string; desc: string; Icon: typeof Coffee; bg: string; border: string; text: string }[] = [
  { key: 'consumo',  label: 'Consumo',  desc: 'Dueños, reuniones, degustaciones', Icon: Coffee,         bg: 'oklch(96% 0.015 60)',  border: 'oklch(65% 0.13 55)',  text: 'oklch(40% 0.12 55)' },
  { key: 'traslado', label: 'Traslado', desc: 'Enviar producto a otra sede',      Icon: ArrowLeftRight, bg: 'oklch(95% 0.015 245)', border: 'oklch(55% 0.14 245)', text: 'oklch(35% 0.12 245)' },
  { key: 'daño',     label: 'Daño',     desc: 'Producto dañado o vencido',        Icon: HeartCrack,     bg: 'oklch(96% 0.015 20)',  border: 'oklch(58% 0.18 25)',  text: 'oklch(38% 0.16 25)' },
]

const fmtHora = (iso: string) => {
  const s = iso.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  const d = new Date(s.endsWith('Z') ? s : s + 'Z')
  return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}
const esHoyLocal = (iso: string) => {
  const s = iso.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  const d = new Date(s.endsWith('Z') ? s : s + 'Z')
  const h = new Date()
  return d.getFullYear() === h.getFullYear() && d.getMonth() === h.getMonth() && d.getDate() === h.getDate()
}

export default function Mermas() {
  const { user } = useAuth()
  const [vista, setVista] = useState<'menu' | Tipo>('menu')
  const [productos, setProductos] = useState<ProductoCat[]>([])
  const [mermas, setMermas] = useState<Merma[]>([])
  const [sedes, setSedes] = useState<Sede[]>([])
  const [traslados, setTraslados] = useState<TrasladoPendiente[]>([])
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [recibiendoId, setRecibiendoId] = useState<number | null>(null)
  const [anulandoId, setAnulandoId] = useState<number | null>(null)
  const [confirmarAnular, setConfirmarAnular] = useState<Merma | null>(null)
  // Anular es solo del admin (el endpoint también lo exige): devuelve stock y
  // borra el registro, así que no es una acción de operación diaria.
  const esAdmin = user?.rol === 'admin'

  // Formulario del tipo activo
  const [quien, setQuien] = useState('')
  const [sedeDestinoId, setSedeDestinoId] = useState<number | null>(null)
  const [nota, setNota] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [items, setItems] = useState<ItemSeleccionado[]>([])

  const load = async () => {
    if (!user?.tienda_id) return
    try {
      const [prodRes, mermasRes, sedesRes, trasladosRes] = await Promise.all([
        api.get('/inventario/productos'),
        api.get(`/mermas/tienda/${user.tienda_id}`),
        api.get('/mermas/sedes'),
        api.get(`/mermas/traslados/pendientes/${user.tienda_id}`),
      ])
      setProductos(prodRes.data)
      setMermas(mermasRes.data)
      setSedes(sedesRes.data)
      setTraslados(trasladosRes.data)
    } catch (e) { console.error('Error al cargar datos de mermas:', e) }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [user?.tienda_id])

  const abrirTipo = (t: Tipo) => {
    setVista(t); setQuien(''); setSedeDestinoId(null); setNota(''); setBusqueda(''); setItems([]); setError('')
  }

  const agregarProducto = (p: ProductoCat) => {
    if (items.some(i => i.producto.id === p.id)) return
    setItems(prev => [...prev, { producto: p, cantidad: '' }])
    setBusqueda('')
  }

  const setCantidadItem = (id: number, v: string) =>
    setItems(prev => prev.map(i => i.producto.id === id ? { ...i, cantidad: v } : i))

  const quitarItem = (id: number) => setItems(prev => prev.filter(i => i.producto.id !== id))

  const registrar = async () => {
    if (vista === 'menu') return
    setError(''); setSaving(true)
    const destinoNombre = sedes.find(s => s.id === sedeDestinoId)?.nombre || 'sede'
    const motivo = vista === 'consumo'
      ? (nota.trim() || `Consumo de ${quien.trim()}`)
      : vista === 'traslado'
      ? (nota.trim() || `Traslado a ${destinoNombre}`)
      : nota.trim()
    try {
      let enviados = 0
      for (const it of items) {
        const payload = {
          tienda_id: user?.tienda_id,
          producto_id: it.producto.id,
          cantidad: Number(it.cantidad),
          motivo,
          tipo: vista,
          tienda_destino_id: vista === 'traslado' ? sedeDestinoId : null,
          quien: vista === 'consumo' ? quien.trim() : null,
        }
        try {
          await api.post('/mermas/', payload)
          enviados++
        } catch (err: any) {
          // 409 = guard anti-doble-envío: el mismo traslado ya salió hace un momento.
          // Confirmar reenvía; cancelar saltea este ítem (los demás siguen).
          if (err.response?.status === 409) {
            if (window.confirm(err.response.data?.detail || '¿Enviar de nuevo este traslado?')) {
              await api.post('/mermas/', { ...payload, confirmar: true })
              enviados++
            }
            continue
          }
          throw err
        }
      }
      // Solo confirmar si realmente se registró algo (si canceló todos los
      // reenvíos, no mostrar el "Registrado correctamente" ni resetear).
      if (enviados > 0) {
        setSaved(true); setTimeout(() => setSaved(false), 2500)
        setVista('menu')
      }
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error al registrar') }
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

  // Anular devuelve al inventario lo que la merma descontó y borra el registro.
  // Existe por el doble toque: guardar el mismo formulario dos veces descontaba
  // dos veces y no había forma de deshacerlo, así que el faltante aparecía días
  // después en un conteo sin que nadie pudiera explicarlo.
  const anular = async (m: Merma) => {
    setAnulandoId(m.id)
    setConfirmarAnular(null)
    try {
      await api.delete(`/mermas/${m.id}/anular`)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error al anular') }
    finally { setAnulandoId(null) }
  }

  const norm = (s: string) => s.toUpperCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
  const resultados = busqueda.trim().length >= 2
    ? productos.filter(p => norm(p.nombre).includes(norm(busqueda))).slice(0, 8)
    : []

  const itemsValidos = items.length > 0 && items.every(i => Number(i.cantidad) > 0)
  const canSubmit = !saving && itemsValidos &&
    (vista !== 'consumo' || quien.trim() !== '') &&
    (vista !== 'traslado' || !!sedeDestinoId) &&
    (vista !== 'daño' || nota.trim() !== '')

  const mermasHoy = mermas.filter(m => esHoyLocal(m.fecha_registro))
  const tipoCfg = TIPOS.find(t => t.key === vista)

  // ── Pantalla del tipo (consumo / traslado / daño) ──────────────────────────
  if (vista !== 'menu' && tipoCfg) {
    return (
      <BaristaLayout title={`Mermas · ${tipoCfg.label}`}>
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <button onClick={() => setVista('menu')} className="p-2 rounded-xl bg-gray-100" aria-label="Volver">
              <ChevronLeft size={16} className="text-gray-600" />
            </button>
            <div className="flex items-center gap-2">
              <tipoCfg.Icon size={18} style={{ color: tipoCfg.text }} />
              <h1 className="text-lg font-bold" style={{ color: tipoCfg.text }}>{tipoCfg.label}</h1>
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
              <AlertTriangle size={14} /> {error}
            </div>
          )}

          {vista === 'consumo' && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">¿Quién consumió?</p>
              <div className="relative">
                <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input value={quien} onChange={e => setQuien(e.target.value)}
                  placeholder="Nombre (dueño, reunión, degustación...)"
                  className="w-full pl-9 pr-3 py-3 rounded-xl border-2 border-gray-200 text-sm font-semibold focus:outline-none"
                  style={{ borderColor: quien ? tipoCfg.border : undefined }} />
              </div>
            </div>
          )}

          {vista === 'traslado' && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Sede destino</p>
              <div className="grid grid-cols-2 gap-2">
                {sedes.filter(s => s.id !== user?.tienda_id).map(s => (
                  <button key={s.id} onClick={() => setSedeDestinoId(s.id)}
                    className="py-3 rounded-xl border-2 text-sm font-bold"
                    style={sedeDestinoId === s.id
                      ? { background: tipoCfg.bg, borderColor: tipoCfg.border, color: tipoCfg.text }
                      : { background: 'white', borderColor: 'oklch(88% 0.006 75)', color: 'oklch(40% 0.01 60)' }}>
                    {s.nombre}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Buscador de productos (todo el catálogo: bebidas, panadería, pastelería, insumos) */}
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Productos</p>
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input value={busqueda} onChange={e => setBusqueda(e.target.value)}
                placeholder="Buscar producto..."
                className="w-full pl-9 pr-3 py-3 rounded-xl border-2 border-gray-200 text-sm focus:outline-none" />
            </div>
            {resultados.length > 0 && (
              <div className="mt-1 rounded-xl border border-gray-200 bg-white divide-y divide-gray-50 overflow-hidden shadow-sm">
                {resultados.map(p => (
                  <button key={p.id} onClick={() => agregarProducto(p)}
                    className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-gray-50">
                    <span className="text-sm font-semibold text-gray-800">{p.nombre}</span>
                    <span className="text-xs text-gray-400">{p.categoria} · {p.unidad_medida}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Items seleccionados con cantidades */}
          {items.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white divide-y divide-gray-50 overflow-hidden">
              {items.map(i => (
                <div key={i.producto.id} className="flex items-center gap-2 px-4 py-2.5">
                  <span className="flex-1 text-sm font-semibold text-gray-800 truncate">{i.producto.nombre}</span>
                  <input type="number" inputMode="decimal" min={0} value={i.cantidad}
                    onChange={e => setCantidadItem(i.producto.id, e.target.value)}
                    placeholder="0" autoFocus={i.cantidad === ''}
                    className="w-20 text-right rounded-lg border-2 border-gray-200 px-2 py-1.5 text-sm font-bold focus:outline-none font-mono" />
                  <span className="text-xs text-gray-400 w-8">{i.producto.unidad_medida}</span>
                  <button onClick={() => quitarItem(i.producto.id)} className="p-1 text-gray-300 hover:text-red-500" aria-label="Quitar">
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              {vista === 'daño' ? 'Motivo (obligatorio)' : 'Nota (opcional)'}
            </p>
            <input value={nota} onChange={e => setNota(e.target.value)}
              placeholder={vista === 'daño' ? '¿Qué pasó?' : 'Detalle adicional...'}
              className="w-full px-4 py-3 rounded-xl border-2 border-gray-200 text-sm focus:outline-none" />
          </div>

          <button onClick={registrar} disabled={!canSubmit}
            className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40"
            style={{ background: tipoCfg.border }}>
            {saving ? 'Registrando...'
              : items.length === 0 ? 'Agregá al menos un producto'
              : `Registrar ${tipoCfg.label.toLowerCase()} (${items.length})`}
          </button>
        </div>
      </BaristaLayout>
    )
  }

  // ── Menú principal: 3 tarjetas + revisión del día ──────────────────────────
  return (
    <BaristaLayout title="Mermas">
      <div className="space-y-5">
        <h1 className="text-xl font-bold text-gray-900">Mermas</h1>

        {saved && (
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">
            <Check size={14} /> Registrado correctamente
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

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

        {/* Las 3 opciones — sin lista de stock debajo */}
        <div className="space-y-2.5">
          {TIPOS.map(t => (
            <button key={t.key} onClick={() => abrirTipo(t.key)}
              className="w-full flex items-center gap-4 px-5 py-4 rounded-2xl border-2 text-left transition-all active:scale-[0.99]"
              style={{ background: 'white', borderColor: 'oklch(90% 0.008 75)' }}>
              <span className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0" style={{ background: t.bg }}>
                <t.Icon size={20} style={{ color: t.text }} />
              </span>
              <span className="flex-1">
                <span className="block text-[15px] font-bold text-gray-800">{t.label}</span>
                <span className="block text-xs text-gray-400 mt-0.5">{t.desc}</span>
              </span>
              <ArrowRight size={16} className="text-gray-300" />
            </button>
          ))}
        </div>

        {/* Revisión: registradas hoy */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Registradas hoy ({mermasHoy.length})
          </p>
          {mermasHoy.length === 0 ? (
            <div className="rounded-xl border border-dashed border-gray-200 px-4 py-6 text-center">
              <Trash2 size={18} className="text-gray-300 mx-auto mb-1" />
              <p className="text-xs text-gray-400">Sin mermas registradas hoy</p>
            </div>
          ) : (
            <div className="rounded-xl border border-gray-200 bg-white divide-y divide-gray-50 overflow-hidden">
              {mermasHoy.map(m => {
                const t = TIPOS.find(x => x.key === (m.tipo as Tipo))
                return (
                  <div key={m.id} className="px-4 py-2.5 flex items-center gap-3">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0"
                      style={{ background: t?.bg ?? '#f3f4f6', color: t?.text ?? '#374151' }}>
                      {t?.label ?? m.tipo}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-gray-800 truncate">{m.producto_nombre ?? `#${m.producto_id}`}</p>
                      <p className="text-[11px] text-gray-400 truncate">
                        {fmtHora(m.fecha_registro)}
                        {m.quien ? ` · consumió ${m.quien}` : ''}
                        {m.barista_nombre ? ` · registró ${m.barista_nombre}` : ''}
                      </p>
                    </div>
                    <span className="text-sm font-bold font-mono text-gray-700 shrink-0">
                      {m.cantidad} {m.unidad_medida ?? ''}
                    </span>
                    {esAdmin && (
                      <button
                        onClick={() => setConfirmarAnular(m)}
                        disabled={anulandoId === m.id}
                        title="Anular y devolver al inventario"
                        className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center border transition-colors disabled:opacity-40"
                        style={{ borderColor: 'oklch(88% 0.01 75)', color: 'oklch(52% 0.13 25)' }}
                      >
                        <Undo2 size={15} />
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Confirmar anulación: devuelve stock y borra el registro, así que se pregunta. */}
        {confirmarAnular && (
          <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center px-4 pb-6 sm:pb-0"
            style={{ background: 'rgba(0,0,0,0.35)' }} onClick={() => setConfirmarAnular(null)}>
            <div className="w-full max-w-sm rounded-2xl bg-white p-5" onClick={e => e.stopPropagation()}>
              <div className="flex items-start gap-3 mb-3">
                <span className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                  style={{ background: 'oklch(95% 0.03 25)' }}>
                  <Undo2 size={18} style={{ color: 'oklch(52% 0.13 25)' }} />
                </span>
                <div className="min-w-0">
                  <p className="text-[15px] font-bold text-gray-800">Anular esta merma</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {confirmarAnular.producto_nombre ?? `#${confirmarAnular.producto_id}`}
                    {' · '}{confirmarAnular.cantidad} {confirmarAnular.unidad_medida ?? ''}
                  </p>
                </div>
              </div>
              <p className="text-[13px] text-gray-600 mb-4">
                Devuelve al inventario exactamente lo que descontó y borra el registro.
                Queda en el historial de movimientos como «Anulación».
              </p>
              <div className="flex gap-2">
                <button onClick={() => setConfirmarAnular(null)}
                  className="flex-1 py-2.5 rounded-xl border text-sm font-semibold text-gray-600"
                  style={{ borderColor: 'oklch(90% 0.008 75)' }}>
                  Cancelar
                </button>
                <button onClick={() => anular(confirmarAnular)}
                  disabled={anulandoId === confirmarAnular.id}
                  className="flex-1 py-2.5 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                  style={{ background: 'oklch(52% 0.13 25)' }}>
                  {anulandoId === confirmarAnular.id ? 'Anulando...' : 'Anular'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </BaristaLayout>
  )
}
