import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { dark } from '../constants/darkTheme'

interface TickerItem {
  id: string
  tipo: 'pasteleria' | 'comunicado' | 'consignacion'
  label: string
  urgente: boolean
  navigateTo?: string
}

const TIPO_CFG = {
  pasteleria:   { icon: '🥐', color: dark.amber  },
  comunicado:   { icon: '📢', color: dark.inkMuted },
  consignacion: { icon: '💰', color: dark.danger  },
}

export default function TickerNoticias() {
  const { tiendaId } = useAuth()
  const navigate = useNavigate()
  const [items, setItems] = useState<TickerItem[]>([])

  const load = async () => {
    if (!tiendaId) return
    const next: TickerItem[] = []

    try {
      const { data } = await api.get(`/pasteleria/tienda/${tiendaId}/activos`)
      const hoy = new Date()
      hoy.setHours(0, 0, 0, 0)
      for (const p of data ?? []) {
        if (!p.fecha_vencimiento) continue
        const venc = new Date(p.fecha_vencimiento)
        venc.setHours(0, 0, 0, 0)
        const diff = Math.round((venc.getTime() - hoy.getTime()) / 86_400_000)
        if (diff <= 2) {
          next.push({
            id: `past-${p.producto_nombre}`,
            tipo: 'pasteleria',
            label: diff <= 0
              ? `${p.producto_nombre} — vence HOY, impulsá la venta`
              : diff === 1
                ? `${p.producto_nombre} — vence mañana`
                : `${p.producto_nombre} — vence en 2 días`,
            urgente: diff <= 0,
          })
        }
      }
    } catch {}

    try {
      const { data } = await api.get('/comunicados/mis-comunicados')
      for (const c of data ?? []) {
        next.push({
          id: `com-${c.id}`,
          tipo: 'comunicado',
          label: c.mensaje ? `${c.titulo}: ${c.mensaje}` : c.titulo,
          urgente: c.urgente ?? false,
        })
      }
    } catch {}

    try {
      const { data } = await api.get(`/consignaciones/pendiente/${tiendaId}`)
      for (const item of data?.items ?? []) {
        if ((item.pendiente ?? 0) <= 0) continue
        const fecha = item.fecha_cierre
          ? new Date(item.fecha_cierre).toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit' })
          : `turno #${item.turno_id}`
        next.push({
          id: `consig-${item.turno_id}`,
          tipo: 'consignacion',
          label: `Consignación pendiente (${fecha}): $${Math.round(item.pendiente).toLocaleString('es-CO')}`,
          urgente: false,
          navigateTo: '/consignaciones',
        })
      }
    } catch {}

    setItems(next)
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [tiendaId])

  if (items.length === 0) return null

  const duration = Math.max(12, items.length * 6)
  const doubled = [...items, ...items]

  return (
    <div
      style={{
        height: 30,
        overflow: 'hidden',
        background: dark.surfaceAlt,
        borderBottom: `1px solid ${dark.border}`,
        flexShrink: 0,
      }}
    >
      <style>{`
        @keyframes ticker-scroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .ticker-track {
          display: flex;
          align-items: center;
          height: 100%;
          white-space: nowrap;
          width: max-content;
          animation: ticker-scroll ${duration}s linear infinite;
        }
        .ticker-track:hover { animation-play-state: paused; }
      `}</style>
      <div className="ticker-track">
        {doubled.map((item, i) => {
          const cfg = TIPO_CFG[item.tipo]
          if (item.navigateTo) {
            return (
              <button
                key={`${item.id}-${i}`}
                onClick={() => navigate(item.navigateTo!)}
                className="inline-flex items-center gap-1.5 px-4 h-full cursor-pointer"
              >
                <span className="text-[12px]">{cfg.icon}</span>
                <span className="text-[11px] font-semibold" style={{ color: item.urgente ? dark.danger : cfg.color }}>
                  {item.label}
                </span>
                <span className="mx-2 text-[8px]" style={{ color: dark.border }}>◆</span>
              </button>
            )
          }
          return (
            <span
              key={`${item.id}-${i}`}
              className="inline-flex items-center gap-1.5 px-4 h-full"
            >
              <span className="text-[12px]">{cfg.icon}</span>
              <span className="text-[11px] font-semibold" style={{ color: item.urgente ? dark.danger : cfg.color }}>
                {item.label}
              </span>
              <span className="mx-2 text-[8px]" style={{ color: dark.border }}>◆</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}
