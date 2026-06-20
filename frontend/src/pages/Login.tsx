import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Coffee, Lock } from 'lucide-react'

// Login de ADMINISTRADOR únicamente. Las baristas NO inician sesión: bajo el modelo de
// turnos con responsabilidad colectiva, la responsabilidad se asigna al ABRIR el turno
// (selección de baristas), y el dispositivo corre en modo kiosko (PIN de dispositivo).
export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  const entrar = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!email.trim() || !password) return
    setLoading(true); setError('')
    try {
      const { data } = await api.post('/auth/login', {
        email: email.trim().toLowerCase(),
        password,
      })
      if (data.rol !== 'admin') {
        setError('Esta pantalla es solo para administradores.')
        return
      }
      login({
        token: data.access_token, rol: data.rol, nombre: data.nombre,
        tienda_id: data.tienda_id, user_id: data.user_id,
      })
      navigate('/dashboard', { replace: true })
    } catch {
      setError('Credenciales inválidas')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-bark-900 flex items-center justify-center p-5">
      <form onSubmit={entrar} className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <Coffee size={26} className="text-forest-400" />
          <span className="text-xl font-bold text-warm-50 tracking-tight">Sistema Café · Admin</span>
        </div>

        <div className="bg-bark-800 border border-bark-700 rounded-2xl p-6 space-y-4">
          <div>
            <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1.5">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              autoFocus
              placeholder="admin@cafe.com"
              className="w-full rounded-xl px-4 py-3 text-sm bg-bark-900 border border-bark-700 outline-none text-warm-50 focus:border-forest-400 transition-colors"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1.5">
              Contraseña
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full rounded-xl px-4 py-3 text-sm bg-bark-900 border border-bark-700 outline-none text-warm-50 focus:border-forest-400 transition-colors"
            />
          </div>

          {error && <p className="text-sm text-red-400 font-semibold">{error}</p>}

          <button
            type="submit"
            disabled={!email.trim() || !password || loading}
            className="w-full py-3.5 rounded-xl font-bold text-white text-sm flex items-center justify-center gap-2 transition-all disabled:opacity-40"
            style={{ background: 'oklch(48% 0.12 155)' }}
          >
            <Lock size={15} />
            {loading ? 'Ingresando...' : 'Ingresar'}
          </button>
        </div>

        <p className="text-center text-xs text-warm-500 mt-5 leading-relaxed">
          Las baristas no inician sesión.<br />
          La responsabilidad se asigna al abrir el turno.
        </p>
      </form>
    </div>
  )
}
