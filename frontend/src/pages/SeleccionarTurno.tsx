import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Coffee, Sun, Repeat2, Moon, LogOut, ArrowRight } from 'lucide-react'

export default function SeleccionarTurno() {
  const { user, logout, setTipoTurno } = useAuth()
  const navigate = useNavigate()
  const [turnoActivo, setTurnoActivo] = useState<boolean | null>(null)

  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/caja/activo/${user.tienda_id}`)
      .then(({ data }) => setTurnoActivo(!!data))
      .catch(() => setTurnoActivo(false))
  }, [user?.tienda_id])

  const elegir = (tipo: string) => {
    setTipoTurno(tipo)
    navigate('/', { replace: true })
  }

  return (
    <div className="min-h-screen bg-bark-900 flex flex-col items-center justify-center p-5">
      {/* Logo */}
      <div className="flex items-center gap-2.5 mb-2">
        <Coffee size={26} className="text-forest-400" />
        <span className="text-xl font-bold text-warm-50 tracking-tight">Sistema Café</span>
      </div>

      {user && (
        <p className="text-xs text-warm-500 mb-8">{user.nombre}</p>
      )}

      {turnoActivo === null ? (
        <p className="text-sm text-warm-500 animate-pulse">Consultando estado del día...</p>
      ) : (
        <div className="w-full max-w-sm">
          <p className="text-xs font-semibold text-warm-500 text-center mb-5 uppercase tracking-[0.12em]">
            ¿Qué turno es el tuyo hoy?
          </p>

          <div className="flex flex-col gap-3">
            {!turnoActivo && (
              <button
                onClick={() => elegir('apertura')}
                className="bg-bark-800 border border-bark-700 rounded-xl px-5 py-5 flex items-center gap-4
                           hover:border-amber-400 active:scale-95 transition-all"
              >
                <div className="w-11 h-11 rounded-full bg-amber-500/20 flex items-center justify-center shrink-0">
                  <Sun size={20} className="text-amber-400" />
                </div>
                <div className="text-left">
                  <p className="text-sm font-bold text-warm-50">Apertura</p>
                  <p className="text-xs text-warm-500 mt-0.5">Primer turno del día · conteo inicial de caja</p>
                </div>
              </button>
            )}

            {turnoActivo && (
              <>
                <button
                  onClick={() => elegir('apertura')}
                  className="bg-amber-600 border border-amber-500 rounded-xl px-5 py-5 flex items-center gap-4
                             hover:bg-amber-500 active:scale-95 transition-all"
                >
                  <div className="w-11 h-11 rounded-full bg-white/20 flex items-center justify-center shrink-0">
                    <ArrowRight size={20} className="text-white" />
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-bold text-white">Continuar mi turno</p>
                    <p className="text-xs text-amber-100 mt-0.5">Ya abriste hoy · volver al dashboard</p>
                  </div>
                </button>

                <button
                  onClick={() => elegir('intermedio')}
                  className="bg-bark-800 border border-bark-700 rounded-xl px-5 py-5 flex items-center gap-4
                             hover:border-blue-400 active:scale-95 transition-all"
                >
                  <div className="w-11 h-11 rounded-full bg-blue-500/20 flex items-center justify-center shrink-0">
                    <Repeat2 size={20} className="text-blue-400" />
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-bold text-warm-50">Intermedio</p>
                    <p className="text-xs text-warm-500 mt-0.5">Relevo de turno · cuadre de llegada</p>
                  </div>
                </button>

                <button
                  onClick={() => elegir('cierre')}
                  className="bg-bark-800 border border-bark-700 rounded-xl px-5 py-5 flex items-center gap-4
                             hover:border-purple-400 active:scale-95 transition-all"
                >
                  <div className="w-11 h-11 rounded-full bg-purple-500/20 flex items-center justify-center shrink-0">
                    <Moon size={20} className="text-purple-400" />
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-bold text-warm-50">Cierre</p>
                    <p className="text-xs text-warm-500 mt-0.5">Último turno del día · conteo final</p>
                  </div>
                </button>
              </>
            )}
          </div>

          <button
            onClick={() => { logout(); navigate('/login', { replace: true }) }}
            className="w-full flex items-center justify-center gap-1.5 text-xs text-warm-500 hover:text-warm-400 mt-6 transition-colors"
          >
            <LogOut size={12} /> Cambiar usuario
          </button>
        </div>
      )}
    </div>
  )
}
