import { ReactNode, useMemo } from 'react'
import { ArrowRight, TrendingDown, TrendingUp } from 'lucide-react'
import { Dato, datoListo } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { NoSeSabe, SegunDato } from '../ui'
import { Banner, ComoSeCalcula } from '../plata/campos'
import { AlertaCosto, PorProductoData, ProdMargen, fmt, prodUtil } from './helpers'

/** Lo que este banner necesita del payload, ya ordenado. */
interface Lectura {
  top: ProdMargen[]
  fondo: ProdMargen[]
  excluidos: number
  alertas: AlertaCosto[]
}

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
 *
 * ── EL `return null` AHORA CUESTA UNA CONDICIÓN MÁS ─────────────────────────
 * El banner entero desaparecía con `prodData` en null, porque el ranking vacío
 * de un fetch caído se veía idéntico al ranking vacío de un negocio sin ventas.
 * Un banner que no está no dice «no pude leer»: dice «no hay nada que mostrar».
 * Ahora el vacío solo puede desaparecer cuando de verdad se MIRÓ y no había.
 */
export default function BannerProductos({ prodData }: { prodData: Fuente<PorProductoData> }) {
  const lectura: Dato<Lectura> = useMemo(() => {
    const d = prodData.dato
    // Las otras tres ramas viajan tal cual: acá no hay nada que derivar de un
    // dato que no está.
    if (d.estado !== 'listo') return d
    const all = d.valor.productos
    // Vendidos Y costeados: los dos filtros son necesarios. Sin ventas, la
    // utilidad aportada es 0 para todos y el ranking no dice nada; sin costo
    // completo, el margen está inflado.
    const vivos = all.filter(p => p.unidades_30d > 0 && p.costo_completo && p.margen != null)
    const sinCosto = all.filter(p => p.unidades_30d > 0 && !p.costo_completo).length
    const orden = [...vivos].sort((a, b) => prodUtil(b) - prodUtil(a))
    return datoListo({
      top: orden.slice(0, 3),
      // Los de abajo solo si hay suficientes para que «los últimos» no sean «los
      // mismos de arriba al revés».
      fondo: orden.length >= 6 ? orden.slice(-3).reverse() : [],
      excluidos: sinCosto,
      alertas: (d.valor.alertas_costo ?? []).slice(0, 3),
    })
  }, [prodData.dato])

  /** La cáscara: título y subtítulo son los mismos falte o no el dato. */
  const marco = (cuerpo: ReactNode) => (
    <Banner
      titulo="Los productos — últimos 30 días"
      sub="Esta ventana es fija y no cambia con el filtro de período de arriba"
    >
      {cuerpo}
    </Banner>
  )

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
    <SegunDato dato={lectura}
      /* Mudo a propósito: el primer segundo de una pantalla no es un error. */
      cargando={marco(
        <div className="px-4 py-5 space-y-2" aria-label="Cargando">
          <div className="h-3 w-2/3 rounded bg-warm-100 animate-pulse" />
          <div className="h-3 w-1/2 rounded bg-warm-100 animate-pulse" />
        </div>,
      )}
      falla={m => marco(
        <div className="p-3">
          <NoSeSabe bloque mensaje={m} onReintentar={prodData.recargar} />
        </div>,
      )}
      listo={({ top, fondo, excluidos, alertas }) => {
        // ACÁ SÍ: el backend contestó, se miraron los productos y no hay ni un
        // ranking ni una alerta que mostrar. Ese vacío está medido.
        if (top.length === 0 && alertas.length === 0) return null
        return marco(<>
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
        </>)
      }} />
  )
}
