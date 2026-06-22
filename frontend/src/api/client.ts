import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

const api = axios.create({ baseURL: BASE })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  // Barista REAL que opera (≠ usuario del dispositivo/kiosko). El backend la persiste
  // como snapshot en cada escritura. Robusto: si no hay barista activa, no se manda.
  const baristaId = localStorage.getItem('barista_activa_id')
  if (baristaId) config.headers['X-Barista-Id'] = baristaId
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('rol')
      localStorage.removeItem('nombre')
      localStorage.removeItem('tienda_id')
      localStorage.removeItem('user_id')
      localStorage.removeItem('kiosk')
      localStorage.removeItem('barista_activa_id')
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)

export default api
