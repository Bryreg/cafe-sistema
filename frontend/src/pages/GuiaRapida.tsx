import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { ChevronDown, BookOpen } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface Seccion { titulo: string; pasos: string[] }

const GUIA_BARISTA: Seccion[] = [
  {
    titulo: 'Tu día en 5 pasos',
    pasos: [
      '1. Al llegar: registrá tu entrada y hacé el cuadre de llegada (contar el efectivo).',
      '2. Apertura: hacé el conteo de apertura — los graneles se pesan con la gramera, en gramos.',
      '3. Vendé en el POS: el inventario se descuenta solo con cada venta.',
      '4. Durante el día: recibí pedidos, registrá mermas y preparaciones cuando pasen.',
      '5. Al salir: cuadre de salida. Las últimas del día hacen el conteo de cierre y el cuadre de cierre del negocio.',
    ],
  },
  {
    titulo: 'Cuadres de caja',
    pasos: [
      'Contá el efectivo con el contador de billetes y monedas.',
      'En la APERTURA: el cuadre muestra los días con plata pendiente por consignar — marcá solo los que están físicamente en la caja. El esperado se arma con esos.',
      'Si la venta de ayer quedó apartada de la registradora, marcá la casilla "venta de ayer separada".',
      'Si los pagos del día superan la venta en efectivo, la plata que faltó salió de la separada: la casilla desaparece y se cuenta TODO junto (registradora + lo que quede separado).',
      'Si hay diferencia, el sistema pide una justificación — escribila tal cual pasó.',
      'El cuadre de cierre lo hacen juntas las últimas baristas: es del negocio, no individual.',
    ],
  },
  {
    titulo: 'Conteos de inventario',
    pasos: [
      'El orden del conteo es el mismo de la planilla física.',
      'Cada producto muestra el conteo ANTERIOR como referencia: en la apertura ves el cierre de anoche; en el cierre ves la apertura de hoy.',
      'Si el producto no se movió, tocá "Coincide" y listo. Si se movió (o es de los que rotan), pesalo con la gramera o contalo.',
      'Graneles (café, azúcar, chai, milo...): en GRAMOS. La jarra de mezcla de granizado también se pesa.',
      'Hay que registrar TODOS los productos para confirmar. El sistema compara después contra su propio conteo — si hay diferencia no pasa nada, se investiga.',
    ],
  },
  {
    titulo: 'Recibir pedidos (facturas)',
    pasos: [
      'Menú → Recibir: buscá el producto, poné cantidad y precio.',
      'Sacale foto a la factura física.',
      'Lote y vencimiento: escribilos tal como vienen del proveedor; si no vienen, dejalos vacíos.',
      'Al guardar, el inventario suma solo.',
    ],
  },
  {
    titulo: 'Mermas y consumos',
    pasos: [
      'Menú → Merma: elegí el tipo — consumo, traslado o daño.',
      'En consumo: registrá QUIÉN consumió (buscador de todo el catálogo).',
      'Las bebidas preparadas (ej. un cappuccino) descuentan sus ingredientes automáticamente.',
      'Regla de oro: ustedes registran lo que PASA (entradas, salidas, mermas, preparaciones). Si un número del inventario no cuadra, NO se ajusta — se cuenta en el conteo o se le avisa al administrador.',
    ],
  },
  {
    titulo: 'Preparaciones (mezcla de granizado)',
    pasos: [
      'Cada vez que prepares una tanda de mezcla: Menú → Preparaciones → Registrar.',
      'Si hiciste media tanda o más de una, ajustá con los botones + / −.',
      'El sistema descuenta la materia prima y suma la mezcla preparada.',
    ],
  },
  {
    titulo: 'Pedidos, existencia y sencilla',
    pasos: [
      'Menú → Pedido / Existencia: arriba elegís el modo.',
      'Modo "Pedir": los productos con stock bajo aparecen con cantidad sugerida — podés cambiar cantidad y unidad.',
      'Modo "Contar existencia": registrá cuánto hay de lo que NO entra al conteo diario (vasos, tapas, helado). No cambia el inventario; queda para que el admin lo revise.',
      'Menú → Sencilla: solicitá cambio cuando falte.',
      'Los avisos del administrador aparecen en tu pantalla de inicio — tocá "Entendido" cuando los leas.',
    ],
  },
]

const GUIA_ADMIN: Seccion[] = [
  {
    titulo: 'Cuadres y turnos',
    pasos: [
      'Cuadres: cada día es una tarjeta con base, ventas, cuadres de cada barista y cierre — todo a la vista.',
      'Si un turno quedó abierto de ayer, usá "Cerrar turno pendiente" desde la misma tarjeta.',
    ],
  },
  {
    titulo: 'Doble conteo de inventario',
    pasos: [
      'El sistema lleva su propio stock por movimientos: ventas (con recetas), facturas, mermas y preparaciones.',
      'Los conteos físicos de las baristas COMPARAN contra ese stock — las diferencias se investigan en el monitor de conteos.',
      'Si un conteo físico es la verdad (ej. inventario inicial), usá "Aplicar" para promoverlo.',
      'El toggle "Bajo gramaje" del monitor sirve para armar el pedido de la semana.',
    ],
  },
  {
    titulo: 'Recetas y descuento automático',
    pasos: [
      'Cada producto de venta tiene una receta: los insumos que descuenta cada venta.',
      'Los granizados descuentan MEZCLA GRANIZADO (150 gr); la mezcla se produce con Preparaciones.',
      'La leche se descuenta por fracción de bolsa (un cappuccino ≈ 0,19 bolsas).',
    ],
  },
  {
    titulo: 'Pagos a proveedores',
    pasos: [
      'Dashboard con facturado, pagado y pendiente por proveedor y sede.',
      'Registrar pago: monto, forma de pago y foto del soporte.',
      '"Editar" corrige cualquier dato de una factura (montos, productos, proveedor) ajustando inventario y caja.',
      '"Eliminar" revierte TODO: inventario, lotes y caja.',
    ],
  },
  {
    titulo: 'Comunicación con el equipo',
    pasos: [
      'Comunicados: lo que publiques aparece en el inicio de las baristas hasta que confirmen "Entendido".',
      'Desechables: solicitá el formato desde el admin y la sede lo llena ese día.',
      'Novedades (✨): cada actualización del sistema queda registrada acá, con su fecha.',
    ],
  },
  {
    titulo: 'Otras herramientas',
    pasos: [
      'Lotes: agrupados por producto, con vencimientos, consumo e historial rápido de entradas.',
      'Conciliación mensual: en orden de planilla, con "Reiniciar mes" si hay que rehacer.',
      'Config ticket: elegí la sede arriba y editá el ticket de cada una.',
    ],
  },
]

export default function GuiaRapida() {
  const { user } = useAuth()
  const esAdmin = user?.rol === 'admin'
  const secciones = esAdmin ? GUIA_ADMIN : GUIA_BARISTA
  const [abierta, setAbierta] = useState<number>(0)

  const contenido = (
    <div className="space-y-3 max-w-2xl">
      <div className="flex items-start gap-2.5">
        <BookOpen size={18} className="text-forest mt-0.5 shrink-0" />
        <div>
          <h1 className="text-base font-bold text-gray-800">Guía rápida</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {esAdmin
              ? 'Cómo funciona cada herramienta del hub de administración.'
              : 'Cómo usar el sistema en el día a día. Si algo no cuadra, avisale al administrador.'}
          </p>
        </div>
      </div>

      {secciones.map((s, i) => (
        <div key={s.titulo} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <button onClick={() => setAbierta(abierta === i ? -1 : i)}
            className="w-full flex items-center justify-between px-4 py-3 text-left">
            <span className="text-sm font-bold text-gray-800">{s.titulo}</span>
            <ChevronDown size={16} className={`text-gray-400 transition-transform ${abierta === i ? 'rotate-180' : ''}`} />
          </button>
          {abierta === i && (
            <div className="px-4 pb-4 space-y-2 border-t border-gray-50 pt-3">
              {s.pasos.map((p, j) => (
                <p key={j} className="text-[13px] text-gray-600 leading-relaxed">{p}</p>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )

  // El Layout admin lo envuelve la ruta (patrón de App.tsx); barista se auto-envuelve.
  if (esAdmin) return contenido
  return <BaristaLayout title="Guía rápida">{contenido}</BaristaLayout>
}
