import {
  createContext, useContext, useState, useEffect, useCallback, useMemo, ReactNode,
} from 'react'
import api from '../api/client'
import { useAuth } from './AuthContext'
import { useTurno } from './TurnoContext'

export interface BaristaRef {
  id: number
  nombre: string
}

interface BaristaActivaCtx {
  baristaActiva: BaristaRef | null
  setBaristaActiva: (b: BaristaRef) => void
  baristasTurno: BaristaRef[]
}

const BaristaActivaContext = createContext<BaristaActivaCtx>({} as BaristaActivaCtx)

// Clave por-tienda: la barista activa es propia del dispositivo en esa sede.
const storeKey = (tiendaId: number | null) => `barista_activa_${tiendaId ?? 'none'}`
// Clave global plana: la lee el interceptor de axios sin conocer la tienda.
const GLOBAL_KEY = 'barista_activa_id'

interface BaristaApi {
  id: number
  nombre: string
}

export function BaristaActivaProvider({ children }: { children: ReactNode }) {
  const { tiendaId } = useAuth()
  const { turno } = useTurno()
  const [roster, setRoster] = useState<BaristaApi[]>([])
  const [baristaActiva, setBaristaActivaState] = useState<BaristaRef | null>(null)

  // Roster completo de baristas (id + nombre) para cruzar con los nombres del turno.
  useEffect(() => {
    let cancelled = false
    api.get<BaristaApi[]>('/auth/baristas')
      .then(r => { if (!cancelled) setRoster(r.data) })
      .catch(() => { if (!cancelled) setRoster([]) })
    return () => { cancelled = true }
  }, [tiendaId])

  // Baristas ACTIVAS del turno con id: cruza turno.baristas (solo nombres) contra el roster,
  // excluyendo a las que ya registraron salida (turno.baristas_salidas). Sin este filtro, una
  // barista que marcó salida seguía figurando como activa en el selector del header.
  const baristasTurno = useMemo<BaristaRef[]>(() => {
    const salidas = new Set(turno?.baristas_salidas ?? [])
    const nombres = (turno?.baristas ?? []).filter(nombre => !salidas.has(nombre))
    return nombres
      .map(nombre => {
        const match = roster.find(b => b.nombre === nombre)
        return match ? { id: match.id, nombre: match.nombre } : null
      })
      .filter((b): b is BaristaRef => b !== null)
  }, [turno?.baristas, turno?.baristas_salidas, roster])

  const persist = useCallback((b: BaristaRef | null) => {
    if (b) {
      localStorage.setItem(storeKey(tiendaId), String(b.id))
      localStorage.setItem(GLOBAL_KEY, String(b.id))
    } else {
      localStorage.removeItem(storeKey(tiendaId))
      localStorage.removeItem(GLOBAL_KEY)
    }
  }, [tiendaId])

  const setBaristaActiva = useCallback((b: BaristaRef) => {
    setBaristaActivaState(b)
    persist(b)
  }, [persist])

  // Inicialización / reconciliación: si no hay guardada o la guardada ya no está en el
  // turno, caer a la primera barista del turno. Mantener la guardada si sigue vigente.
  useEffect(() => {
    if (baristasTurno.length === 0) {
      if (baristaActiva !== null) { setBaristaActivaState(null); persist(null) }
      return
    }
    const savedId = Number(localStorage.getItem(storeKey(tiendaId)))
    const saved = baristasTurno.find(b => b.id === savedId)
    const next = saved ?? baristasTurno[0]
    if (!baristaActiva || baristaActiva.id !== next.id) {
      setBaristaActivaState(next)
      persist(next)
    }
  }, [baristasTurno, tiendaId]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <BaristaActivaContext.Provider value={{ baristaActiva, setBaristaActiva, baristasTurno }}>
      {children}
    </BaristaActivaContext.Provider>
  )
}

export const useBaristaActiva = () => useContext(BaristaActivaContext)
