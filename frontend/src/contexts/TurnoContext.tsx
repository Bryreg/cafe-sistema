import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import api from '../api/client'
import { useAuth } from './AuthContext'

export interface Turno {
  id: number
  tienda_id: number
  base_sistema: number
  base_real: number
  diferencia_apertura: number
  total_ventas: number
  total_efectivo: number
  total_tarjeta: number
  ingresos_movimientos: number
  egresos_movimientos: number
  efectivo_esperado_actual: number
  efectivo_final_real: number | null
  datafono_real: number | null
  diferencia_cierre: number | null
  diferencia_tarjeta: number | null
  estado: string
  fecha_apertura: string
  tiene_conteo_apertura: boolean
  tiene_ventas: boolean
  tiene_conteo_cierre: boolean
  ultima_entrega_fecha: string | null
  ultima_entrega_diferencia_efectivo: number | null
}

interface TurnoCtx {
  turno: Turno | null
  loading: boolean
  refresh: () => Promise<void>
}

const TurnoContext = createContext<TurnoCtx>({} as TurnoCtx)

export function TurnoProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [turno, setTurno] = useState<Turno | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!user?.tienda_id) { setLoading(false); return }
    setLoading(true)
    try {
      const { data } = await api.get(`/caja/activo/${user.tienda_id}`)
      setTurno(data)
    } catch {
      setTurno(null)
    } finally {
      setLoading(false)
    }
  }, [user?.tienda_id])

  useEffect(() => {
    if (user?.rol !== 'barista') { setTurno(null); setLoading(false); return }
    refresh()
    const t = setInterval(refresh, 15_000)
    return () => clearInterval(t)
  }, [user?.tienda_id, user?.rol])

  return (
    <TurnoContext.Provider value={{ turno, loading, refresh }}>
      {children}
    </TurnoContext.Provider>
  )
}

export const useTurno = () => useContext(TurnoContext)
