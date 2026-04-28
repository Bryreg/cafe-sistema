import { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { ArrowLeft, LogOut, Coffee } from 'lucide-react'

interface Props {
  children: ReactNode
  title?: string
  backTo?: string
}

export default function BaristaLayout({ children, title, backTo = '/hub' }: Props) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center gap-3 sticky top-0 z-10">
        <button onClick={() => navigate(backTo)}
          className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors">
          <ArrowLeft size={18} />
        </button>
        {title ? (
          <span className="flex-1 text-sm font-bold text-gray-800">{title}</span>
        ) : (
          <div className="flex-1 flex items-center gap-1.5">
            <Coffee size={15} className="text-amber-600" />
            <span className="text-sm font-bold text-gray-800">Sistema Café</span>
          </div>
        )}
        <span className="text-xs text-gray-400">{user?.nombre}</span>
        <button onClick={() => { logout(); navigate('/login') }}
          className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors">
          <LogOut size={15} />
        </button>
      </header>
      <main className="flex-1 p-4 max-w-lg mx-auto w-full">{children}</main>
    </div>
  )
}
