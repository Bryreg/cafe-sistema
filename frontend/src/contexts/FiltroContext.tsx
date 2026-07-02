import React, { createContext, useContext, useState } from 'react'

export interface InformeFiltro {
  desde: string
  hasta: string
  /** null = todas las sedes */
  tiendaId: number | null
  categoria: string | null
  turnoId: number | null
  productoSearch: string | null
  conDescuento: boolean | null
}

interface FiltroContextType {
  filtro: InformeFiltro
  setFiltro: React.Dispatch<React.SetStateAction<InformeFiltro>>
}

const FiltroContext = createContext<FiltroContextType | null>(null)

function todayStr() {
  // Hora LOCAL: toISOString es UTC y despues de las 19:00 Colombia da la fecha de manana.
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function firstOfMonthStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

export const FiltroProvider: React.FC<{ children: React.ReactNode; tiendaId: number | null }> = ({ children, tiendaId }) => {
  const [filtro, setFiltro] = useState<InformeFiltro>({
    desde: firstOfMonthStr(),
    hasta: todayStr(),
    tiendaId,
    categoria: null,
    turnoId: null,
    productoSearch: null,
    conDescuento: null,
  })

  return (
    <FiltroContext.Provider value={{ filtro, setFiltro }}>
      {children}
    </FiltroContext.Provider>
  )
}

export const useFiltro = () => {
  const ctx = useContext(FiltroContext)
  if (!ctx) throw new Error('useFiltro must be used inside FiltroProvider')
  return ctx
}
