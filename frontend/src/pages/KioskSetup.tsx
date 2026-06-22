import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Lock, Wifi, AlertTriangle, Smartphone, User, ArrowLeft } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import api from '../api/client'

interface BaristaRef { id: number; nombre: string }

/**
 * Entrada del dispositivo. Dos modos:
 *  - 'kiosk'   → PC compartida del punto de venta (parea con el PIN del sistema).
 *  - 'barista' → celular personal: la barista entra con su propio PIN (login individual,
 *                sus acciones quedan firmadas por ella, sin selector ni X-Barista-Id).
 * Ambos operan sobre el MISMO turno de la tienda.
 */
export default function KioskSetup() {
  const { initKiosk, loginBarista } = useAuth()
  const [modo, setModo] = useState<'kiosk' | 'barista'>('kiosk')

  // kiosk
  const [pin, setPin] = useState('')
  const [tiendaId, setTiendaId] = useState('1')

  // barista
  const [roster, setRoster] = useState<BaristaRef[]>([])
  const [sel, setSel] = useState<BaristaRef | null>(null)
  const [baristaPin, setBaristaPin] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (modo === 'barista' && roster.length === 0) {
      api.get<BaristaRef[]>('/auth/baristas-login')
        .then(r => setRoster(r.data))
        .catch(() => setError('No se pudo cargar la lista de baristas'))
    }
  }, [modo]) // eslint-disable-line react-hooks/exhaustive-deps

  const activarKiosk = async () => {
    if (!pin.trim()) return
    setLoading(true); setError('')
    try { await initKiosk(pin, Number(tiendaId)) }
    catch (e: any) { setError(e.response?.data?.detail || 'PIN incorrecto') }
    finally { setLoading(false) }
  }

  const entrarBarista = async () => {
    if (!sel || baristaPin.length < 4) return
    setLoading(true); setError('')
    try { await loginBarista(sel.id, baristaPin) }
    catch (e: any) { setError(e.response?.data?.detail || 'PIN incorrecto'); setBaristaPin('') }
    finally { setLoading(false) }
  }

  const switchModo = (m: 'kiosk' | 'barista') => {
    setModo(m); setError(''); setSel(null); setBaristaPin('')
  }

  const ErrorBox = error ? (
    <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs"
      style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
      <AlertTriangle size={12} /> {error}
    </div>
  ) : null

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6" style={{ background: dark.bg }}>
      <div className="w-full max-w-sm space-y-6">

        {/* Branding */}
        <div className="text-center">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
            style={{ background: modo === 'kiosk' ? 'oklch(62% 0.18 50)' : dark.greenDim }}>
            {modo === 'kiosk'
              ? <Wifi size={28} className="text-white" />
              : <Smartphone size={28} className="text-white" />}
          </div>
          <h1 className="text-xl font-bold" style={{ color: dark.ink }}>
            {modo === 'kiosk' ? 'Activar caja (kiosko)' : 'Entrar como barista'}
          </h1>
          <p className="text-sm mt-1" style={{ color: dark.inkMuted }}>
            {modo === 'kiosk'
              ? 'Para la PC compartida del punto de venta'
              : 'Desde tu celular, con tu PIN personal'}
          </p>
        </div>

        {/* ── Modo kiosko ── */}
        {modo === 'kiosk' && (
          <div className="rounded-2xl p-5 space-y-4"
            style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
            <div>
              <label className="text-xs font-bold uppercase tracking-widest block mb-2" style={{ color: dark.amber }}>
                Sede (ID)
              </label>
              <input type="number" value={tiendaId} onChange={e => setTiendaId(e.target.value)}
                className="w-full rounded-xl px-4 py-3 text-sm font-mono bg-transparent border outline-none"
                style={{ borderColor: dark.border, color: dark.ink }} />
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
            {ErrorBox}
            <button onClick={activarKiosk} disabled={!pin.trim() || loading}
              className="w-full py-3.5 rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all disabled:opacity-40"
              style={{ background: 'oklch(62% 0.18 50)', color: 'white' }}>
              <Lock size={15} /> {loading ? 'Activando...' : 'Activar dispositivo'}
            </button>
          </div>
        )}

        {/* ── Modo barista (celular) ── */}
        {modo === 'barista' && (
          <div className="rounded-2xl p-5 space-y-4"
            style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
            {!sel ? (
              <>
                <label className="text-xs font-bold uppercase tracking-widest block" style={{ color: dark.green }}>
                  ¿Quién sos?
                </label>
                <div className="grid grid-cols-2 gap-2 max-h-[260px] overflow-y-auto">
                  {roster.map(b => (
                    <button key={b.id} onClick={() => { setSel(b); setError('') }}
                      className="flex items-center gap-2 px-3 py-3 rounded-xl text-sm font-semibold text-left transition-colors"
                      style={{ background: dark.surfaceAlt, border: `1px solid ${dark.border}`, color: dark.ink }}>
                      <User size={14} style={{ color: dark.amber }} />
                      <span className="truncate">{b.nombre}</span>
                    </button>
                  ))}
                  {roster.length === 0 && !error && (
                    <p className="col-span-2 text-sm text-center py-4" style={{ color: dark.inkSubtle }}>Cargando…</p>
                  )}
                </div>
                {ErrorBox}
              </>
            ) : (
              <>
                <button onClick={() => { setSel(null); setBaristaPin(''); setError('') }}
                  className="flex items-center gap-1 text-xs font-semibold" style={{ color: dark.inkMuted }}>
                  <ArrowLeft size={12} /> cambiar
                </button>
                <p className="text-base font-bold" style={{ color: dark.ink }}>Hola, {sel.nombre}</p>
                <input type="password" inputMode="numeric" maxLength={4} value={baristaPin}
                  onChange={e => setBaristaPin(e.target.value.replace(/\D/g, ''))}
                  onKeyDown={e => e.key === 'Enter' && entrarBarista()} placeholder="• • • •" autoFocus
                  className="w-full rounded-xl px-4 py-3 text-center text-lg tracking-[0.5em] font-mono bg-transparent border outline-none"
                  style={{ borderColor: dark.border, color: dark.ink }} />
                {ErrorBox}
                <button onClick={entrarBarista} disabled={baristaPin.length < 4 || loading}
                  className="w-full py-3.5 rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all disabled:opacity-40"
                  style={{ background: dark.greenDim, color: 'white' }}>
                  <Lock size={15} /> {loading ? 'Entrando...' : 'Entrar'}
                </button>
              </>
            )}
          </div>
        )}

        {/* Toggle de modo + admin */}
        <div className="flex items-center justify-between">
          {modo === 'kiosk' ? (
            <button onClick={() => switchModo('barista')}
              className="text-xs font-semibold flex items-center gap-1.5 transition-colors"
              style={{ color: dark.inkMuted }}>
              <Smartphone size={13} /> Soy barista (mi celular) →
            </button>
          ) : (
            <button onClick={() => switchModo('kiosk')}
              className="text-xs font-semibold flex items-center gap-1.5 transition-colors"
              style={{ color: dark.inkMuted }}>
              <ArrowLeft size={13} /> Caja compartida
            </button>
          )}
          <Link to="/admin-login" className="text-xs font-semibold" style={{ color: dark.inkMuted }}>
            Admin →
          </Link>
        </div>
      </div>
    </div>
  )
}
