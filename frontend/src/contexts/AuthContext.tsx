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
  login: (data: AuthUser) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextType>({} as AuthContextType)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)

  useEffect(() => {
    const token = localStorage.getItem('token')
    const rol = localStorage.getItem('rol')
    const nombre = localStorage.getItem('nombre')
    const tienda_id = localStorage.getItem('tienda_id')
    const user_id = localStorage.getItem('user_id')
    if (token && rol && nombre && user_id) {
      setUser({ token, rol, nombre, tienda_id: tienda_id ? Number(tienda_id) : null, user_id: Number(user_id) })
    }
  }, [])

  const login = (data: AuthUser) => {
    localStorage.setItem('token', data.token)
    localStorage.setItem('rol', data.rol)
    localStorage.setItem('nombre', data.nombre)
    localStorage.setItem('tienda_id', String(data.tienda_id))
    localStorage.setItem('user_id', String(data.user_id))
    setUser(data)
  }

  const logout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('rol')
    localStorage.removeItem('nombre')
    localStorage.removeItem('tienda_id')
    localStorage.removeItem('user_id')
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
