import { useMemo } from 'react'
import { ArrowRight, TrendingDown, TrendingUp } from 'lucide-react'
import { Banner, ComoSeCalcula } from '../plata/campos'
import { PorProductoData, ProdMargen, fmt, prodUtil } from './helpers'

/**
 * ═════════════════════════════════════════════════════════════════════════════
 * LOS PRODUCTOS — «¿gano?» también se contesta plato por plato
 * ═════════════════════════════════════════════════════════════════════════════
 * El módulo YA pagaba el fetch de `/rentabilidad/por-producto` y usaba cuatro
 * cosas de todo el payload (outliers, insumos sin costo, facturas pendientes y
 * alertas de costo). La tabla de márgenes por producto y el simulador viven en
 * /carta, que es donde se decide el menú — duplicarlos enteros acá crearía dos
 * verdades del mismo número. Lo que sí faltaba es la LECTURA CORTA: cuáles son
 * los tres que más plata dejan y los tres que menos.
 *
 * ── LA VENTANA ES DE 30 DÍAS FIJOS, Y NO SIGUE AL FILTRO DE ARRIBA ─────────
 * `/rentabilidad/por-producto` no acepta rango: `unidades_30d` y `venta_30d` son
 * siempre los últimos 30 días. Mirando «Este año» arriba, estos números siguen
 * siendo del último mes — así que el banner lo dice en el título en vez de
 * dejarlo creer que se movieron con el filtro. Es la misma disciplina que costó
 * nueve rondas: un dato que está CERCA del correcto no sirve.
 *
 * ── SOLO PRODUCTOS CON COSTO COMPLETO ──────────────────────────────────────
 * Un producto sin costo cargado tiene margen falso (el backend le pone $0 de
 * costo), así que aparecería siempre como el que más deja. Se excluyen, y se
 * dice cuántos quedaron afuera: esconderlos sin avisar sería un ranking mentiroso.
 */
export default function BannerProductos({ prodData }: { prodData: PorProductoData | null }) {
  const alertas = (prodData?.alertas_costo ?? []).slice(0, 3)

  const { top, fondo, excluidos } = useMemo(() => {
    const all = prodData?.productos ?? []
    // Vendidos Y costeados: los dos filtros son necesarios. Sin ventas, la
    // utilidad aportada es 0 para todos y el ranking no dice nada; sin costo
    // completo, el margen está inflado.
    const vivos = all.filter(p => p.unidades_30d > 0 && p.costo_completo && p.margen != null)
    const sinCosto = all.filter(p => p.unidades_30d > 0 && !p.costo_completo).length
    const orden = [...vivos].sort((a, b) => prodUtil(b) - prodUtil(a))
    return {
      top: orden.slice(0, 3),
      // Los de abajo solo si hay suficientes para que «los últimos» no sean «los
      // mismos de arriba al revés».
      fondo: orden.length >= 6 ? orden.slice(-3).reverse() : [],
      excluidos: sinCosto,
    }
  }, [prodData])

  if (top.length === 0 && alertas.length === 0) return null

  const fila = (p: ProdMargen, tono: 'bien' | 'mal') => (
    <div key={p.producto_id} className="flex items-center gap-2 px-4 py-2 border-b border-warm-100 last:border-0">
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-warm-700 truncate">{p.nombre}</span>
        <span className="block text-[11px] text-warm-500">
          {p.unidades_30d} vendidos · {fmt(p.margen ?? 0)} de margen c/u
          {p.pct_margen != null && ` · ${p.pct_margen}%`}
        </span>
      </span>
      <span className={`font-mono font-bold text-sm tabular-nums shrink-0 ${
        tono === 'bien' ? 'text-success-600' : 'text-warm-500'}`}>
        {fmt(prodUtil(p))}
      </span>
    </div>
  )

  return (
    <Banner
      titulo="Los productos — últimos 30 días"
      sub="Esta ventana es fija y no cambia con el filtro de período de arriba"
    >
      {top.length > 0 && (
        <>
          <p className="px-4 py-2 text-[10px] font-bold uppercase tracking-wide text-warm-500 bg-warm-50 border-b border-warm-100 flex items-center gap-1">
            <TrendingUp size={11} className="text-success-600" /> Los que más plata dejan
          </p>
          {top.map(p => fila(p, 'bien'))}
        </>
      )}
      {fondo.length > 0 && (
        <>
          <p className="px-4 py-2 text-[10px] font-bold uppercase tracking-wide text-warm-500 bg-warm-50 border-y border-warm-100 flex items-center gap-1">
            <TrendingDown size={11} className="text-warm-400" /> Los que menos dejan
          </p>
          {fondo.map(p => fila(p, 'mal'))}
        </>
      )}

      {/* ── Insumos que se encarecieron ─────────────────────────────────────
          Es plata que ya se está yendo en CADA venta, así que se quiere saber
          hoy. Sale de `prodData.alertas_costo`, que el módulo ya pedía. */}
      {alertas.length > 0 && (
        <>
          <p className="px-4 py-2 text-[10px] font-bold uppercase tracking-wide text-warm-500 bg-gold-50 border-y border-gold-200 text-gold-700">
            Insumos que subieron de precio — te comen el margen en cada venta
          </p>
          {alertas.map(a => (
            <div key={a.insumo_id} className="flex items-center gap-3 px-4 py-2 border-b border-warm-100 last:border-0">
              <span className="flex-1 min-w-0">
                <span className="block text-sm font-semibold text-warm-700 truncate">{a.nombre}</span>
                <span className="block text-[11px] text-warm-500">
                  {fmt(a.costo_usado)} → {fmt(a.costo_ultimo)}
                  {a.productos_afectados.length > 0
                    && ` · afecta ${a.productos_afectados.length} producto${a.productos_afectados.length !== 1 ? 's' : ''}`}
                </span>
              </span>
              <span className="text-sm font-bold tabular-nums text-danger-700 shrink-0">
                +{a.pct_suba}%
              </span>
            </div>
          ))}
        </>
      )}

      <ComoSeCalcula titulo="¿Cómo se ordenan y por qué faltan productos?">
        <p>
          El orden es por <b>plata aportada</b>: el margen de cada unidad multiplicado por las
          unidades vendidas en los últimos 30 días. No es el % de margen — un producto con 70% de
          margen que se vende dos veces al mes aporta menos que uno con 40% que se vende doscientas.
        </p>
        <p>
          Solo entran los productos <b>con el costo completo cargado</b>: el que no lo tiene cuenta
          con costo $0 y saldría siempre primero.
          {excluidos > 0 && (
            <> Ahora mismo hay <b>{excluidos}</b> {excluidos === 1 ? 'producto vendido' : 'productos vendidos'}{' '}
              sin costo completo, así que no {excluidos === 1 ? 'aparece' : 'aparecen'} en esta
              lista. Están detallados en el banner de abajo.</>
          )}
        </p>
        <p className="flex items-center gap-1">
          La tabla completa producto por producto, con el simulador de precios, está en{' '}
          <b>Carta</b>. <ArrowRight size={12} className="inline shrink-0" />
        </p>
      </ComoSeCalcula>
    </Banner>
  )
}
