import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import BaristaLayout from '../components/BaristaLayout'
import { CheckCircle2, Circle, ChevronLeft, ChevronRight, Trash2, ShieldCheck } from 'lucide-react'

// ─── Catálogo fijo (igual que el backend) ────────────────────────────────────
const TAREAS = [
  { key: 'pisos_puntos_ciegos',  label: 'Aseo general pisos y puntos ciegos' },
  { key: 'computador_caja',      label: 'Limpieza del computador, cajón monedero, impresora, teléfono, datafono' },
  { key: 'congelador_helado',    label: 'Lavar congelador de helado' },
  { key: 'nevera_pasteleria',    label: 'Lavar nevera de pastelería' },
  { key: 'nevera_leche',         label: 'Lavar nevera de leche' },
  { key: 'trampa_grasas',        label: 'Lavar trampa de grasas' },
  { key: 'gabinetes_cajones',    label: 'Asear y organizar gabinetes, puertas, cajones y materias primas por fecha' },
  { key: 'maquinas',             label: 'Aseo de máquinas (licuadoras, hornos y molinos)' },
  { key: 'recipientes',          label: 'Limpieza de recipientes (Milo, Oreo, granizado, café descafeinado, azúcar)' },
  { key: 'loza',                 label: 'Limpieza y desmanchado de loza (tazas, platos y copas)' },
  { key: 'utensilios',           label: 'Desinfección de utensilios (jarras, espresso, cucharas, jigger, cuchillos)' },
  { key: 'avisos_pop',           label: 'Limpieza de avisos y material POP' },
  { key: 'sillas_mesas_barra',   label: 'Sillas, mesas y barra (aseo general patas y por debajo)' },
]

interface Registro {
  id: number; tarea_key: string; fecha: string; semana: number
  usuario_nombre: string; usuario_id: number; vobo: boolean
}

const MESES = [
  'Enero','Febrero','Marzo','Abril','Mayo','Junio',
  'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre',
]

function semanaDelMes(d: Date) {
  return Math.floor((d.getDate() - 1) / 7) + 1
}

export default function Limpieza() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.rol === 'admin'

  const hoy = new Date()
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [semana, setSemana] = useState(semanaDelMes(hoy))
  const [registros, setRegistros] = useState<Registro[]>([])
  const [loading, setLoading] = useState(false)
  const [marcando, setMarcando] = useState<string | null>(null)

  const cargar = async () => {
    if (!user?.tienda_id) return
    setLoading(true)
    try {
      const { data } = await api.get(`/limpieza/${user.tienda_id}/semanal`, { params: { mes, anio } })
      setRegistros(data)
    } catch {
      setRegistros([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { cargar() }, [mes, anio, user?.tienda_id])

  // Registros de la semana seleccionada, indexados por tarea_key
  const deEstaSemana: Record<string, Registro> = {}
  registros.filter(r => r.semana === semana).forEach(r => { deEstaSemana[r.tarea_key] = r })
  const completadas = Object.keys(deEstaSemana).length

  const marcar = async (key: string) => {
    if (!user?.tienda_id || marcando) return
    setMarcando(key)
    try {
      // Calculate date within selected week
      const dia = (semana - 1) * 7 + 1  // first day of that week
      const fechaTarea = new Date(anio, mes - 1, dia)
      // If current month/week and today falls in it, use today
      const esHoy = mes === hoy.getMonth() + 1 && anio === hoy.getFullYear() && semana === semanaDelMes(hoy)
      const fechaEnviar = esHoy ? hoy.toISOString().split('T')[0] : fechaTarea.toISOString().split('T')[0]

      const { data } = await api.post(`/limpieza/${user.tienda_id}/semanal`, {
        tarea_key: key,
        fecha: fechaEnviar,
      })
      setRegistros(prev => [...prev, data])
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Error al registrar tarea')
    } finally {
      setMarcando(null)
    }
  }

  const eliminar = async (registro: Registro) => {
    if (!user?.tienda_id) return
    if (!confirm('¿Eliminar este registro?')) return
    try {
      await api.delete(`/limpieza/${user.tienda_id}/semanal/${registro.id}`)
      setRegistros(prev => prev.filter(r => r.id !== registro.id))
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Error al eliminar')
    }
  }

  const toggleVobo = async (registro: Registro) => {
    if (!user?.tienda_id) return
    try {
      await api.patch(`/limpieza/${user.tienda_id}/semanal/${registro.id}/vobo`, {
        valor: !registro.vobo,
      })
      setRegistros(prev => prev.map(r => r.id === registro.id ? { ...r, vobo: !r.vobo } : r))
    } catch {
      alert('Error al actualizar VoBo')
    }
  }

  const prevMes = () => {
    if (mes === 1) { setMes(12); setAnio(a => a - 1) }
    else setMes(m => m - 1)
    setSemana(1)
  }
  const nextMes = () => {
    if (mes === 12) { setMes(1); setAnio(a => a + 1) }
    else setMes(m => m + 1)
    setSemana(1)
  }

  const content = (
    <div className="space-y-4 pb-10">
      {/* Month nav */}
      <div className="flex items-center justify-between">
        <button onClick={prevMes} className="p-2 rounded-lg hover:bg-warm-100 transition-colors">
          <ChevronLeft size={18} className="text-warm-600" />
        </button>
        <div className="text-center">
          <p className="text-base font-bold text-warm-700 capitalize">{MESES[mes - 1]} {anio}</p>
          <p className="text-xs text-warm-400">{completadas} / {TAREAS.length} tareas esta semana</p>
        </div>
        <button onClick={nextMes} className="p-2 rounded-lg hover:bg-warm-100 transition-colors">
          <ChevronRight size={18} className="text-warm-600" />
        </button>
      </div>

      {/* Week selector */}
      <div className="flex gap-2">
        {[1, 2, 3, 4].map(s => (
          <button
            key={s}
            onClick={() => setSemana(s)}
            className="flex-1 py-2 rounded-xl text-xs font-semibold transition-all"
            style={{
              background: semana === s ? 'oklch(35% 0.05 155)' : 'oklch(96% 0.008 75)',
              color: semana === s ? 'white' : 'oklch(40% 0.01 60)',
            }}
          >
            Semana {s}
          </button>
        ))}
      </div>

      {/* Progress bar */}
      <div className="w-full bg-warm-200 rounded-full h-1.5">
        <div
          className="h-1.5 rounded-full transition-all"
          style={{ width: `${(completadas / TAREAS.length) * 100}%`, background: 'oklch(48% 0.12 155)' }}
        />
      </div>

      {/* Task list */}
      {loading ? (
        <p className="text-sm text-warm-400 text-center py-8 animate-pulse">Cargando...</p>
      ) : (
        <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
          <div className="divide-y divide-warm-100">
            {TAREAS.map((tarea, i) => {
              const reg = deEstaSemana[tarea.key]
              const hecho = !!reg
              const puedoEliminar = reg && (reg.usuario_id === user?.user_id || isAdmin)

              return (
                <div key={tarea.key} className={`px-4 py-3.5 transition-colors ${hecho ? 'bg-forest-50' : ''}`}>
                  <div className="flex items-start gap-3">
                    {/* Status icon / tap to mark */}
                    <button
                      onClick={() => !hecho && marcar(tarea.key)}
                      disabled={hecho || marcando === tarea.key}
                      className="shrink-0 mt-0.5 transition-all active:scale-95 disabled:cursor-default"
                    >
                      {marcando === tarea.key ? (
                        <div className="w-5 h-5 rounded-full border-2 border-forest animate-spin border-t-transparent" />
                      ) : hecho ? (
                        <CheckCircle2 size={20} className="text-forest-500" />
                      ) : (
                        <Circle size={20} className="text-warm-300" />
                      )}
                    </button>

                    {/* Label + info */}
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm leading-snug ${hecho ? 'text-warm-700 font-medium' : 'text-warm-500'}`}>
                        <span className="text-[10px] font-bold text-warm-300 mr-1.5">{String(i + 1).padStart(2, '0')}</span>
                        {tarea.label}
                      </p>
                      {hecho && (
                        <p className="text-xs text-forest mt-0.5">
                          {reg.usuario_nombre} ·{' '}
                          {new Date(reg.fecha).toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })}
                          {reg.vobo && (
                            <span className="ml-2 inline-flex items-center gap-0.5 text-forest-500 font-semibold">
                              <ShieldCheck size={11} /> VoBo
                            </span>
                          )}
                        </p>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1.5 shrink-0">
                      {/* Admin VoBo toggle */}
                      {isAdmin && hecho && (
                        <button
                          onClick={() => toggleVobo(reg)}
                          className="p-1.5 rounded-lg transition-colors"
                          style={{
                            background: reg.vobo ? 'oklch(90% 0.025 155)' : 'oklch(92% 0.006 75)',
                            color: reg.vobo ? 'oklch(35% 0.05 155)' : 'oklch(58% 0.01 60)',
                          }}
                          title="Marcar VoBo"
                        >
                          <ShieldCheck size={14} />
                        </button>
                      )}
                      {/* Delete */}
                      {puedoEliminar && (
                        <button
                          onClick={() => eliminar(reg)}
                          className="p-1.5 rounded-lg text-warm-300 hover:text-red-500 hover:bg-red-50 transition-colors"
                          title="Eliminar"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Legend */}
      <p className="text-xs text-warm-400 text-center">
        Toca el círculo de una tarea para marcarla como realizada
      </p>
    </div>
  )

  if (isAdmin) return content

  return (
    <BaristaLayout title="Limpieza semanal" backTo="/hub">
      {content}
    </BaristaLayout>
  )
}
