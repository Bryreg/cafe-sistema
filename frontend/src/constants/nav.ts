import {
  LayoutDashboard, Layers, ClipboardList, ShoppingCart,
  Banknote, Wrench, ClipboardCheck, Activity,
  Bell, Inbox, BarChart2, Users, Link2,
} from 'lucide-react'

export const NAV_ADMIN = [
  { to: '/dashboard',          label: 'Dashboard',      icon: LayoutDashboard },
  { to: '/control-inventario', label: 'Inventario',     icon: Layers          },
  { to: '/pedidos-admin',      label: 'Pedidos',        icon: ClipboardList   },
  { to: '/compras',            label: 'Compras',        icon: ShoppingCart    },
  { to: '/consignaciones',     label: 'Consignaciones', icon: Banknote        },
  { to: '/mantenimientos',     label: 'Mantenimientos', icon: Wrench          },
  { to: '/auditorias',         label: 'Auditorías',     icon: ClipboardCheck  },
  { to: '/audit-log',          label: 'Historial',      icon: Activity        },
  { to: '/comunicados',        label: 'Comunicados',    icon: Bell            },
  { to: '/bandeja',            label: 'Bandeja',        icon: Inbox           },
  { to: '/informes',           label: 'Informes',       icon: BarChart2       },
  { to: '/usuarios',           label: 'Usuarios',       icon: Users           },
  { to: '/siigo-mapeo',        label: 'Mapeo Siigo',    icon: Link2           },
]
