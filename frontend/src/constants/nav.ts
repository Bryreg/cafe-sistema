import {
  LayoutDashboard, Layers, ClipboardList, ShoppingCart,
  Banknote, Wrench, ClipboardCheck, Activity,
  Bell, Inbox, BarChart2, Users, Tag, BarChart3, RotateCcw, Calculator,
} from 'lucide-react'

export interface NavItem { to: string; label: string; icon: typeof Layers }
export interface NavGroup { label: string; items: NavItem[] }

/**
 * Navegación admin agrupada por dominio. ÚNICA fuente de navegación del cockpit
 * (la usan el sidebar y el drawer de Layout, y el dashboard cuando va envuelto en
 * Layout). Reemplaza las 3 navegaciones desconectadas (top-nav de AdminHub,
 * lista plana de 15 items, bottom-nav mobile).
 */
export const NAV_GROUPS: NavGroup[] = [
  { label: 'Resumen', items: [
    { to: '/dashboard',          label: 'Dashboard',      icon: LayoutDashboard },
  ]},
  { label: 'Ventas', items: [
    { to: '/analytics',          label: 'Analítica',        icon: BarChart3       },
    { to: '/informe-contador',   label: 'Informe Contador', icon: Calculator      },
    { to: '/informes',           label: 'Informes',         icon: BarChart2       },
    { to: '/notas-credito',      label: 'Notas crédito',    icon: RotateCcw       },
  ]},
  { label: 'Inventario', items: [
    { to: '/control-inventario', label: 'Inventario',     icon: Layers          },
    { to: '/catalogo',           label: 'Catálogo',       icon: Tag             },
  ]},
  { label: 'Pedidos y compras', items: [
    { to: '/pedidos-admin',      label: 'Pedidos',        icon: ClipboardList   },
    { to: '/compras',            label: 'Compras',        icon: ShoppingCart    },
  ]},
  { label: 'Caja', items: [
    { to: '/consignaciones',     label: 'Consignaciones', icon: Banknote        },
  ]},
  { label: 'Operación', items: [
    { to: '/mantenimientos',     label: 'Mantenimientos', icon: Wrench          },
    { to: '/auditorias',         label: 'Auditorías',     icon: ClipboardCheck  },
    { to: '/comunicados',        label: 'Comunicados',    icon: Bell            },
    { to: '/bandeja',            label: 'Bandeja',        icon: Inbox           },
  ]},
  { label: 'Registro', items: [
    { to: '/audit-log',          label: 'Historial',      icon: Activity        },
  ]},
  { label: 'Maestros', items: [
    { to: '/usuarios',           label: 'Usuarios',       icon: Users           },
  ]},
]

/** Lista plana derivada — compat para componentes que aún no migraron a grupos. */
export const NAV_ADMIN: NavItem[] = NAV_GROUPS.flatMap(g => g.items)
