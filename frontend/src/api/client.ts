import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

const api = axios.create({ baseURL: BASE })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  // Barista REAL que opera. SOLO en modo kiosko (PC compartido): la barista llega por el
  // selector "barista activa". En login individual (celular) NO se manda → el backend
  // atribuye por el usuario autenticado (la propia barista).
  if (localStorage.getItem('kiosk') === 'true') {
    const baristaId = localStorage.getItem('barista_activa_id')
    if (baristaId) config.headers['X-Barista-Id'] = baristaId
  }
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
      // Limpia barista activa global Y por tienda (barista_activa_{id}) para no re-atribuir
      // a la barista anterior al volver a entrar.
      Object.keys(localStorage)
        .filter(k => k.startsWith('barista_activa'))
        .forEach(k => localStorage.removeItem(k))
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)

export default api
