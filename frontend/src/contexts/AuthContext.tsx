import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import api from '../api/client'

interface AuthUser {
  token: string
  rol: string
  nombre: string
  tienda_id: number | null
  user_id: number
  kiosk?: boolean
}

interface AuthContextType {
  user: AuthUser | null
  tiendaId: number | null
  isKiosk: boolean
  login: (data: AuthUser) => void
  logout: () => void
  initKiosk: (pin: string, tiendaId: number) => Promise<void>
  resetKiosk: () => void
}

const AuthContext = createContext<AuthContextType>({} as AuthContextType)

/** La sesión guardada, leída SINCRÓNICO. localStorage es sincrónico, así que
 *  no hay ningún motivo para hidratarla en un efecto — y hacerlo costaba caro:
 *  en el primer render `user` era null, `RequireAdmin` redirigía a
 *  /admin-login, y para cuando el efecto corría el login veía al admin y lo
 *  mandaba a /dashboard. Resultado: NINGUNA URL admin se podía abrir directo
 *  — el bookmark de La Plata en la tablet aterrizaba siempre en el dashboard. */
function sesionGuardada(): AuthUser | null {
  const token = localStorage.getItem('token')
  const rol = localStorage.getItem('rol')
  const nombre = localStorage.getItem('nombre')
  const tienda_id = localStorage.getItem('tienda_id')
  const user_id = localStorage.getItem('user_id')
  const kiosk = localStorage.getItem('kiosk') === 'true'
  if (!(token && rol && nombre && user_id)) return null
  return {
    token, rol, nombre, kiosk,
    tienda_id: tienda_id ? Number(tienda_id) : null,
    user_id: Number(user_id),
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(sesionGuardada)

  const login = (data: AuthUser) => {
    localStorage.setItem('token', data.token)
    localStorage.setItem('rol', data.rol)
    localStorage.setItem('nombre', data.nombre)
    localStorage.setItem('tienda_id', String(data.tienda_id))
    localStorage.setItem('user_id', String(data.user_id))
    localStorage.setItem('kiosk', String(data.kiosk ?? false))
    setUser(data)
  }

  const logout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('rol')
    localStorage.removeItem('nombre')
    localStorage.removeItem('tienda_id')
    localStorage.removeItem('user_id')
    localStorage.removeItem('kiosk')
    // Limpia la barista activa global Y la persistida por tienda (barista_activa_{id}),
    // si no, la barista anterior se re-selecciona sola en el próximo turno (atribución cruzada).
    Object.keys(localStorage)
      .filter(k => k.startsWith('barista_activa'))
      .forEach(k => localStorage.removeItem(k))
    setUser(null)
  }

  const initKiosk = async (pin: string, tiendaId: number) => {
    const params = new URLSearchParams({ tienda_id: String(tiendaId), kiosk_pin: pin })
    const { data } = await api.post(`/auth/kiosk-init?${params}`)
    login({
      token: data.access_token,
      rol: data.rol,
      nombre: data.nombre,
      tienda_id: data.tienda_id,
      user_id: data.user_id,
      kiosk: true,
    })
  }

  const resetKiosk = () => logout()

  const tiendaId = user?.tienda_id ?? null
  const isKiosk = user?.kiosk ?? false

  return (
    <AuthContext.Provider value={{ user, tiendaId, isKiosk, login, logout, initKiosk, resetKiosk }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
