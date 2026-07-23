import { useEffect, useRef } from 'react'

export interface TicketData {
  id: number
  fecha: string
  total: number
  cambio: number
  metodo_pago: 'efectivo' | 'tarjeta' | 'mixto'
  efectivo_recibido?: number
  monto_efectivo?: number
  monto_tarjeta?: number
  items: Array<{
    nombre_producto: string
    cantidad: number
    precio_unitario: number
    subtotal: number
    descuento?: number
    // Solo líneas de combo: combinación elegida (se imprime como sub-líneas)
    combo_selecciones?: Array<{ nombre_grupo: string; nombre_opcion: string; cantidad: number }>
  }>
}

interface Props {
  ticket: TicketData
  negocio?: string
  nit?: string
  telefono?: string
  direccion?: string
  logoUrl?: string | null
  mensajeFooter?: string
  anchoPapelMm?: number
  margenMm?: number
  escalaFuente?: 'small' | 'normal' | 'large'
}

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

function parseTicketDate(raw: string): Date {
  const t = raw.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

const ESCALA: Record<string, number> = { small: 0.82, normal: 1.0, large: 1.22 }

export default function TicketRecibo({
  ticket,
  negocio = 'AZ CAFE',
  nit,
  telefono,
  direccion,
  logoUrl,
  mensajeFooter = '¡Gracias por tu compra!',
  anchoPapelMm = 80,
  margenMm = 2,
  escalaFuente = 'normal',
}: Props) {
  const zoom = ESCALA[escalaFuente] ?? 1.0
  const anchoBase = Math.round(anchoPapelMm / zoom)
  // Margen lateral configurable (compensado por el zoom). El extra abajo deja aire para el corte.
  const padH = +(margenMm / zoom).toFixed(2)
  const padBottom = +((margenMm + 4) / zoom).toFixed(2)
  const containerRef = useRef<HTMLDivElement>(null)

  // Inyecta CSS de impresión — se actualiza si cambian anchoPapelMm o escalaFuente
  useEffect(() => {
    const styleId = 'ticket-print-style'
    let style = document.getElementById(styleId) as HTMLStyleElement | null
    if (!style) {
      style = document.createElement('style')
      style.id = styleId
      document.head.appendChild(style)
    }
    // Patrón "imprimir solo este div" con visibility (NO display:none).
    // zoom escala todo el contenido; anchoBase compensa para que al escalar
    // quede exactamente el ancho de papel seleccionado.
    style.textContent = `
      @media print {
        @page {
          size: ${anchoPapelMm}mm auto;
          margin: 0;
        }
        html, body {
          margin: 0 !important;
          padding: 0 !important;
          background: #fff !important;
        }
        body * {
          visibility: hidden !important;
        }
        #ticket-print-root,
        #ticket-print-root * {
          visibility: visible !important;
        }
        #ticket-print-root {
          display: block !important;
          position: absolute;
          left: 0;
          top: 0;
          box-sizing: border-box !important;
          width: ${anchoBase}mm;
          padding: ${padH}mm ${padH}mm ${padBottom}mm !important;
          zoom: ${zoom};
        }
      }
    `
    return () => {
      const el = document.getElementById(styleId)
      if (el) el.remove()
    }
  }, [anchoPapelMm, anchoBase, zoom, margenMm, padH, padBottom])

  const fecha = parseTicketDate(ticket.fecha)
  const fechaStr = fecha.toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' })
  const horaStr = fecha.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })

  const metodoPagoLabel: Record<string, string> = {
    efectivo: 'EFECTIVO',
    tarjeta: 'TARJETA',
    mixto: 'MIXTO',
  }

  const totalDescuento = ticket.items.reduce((s, i) => s + (i.descuento || 0), 0)

  const row = (label: string, value: string, bold = false, small = false) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: small ? '9px' : '10px', fontWeight: 'bold', margin: '4px 0' }}>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  )

  return (
    <>
      {/* Hidden on screen; only visible when printing */}
      <div
        id="ticket-print-root"
        ref={containerRef}
        style={{
          display: 'none',
          fontFamily: '"Courier New", Courier, monospace',
          fontSize: '11px',
          fontWeight: 'bold',
          lineHeight: '1.9',
          width: '80mm',
          padding: '4mm 4mm 8mm',
          color: '#000',
          background: '#fff',
        }}
      >
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: '10px' }}>
          {logoUrl && (
            <img
              src={logoUrl}
              alt="Logo"
              style={{ maxHeight: '40px', maxWidth: '120px', objectFit: 'contain', display: 'block', margin: '0 auto 4px' }}
            />
          )}
          <div style={{ fontWeight: 'bold', fontSize: '16px', letterSpacing: '3px' }}>
            {negocio.toUpperCase()}
          </div>
          {nit      && <div style={{ fontSize: '10px', marginTop: '1px' }}>NIT: {nit}</div>}
          {telefono && <div style={{ fontSize: '10px', marginTop: '1px' }}>Tel: {telefono}</div>}
          {direccion && <div style={{ fontSize: '9px', marginTop: '1px', color: '#000' }}>{direccion}</div>}
          <div style={{ fontSize: '9px', color: '#000', marginTop: '2px' }}>
            Documento de Ingreso — NO reemplaza la factura
          </div>
        </div>

        <div style={{ borderBottom: '1px dashed #000', margin: '9px 0' }} />

        {/* Date / ticket / client */}
        <div style={{ fontSize: '10px', display: 'flex', justifyContent: 'space-between' }}>
          <span>Fecha: {fechaStr}</span>
          <span>Hora: {horaStr}</span>
        </div>
        <div style={{ fontSize: '10px' }}>No. Ticket: #{String(ticket.id).padStart(6, '0')}</div>
        <div style={{ fontSize: '10px' }}>Cliente: Consumidor Final</div>

        <div style={{ borderBottom: '1px dashed #000', margin: '9px 0' }} />

        {/* Column headers */}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', fontWeight: 'bold', textTransform: 'uppercase', marginBottom: '3px' }}>
          <span style={{ flex: 1 }}>Producto</span>
          <span style={{ width: '24px', textAlign: 'right' }}>Cant</span>
          <span style={{ width: '58px', textAlign: 'right' }}>P.Unit</span>
          <span style={{ width: '62px', textAlign: 'right' }}>Subtotal</span>
        </div>

        {/* Item rows */}
        {ticket.items.map((item, i) => {
          const bruto = item.precio_unitario * item.cantidad
          const desc = item.descuento || 0
          return (
            <div key={i} style={{ marginBottom: desc > 0 ? '8px' : '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px' }}>
                <span style={{ flex: 1, paddingRight: '4px', wordBreak: 'break-word' }}>{item.nombre_producto}</span>
                <span style={{ width: '24px', textAlign: 'right', flexShrink: 0 }}>{item.cantidad}</span>
                <span style={{ width: '58px', textAlign: 'right', flexShrink: 0 }}>{fmtCO(item.precio_unitario)}</span>
                <span style={{ width: '62px', textAlign: 'right', flexShrink: 0, fontWeight: 'bold' }}>
                  {fmtCO(bruto)}
                </span>
              </div>
              {/* Combinación elegida (líneas de combo) — una sub-línea por opción.
                  Las opciones compuestas traen una fila por producto: se dedupe
                  por grupo+opción para imprimir la opción una sola vez. */}
              {Array.from(
                new Map(
                  (item.combo_selecciones || []).map(s => [
                    `${s.nombre_grupo}|${s.nombre_opcion}`, s,
                  ]),
                ).values(),
              ).map((s, j) => (
                <div key={j} style={{ fontSize: '9px', color: '#000', paddingLeft: '8px' }}>
                  · {s.nombre_opcion}
                </div>
              ))}
              {desc > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: '#000', paddingLeft: '8px' }}>
                  <span>Descuento ({Math.round(desc / bruto * 100)}%)</span>
                  <span style={{ fontWeight: 'bold', color: '#000' }}>−{fmtCO(desc)}</span>
                </div>
              )}
            </div>
          )
        })}

        <div style={{ borderBottom: '1px solid #000', margin: '9px 0' }} />

        {/* Totals section */}
        {totalDescuento > 0 ? (
          <>
            {row('Subtotal bruto:', fmtCO(ticket.items.reduce((s, i) => s + i.precio_unitario * i.cantidad, 0)))}
            {row('Descuento total:', `−${fmtCO(totalDescuento)}`)}
            <div style={{ borderBottom: '1px dashed #000', margin: '3px 0' }} />
          </>
        ) : null}

        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', fontWeight: 'bold', margin: '3px 0' }}>
          <span>TOTAL</span>
          <span>{fmtCO(ticket.total)}</span>
        </div>

        <div style={{ borderBottom: '1px dashed #000', margin: '9px 0' }} />

        {/* Payment info */}
        <div style={{ fontSize: '10px', margin: '2px 0' }}>
          {row('Método de pago:', metodoPagoLabel[ticket.metodo_pago] ?? ticket.metodo_pago, true)}

          {ticket.metodo_pago === 'efectivo' && ticket.efectivo_recibido != null && (
            <>
              {row('Recibido:', fmtCO(ticket.efectivo_recibido))}
              {row('Cambio:', fmtCO(ticket.cambio), true)}
            </>
          )}

          {ticket.metodo_pago === 'mixto' && (
            <>
              {ticket.monto_efectivo != null && row('Efectivo:', fmtCO(ticket.monto_efectivo))}
              {ticket.monto_tarjeta != null && row('Tarjeta:', fmtCO(ticket.monto_tarjeta))}
              {ticket.cambio > 0 && row('Cambio:', fmtCO(ticket.cambio), true)}
            </>
          )}
        </div>

        <div style={{ borderBottom: '1px dashed #000', margin: '9px 0' }} />

        {/* Footer */}
        <div style={{ textAlign: 'center', fontSize: '9px', color: '#000', marginTop: '4px' }}>
          {mensajeFooter && <div style={{ fontWeight: 'bold' }}>{mensajeFooter}</div>}
          <div style={{ marginTop: '4px' }}>{'- '.repeat(16)}</div>
        </div>
      </div>
    </>
  )
}

/** Renderiza el ticket en el DOM oculto y dispara window.print() */
export function imprimirTicket(ticket: TicketData, negocio?: string) {
  // Asegura que el root exista (si el componente aún no montó)
  let root = document.getElementById('ticket-print-root')
  if (!root) {
    root = document.createElement('div')
    root.id = 'ticket-print-root'
    document.body.appendChild(root)
  }
  window.print()
}
