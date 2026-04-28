interface MoneyInputProps {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
  dark?: boolean
  size?: 'sm' | 'lg'
}

export default function MoneyInput({ label, value, onChange, placeholder = '0', hint, dark = false, size = 'lg' }: MoneyInputProps) {
  const base = dark
    ? 'bg-gray-800 border-gray-700 text-white placeholder-gray-500 focus:border-amber-400'
    : 'bg-white border-gray-200 text-gray-900 placeholder-gray-300 focus:border-amber-400'
  const labelColor = dark ? 'text-gray-400' : 'text-gray-500'
  const symbolColor = dark ? 'text-gray-500' : 'text-gray-300'
  const textSize = size === 'lg' ? 'text-3xl' : 'text-xl'
  const py = size === 'lg' ? 'py-4' : 'py-3'

  return (
    <div>
      <label className={`text-xs font-semibold uppercase tracking-wide block mb-1.5 ${labelColor}`}>{label}</label>
      {hint && <p className={`text-xs mb-2 ${dark ? 'text-gray-500' : 'text-gray-400'}`}>{hint}</p>}
      <div className="relative">
        <span className={`absolute left-4 top-1/2 -translate-y-1/2 text-xl font-bold ${symbolColor}`}>$</span>
        <input
          type="number"
          inputMode="numeric"
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className={`w-full pl-10 pr-4 ${py} ${textSize} font-bold border-2 rounded-xl focus:outline-none transition-colors ${base}`}
        />
      </div>
    </div>
  )
}
