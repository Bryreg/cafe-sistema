import { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { ArrowLeft, Coffee } from 'lucide-react'

interface Props {
  children: ReactNode
  title?: string
  backTo?: string
  alertaBadge?: number
  /** Acción extra en el lado derecho del header (botón o texto) */
  rightAction?: ReactNode
}

export default function BaristaLayout({
  children,
  title,
  backTo = '/hub',
  rightAction,
}: Props) {
  const { user } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">

      {/* ── Header sticky ── */}
      <header className="bg-white border-b border-warm-200 px-4 pb-3 header-safe flex items-center gap-3 sticky top-0 z-10">
        <button
          onClick={() => navigate(backTo)}
          className="p-2 rounded-xl text-warm-400 hover:text-warm-700 hover:bg-warm-100 transition-colors -ml-1"
        >
          <ArrowLeft size={18} />
        </button>

        {title ? (
          <span className="flex-1 text-sm font-bold text-warm-700">{title}</span>
        ) : (
          <div className="flex-1 flex items-center gap-1.5">
            <Coffee size={15} className="text-forest" />
            <span className="text-sm font-bold text-warm-700">Sistema Café</span>
          </div>
        )}

        {rightAction ?? (
          <span className="text-xs text-warm-400 font-medium">
            {user?.nombre?.split(' ')[0]}
          </span>
        )}
      </header>

      {/* ── Contenido principal ── */}
      <main className="flex-1 p-4 max-w-lg mx-auto w-full pb-nav">
        {children}
      </main>
    </div>
  )
}
