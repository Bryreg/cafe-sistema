import { useRef, useState } from 'react'
import { Camera, X, ImageIcon } from 'lucide-react'

interface ImageUploaderProps {
  onFileChange: (file: File | null) => void
  dark?: boolean
}

export default function ImageUploader({ onFileChange, dark = false }: ImageUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)

  const handleFile = (file: File | null) => {
    if (!file) { setPreview(null); onFileChange(null); return }
    const url = URL.createObjectURL(file)
    setPreview(url)
    onFileChange(file)
  }

  const clear = () => {
    if (inputRef.current) inputRef.current.value = ''
    handleFile(null)
  }

  const border = dark ? 'border-gray-700' : 'border-gray-200'
  const bg = dark ? 'bg-gray-800' : 'bg-gray-50'
  const text = dark ? 'text-gray-400' : 'text-gray-400'
  const hint = dark ? 'text-gray-500' : 'text-gray-400'

  return (
    <div>
      <label className={`text-xs font-semibold uppercase tracking-wide block mb-1.5 ${text}`}>
        Foto de evidencia
      </label>
      <p className={`text-xs mb-2 ${hint}`}>
        Incluye el cuadre físico en la foto
      </p>

      {preview ? (
        <div className="relative">
          <img src={preview} alt="preview" className="w-full h-48 object-cover rounded-xl border border-gray-700" />
          <button onClick={clear}
            className="absolute top-2 right-2 bg-black/60 text-white rounded-full p-1 hover:bg-black/80">
            <X size={14} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className={`w-full flex flex-col items-center gap-2 py-6 border-2 border-dashed rounded-xl transition-colors hover:border-amber-400 ${border} ${bg}`}
        >
          <div className="flex gap-3">
            <Camera size={22} className="text-amber-500" />
            <ImageIcon size={22} className="text-gray-400" />
          </div>
          <span className={`text-sm font-medium ${text}`}>Tomar foto o subir imagen</span>
          <span className={`text-xs ${hint}`}>Opcional pero recomendado</span>
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={e => handleFile(e.target.files?.[0] ?? null)}
      />
    </div>
  )
}
