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
  ts_conteo_apertura: string | null
  ts_conteo_cierre: string | null
  ultima_entrega_fecha: string | null
  ultima_entrega_diferencia_efectivo: number | null
  consignaciones_turno: number
  consignaciones_deducidas?: number
  usuario_apertura_id?: number
  tipo_turno: string | null
  tiene_cuadre_llegada: boolean
  es_operativo: boolean
  dia_tiene_conteo_apertura: boolean
  baristas: string[]
}

interface TurnoCtx {
  turno: Turno | null
  loading: boolean
  refresh: () => Promise<void>
}

const TurnoContext = createContext<TurnoCtx>({} as TurnoCtx)

const POLL_INTERVAL = 8_000  // 8s — sync casi real-time

export function TurnoProvider({ children }: { children: ReactNode }) {
  const { tiendaId, user } = useAuth()
  const [turno, setTurno] = useState<Turno | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchTurno = useCallback(async (silent = false) => {
    if (!tiendaId) { if (!silent) { setTurno(null); setLoading(false) }; return }
    if (!silent) setLoading(true)
    try {
      // Kiosko usa el endpoint público; usuarios autenticados usan el protegido
      const endpoint = user?.kiosk
        ? `/caja/activo-pub/${tiendaId}`
        : `/caja/activo/${tiendaId}`
      const { data } = await api.get(endpoint)
      setTurno(data ? { baristas: [], tipo_turno: null, tiene_cuadre_llegada: false, es_operativo: false, dia_tiene_conteo_apertura: false, ...data } : null)
    } catch {
      if (!silent) setTurno(null)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [tiendaId, user?.kiosk])

  const refresh = useCallback(async () => { await fetchTurno(false) }, [fetchTurno])

  useEffect(() => {
    if (!tiendaId) { setTurno(null); setLoading(false); return }

    fetchTurno(false)

    const interval = setInterval(() => fetchTurno(true), POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [tiendaId]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <TurnoContext.Provider value={{ turno, loading, refresh }}>
      {children}
    </TurnoContext.Provider>
  )
}

export const useTurno = () => useContext(TurnoContext)
