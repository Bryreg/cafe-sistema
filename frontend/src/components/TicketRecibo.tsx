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
  }>
}

interface Props {
  ticket: TicketData
  negocio?: string
}

const fmtCO = (v: number) => `$${v.toLocaleString('es-CO')}`

function parseTicketDate(raw: string): Date {
  const t = raw.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

export default function TicketRecibo({ ticket, negocio = 'Café' }: Props) {
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
  const line = '─'.repeat(32)

  const metodoPagoLabel: Record<string, string> = {
    efectivo: 'EFECTIVO',
    tarjeta: 'TARJETA',
    mixto: 'MIXTO',
  }

  return (
    <>
      {/* Contenedor oculto en pantalla; solo visible en impresión */}
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
        {/* Encabezado */}
        <div style={{ textAlign: 'center', marginBottom: '4px' }}>
          <div style={{ fontWeight: 'bold', fontSize: '14px', letterSpacing: '2px' }}>
            {negocio.toUpperCase()}
          </div>
          <div style={{ fontSize: '10px', marginTop: '2px' }}>
            Documento de Ingreso
          </div>
          <div style={{ fontSize: '9px', color: '#555', marginTop: '1px' }}>
            Este documento NO reemplaza la factura de venta
          </div>
        </div>

        <div style={{ borderBottom: '1px dashed #000', margin: '5px 0' }} />

        {/* Fecha y hora */}
        <div style={{ fontSize: '10px', display: 'flex', justifyContent: 'space-between' }}>
          <span>Fecha: {fechaStr}</span>
          <span>Hora: {horaStr}</span>
        </div>
        <div style={{ fontSize: '10px' }}>
          No. Ticket: #{String(ticket.id).padStart(6, '0')}
        </div>

        <div style={{ borderBottom: '1px dashed #000', margin: '5px 0' }} />

        {/* Cabecera de columnas */}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', fontWeight: 'bold', textTransform: 'uppercase', marginBottom: '2px' }}>
          <span style={{ flex: 1 }}>Producto</span>
          <span style={{ width: '28px', textAlign: 'right' }}>Cant</span>
          <span style={{ width: '60px', textAlign: 'right' }}>Precio</span>
          <span style={{ width: '60px', textAlign: 'right' }}>Subtotal</span>
        </div>

        {/* Items */}
        {ticket.items.map((item, i) => (
          <div key={i}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', padding: '1px 0' }}>
              <span style={{ flex: 1, paddingRight: '4px', wordBreak: 'break-word' }}>{item.nombre_producto}</span>
              <span style={{ width: '28px', textAlign: 'right', flexShrink: 0 }}>{item.cantidad}</span>
              <span style={{ width: '60px', textAlign: 'right', flexShrink: 0 }}>{fmtCO(item.precio_unitario)}</span>
              <span style={{ width: '60px', textAlign: 'right', flexShrink: 0, fontWeight: 'bold' }}>{fmtCO(item.subtotal)}</span>
            </div>
          </div>
        ))}

        <div style={{ borderBottom: '1px solid #000', margin: '5px 0' }} />

        {/* Total */}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', fontWeight: 'bold', margin: '3px 0' }}>
          <span>TOTAL</span>
          <span>{fmtCO(ticket.total)}</span>
        </div>

        <div style={{ borderBottom: '1px dashed #000', margin: '5px 0' }} />

        {/* Método de pago */}
        <div style={{ fontSize: '10px', margin: '2px 0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>Método:</span>
            <span style={{ fontWeight: 'bold' }}>{metodoPagoLabel[ticket.metodo_pago] ?? ticket.metodo_pago}</span>
          </div>

          {ticket.metodo_pago === 'efectivo' && ticket.efectivo_recibido != null && (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Recibido:</span>
                <span>{fmtCO(ticket.efectivo_recibido)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold' }}>
                <span>Cambio:</span>
                <span>{fmtCO(ticket.cambio)}</span>
              </div>
            </>
          )}

          {ticket.metodo_pago === 'mixto' && (
            <>
              {ticket.monto_efectivo != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Efectivo:</span>
                  <span>{fmtCO(ticket.monto_efectivo)}</span>
                </div>
              )}
              {ticket.monto_tarjeta != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Tarjeta:</span>
                  <span>{fmtCO(ticket.monto_tarjeta)}</span>
                </div>
              )}
              {ticket.cambio > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold' }}>
                  <span>Cambio:</span>
                  <span>{fmtCO(ticket.cambio)}</span>
                </div>
              )}
            </>
          )}
        </div>

        <div style={{ borderBottom: '1px dashed #000', margin: '5px 0' }} />

        {/* Pie */}
        <div style={{ textAlign: 'center', fontSize: '9px', color: '#444', marginTop: '4px' }}>
          <div>¡Gracias por tu compra!</div>
          <div style={{ marginTop: '2px' }}>
            {'- '.repeat(16)}
          </div>
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
