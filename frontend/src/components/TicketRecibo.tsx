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
  }>
}

interface Props {
  ticket: TicketData
  negocio?: string
  nit?: string
}

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

function parseTicketDate(raw: string): Date {
  const t = raw.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

export default function TicketRecibo({ ticket, negocio = 'AZ CAFE', nit = '52425817-4' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Inyecta CSS de impresión una sola vez en el <head>
  useEffect(() => {
    const styleId = 'ticket-print-style'
    if (document.getElementById(styleId)) return

    const style = document.createElement('style')
    style.id = styleId
    // Patrón "imprimir solo este div" con visibility (NO display:none).
    // El ticket está anidado dentro de #root; si se oculta el padre con
    // display:none, el hijo no se muestra aunque tenga display:block. visibility
    // sí se hereda y se puede revertir en los descendientes, así que ocultamos
    // todo y volvemos a mostrar solo el subárbol del ticket.
    style.textContent = `
      @media print {
        @page {
          size: 80mm auto;
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
          width: 80mm;
        }
      }
    `
    document.head.appendChild(style)
    return () => {
      const el = document.getElementById(styleId)
      if (el) el.remove()
    }
  }, [])

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
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: small ? '9px' : '10px', fontWeight: bold ? 'bold' : 'normal', margin: '1px 0' }}>
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
          lineHeight: '1.4',
          width: '80mm',
          padding: '4mm 4mm 8mm',
          color: '#000',
          background: '#fff',
        }}
      >
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: '6px' }}>
          {/* Logo placeholder — replace with <img> tag when logo file is available */}
          <div style={{ fontWeight: 'bold', fontSize: '16px', letterSpacing: '3px' }}>
            {negocio.toUpperCase()}
          </div>
          <div style={{ fontSize: '10px', marginTop: '1px' }}>
            NIT: {nit}
          </div>
          <div style={{ fontSize: '9px', color: '#555', marginTop: '2px' }}>
            Documento de Ingreso — NO reemplaza la factura
          </div>
        </div>

        <div style={{ borderBottom: '1px dashed #000', margin: '5px 0' }} />

        {/* Date / ticket / client */}
        <div style={{ fontSize: '10px', display: 'flex', justifyContent: 'space-between' }}>
          <span>Fecha: {fechaStr}</span>
          <span>Hora: {horaStr}</span>
        </div>
        <div style={{ fontSize: '10px' }}>No. Ticket: #{String(ticket.id).padStart(6, '0')}</div>
        <div style={{ fontSize: '10px' }}>Cliente: Consumidor Final</div>

        <div style={{ borderBottom: '1px dashed #000', margin: '5px 0' }} />

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
            <div key={i} style={{ marginBottom: desc > 0 ? '4px' : '2px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px' }}>
                <span style={{ flex: 1, paddingRight: '4px', wordBreak: 'break-word' }}>{item.nombre_producto}</span>
                <span style={{ width: '24px', textAlign: 'right', flexShrink: 0 }}>{item.cantidad}</span>
                <span style={{ width: '58px', textAlign: 'right', flexShrink: 0 }}>{fmtCO(item.precio_unitario)}</span>
                <span style={{ width: '62px', textAlign: 'right', flexShrink: 0, fontWeight: desc > 0 ? 'normal' : 'bold' }}>
                  {fmtCO(bruto)}
                </span>
              </div>
              {desc > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: '#555', paddingLeft: '8px' }}>
                  <span>Descuento ({Math.round(desc / bruto * 100)}%)</span>
                  <span style={{ fontWeight: 'bold', color: '#000' }}>−{fmtCO(desc)}</span>
                </div>
              )}
            </div>
          )
        })}

        <div style={{ borderBottom: '1px solid #000', margin: '5px 0' }} />

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

        <div style={{ borderBottom: '1px dashed #000', margin: '5px 0' }} />

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

        <div style={{ borderBottom: '1px dashed #000', margin: '5px 0' }} />

        {/* Footer */}
        <div style={{ textAlign: 'center', fontSize: '9px', color: '#444', marginTop: '4px' }}>
          <div style={{ fontWeight: 'bold' }}>¡Gracias por tu compra!</div>
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
