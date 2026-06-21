import { useState, useEffect, useCallback, useRef } from 'react'
import api from '../api/client'

export interface RutinaEstado {
  clave: string
  nombre: string
  every: number | null
  track: boolean
  ultimo: string | null
  minutos: number | null
  status: 'ok' | 'warn' | 'alert' | null
  count: number
}

export interface BitacoraEntry {
  fecha: string
  txt: string
  by: string | null
  hito: boolean
}

const POLL_MS = 60_000

export function useRutinasEstado(tiendaId: number | null) {
  const [estados, setEstados] = useState<RutinaEstado[]>([])
  const [bitacora, setBitacora] = useState<BitacoraEntry[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetch = useCallback(async () => {
    if (!tiendaId) return
    try {
      const [eRes, bRes] = await Promise.all([
        api.get<RutinaEstado[]>('/rutinas/estado-turno', { params: { tienda_id: tiendaId } }),
        api.get<BitacoraEntry[]>('/rutinas/bitacora', { params: { tienda_id: tiendaId } }),
      ])
      setEstados(eRes.data)
      setBitacora(bRes.data)
    } catch {
      // silencioso — muestra último estado conocido
    }
  }, [tiendaId])

  useEffect(() => {
    if (!tiendaId) return
    fetch()
    timerRef.current = setInterval(fetch, POLL_MS)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [tiendaId, fetch])

  const registrar = useCallback(
    async (clave: string, nota?: string) => {
      if (!tiendaId) return
      await api.post('/rutinas/quick', { tienda_id: tiendaId, clave, nota })
      await fetch()
    },
    [tiendaId, fetch],
  )

  return { estados, bitacora, registrar, refresh: fetch }
}
