import { createContext, useContext, useState, useEffect, ReactNode } from 'react'

interface AuthUser {
  token: string
  rol: string
  nombre: string
  tienda_id: number | null
  user_id: number
}

interface AuthContextType {
  user: AuthUser | null
  tipo_turno: string | null
  cuadre_llegada_turno_id: number | null
  login: (data: AuthUser) => void
  logout: () => void
  setTipoTurno: (tipo: string) => void
  setCuadreLlegadaDone: (turnoId: number) => void
}

const AuthContext = createContext<AuthContextType>({} as AuthContextType)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [tipo_turno, setTipoTurnoState] = useState<string | null>(null)
  const [cuadre_llegada_turno_id, setCuadreLlegadaState] = useState<number | null>(null)

  useEffect(() => {
    const token = localStorage.getItem('token')
    const rol = localStorage.getItem('rol')
    const nombre = localStorage.getItem('nombre')
    const tienda_id = localStorage.getItem('tienda_id')
    const user_id = localStorage.getItem('user_id')
    if (token && rol && nombre && user_id) {
      setUser({ token, rol, nombre, tienda_id: tienda_id ? Number(tienda_id) : null, user_id: Number(user_id) })
      const savedTipo = localStorage.getItem(`tipo_turno_${user_id}`)
      const savedCuadre = localStorage.getItem(`cuadre_llegada_${user_id}`)
      if (savedTipo) setTipoTurnoState(savedTipo)
      if (savedCuadre) setCuadreLlegadaState(Number(savedCuadre))
    }
  }, [])

  const login = (data: AuthUser) => {
    localStorage.setItem('token', data.token)
    localStorage.setItem('rol', data.rol)
    localStorage.setItem('nombre', data.nombre)
    localStorage.setItem('tienda_id', String(data.tienda_id))
    localStorage.setItem('user_id', String(data.user_id))
    setUser(data)
    // Restaurar estado de turno del usuario al volver a entrar
    const savedTipo = localStorage.getItem(`tipo_turno_${data.user_id}`)
    const savedCuadre = localStorage.getItem(`cuadre_llegada_${data.user_id}`)
    setTipoTurnoState(savedTipo ?? null)
    setCuadreLlegadaState(savedCuadre ? Number(savedCuadre) : null)
  }

  const logout = () => {
    const uid = localStorage.getItem('user_id')
    localStorage.removeItem('token')
    localStorage.removeItem('rol')
    localStorage.removeItem('nombre')
    localStorage.removeItem('tienda_id')
    localStorage.removeItem('user_id')
    if (uid) {
      localStorage.removeItem(`tipo_turno_${uid}`)
      localStorage.removeItem(`cuadre_llegada_${uid}`)
    }
    setUser(null)
    setTipoTurnoState(null)
    setCuadreLlegadaState(null)
  }

  const setTipoTurno = (tipo: string) => {
    if (user?.user_id) localStorage.setItem(`tipo_turno_${user.user_id}`, tipo)
    setTipoTurnoState(tipo)
  }

  const setCuadreLlegadaDone = (turnoId: number) => {
    if (user?.user_id) localStorage.setItem(`cuadre_llegada_${user.user_id}`, String(turnoId))
    setCuadreLlegadaState(turnoId)
  }

  return (
    <AuthContext.Provider value={{ user, tipo_turno, cuadre_llegada_turno_id, login, logout, setTipoTurno, setCuadreLlegadaDone }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
