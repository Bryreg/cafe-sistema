import { useState } from 'react'
import { Home, BarChart3 } from 'lucide-react'
import AdminHub from './AdminHub'
import DashboardEjecutivo from './DashboardEjecutivo'

type Vista = 'hoy' | 'ejecutivo'

/**
 * Dashboard unificado: una sola entrada que reúne la vista operativa "Hoy"
 * (ventas del día, alertas, top productos, actividad) y la vista "Ejecutivo"
 * (KPIs multi-período, resumen de todos los paneles y gráficos). Reemplaza las
 * dos rutas separadas /dashboard y /dashboard-ejecutivo.
 */
export default function Dashboard() {
  const [vista, setVista] = useState<Vista>('hoy')

  const opciones: [Vista, string, typeof Home][] = [
    ['hoy', 'Hoy', Home],
    ['ejecutivo', 'Ejecutivo', BarChart3],
  ]

  return (
    <div className="w-full">
      {/* Toggle de vista */}
      <div className="flex justify-center" style={{ marginTop: 12 }}>
        <div className="inline-flex bg-warm-100 border border-warm-200 rounded-full p-1 gap-1">
          {opciones.map(([k, label, Icon]) => {
            const activo = vista === k
            return (
              <button
                key={k}
                onClick={() => setVista(k)}
                className={`flex items-center gap-1.5 px-5 py-1.5 rounded-full text-sm font-semibold transition-colors ${
                  activo ? 'bg-white text-forest-700 shadow-sm' : 'text-warm-500 hover:text-warm-700'
                }`}
              >
                <Icon size={14} /> {label}
              </button>
            )
          })}
        </div>
      </div>

      {vista === 'hoy' ? <AdminHub /> : <DashboardEjecutivo />}
    </div>
  )
}
