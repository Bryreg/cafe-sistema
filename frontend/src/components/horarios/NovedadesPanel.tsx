import { useEffect, useState } from 'react'
import api from '../../api/client'
import { Info, Loader2, Plus, Trash2 } from 'lucide-react'
import { Aviso } from './SemanaGrid'
import { aISO, type Novedad, type TipoNovedad } from './tipos'

/**
 * Novedades laborales: cargar una y ver las del período.
 *
 * Cada tipo muestra su RAZÓN antes de elegirlo: qué implica para la liquidación
 * no puede ser algo que se descubre a fin de mes.
 */

interface Barista { id: number; nombre: string }
interface Props { tiendaId: number; desde: string; hasta: string }

export default function NovedadesPanel({ tiendaId, desde, hasta }: Props) {
  const [tipos, setTipos] = useState<TipoNovedad[]>([])
  const [baristas, setBaristas] = useState<Barista[]>([])
  const [items, setItems] = useState<Novedad[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [abrir, setAbrir] = useState(false)

  const [usuarioId, setUsuarioId] = useState<number | ''>('')
  const [tipo, setTipo] = useState('incapacidad')
  const [fDesde, setFDesde] = useState(() => aISO(new Date()))
  const [fHasta, setFHasta] = useState(() => aISO(new Date()))
  const [remunerada, setRemunerada] = useState<boolean | null>(null)
  const [nota, setNota] = useState('')

  useEffect(() => {
    api.get<TipoNovedad[]>('/horarios/novedades/tipos')
      .then(r => setTipos(r.data)).catch(() => setTipos([]))
    api.get<Barista[]>('/auth/baristas')
      .then(r => setBaristas(r.data)).catch(() => setBaristas([]))
  }, [])

  const cargar = () => {
    setLoading(true)
    api.get<Novedad[]>('/horarios/novedades',
      { params: { tienda_id: tiendaId, desde, hasta } })
      .then(r => setItems(r.data))
      .catch(() => setError('No se pudieron cargar las novedades.'))
      .finally(() => setLoading(false))
  }
  useEffect(cargar, [tiendaId, desde, hasta])

  const metaTipo = tipos.find(t => t.tipo === tipo)

  const crear = async () => {
    if (!usuarioId) { setError('Elegí a quién le corresponde la novedad.'); return }
    setBusy(true); setError(null)
    try {
      await api.post('/horarios/novedades', {
        tienda_id: tiendaId, usuario_id: usuarioId, tipo,
        fecha_desde: fDesde, fecha_hasta: fHasta,
        remunerada: remunerada === null ? undefined : remunerada,
        nota: nota.trim() || null,
      })
      setAbrir(false); setNota(''); setRemunerada(null)
      cargar()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'No se pudo guardar la novedad.')
    } finally { setBusy(false) }
  }

  const borrar = async (id: number) => {
    setBusy(true)
    try { await api.delete(`/horarios/novedades/${id}`); cargar() }
    catch { setError('No se pudo borrar la novedad.') }
    finally { setBusy(false) }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setAbrir(v => !v)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold bg-forest text-white hover:bg-forest/90"
        >
          <Plus size={14} /> Cargar novedad
        </button>
        <span className="text-xs text-warm-400">
          Del {desde} al {hasta}
        </span>
      </div>

      {error && <Aviso tono="error">{error}</Aviso>}

      {abrir && (
        <div className="bg-white rounded-2xl border border-warm-200 p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs font-semibold text-warm-500">Barista</span>
              <select
                value={usuarioId}
                onChange={e => setUsuarioId(e.target.value ? Number(e.target.value) : '')}
                className="mt-1 w-full border border-warm-200 rounded-lg px-2 py-1.5 text-sm bg-white"
              >
                <option value="">Elegí una…</option>
                {baristas.map(b => <option key={b.id} value={b.id}>{b.nombre}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-warm-500">Tipo</span>
              <select
                value={tipo}
                onChange={e => { setTipo(e.target.value); setRemunerada(null) }}
                className="mt-1 w-full border border-warm-200 rounded-lg px-2 py-1.5 text-sm bg-white"
              >
                {tipos.map(t => <option key={t.tipo} value={t.tipo}>{t.label}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-warm-500">Desde</span>
              <input type="date" value={fDesde} onChange={e => setFDesde(e.target.value)}
                className="mt-1 w-full border border-warm-200 rounded-lg px-2 py-1.5 text-sm" />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-warm-500">Hasta</span>
              <input type="date" value={fHasta} onChange={e => setFHasta(e.target.value)}
                className="mt-1 w-full border border-warm-200 rounded-lg px-2 py-1.5 text-sm" />
            </label>
          </div>

          {metaTipo && (
            <div className="flex items-start gap-2 rounded-xl bg-warm-100 border border-warm-200 px-3 py-2">
              <Info size={14} className="text-warm-500 shrink-0 mt-0.5" />
              <div className="text-xs text-warm-600">
                <p className="font-semibold text-warm-700 mb-0.5">
                  {metaTipo.acredita_horas
                    ? 'Cuenta como tiempo trabajado'
                    : 'No cuenta como tiempo trabajado'}
                </p>
                <p>{metaTipo.razon}</p>
              </div>
            </div>
          )}

          <label className="flex items-center gap-2 text-xs text-warm-600">
            <input
              type="checkbox"
              checked={remunerada === null ? (metaTipo?.remunerada ?? false) : remunerada}
              onChange={e => setRemunerada(e.target.checked)}
              className="h-4 w-4 rounded border-warm-200 text-forest focus:ring-forest"
            />
            Se paga (podés cambiarlo para este caso puntual)
          </label>

          <label className="block">
            <span className="text-xs font-semibold text-warm-500">Nota</span>
            <textarea
              value={nota} onChange={e => setNota(e.target.value)} rows={2}
              placeholder="Opcional: número de incapacidad, quién autorizó, etc."
              className="mt-1 w-full border border-warm-200 rounded-lg px-2 py-1.5 text-sm"
            />
          </label>

          <div className="flex items-center gap-2">
            <button
              onClick={crear} disabled={busy}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold bg-forest text-white hover:bg-forest/90 disabled:opacity-40"
            >
              {busy && <Loader2 size={14} className="animate-spin" />} Guardar
            </button>
            <button
              onClick={() => setAbrir(false)}
              className="px-3 py-2 rounded-xl text-sm font-semibold text-warm-500 hover:bg-warm-100"
            >
              Cancelar
            </button>
          </div>
          <p className="text-[11px] text-warm-400">
            Si la novedad cae sobre un turno que ya le enviaste, a esa barista le llega el aviso.
          </p>
        </div>
      )}

      {loading && <p className="text-sm text-warm-400 py-6 text-center animate-pulse">Cargando…</p>}

      {!loading && items.length === 0 && (
        <div className="bg-white border border-warm-200 rounded-2xl px-4 py-10 text-center">
          <p className="text-sm text-warm-500">No hay novedades cargadas en este período.</p>
        </div>
      )}

      {items.length > 0 && (
        <div className="bg-white rounded-2xl border border-warm-200 divide-y divide-warm-100">
          {items.map(n => (
            <div key={n.id} className="flex items-start gap-3 px-4 py-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-warm-700">
                  {n.nombre} · {n.label}
                </p>
                <p className="text-xs text-warm-500 font-mono">
                  {n.fecha_desde} → {n.fecha_hasta} ({n.dias} día{n.dias > 1 ? 's' : ''})
                </p>
                {n.nota && <p className="text-xs text-warm-400 mt-0.5">{n.nota}</p>}
              </div>
              <span className={`text-[10px] font-semibold px-2 py-1 rounded-full whitespace-nowrap ${
                n.acredita_horas
                  ? 'bg-forest-50 text-forest-700'
                  : 'bg-warm-100 text-warm-500'
              }`}>
                {n.acredita_horas ? 'Cuenta horas' : 'No cuenta horas'}
              </span>
              <button
                onClick={() => borrar(n.id)} disabled={busy}
                className="text-warm-400 hover:text-danger-500 p-1"
                title="Borrar novedad"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
