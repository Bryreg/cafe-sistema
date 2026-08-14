import { useMemo, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import SemanaGrid from '../components/horarios/SemanaGrid'
import NovedadesPanel from '../components/horarios/NovedadesPanel'
import ResumenMensual from '../components/horarios/ResumenMensual'
import SueldosPanel from '../components/horarios/SueldosPanel'
import TasasPanel from '../components/horarios/TasasPanel'
import ParametrosNominaPanel from '../components/horarios/ParametrosNominaPanel'
import { aISO, MESES } from '../components/horarios/tipos'

/**
 * Horarios & horas trabajadas.
 *
 * Seis pestañas, una por pregunta:
 *   Semana   → ¿quién trabaja esta semana? (y ¿alguien se pasa de la jornada?)
 *   Novedades→ ¿qué pasó con la gente? (incapacidades, permisos, vacaciones)
 *   El mes   → ¿cuántas horas de cada tipo, planeado vs real, y cuánto sale?
 *   Sueldos  → el dato que hace falta para estimar la plata
 *   Tasas    → los números de ley que usa el cálculo, editables y con su origen
 *   Nómina   → hermana de Tasas: el mínimo, el auxilio y los aportes de ley.
 *              Van separadas porque se corrigen en momentos distintos (las tasas
 *              cuando cambia una norma; éstos cada enero, con el decreto nuevo).
 */

type Tab = 'semana' | 'novedades' | 'mes' | 'sueldos' | 'tasas' | 'nomina'

const TABS: { id: Tab; label: string }[] = [
  { id: 'semana', label: 'Semana' },
  { id: 'novedades', label: 'Novedades' },
  { id: 'mes', label: 'El mes' },
  { id: 'sueldos', label: 'Sueldos' },
  { id: 'tasas', label: 'Tasas y festivos' },
  { id: 'nomina', label: 'Parámetros de nómina' },
]

export default function Horarios() {
  const { user } = useAuth()
  const tiendaId = user?.tienda_id ?? null

  const hoy = new Date()
  const [tab, setTab] = useState<Tab>('semana')
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)

  const rangoMes = useMemo(() => {
    const primero = new Date(anio, mes - 1, 1)
    const ultimo = new Date(anio, mes, 0)
    return { desde: aISO(primero), hasta: aISO(ultimo) }
  }, [anio, mes])

  const moverMes = (n: number) => {
    const d = new Date(anio, mes - 1 + n, 1)
    setAnio(d.getFullYear())
    setMes(d.getMonth() + 1)
  }

  if (!tiendaId) {
    return (
      <p className="text-sm text-warm-500">
        Elegí una sede para armar horarios: cada sede tiene su propio equipo.
      </p>
    )
  }

  const conMes = tab === 'novedades' || tab === 'mes' || tab === 'tasas'

  return (
    <div className="space-y-4">
      {/* ── Header ── */}
      <div className="flex flex-wrap items-center gap-2">
        <CalendarDays size={20} className="text-forest" />
        <h1 className="text-lg font-bold text-warm-700">Horarios y horas</h1>
        <div className="flex-1" />
        {conMes && (
          <div className="flex items-center gap-1 bg-white border border-warm-200 rounded-xl p-1">
            <button onClick={() => moverMes(-1)} className="p-1.5 rounded-lg hover:bg-warm-100 text-warm-500">
              <ChevronLeft size={16} />
            </button>
            <span className="text-xs font-semibold text-warm-700 px-2 whitespace-nowrap">
              {MESES[mes - 1]} {anio}
            </span>
            <button onClick={() => moverMes(1)} className="p-1.5 rounded-lg hover:bg-warm-100 text-warm-500">
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>

      {/* ── Tabs ── */}
      <div className="flex flex-wrap gap-1 border-b border-warm-200">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? 'border-forest text-forest-700'
                : 'border-transparent text-warm-400 hover:text-warm-600'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'semana' && <SemanaGrid tiendaId={tiendaId} />}
      {tab === 'novedades' && (
        <NovedadesPanel tiendaId={tiendaId} desde={rangoMes.desde} hasta={rangoMes.hasta} />
      )}
      {tab === 'mes' && <ResumenMensual tiendaId={tiendaId} anio={anio} mes={mes} />}
      {tab === 'sueldos' && <SueldosPanel tiendaId={tiendaId} />}
      {tab === 'tasas' && <TasasPanel anio={anio} />}
      {/* Sin el selector de mes a propósito (no está en `conMes`): estas filas
          tienen su propia vigencia y no se filtran por el mes que se esté
          mirando arriba. Un selector que no hace nada haría creer lo contrario. */}
      {tab === 'nomina' && <ParametrosNominaPanel />}
    </div>
  )
}
