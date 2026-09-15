import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import {
  ArrowLeft, Plus, Trash2, AlertTriangle, Check, CalendarClock, Wrench, ListChecks,
} from 'lucide-react'

interface Sede { id: number; nombre: string }
interface Item {
  producto_id: number
  nombre: string
  unidad_medida: string
  proveedor: string
  tienda_ids: number[]
  /** false = este renglón NO le llega a todas las sedes */
  en_todas: boolean
}
interface Formato {
  tiendas: Sede[]
  dias: number[]
  nombres_dias: string[]
  items: Item[]
}
interface ProductoOpt { id: number; nombre: string; unidad_medida: string; grupo_conteo: string | null }
interface Pendiente { pendiente: boolean; solicitud_id?: number; automatica?: boolean; fecha_solicitud?: string }

const DIAS_CORTOS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

/**
 * Qué lleva el formato de desechables, y qué días sale solo.
 *
 * No existía: los items del formato son los productos con
 * `grupo_conteo='desechables'`, y eso solo se podía cambiar en la base. Agregar
 * un vaso nuevo al conteo era un UPDATE a mano.
 *
 * La columna de sedes no es informativa, es la guarda del problema real: la
 * lista que ve cada sede sale de cruzar esos productos con SU tabla de
 * inventario, así que un desechable sin fila en una sede no aparece en su
 * formato — y las dos pantallas del kiosko se ven perfectas por separado, así
 * que la divergencia no se nota desde ninguna de las dos.
 */
export default function FormatoDesechables() {
  const [f, setF] = useState<Formato | null>(null)
  const [productos, setProductos] = useState<ProductoOpt[]>([])
  const [loading, setLoading] = useState(true)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [buscar, setBuscar] = useState('')
  const [agregando, setAgregando] = useState(false)
  // Qué tiene abierto cada sede ahora mismo. Un formato pedido y nunca
  // respondido le queda en ámbar a la barista y bloquea el arranque de uno
  // nuevo, así que hay que poder verlo y retirarlo desde acá.
  const [abiertos, setAbiertos] = useState<Record<number, Pendiente>>({})

  const cargar = async () => {
    try {
      const [ff, pp] = await Promise.all([
        api.get<Formato>('/conteos/desechables/formato'),
        api.get<ProductoOpt[]>('/inventario/productos'),
      ])
      setF(ff.data)
      setProductos(pp.data)
      const estados = await Promise.all(ff.data.tiendas.map(t =>
        api.get<Pendiente>(`/conteos/desechables/pendiente/${t.id}`)
          .then(r => [t.id, r.data] as const)
          .catch(() => [t.id, { pendiente: false }] as const)))
      setAbiertos(Object.fromEntries(estados))
    } catch {
      setError('No se pudo cargar el formato')
    } finally { setLoading(false) }
  }
  useEffect(() => { cargar() }, [])

  const avisar = (t: string) => { setMsg(t); setTimeout(() => setMsg(''), 2500) }

  const enElFormato = useMemo(
    () => new Set((f?.items ?? []).map(i => i.producto_id)), [f])

  const candidatos = useMemo(() => {
    const q = buscar.trim().toLowerCase()
    if (!q) return []
    return productos
      .filter(p => !enElFormato.has(p.id) && p.nombre.toLowerCase().includes(q))
      .slice(0, 12)
  }, [buscar, productos, enElFormato])

  const agregar = async (producto_id: number) => {
    setOcupado(true); setError('')
    try {
      const fd = new FormData()
      fd.append('producto_id', String(producto_id))
      const r = await api.post<Formato>('/conteos/desechables/formato/items', fd)
      setF(r.data); setBuscar(''); setAgregando(false)
      avisar('Agregado en las dos sedes')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo agregar')
    } finally { setOcupado(false) }
  }

  const quitar = async (it: Item) => {
    if (!window.confirm(`¿Sacar «${it.nombre}» del formato de desechables?\n\n`
      + 'Deja de pedirse en este conteo. Su stock y su histórico NO se borran.')) return
    setOcupado(true); setError('')
    try {
      const r = await api.delete<Formato>(`/conteos/desechables/formato/items/${it.producto_id}`)
      setF(r.data)
      avisar('Sacado del formato')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo quitar')
    } finally { setOcupado(false) }
  }

  const sincronizar = async () => {
    setOcupado(true); setError('')
    try {
      const r = await api.post<Formato & { filas_creadas: string[] }>(
        '/conteos/desechables/formato/sincronizar')
      setF(r.data)
      avisar(r.data.filas_creadas.length
        ? `${r.data.filas_creadas.length} renglón(es) igualados entre sedes`
        : 'Ya estaba igual en todas las sedes')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo sincronizar')
    } finally { setOcupado(false) }
  }

  const cancelar = async (sede: Sede) => {
    if (!window.confirm(`¿Retirar el formato pendiente de ${sede.nombre}?\n\n`
      + 'Le desaparece de la pantalla a la barista y NO queda como contado: '
      + 'esos días no van a tener medición, y así es como debe verse.')) return
    setOcupado(true); setError('')
    try {
      const fd = new FormData()
      fd.append('tienda_id', String(sede.id))
      await api.post('/conteos/desechables/cancelar', fd)
      setAbiertos(a => ({ ...a, [sede.id]: { pendiente: false } }))
      avisar(`Formato de ${sede.nombre} retirado`)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo cancelar')
    } finally { setOcupado(false) }
  }

  const toggleDia = async (d: number) => {
    if (!f) return
    const nuevos = f.dias.includes(d) ? f.dias.filter(x => x !== d) : [...f.dias, d].sort()
    setOcupado(true); setError('')
    try {
      const fd = new FormData()
      fd.append('dias', JSON.stringify(nuevos))
      await api.put('/conteos/desechables/programacion', fd)
      setF({ ...f, dias: nuevos })
      avisar(nuevos.length ? 'Programación guardada' : 'Programación apagada')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo guardar la programación')
    } finally { setOcupado(false) }
  }

  if (loading) return <p className="text-sm text-gray-400 text-center py-12">Cargando formato...</p>
  if (!f) return <p className="text-sm text-red-500 text-center py-12">{error || 'Sin datos'}</p>

  const desalineados = f.items.filter(i => !i.en_todas)
  const porProveedor = f.items.reduce<Record<string, Item[]>>((acc, i) => {
    (acc[i.proveedor] = acc[i.proveedor] ?? []).push(i)
    return acc
  }, {})

  return (
    <div className="space-y-5">
      <div>
        <Link to="/conteos-admin" className="text-xs text-gray-400 hover:text-gray-700 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} /> Conteos
        </Link>
        <h1 className="text-2xl font-bold text-gray-900">Formato de desechables</h1>
        <p className="text-sm text-gray-500 mt-1">
          Qué se le pide contar a las baristas. <strong>El conteo lo arranca la barista</strong> desde
          su hub, cuando tiene un momento tranquilo. Los desechables no entran en el conteo diario:
          si nadie arranca este formato, esos días no quedan medidos.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-red-600">
          <AlertTriangle size={14} /> {error}
        </div>
      )}
      {msg && (
        <div className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl bg-green-50 border border-green-200 text-green-700">
          <Check size={14} /> {msg}
        </div>
      )}

      {/* ── Programación ───────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 p-5">
        <p className="text-sm font-bold text-gray-800 flex items-center gap-1.5">
          <CalendarClock size={15} style={{ color: 'oklch(48% 0.12 155)' }} />
          Red de seguridad <span className="text-[11px] font-semibold text-gray-400">(opcional)</span>
        </p>
        <p className="text-xs text-gray-400 mt-1 mb-3">
          Normalmente esto va apagado: el conteo lo arranca la barista. Si marcás días, el
          formato aparece solo esos días cuando la sede abre —<strong>únicamente si nadie lo
          arrancó ya</strong>— y sirve de piso para que no se pase una semana sin medición.
        </p>
        <div className="flex gap-2 flex-wrap">
          {DIAS_CORTOS.map((nombre, d) => {
            const on = f.dias.includes(d)
            return (
              <button key={d} onClick={() => toggleDia(d)} disabled={ocupado}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold border-2 transition-colors disabled:opacity-50 ${
                  on ? 'bg-green-50 text-green-700 border-green-400'
                     : 'bg-white text-gray-400 border-gray-200 hover:border-green-300'}`}>
                {nombre}
              </button>
            )
          })}
        </div>
        {f.dias.length === 0 && (
          <p className="text-xs text-gray-400 mt-3">
            Apagada. El formato sale cuando la barista lo arranca, o cuando lo pedís desde Conteos.
          </p>
        )}
      </div>

      {/* ── Qué tiene abierto cada sede ────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 p-5">
        <p className="text-sm font-bold text-gray-800">Formatos abiertos ahora</p>
        <p className="text-xs text-gray-400 mt-1 mb-3">
          Un formato pedido y nunca respondido le queda en ámbar a la barista y le bloquea
          arrancar uno nuevo. Retirarlo no lo cuenta como hecho.
        </p>
        <div className="space-y-2">
          {f.tiendas.map(t => {
            const p = abiertos[t.id]
            return (
              <div key={t.id} className="flex items-center gap-3 flex-wrap">
                <span className="text-sm font-semibold text-gray-700 w-24">{t.nombre}</span>
                {p?.pendiente ? (
                  <>
                    <span className="text-xs px-2 py-0.5 rounded-full font-semibold bg-amber-100 text-amber-700">
                      pendiente desde {p.fecha_solicitud
                        ? new Date(p.fecha_solicitud).toLocaleString('es-CO',
                            { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
                        : '—'}
                    </span>
                    <button onClick={() => cancelar(t)} disabled={ocupado}
                      className="text-xs font-semibold px-3 py-1 rounded-lg border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50">
                      Retirar
                    </button>
                  </>
                ) : (
                  <span className="text-xs text-gray-400">sin formato abierto</span>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Divergencia entre sedes ────────────────────────────────────── */}
      {desalineados.length > 0 && (
        <div className="rounded-2xl border-2 border-amber-300 bg-amber-50 p-5">
          <p className="text-sm font-bold text-amber-800 flex items-center gap-1.5">
            <AlertTriangle size={15} /> El formato NO es el mismo en las dos sedes
          </p>
          <p className="text-xs text-amber-700 mt-1">
            {desalineados.length} renglón(es) le faltan a alguna sede, así que esa sede está
            contando una lista distinta y la comparación entre sedes no dice lo que parece.
          </p>
          <ul className="mt-2 space-y-0.5">
            {desalineados.map(i => (
              <li key={i.producto_id} className="text-xs text-amber-800">
                · <strong>{i.nombre}</strong> — solo en{' '}
                {i.tienda_ids.map(id => f.tiendas.find(t => t.id === id)?.nombre).join(', ') || 'ninguna'}
              </li>
            ))}
          </ul>
          <button onClick={sincronizar} disabled={ocupado}
            className="mt-3 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-white disabled:opacity-50"
            style={{ background: 'oklch(56% 0.14 65)' }}>
            <Wrench size={13} /> Igualar en todas las sedes
          </button>
        </div>
      )}

      {/* ── Items ──────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200">
        <div className="px-5 py-4 flex items-center justify-between gap-3 flex-wrap border-b border-gray-100">
          <p className="text-sm font-bold text-gray-800 flex items-center gap-1.5">
            <ListChecks size={15} style={{ color: 'oklch(48% 0.12 155)' }} />
            {f.items.length} items en el formato
          </p>
          <button onClick={() => setAgregando(a => !a)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-white"
            style={{ background: 'oklch(48% 0.12 155)' }}>
            <Plus size={13} /> Agregar item
          </button>
        </div>

        {agregando && (
          <div className="px-5 py-4 border-b border-gray-100 bg-gray-50">
            <input value={buscar} onChange={e => setBuscar(e.target.value)} autoFocus
              placeholder="Buscar el producto por nombre…"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
            <p className="text-[11px] text-gray-400 mt-1.5">
              Al agregarlo se le crea la existencia en las dos sedes y se lo saca del conteo
              diario, para que no se cuente dos veces.
            </p>
            {buscar.trim() && candidatos.length === 0 && (
              <p className="text-xs text-gray-400 mt-2">
                Sin resultados. Si el producto no existe todavía, crealo primero en Catálogo.
              </p>
            )}
            <div className="mt-2 space-y-1">
              {candidatos.map(p => (
                <button key={p.id} onClick={() => agregar(p.id)} disabled={ocupado}
                  className="w-full text-left px-3 py-2 rounded-lg text-xs bg-white border border-gray-200 hover:border-green-400 disabled:opacity-50 flex items-center justify-between gap-2">
                  <span className="font-semibold text-gray-700">{p.nombre}</span>
                  <span className="text-gray-400">{p.unidad_medida}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {f.items.length === 0 && (
          <p className="text-sm text-gray-400 text-center py-10">
            El formato está vacío — no hay nada que contar.
          </p>
        )}

        <div className="divide-y divide-gray-50">
          {Object.entries(porProveedor).map(([proveedor, items]) => (
            <div key={proveedor} className="px-5 py-3">
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wide mb-1.5">
                {proveedor}
              </p>
              <div className="space-y-1">
                {items.map(i => (
                  <div key={i.producto_id} className="flex items-center gap-3 py-1">
                    <span className="flex-1 min-w-0 text-sm text-gray-700">
                      {i.nombre}
                      <span className="text-gray-400 text-xs"> · {i.unidad_medida}</span>
                    </span>
                    <span className="flex gap-1 shrink-0">
                      {f.tiendas.map(t => {
                        const on = i.tienda_ids.includes(t.id)
                        return (
                          <span key={t.id} title={on ? `Le llega a ${t.nombre}` : `NO le llega a ${t.nombre}`}
                            className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                              on ? 'bg-green-50 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
                            {t.nombre}{on ? '' : ' ✕'}
                          </span>
                        )
                      })}
                    </span>
                    <button onClick={() => quitar(i)} disabled={ocupado}
                      title="Sacar del formato (no borra stock ni histórico)"
                      className="text-red-300 hover:text-red-600 disabled:opacity-50 shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
