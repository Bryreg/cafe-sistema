import { Truck, Trash2, Package, ShoppingCart, Coins, Receipt, UserPlus, DoorOpen } from 'lucide-react'
import { dark } from '../constants/darkTheme'

const TOOLS = [
  { key: 'entrada',        label: 'Entrada',        icon: UserPlus  },
  { key: 'salida',         label: 'Salida',         icon: DoorOpen  },
  { key: 'ingresos',       label: 'Recibir',        icon: Truck     },
  { key: 'mermas',         label: 'Merma',          icon: Trash2    },
  { key: 'inventario',     label: 'Inventario',     icon: Package   },
  { key: 'pedido',         label: 'Pedido',         icon: ShoppingCart },
  { key: 'sencilla',       label: 'Sencilla',       icon: Coins     },
  { key: 'consignaciones', label: 'Consignaciones', icon: Receipt   },
]

export default function DockBar({
  active,
  onSelect,
}: {
  active: string | null
  onSelect: (key: string | null) => void
}) {
  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-30 flex items-center justify-around border-t px-1"
      style={{
        height: 60,
        background: dark.surface,
        borderColor: dark.border,
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
      }}
    >
      {TOOLS.map(({ key, label, icon: Icon }) => {
        const on = active === key
        return (
          <button
            key={key}
            onClick={() => onSelect(on ? null : key)}
            className="flex flex-col items-center justify-center gap-0.5 rounded-xl transition-all"
            style={{
              minWidth: 44,
              height: 48,
              padding: '6px 4px',
              background: on ? dark.greenTint : 'transparent',
              color: on ? dark.green : dark.inkSubtle,
            }}
          >
            <Icon size={18} />
            <span style={{ fontSize: 9, fontWeight: 600, lineHeight: 1.1 }}>{label}</span>
          </button>
        )
      })}
    </div>
  )
}
