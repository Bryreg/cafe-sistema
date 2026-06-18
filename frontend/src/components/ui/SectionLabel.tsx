import type { ReactNode, HTMLAttributes } from 'react'

export interface SectionLabelProps extends HTMLAttributes<HTMLParagraphElement> {
  children: ReactNode
}

/**
 * Label de sección en mayúsculas — el patrón repetido
 * `text-[11px] font-bold uppercase tracking-wide text-warm-500`.
 * Usado encima de grupos de campos, KPIs y listas.
 */
export default function SectionLabel({ children, className = '', ...rest }: SectionLabelProps) {
  return (
    <p
      className={`text-[11px] font-bold uppercase tracking-wide text-warm-500 ${className}`}
      {...rest}
    >
      {children}
    </p>
  )
}
