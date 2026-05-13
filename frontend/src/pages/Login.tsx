import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Coffee, Delete, Store } from 'lucide-react'

interface UsuarioPublic {
  id: number; nombre: string; rol: string; tienda_id: number | null
}

interface Sede {
  id: number; nombre: string
}

interface PendingAuth {
  token: string; rol: string; nombre: string; tienda_id: number | null; user_id: number
}

// Unique avatar tints per slot — oklch hues across the spectrum
const TINTS = [
  'oklch(50% 0.12 155)', // green
  'oklch(48% 0.13 240)', // blue
  'oklch(50% 0.14 300)', // purple
  'oklch(52% 0.16 30)',  // orange
  'oklch(48% 0.14 340)', // pink
  'oklch(50% 0.12 200)', // cyan
  'oklch(50% 0.14 85)',  // yellow-green
  'oklch(48% 0.15 15)',  // red-orange
]

const iniciales = (nombre: string) =>
  nombre.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()

export default function Login() {
  const [usuarios, setUsuarios] = useState<UsuarioPublic[]>([])
  const [sedes, setSedes] = useState<Sede[]>([])
  const [selected, setSelected] = useState<UsuarioPublic | null>(null)
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [pendingAuth, setPendingAuth] = useState<PendingAuth | null>(null)
  const { login } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    api.get('/auth/usuarios').then(r => setUsuarios(r.data))
    api.get('/auth/tiendas').then(r => setSedes(r.data))
  }, [])

  const seleccionar = (u: UsuarioPublic) => {
    setSelected(u); setPin(''); setError('')
  }

  const presionar = (digit: string) => {
    if (pin.length >= 4 || loading) return
    const nuevo = pin + digit
    setPin(nuevo)
    setError('')
    if (nuevo.length === 4) {
      setTimeout(() => intentarLogin(nuevo), 80)
    }
  }

  const borrar = () => setPin(p => p.slice(0, -1))

  const intentarLogin = async (pinValor: string) => {
    if (!selected) return
    setLoading(true); setError('')
    try {
      const { data } = await api.post('/auth/login-pin', { user_id: selected.id, pin: pinValor })
      const authData: PendingAuth = {
        token: data.access_token, rol: data.rol,
        nombre: data.nombre, tienda_id: data.tienda_id, user_id: data.user_id,
      }
      if (data.rol === 'barista') {
        setPendingAuth(authData)
      } else {
        login({ ...authData, tienda_id: authData.tienda_id })
        navigate('/', { replace: true })
      }
    } catch {
      setError('PIN incorrecto')
      setPin('')
    } finally {
      setLoading(false)
    }
  }

  const elegirSede = async (sedeId: number) => {
    if (!pendingAuth) return
    try {
      const { data } = await api.post(
        '/auth/seleccionar-sede',
        { tienda_id: sedeId },
        { headers: { Authorization: `Bearer ${pendingAuth.token}` } }
      )
      login({ token: data.access_token, rol: data.rol, nombre: data.nombre, tienda_id: sedeId, user_id: data.user_id })
    } catch {
      // fallback: usar token original con tienda seleccionada
      login({ ...pendingAuth, tienda_id: sedeId })
    }
    navigate('/seleccionar-turno', { replace: true })
  }

  const teclas = ['1','2','3','4','5','6','7','8','9','','0','⌫']
  const pinFull = pin.length === 4

  return (
    <div className="min-h-screen bg-bark-900 flex flex-col items-center justify-center p-5">
      {/* Logo */}
      <div className="flex items-center gap-2.5 mb-8">
        <Coffee size={26} className="text-forest-400" />
        <span className="text-xl font-bold text-warm-50 tracking-tight">Sistema Café</span>
      </div>

      {pendingAuth ? (
        /* ── Step 3: sede selection (barista only) ── */
        <div className="w-full max-w-sm">
          <div className="flex flex-col items-center mb-7">
            <div
              className="w-14 h-14 rounded-full flex items-center justify-center mb-3 shadow-md"
              style={{ background: TINTS[usuarios.indexOf(selected!) % TINTS.length] }}
            >
              <span className="text-xl font-bold text-white">{iniciales(pendingAuth.nombre)}</span>
            </div>
            <p className="text-sm font-semibold text-warm-50">{pendingAuth.nombre}</p>
          </div>
          <p className="text-xs font-semibold text-warm-500 text-center mb-5 uppercase tracking-[0.12em]">
            ¿En qué sede estás hoy?
          </p>
          <div className="flex flex-col gap-3">
            {sedes.map(sede => (
              <button
                key={sede.id}
                onClick={() => elegirSede(sede.id)}
                className="bg-bark-800 border border-bark-700 rounded-xl px-5 py-4 flex items-center gap-4
                           hover:border-forest-400 active:scale-95 transition-all"
              >
                <div className="w-10 h-10 rounded-full bg-forest-400/20 flex items-center justify-center shrink-0">
                  <Store size={18} className="text-forest-400" />
                </div>
                <span className="text-base font-bold text-warm-50">{sede.nombre}</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => { setPendingAuth(null); setPin(''); setSelected(null) }}
            className="w-full text-xs text-warm-500 hover:text-warm-400 mt-5 transition-colors"
          >
            Volver al inicio
          </button>
        </div>
      ) : !selected ? (
        /* ── User selection ── */
        <div className="w-full max-w-sm">
          <p className="text-xs font-semibold text-warm-500 text-center mb-5 uppercase tracking-[0.12em]">
            ¿Quién eres?
          </p>
          <div className="grid grid-cols-2 gap-3">
            {usuarios.map((u, i) => (
              <button
                key={u.id}
                onClick={() => seleccionar(u)}
                className="bg-bark-800 border border-bark-700 rounded-xl p-4 flex flex-col items-center gap-3
                           hover:border-forest-400 active:scale-95 transition-all"
              >
                <div
                  className="w-14 h-14 rounded-full flex items-center justify-center shadow-sm shrink-0"
                  style={{ background: TINTS[i % TINTS.length] }}
                >
                  <span className="text-lg font-bold text-white">{iniciales(u.nombre)}</span>
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold text-warm-50 leading-tight">{u.nombre}</p>
                  <p className="text-xs text-warm-500 mt-0.5 capitalize">{u.rol}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        /* ── PIN entry ── */
        <div className="w-full max-w-xs">
          {/* Selected user */}
          <div className="flex flex-col items-center mb-8">
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center mb-3 shadow-md"
              style={{ background: TINTS[usuarios.indexOf(selected) % TINTS.length] }}
            >
              <span className="text-2xl font-bold text-white">{iniciales(selected.nombre)}</span>
            </div>
            <p className="text-base font-semibold text-warm-50">{selected.nombre}</p>
            <p className="text-xs text-warm-500 capitalize mt-0.5">{selected.rol}</p>
            <button
              onClick={() => setSelected(null)}
              className="text-xs text-forest-400 hover:text-forest-400/80 mt-2 transition-colors"
            >
              Cambiar usuario
            </button>
          </div>

          {/* PIN dots */}
          <div className="flex justify-center gap-4 mb-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="w-3.5 h-3.5 rounded-full border-2 transition-all duration-150"
                style={{
                  borderColor: i < pin.length ? 'oklch(55% 0.12 155)' : 'oklch(45% 0.014 55)',
                  background: i < pin.length ? 'oklch(55% 0.12 155)' : 'transparent',
                  transform: i < pin.length ? 'scale(1.15)' : 'scale(1)',
                }}
              />
            ))}
          </div>

          {error && (
            <p className="text-center text-sm text-red-400 mb-4 font-semibold">{error}</p>
          )}

          {/* Numpad */}
          <div className="grid grid-cols-3 gap-2.5">
            {teclas.map((t, i) => {
              if (t === '') return <div key={i} />
              if (t === '⌫') return (
                <button
                  key={i}
                  onClick={borrar}
                  className="h-[58px] rounded-xl bg-bark-800 border border-bark-700 hover:bg-bark-700
                             active:scale-95 flex items-center justify-center transition-all"
                >
                  <Delete size={18} className="text-warm-400" />
                </button>
              )
              return (
                <button
                  key={i}
                  onClick={() => presionar(t)}
                  disabled={loading}
                  className="h-[58px] rounded-xl bg-bark-800 border border-bark-700 hover:bg-bark-700
                             active:scale-95 text-2xl font-bold text-warm-50 transition-all disabled:opacity-50"
                >
                  {t}
                </button>
              )
            })}
          </div>

          {/* CTA */}
          <button
            disabled={!pinFull || loading}
            onClick={() => pinFull && intentarLogin(pin)}
            className="w-full mt-5 h-14 rounded-xl font-bold text-white text-sm transition-all disabled:opacity-40"
            style={{
              background: pinFull ? 'oklch(48% 0.12 155)' : 'oklch(25% 0.03 155)',
            }}
          >
            {loading ? 'Verificando...' : 'Iniciar turno'}
          </button>
        </div>
      )}
    </div>
  )
}
