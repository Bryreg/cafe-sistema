import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Banknote, Upload, AlertTriangle, Check, ImageIcon } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface Consignacion {
  id: number; valor: number; imagen_url: string | null
  estado: string; fecha: string
}

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

export default function Consignaciones() {
  const { user } = useAuth()
  const [lista, setLista] = useState<Consignacion[]>([])
  const [valor, setValor] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    if (!user?.tienda_id) return
    const { data } = await api.get(`/consignaciones/tienda/${user.tienda_id}`)
    setLista(data)
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
      setSaved(true); setTimeout(() => setSaved(false), 2000)
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
    finally { setSaving(false) }
  }

  const estadoBadge = (estado: string) => {
    const map: Record<string, string> = {
      pendiente: 'bg-amber-100 text-amber-700',
      realizada: 'bg-green-100 text-green-700',
    }
    return map[estado] || 'bg-gray-100 text-gray-500'
  }

  return (
    <BaristaLayout title="Consignaciones">
      <div className="space-y-5">
        <h1 className="text-xl font-bold text-gray-900">Registrar consignación</h1>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}
        {saved && (
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">
            <Check size={14} /> Consignación registrada
          </div>
        )}

        <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Valor</label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-2xl font-bold text-gray-300">$</span>
              <input type="number" value={valor} onChange={e => setValor(e.target.value)}
                placeholder="0"
                className="w-full pl-12 pr-4 py-4 text-3xl font-bold border-2 border-gray-200 rounded-xl focus:outline-none focus:border-amber-400 transition-colors"
                autoFocus />
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Comprobante</label>
            <input ref={fileRef} type="file" accept="image/*" onChange={onFile} className="hidden" />
            {preview ? (
              <div className="relative">
                <img src={preview} alt="preview" className="w-full h-32 object-cover rounded-xl border-2 border-amber-300" />
                <button onClick={() => { setArchivo(null); setPreview(null) }}
                  className="absolute top-2 right-2 bg-black/60 text-white rounded-full w-6 h-6 flex items-center justify-center text-xs">✕</button>
              </div>
            ) : (
              <button onClick={() => fileRef.current?.click()}
                className="w-full h-24 border-2 border-dashed border-gray-300 rounded-xl flex flex-col items-center justify-center gap-2 hover:border-amber-400 hover:bg-amber-50 transition-colors">
                <Upload size={20} className="text-gray-400" />
                <span className="text-xs text-gray-400">Toca para subir foto</span>
              </button>
            )}
          </div>

          <button onClick={guardar} disabled={!valor || saving}
            className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-3.5 rounded-xl text-sm flex items-center justify-center gap-2 transition-colors">
            <Banknote size={16} />
            {saving ? 'Guardando...' : 'Registrar consignación'}
          </button>
        </div>

        {lista.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Historial</p>
            </div>
            <div className="divide-y divide-gray-50">
              {lista.map(c => (
                <div key={c.id} className="px-4 py-3 flex items-center gap-3">
                  {c.imagen_url
                    ? <img src={c.imagen_url} className="w-10 h-10 rounded-lg object-cover border border-gray-200" alt="" />
                    : <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center">
                        <ImageIcon size={16} className="text-gray-400" />
                      </div>
                  }
                  <div className="flex-1">
                    <p className="text-sm font-bold text-gray-800">{fmt(c.valor)}</p>
                    <p className="text-xs text-gray-400">{new Date(c.fecha).toLocaleDateString('es-CO')}</p>
                  </div>
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${estadoBadge(c.estado)}`}>
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
