import {
  LayoutDashboard, Layers, Coffee,
  Banknote, Wrench, ClipboardCheck, Activity,
  Bell, Inbox, BarChart2, Users, Tag, RotateCcw, Calculator, Scale, Boxes, Wallet,
  Receipt, ShieldCheck, ListChecks, BookOpen, TrendingUp, Package, CalendarDays,
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
  // «Plata» reemplaza a Rentabilidad y a Costos, que nunca fueron dos temas: el
  // costo operativo del P&L ES el módulo de Costos leído por otra puerta. Tenerlos
  // separados producía las dos quejas del dueño a la vez —«rentabilidad es pobre»
  // y «no veo nómina ni arriendo»—, que eran el mismo bug visto de dos lados.
  { label: 'Resumen', items: [
    { to: '/dashboard',           label: 'Dashboard',    icon: LayoutDashboard },
    { to: '/plata',               label: 'Plata',        icon: TrendingUp },
  ]},
  { label: 'Ventas', items: [
    { to: '/informe-contador',   label: 'Informe Contador', icon: Calculator      },
    { to: '/informes',           label: 'Informes',         icon: BarChart2       },
    { to: '/notas-credito',      label: 'Notas crédito',    icon: RotateCcw       },
  ]},
  // Inventario habla de UNA sola cosa —el stock físico— en tres momentos: qué hay
  // hoy, qué contaron las baristas y cómo cierra el mes. Catálogo y Combos NO son
  // inventario: son maestros (definen productos, no existencias) y por eso se fueron
  // al grupo Maestros. Lotes es un detalle del producto, no un tema aparte.
  { label: 'Inventario', items: [
    { to: '/control-inventario',      label: 'Inventario',     icon: Layers          },
    { to: '/conteos-admin',           label: 'Conteos',        icon: ListChecks      },
    { to: '/conciliacion-inventario', label: 'Cierre de mes',  icon: Scale           },
    { to: '/lotes',                   label: 'Lotes',          icon: Boxes           },
  ]},
  // "Pagos proveedores" salió de acá en la fase 5: vive como pestaña dentro de
  // Costos, junto a la agenda y al flujo. La plata que sale es un solo tema.
  { label: 'Caja', items: [
    { to: '/cuadre-turnos',     label: 'Cuadres',        icon: Wallet          },
    { to: '/consignaciones',    label: 'Consignaciones', icon: Banknote        },
  ]},
  { label: 'Operación', items: [
    // Horarios vive en Operación (junto a Comunicados y Cumplimiento) porque su
    // pregunta es «quién trabaja y cuándo», no «cuánto cuesta». El costo estimado
    // de esas horas se lee adentro del propio módulo, en la pestaña del mes.
    { to: '/horarios',            label: 'Horarios',       icon: CalendarDays    },
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
    { to: '/carta',              label: 'Carta',          icon: Coffee          },
    { to: '/catalogo',           label: 'Catálogo',       icon: Tag             },
    { to: '/combos',             label: 'Combos',         icon: Package         },
    { to: '/usuarios',           label: 'Usuarios',       icon: Users           },
    { to: '/config-ticket',      label: 'Config ticket',  icon: Receipt         },
  ]},
  { label: 'Ayuda', items: [
    { to: '/guia',               label: 'Guía rápida',    icon: BookOpen        },
  ]},
]

/** Lista plana derivada — compat para componentes que aún no migraron a grupos. */
export const NAV_ADMIN: NavItem[] = NAV_GROUPS.flatMap(g => g.items)
