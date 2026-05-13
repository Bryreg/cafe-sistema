import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Banknote, Upload, AlertTriangle, Check, ImageIcon, ChevronDown, ChevronUp, X } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface TurnoPendiente {
  turno_id: number
  fecha_apertura: string
  fecha_cierre: string
  esperado: number
  consignado: number
  pendiente: number
}

interface Pendiente {
  items: TurnoPendiente[]
  total_pendiente: number
}

interface Consignacion {
  id: number; valor: number; imagen_url: string | null
  estado: string; fecha: string
}

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
const parseUTC = (f: string) => {
  const s = f.replace(' ', 'T').replace('+00:00', 'Z')
  return new Date(s.endsWith('Z') ? s : s + 'Z')
}

function estadoBadge(estado: string) {
  const map: Record<string, string> = {
    pendiente: 'bg-amber-100 text-amber-700',
    realizada: 'bg-green-100 text-green-700',
  }
  return map[estado] || 'bg-gray-100 text-gray-500'
}

export default function Consignaciones() {
  const { user } = useAuth()
  const [pendiente, setPendiente] = useState<Pendiente | null>(null)
  const [lista, setLista] = useState<Consignacion[]>([])
  const [valor, setValor] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [showDetalle, setShowDetalle] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    if (!user?.tienda_id) return
    const [pendRes, listaRes] = await Promise.all([
      api.get(`/consignaciones/pendiente/${user.tienda_id}`),
      api.get(`/consignaciones/tienda/${user.tienda_id}`),
    ])
    const p: Pendiente = pendRes.data
    setPendiente(p)
    setLista(listaRes.data)
    if (p.total_pendiente > 0) setValor(String(p.total_pendiente))
  }

  useEffect(() => { load() }, [user])

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setArchivo(f)
    setPreview(URL.createObjectURL(f))
  }

  const guardar = async () => {
    setError(''); setSaving(true)
    try {
      const form = new FormData()
      form.append('tienda_id', String(user?.tienda_id))
      form.append('valor', valor)
      if (archivo) form.append('imagen', archivo)
      await api.post('/consignaciones/', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      setValor(''); setArchivo(null); setPreview(null)
      setSaved(true); setTimeout(() => setSaved(false), 3000)
      load()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar')
    } finally {
      setSaving(false)
    }
  }

  const totalPendiente = pendiente?.total_pendiente ?? 0
  const hayPendiente = totalPendiente > 0
  const canSave = !!valor && Number(valor) > 0 && !!archivo && !saving

  return (
    <BaristaLayout title="Consignaciones">
      <div className="space-y-4">

        {/* ── Monto por consignar ── */}
        {pendiente !== null && (
          <div className={`rounded-2xl p-4 ${
            hayPendiente
              ? 'bg-amber-50 border border-amber-200'
              : 'bg-green-50 border border-green-200'
          }`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className={`text-[10px] font-bold uppercase tracking-widest mb-1 ${
                  hayPendiente ? 'text-amber-600' : 'text-green-600'
                }`}>
                  {hayPendiente ? 'Por consignar' : 'Al día'}
                </p>
                <p className={`text-[34px] font-bold font-mono leading-none ${
                  hayPendiente ? 'text-amber-700' : 'text-green-700'
                }`} style={{ letterSpacing: '-1px' }}>
                  {fmt(totalPendiente)}
                </p>
                {!hayPendiente && (
                  <p className="text-xs text-green-600 mt-1">
                    Todas las consignaciones están al día
                  </p>
                )}
              </div>
              {hayPendiente && pendiente.items.length > 1 && (
                <button
                  onClick={() => setShowDetalle(v => !v)}
                  className="flex items-center gap-1 text-xs font-semibold text-amber-600 mt-1 shrink-0"
                >
                  {pendiente.items.length} turnos
                  {showDetalle ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>
              )}
            </div>

            {/* Desglose por turno */}
            {hayPendiente && (showDetalle || pendiente.items.length === 1) && (
              <div className="mt-3 space-y-2.5">
                {pendiente.items.map(item => (
                  <div key={item.turno_id} className="pt-2.5 border-t border-amber-200">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-xs font-semibold text-amber-800">
                          Cierre {parseUTC(item.fecha_cierre).toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })} ·{' '}
                          {parseUTC(item.fecha_cierre).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                        </p>
                        <div className="flex gap-3 mt-0.5">
                          <span className="text-[11px] text-amber-600">
                            Esperado: <span className="font-mono font-bold">{fmt(item.esperado)}</span>
                          </span>
                          {item.consignado > 0 && (
                            <span className="text-[11px] text-green-600">
                              Consignado: <span className="font-mono font-bold">{fmt(item.consignado)}</span>
                            </span>
                          )}
                        </div>
                      </div>
                      <span className="text-sm font-bold font-mono text-amber-700 shrink-0">
                        {fmt(item.pendiente)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Mensajes ── */}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}
        {saved && (
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">
            <Check size={14} /> Consignación registrada correctamente
          </div>
        )}

        {/* ── Formulario ── */}
        <div className="bg-white rounded-2xl border border-warm-200 p-5 space-y-4">
          <p className="text-sm font-bold text-warm-700">Registrar consignación</p>

          {/* Valor — pre-filled */}
          <div>
            <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1.5">
              Valor
              {hayPendiente && (
                <span className="ml-1.5 normal-case font-normal text-amber-500">
                  — calculado del cierre
                </span>
              )}
            </label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-2xl font-bold text-warm-300">$</span>
              <input
                type="number"
                value={valor}
                onChange={e => setValor(e.target.value)}
                placeholder="0"
                inputMode="numeric"
                className="w-full pl-12 pr-4 py-4 text-3xl font-bold font-mono border-2 border-warm-200 rounded-xl focus:outline-none focus:border-amber-400 transition-colors text-warm-700"
              />
            </div>
            {hayPendiente && (
              <p className="text-[11px] text-warm-400 mt-1">
                Puedes ajustar si vas a hacer la consignación en partes.
              </p>
            )}
          </div>

          {/* Soporte bancario — required */}
          <div>
            <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1.5">
              Soporte bancario
              {!archivo && (
                <span className="ml-1.5 normal-case font-normal text-red-400">requerido</span>
              )}
            </label>
            <input ref={fileRef} type="file" accept="image/*" onChange={onFile} className="hidden" />
            {preview ? (
              <div className="relative">
                <img src={preview} alt="preview" className="w-full h-36 object-cover rounded-xl border-2 border-amber-300" />
                <button
                  onClick={() => { setArchivo(null); setPreview(null) }}
                  className="absolute top-2 right-2 bg-black/60 text-white rounded-full w-7 h-7 flex items-center justify-center"
                >
                  <X size={13} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => fileRef.current?.click()}
                className="w-full h-28 border-2 border-dashed border-warm-200 rounded-xl flex flex-col items-center justify-center gap-2 hover:border-amber-400 hover:bg-amber-50 transition-colors"
              >
                <Upload size={22} className="text-warm-300" />
                <span className="text-xs text-warm-400 font-medium">Toca para fotografiar el comprobante</span>
              </button>
            )}
          </div>

          <button
            onClick={guardar}
            disabled={!canSave}
            className="w-full disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-3.5 rounded-xl text-sm flex items-center justify-center gap-2 transition-colors"
            style={{ background: canSave ? 'oklch(58% 0.13 65)' : 'oklch(75% 0.06 65)' }}
          >
            <Banknote size={16} />
            {saving ? 'Guardando...' : 'Registrar consignación'}
          </button>

          {!archivo && (
            <p className="text-center text-[11px] text-warm-400">
              Adjunta la foto del comprobante bancario para continuar
            </p>
          )}
        </div>

        {/* ── Historial ── */}
        {lista.length > 0 && (
          <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-warm-100">
              <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide">Historial</p>
            </div>
            <div className="divide-y divide-warm-50">
              {lista.map(c => (
                <div key={c.id} className="px-4 py-3 flex items-center gap-3">
                  {c.imagen_url
                    ? <img src={c.imagen_url} className="w-10 h-10 rounded-lg object-cover border border-warm-200 shrink-0" alt="" />
                    : <div className="w-10 h-10 rounded-lg bg-warm-100 flex items-center justify-center shrink-0">
                        <ImageIcon size={16} className="text-warm-400" />
                      </div>
                  }
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold text-warm-700">{fmt(c.valor)}</p>
                    <p className="text-xs text-warm-400">
                      {parseUTC(c.fecha).toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })} ·{' '}
                      {parseUTC(c.fecha).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${estadoBadge(c.estado)}`}>
                    {c.estado}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </BaristaLayout>
  )
}
