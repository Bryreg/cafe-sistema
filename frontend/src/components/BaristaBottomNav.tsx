import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  CalendarClock, Banknote, LayoutGrid, X as XIcon,
  Trash2, ShoppingCart, Coins, ClipboardList,
  Truck, ClipboardCheck, Sparkles, Package, UserCheck, Calculator, TrendingUp,
} from 'lucide-react'
import { useTurno } from '../contexts/TurnoContext'
import MovimientoCajaModal from './MovimientoCajaModal'

// ─── Herramientas disponibles en el drawer ────────────────────────────────────
const TOOLS = [
  { label: 'Mermas',     icon: Trash2,        to: '/mermas',         color: 'text-orange-500', bg: 'bg-orange-50'  },
  { label: 'Inventario', icon: Package,        to: '/inventario',     color: 'text-blue-500',   bg: 'bg-blue-50'    },
  { label: 'Pedido',     icon: ShoppingCart,   to: '/pedido',         color: 'text-forest',     bg: 'bg-forest-50'  },
  { label: 'Sencilla',   icon: Coins,          to: '/sencilla',       color: 'text-amber-600',  bg: 'bg-amber-50'   },
  { label: 'Consig.',    icon: Banknote,       to: '/consignaciones', color: 'text-teal-600',   bg: 'bg-teal-50'    },
  { label: 'Conteos',    icon: ClipboardList,  to: '/conteos',        color: 'text-purple-500', bg: 'bg-purple-50'  },
  { label: 'Ingresos',   icon: Truck,          to: '/ingresos',       color: 'text-warm-600',   bg: 'bg-warm-100'   },
  { label: 'Conteo C.',  icon: ClipboardCheck, to: '/conteo-compras', color: 'text-indigo-500', bg: 'bg-indigo-50'  },
  { label: 'Limpieza',   icon: Sparkles,       to: '/limpieza',       color: 'text-pink-500',   bg: 'bg-pink-50'    },
  { label: 'Cuadre',     icon: UserCheck,      to: '/entrega',        color: 'text-warm-500',   bg: 'bg-warm-100'   },
  { label: 'Mis ventas', icon: TrendingUp,     to: '/ventas-hoy',     color: 'text-success-600', bg: 'bg-success-50' },
]

interface Props { alertaBadge?: number }

export default function BaristaBottomNav({ alertaBadge }: Props) {
  const { turno } = useTurno()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [showMas, setShowMas] = useState(false)
  const [showCaja, setShowCaja] = useState(false)

  const tabs = [
    { id: 'pos',    to: '/pos',            label: 'POS',    icon: Calculator  },
    { id: 'turno',  to: '/gestion-turno',  label: 'Turno',  icon: CalendarClock },
    { id: 'caja',   to: null,              label: 'Caja',   icon: Banknote    },
    { id: 'mas',    to: null,              label: 'Más',    icon: LayoutGrid, badge: alertaBadge },
  ]

  return (
    <>
      {/* ── Barra de navegación ── */}
      <nav
        className="fixed bottom-0 left-0 right-0 z-30 bg-white border-t border-warm-200"
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
      >
        <div className="flex max-w-lg mx-auto">
          {tabs.map(tab => {
            const isActive = tab.to ? pathname === tab.to : tab.id === 'mas' && showMas
            const Icon = tab.icon
            const handleClick = tab.to
              ? () => navigate(tab.to!)
              : tab.id === 'caja'
                ? () => turno && setShowCaja(true)
                : () => setShowMas(true)

            const isPOS = tab.id === 'pos'

            return (
              <button
                key={tab.id}
                onClick={handleClick}
                disabled={tab.id === 'caja' && !turno}
                className={`relative flex-1 flex flex-col items-center gap-0.5 transition-all active:scale-95 ${
                  tab.id === 'caja' && !turno ? 'opacity-30' : ''
                } ${isPOS ? 'py-1.5' : 'py-2.5'}`}
              >
                {/* Badge */}
                {tab.badge != null && tab.badge > 0 && (
                  <span className="absolute top-1.5 translate-x-3 bg-red-500 text-white text-[8px] font-bold w-3.5 h-3.5 rounded-full flex items-center justify-center leading-none">
                    {tab.badge > 9 ? '9+' : tab.badge}
                  </span>
                )}

                {isPOS ? (
                  /* POS: pill destacado */
                  <span className={`flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-2xl transition-colors ${
                    isActive ? 'bg-green-600' : 'bg-green-50'
                  }`}>
                    <Icon
                      size={20}
                      className={isActive ? 'text-white' : 'text-green-600'}
                      strokeWidth={2.2}
                    />
                    <span className={`text-[10px] font-bold ${isActive ? 'text-white' : 'text-green-600'}`}>
                      {tab.label}
                    </span>
                  </span>
                ) : (
                  <>
                    <Icon
                      size={21}
                      className={isActive ? 'text-forest' : 'text-warm-400'}
                      strokeWidth={isActive ? 2.2 : 1.8}
                    />
                    <span className={`text-[10px] font-semibold ${isActive ? 'text-forest' : 'text-warm-400'}`}>
                      {tab.label}
                    </span>
                    {/* Active indicator dot */}
                    {isActive && (
                      <span className="absolute top-0 left-1/2 -translate-x-1/2 w-6 h-0.5 rounded-full"
                        style={{ background: 'oklch(35% 0.05 155)' }} />
                    )}
                  </>
                )}
              </button>
            )
          })}
        </div>
      </nav>

      {/* ── Modal: movimiento de caja ── */}
      {showCaja && turno && (
        <MovimientoCajaModal turnoId={turno.id} onClose={() => setShowCaja(false)} />
      )}

      {/* ── Drawer: más herramientas ── */}
      {showMas && (
        <div
          className="fixed inset-0 z-40 bg-black/50 flex items-end"
          onClick={() => setShowMas(false)}
        >
          <div
            className="w-full bg-white rounded-t-3xl"
            style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 1.25rem)' }}
            onClick={e => e.stopPropagation()}
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-3 pb-1">
              <div className="w-10 h-1 rounded-full bg-warm-200" />
            </div>

            {/* Header */}
            <div className="flex items-center justify-between px-5 pt-2 pb-4 border-b border-warm-100">
              <p className="text-sm font-bold text-warm-700">Herramientas</p>
              <button
                onClick={() => setShowMas(false)}
                className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors"
              >
                <XIcon size={16} />
              </button>
            </div>

            {/* Tools grid */}
            <div className="grid grid-cols-5 gap-2 px-4 pt-4">
              {TOOLS.map(({ label, icon: Icon, to, color, bg }) => (
                <button
                  key={to}
                  onClick={() => { setShowMas(false); navigate(to) }}
                  className="flex flex-col items-center gap-1.5 py-3 rounded-2xl border border-warm-100 bg-white hover:bg-warm-50 active:scale-95 transition-all"
                >
                  <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${bg}`}>
                    <Icon size={17} className={color} />
                  </div>
                  <span className="text-xs font-semibold text-warm-500 text-center leading-tight px-0.5">
                    {label}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
