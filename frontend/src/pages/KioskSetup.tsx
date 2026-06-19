import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { Lock, Wifi, AlertTriangle } from 'lucide-react'

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
      style={{ background: 'oklch(10% 0.005 60)' }}>
      <div className="w-full max-w-sm space-y-6">

        {/* Logo / branding */}
        <div className="text-center">
          <div className="w-16 h-16 rounded-2xl bg-amber-600 flex items-center justify-center mx-auto mb-4">
            <Wifi size={28} className="text-white" />
          </div>
          <h1 className="text-xl font-bold text-white">Activar dispositivo</h1>
          <p className="text-sm mt-1" style={{ color: 'oklch(55% 0.01 60)' }}>
            Ingresa el PIN del sistema para iniciar el modo kiosco
          </p>
        </div>

        <div className="rounded-2xl p-5 space-y-4"
          style={{ background: 'oklch(15% 0.005 60)', border: '1px solid oklch(22% 0.01 60)' }}>

          <div>
            <label className="text-xs font-bold uppercase tracking-widest text-amber-400 block mb-2">
              Sede (ID)
            </label>
            <input
              type="number"
              value={tiendaId}
              onChange={e => setTiendaId(e.target.value)}
              className="w-full rounded-xl px-4 py-3 text-sm font-mono bg-transparent border outline-none text-white"
              style={{ borderColor: 'oklch(28% 0.01 60)' }}
            />
          </div>

          <div>
            <label className="text-xs font-bold uppercase tracking-widest text-amber-400 block mb-2">
              PIN de sistema
            </label>
            <input
              type="password"
              value={pin}
              onChange={e => setPin(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && activar()}
              placeholder="••••••••"
              className="w-full rounded-xl px-4 py-3 text-sm bg-transparent border outline-none text-white"
              style={{ borderColor: 'oklch(28% 0.01 60)' }}
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs"
              style={{ background: 'oklch(20% 0.08 25)', border: '1px solid oklch(40% 0.16 25)', color: 'oklch(72% 0.20 25)' }}>
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

        <p className="text-center text-xs" style={{ color: 'oklch(40% 0.01 60)' }}>
          El admin configura el KIOSK_PIN en el servidor
        </p>
      </div>
    </div>
  )
}
