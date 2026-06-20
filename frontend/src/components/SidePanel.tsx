import { X } from 'lucide-react'
import { dark } from '../constants/darkTheme'

export default function SidePanel({
  children,
  onClose,
}: {
  children: React.ReactNode
  onClose: () => void
}) {
  return (
    <div
      className="fixed top-0 right-0 z-40 flex flex-col w-full sm:w-[420px]"
      style={{
        height: 'calc(100% - 60px)',
        background: dark.bg,
        borderLeft: `1px solid ${dark.border}`,
        boxShadow: '-4px 0 24px rgba(0,0,0,0.08)',
      }}
    >
      <div
        className="flex items-center justify-end px-3 py-2 flex-shrink-0"
        style={{ borderBottom: `1px solid ${dark.border}` }}
      >
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-full"
          style={{
            background: dark.surface,
            border: `1px solid ${dark.border}`,
            color: dark.ink,
          }}
          aria-label="Cerrar panel"
        >
          <X size={16} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">{children}</div>
    </div>
  )
}
