import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Lock, Wifi, AlertTriangle } from 'lucide-react'
import { dark } from '../constants/darkTheme'

interface Tienda { id: number; nombre: string }

export default function KioskSetup() {
  const { initKiosk } = useAuth()
  const [pin, setPin] = useState('')
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState(() => localStorage.getItem('ultima_sede') ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas')
      .then(({ data }) => {
        setTiendas(data)
        // Si no hay sede recordada, preseleccionar la primera para que el flujo sea de un toque.
        setTiendaId(prev => prev || (data[0] ? String(data[0].id) : ''))
      })
      .catch(() => setError('No se pudo cargar la lista de sedes'))
  }, [])

  const activarKiosk = async () => {
    if (!pin.trim() || !tiendaId) return
    setLoading(true); setError('')
    try {
      await initKiosk(pin, Number(tiendaId))
      localStorage.setItem('ultima_sede', tiendaId)
    }
    catch (e: any) { setError(e.response?.data?.detail || 'PIN incorrecto') }
    finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6" style={{ background: dark.bg }}>
      <div className="w-full max-w-sm space-y-6">

        <div className="text-center">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
            style={{ background: 'oklch(62% 0.18 50)' }}>
            <Wifi size={28} className="text-white" />
          </div>
          <h1 className="text-xl font-bold" style={{ color: dark.ink }}>Activar caja</h1>
          <p className="text-sm mt-1" style={{ color: dark.inkMuted }}>
            Elegí la sede y poné el PIN del sistema
          </p>
        </div>

        <div className="rounded-2xl p-5 space-y-4"
          style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <div>
            <label className="text-xs font-bold uppercase tracking-widest block mb-2" style={{ color: dark.amber }}>
              Sede
            </label>
            <select value={tiendaId} onChange={e => setTiendaId(e.target.value)}
              className="w-full rounded-xl px-4 py-3 text-sm bg-transparent border outline-none"
              style={{ borderColor: dark.border, color: dark.ink }}>
              {tiendas.length === 0 && <option value="">Cargando sedes…</option>}
              {tiendas.map(t => (
                <option key={t.id} value={t.id} style={{ color: '#111' }}>{t.nombre}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-widest block mb-2" style={{ color: dark.amber }}>
              PIN de sistema
            </label>
            <input type="password" value={pin} onChange={e => setPin(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && activarKiosk()} placeholder="••••••••"
              className="w-full rounded-xl px-4 py-3 text-sm bg-transparent border outline-none"
              style={{ borderColor: dark.border, color: dark.ink }} />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs"
              style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
              <AlertTriangle size={12} /> {error}
            </div>
          )}

          <button onClick={activarKiosk} disabled={!pin.trim() || !tiendaId || loading}
            className="w-full py-3.5 rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all disabled:opacity-40"
            style={{ background: 'oklch(62% 0.18 50)', color: 'white' }}>
            <Lock size={15} /> {loading ? 'Activando...' : 'Activar dispositivo'}
          </button>
        </div>

        <div className="flex justify-end">
          <Link to="/admin-login" className="text-xs font-semibold" style={{ color: dark.inkMuted }}>
            Admin →
          </Link>
        </div>
      </div>
    </div>
  )
}
