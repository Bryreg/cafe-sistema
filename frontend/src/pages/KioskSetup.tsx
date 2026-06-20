import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Lock, Wifi, AlertTriangle } from 'lucide-react'
import { dark } from '../constants/darkTheme'

export default function KioskSetup() {
  const { initKiosk } = useAuth()
  const [pin, setPin] = useState('')
  const [tiendaId, setTiendaId] = useState('1')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const activar = async () => {
    if (!pin.trim()) return
    setLoading(true); setError('')
    try {
      await initKiosk(pin, Number(tiendaId))
    } catch (e: any) {
      setError(e.response?.data?.detail || 'PIN incorrecto')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6"
      style={{ background: dark.bg }}>
      <div className="w-full max-w-sm space-y-6">

        {/* Logo / branding */}
        <div className="text-center">
          <div className="w-16 h-16 rounded-2xl bg-amber-600 flex items-center justify-center mx-auto mb-4">
            <Wifi size={28} className="text-white" />
          </div>
          <h1 className="text-xl font-bold" style={{ color: dark.ink }}>Activar dispositivo</h1>
          <p className="text-sm mt-1" style={{ color: dark.inkMuted }}>
            Ingresa el PIN del sistema para iniciar el modo kiosco
          </p>
        </div>

        <div className="rounded-2xl p-5 space-y-4"
          style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>

          <div>
            <label className="text-xs font-bold uppercase tracking-widest block mb-2" style={{ color: dark.amber }}>
              Sede (ID)
            </label>
            <input
              type="number"
              value={tiendaId}
              onChange={e => setTiendaId(e.target.value)}
              className="w-full rounded-xl px-4 py-3 text-sm font-mono bg-transparent border outline-none"
              style={{ borderColor: dark.border, color: dark.ink }}
            />
          </div>

          <div>
            <label className="text-xs font-bold uppercase tracking-widest block mb-2" style={{ color: dark.amber }}>
              PIN de sistema
            </label>
            <input
              type="password"
              value={pin}
              onChange={e => setPin(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && activar()}
              placeholder="••••••••"
              className="w-full rounded-xl px-4 py-3 text-sm bg-transparent border outline-none"
              style={{ borderColor: dark.border, color: dark.ink }}
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs"
              style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
              <AlertTriangle size={12} /> {error}
            </div>
          )}

          <button
            onClick={activar}
            disabled={!pin.trim() || loading}
            className="w-full py-3.5 rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all disabled:opacity-40"
            style={{ background: 'oklch(62% 0.18 50)', color: 'white' }}
          >
            <Lock size={15} />
            {loading ? 'Activando...' : 'Activar dispositivo'}
          </button>
        </div>

        <div className="flex items-center justify-between">
          <p className="text-xs" style={{ color: dark.inkSubtle }}>
            El admin configura el KIOSK_PIN en el servidor
          </p>
          <Link
            to="/admin-login"
            className="text-xs font-semibold transition-colors"
            style={{ color: dark.inkMuted }}
            onMouseOver={e => (e.currentTarget.style.color = dark.ink)}
            onMouseOut={e => (e.currentTarget.style.color = dark.inkMuted)}
          >
            Admin →
          </Link>
        </div>
      </div>
    </div>
  )
}
