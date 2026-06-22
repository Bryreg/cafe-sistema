import { useRef, useState } from 'react'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { TrendingUp, TrendingDown, Upload, X as XIcon } from 'lucide-react'

interface Props { turnoId: number; onClose: () => void }

export default function MovimientoCajaModal({ turnoId, onClose }: Props) {
  const { refresh } = useTurno()
  const [tipo, setTipo] = useState<'ingreso' | 'egreso'>('ingreso')
  const [concepto, setConcepto] = useState('')
  const [valor, setValor] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setArchivo(f)
    setPreview(URL.createObjectURL(f))
  }

  const guardar = async () => {
    setError(''); setLoading(true)
    try {
      const form = new FormData()
      form.append('tipo', tipo)
      form.append('concepto', concepto)
      form.append('valor', valor)
      if (archivo) form.append('imagen', archivo)
      await api.post(`/caja/${turnoId}/movimiento`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      await refresh()
      onClose()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end justify-center">
      <div className="bg-white w-full max-w-md rounded-t-3xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-base font-bold text-warm-700">Movimiento de caja</p>
          <button onClick={onClose} className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors">
            <XIcon size={18} />
          </button>
        </div>

        {error && <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-xl">{error}</p>}

        {/* Tipo */}
        <div className="flex gap-2">
          {(['ingreso', 'egreso'] as const).map(t => (
            <button key={t} onClick={() => setTipo(t)}
              className={`flex-1 py-2.5 rounded-xl text-sm font-semibold border-2 transition-colors ${
                tipo === t
                  ? t === 'ingreso'
                    ? 'bg-green-100 border-green-400 text-green-700'
                    : 'bg-red-100 border-red-400 text-red-700'
                  : 'border-warm-200 text-warm-400'
              }`}
            >
              {t === 'ingreso'
                ? <><TrendingUp size={13} className="inline mr-1" />Ingreso</>
                : <><TrendingDown size={13} className="inline mr-1" />Egreso</>
              }
            </button>
          ))}
        </div>

        <input
          value={concepto}
          onChange={e => setConcepto(e.target.value)}
          placeholder="Concepto"
          className="w-full border-2 border-warm-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-forest transition-colors"
        />
        <input
          type="number"
          value={valor}
          onChange={e => setValor(e.target.value)}
          placeholder="Valor"
          className="w-full border-2 border-warm-200 rounded-xl px-4 py-3 text-lg font-bold focus:outline-none focus:border-forest transition-colors font-mono"
        />

        {/* Foto soporte */}
        <div>
          <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide mb-2">
            Foto soporte (opcional)
          </p>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" onChange={onFile} className="hidden" />
          {preview ? (
            <div className="relative">
              <img src={preview} alt="preview" className="w-full h-28 object-cover rounded-xl border-2 border-amber-300" />
              <button
                onClick={() => { setArchivo(null); setPreview(null) }}
                className="absolute top-2 right-2 bg-black/60 text-white rounded-full w-6 h-6 flex items-center justify-center"
              >
                <XIcon size={12} />
              </button>
            </div>
          ) : (
            <button
              onClick={() => fileRef.current?.click()}
              className="w-full h-20 border-2 border-dashed border-warm-200 rounded-xl flex flex-col items-center justify-center gap-1.5 hover:border-amber-400 hover:bg-amber-50 transition-colors"
            >
              <Upload size={16} className="text-warm-400" />
              <span className="text-xs text-warm-400">Toca para subir foto</span>
            </button>
          )}
        </div>

        <button
          onClick={guardar}
          disabled={!concepto.trim() || !valor || loading}
          className="w-full disabled:opacity-40 text-white font-bold py-3.5 rounded-xl text-sm transition-colors"
          style={{ background: 'oklch(35% 0.05 155)' }}
        >
          {loading ? 'Guardando...' : 'Registrar'}
        </button>
      </div>
    </div>
  )
}
