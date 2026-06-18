import type { ReactNode, HTMLAttributes } from 'react'

type Padding = 'none' | 'sm' | 'md' | 'lg'

const PADDING: Record<Padding, string> = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-5',
}

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Padding interno. `none` para cards que controlan su propio layout (listas con divide). */
  padding?: Padding
  children: ReactNode
}

/**
 * Contenedor blanco redondeado — la tarjeta base del sistema.
 * `rounded-2xl border border-warm-200`, fondo blanco.
 */
export default function Card({ padding = 'md', className = '', children, ...rest }: CardProps) {
  return (
    <div
      className={`bg-white rounded-2xl border border-warm-200 ${PADDING[padding]} ${className}`}
      {...rest}
    >
      {children}
    </div>
  )
}
