import {
  LayoutDashboard, Layers, ClipboardList,
  Banknote, Wrench, ClipboardCheck, Activity,
  Bell, Inbox, BarChart2, Users, Tag, RotateCcw, Calculator, Truck, Scale, Boxes, Wallet,
  Receipt, ShieldCheck, ListChecks, BookOpen,
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
    { to: '/dashboard',           label: 'Dashboard',   icon: LayoutDashboard },
  ]},
  { label: 'Ventas', items: [
    { to: '/informe-contador',   label: 'Informe Contador', icon: Calculator      },
    { to: '/informes',           label: 'Informes',         icon: BarChart2       },
    { to: '/notas-credito',      label: 'Notas crédito',    icon: RotateCcw       },
  ]},
  { label: 'Inventario', items: [
    { to: '/control-inventario',      label: 'Inventario',     icon: Layers          },
    { to: '/conteos-admin',           label: 'Conteos',        icon: ListChecks      },
    { to: '/lotes',                   label: 'Lotes',          icon: Boxes           },
    { to: '/conciliacion-inventario', label: 'Conciliación',   icon: Scale           },
    { to: '/catalogo',                label: 'Catálogo',       icon: Tag             },
  ]},
  { label: 'Pedidos y compras', items: [
    { to: '/pedidos-admin',      label: 'Pedidos',        icon: ClipboardList   },
    { to: '/pagos-proveedores',  label: 'Pagos proveedores', icon: Truck        },
  ]},
  { label: 'Caja', items: [
    { to: '/cuadre-turnos',     label: 'Cuadres',        icon: Wallet          },
    { to: '/consignaciones',    label: 'Consignaciones', icon: Banknote        },
  ]},
  { label: 'Operación', items: [
    { to: '/mantenimientos',      label: 'Mantenimientos', icon: Wrench          },
    { to: '/auditorias',          label: 'Auditorías',     icon: ClipboardCheck  },
    { to: '/cumplimiento',        label: 'Cumplimiento',   icon: ShieldCheck     },
    { to: '/comunicados',         label: 'Comunicados',    icon: Bell            },
    { to: '/bandeja',             label: 'Bandeja',        icon: Inbox           },
    { to: '/notificaciones-config', label: 'Notificaciones', icon: Bell          },
  ]},
  { label: 'Registro', items: [
    { to: '/audit-log',          label: 'Historial',      icon: Activity        },
  ]},
  { label: 'Maestros', items: [
    { to: '/usuarios',           label: 'Usuarios',       icon: Users           },
    { to: '/config-ticket',      label: 'Config ticket',  icon: Receipt         },
  ]},
  { label: 'Ayuda', items: [
    { to: '/guia',               label: 'Guía rápida',    icon: BookOpen        },
  ]},
]

/** Lista plana derivada — compat para componentes que aún no migraron a grupos. */
export const NAV_ADMIN: NavItem[] = NAV_GROUPS.flatMap(g => g.items)
