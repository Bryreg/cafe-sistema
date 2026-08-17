import { Building2, Truck, Wallet } from 'lucide-react'
import { AgendaItem } from './tipos'
import { fechaCorta, plata } from './banco'

/**
 * Un vencimiento de la agenda, con la CATEGORÍA adelante — que es como el dueño
 * los nombra («la nómina», «el arriendo»), no «costo fijo».
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * POR QUÉ LA FACTURA NO SE PAGA ACÁ MISMO
 * ═════════════════════════════════════════════════════════════════════════════
 * No es estética: `POST /costos/pagos` con `factura_id` guarda el pago pero NO
 * mueve `FacturaCompra.valor_pagado`, así que el saldo de la factura quedaría
 * igual y el pago se vería como si no hubiera pasado. El camino real de una
 * factura es `PATCH /facturas/{id}/pago`, que necesita la factura entera (forma
 * de pago, foto del soporte) y vive en el banner de proveedores.
 *
 * LO QUE CAMBIÓ: antes ese botón mandaba a un CAJÓN —la queja textual del
 * dueño—. Ahora el banner de proveedores está en esta misma página, así que el
 * botón baja hasta esa factura y le abre el formulario. Es un desplazamiento,
 * no una pantalla nueva.
 */
export default function FilaVencimiento({ item, onPagar, activo = false }: {
  item: AgendaItem
  /** Obligación: abre el pago inline. Factura: baja hasta su fila en proveedores. */
  onPagar: (i: AgendaItem) => void
  /** true = su formulario de pago está abierto justo debajo. */
  activo?: boolean
}) {
  const esFactura = item.tipo === 'factura'
  return (
    <div className={`flex items-center gap-2 px-3 py-2.5 ${activo ? 'bg-forest-50' : ''}`}>
      <span className={`shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-lg ${
        esFactura ? 'bg-white text-forest border border-warm-200' : 'bg-gold-50 text-gold-700 border border-gold-200'
      }`}>
        {esFactura ? <Truck size={11} /> : <Building2 size={11} />}
        {esFactura ? 'Proveedor' : (item.categoria_nombre || 'Costo fijo')}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-warm-700 truncate">{item.concepto}</p>
        {/* `origen_fecha` viene resuelto por el backend y explica POR QUÉ cae ese
            día: sin eso, una factura con plazo de 30 días parece agendada a dedo. */}
        <p className="text-[11px] text-warm-500 truncate">
          {item.beneficiario && item.beneficiario !== item.concepto ? `${item.beneficiario} · ` : ''}
          {item.tienda_nombre || 'Corporativo'}
          {item.referencia ? ` · Fact. ${item.referencia}` : ''}
          {` · ${fechaCorta(item.fecha)}`}
          {item.vencida ? ' · vencido' : ''}
          {item.origen_fecha === 'programada' ? ' (programado)' : ''}
          {item.origen_fecha === 'plazo' ? ' (por plazo del proveedor)' : ''}
        </p>
      </div>
      <span className={`font-mono font-bold text-sm shrink-0 tabular-nums ${
        item.vencida ? 'text-danger-600' : 'text-warm-700'}`}>
        {plata(item.monto)}
      </span>
      <button onClick={() => onPagar(item)}
        title={esFactura
          ? 'Baja hasta esta factura en «Lo que le debo a los proveedores»: ahí se registra el pago que mueve su saldo'
          : undefined}
        className={`shrink-0 flex items-center gap-1.5 text-xs font-bold px-3 min-h-[38px] rounded-lg ${
          esFactura
            ? 'text-forest bg-forest-50 hover:bg-forest-100 border border-forest-100'
            : 'text-white bg-forest hover:bg-forest-700'}`}>
        {esFactura ? <Truck size={13} /> : <Wallet size={13} />}
        {esFactura ? 'Ver factura' : 'Pagar'}
      </button>
    </div>
  )
}
