import axios from 'axios'
import router from '../router'
import { useAuthStore } from '../stores/auth'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      const auth = useAuthStore()
      auth.logout()
      router.push('/login')
    }
    return Promise.reject(error)
  }
)

export const login = (username, password) =>
  api.post('/login', { username, password })

export const getIndices = () => api.get('/indices')
export const getLiveIndices = () => api.get('/indices/live')

export const getTopStocks = (limit = 20) =>
  api.get('/top_stocks', { params: { limit } })

export const getStock = (symbol) => api.get(`/stock/${symbol}`)

export const indexScan = () => api.post('/index_scan')

export const fullRefreshData = () => api.post('/full_refresh')

export const getTasks = () => api.get('/tasks')

export const getTask = (taskId) => api.get(`/tasks/${taskId}`)

export const getTaskProgress = (taskId) => api.get(`/tasks/${taskId}/progress`)

export const getAllStocks = (page, pageSize) =>
  api.get('/all_stocks', { params: { page, page_size: pageSize } })

export const getLogs = () => api.get('/logs')

export const healthCheck = () => api.get('/health')

// 舆情监控
export const getSentimentConfigs = () => api.get('/sentiment/configs')
export const searchStocks = (q) => api.get('/sentiment/search', { params: { q } })
export const addSentimentConfig = (stock_code, stock_name = '', forum_type = 'eastmoney') =>
  api.post('/sentiment/configs', { stock_code, stock_name, forum_type })
export const deleteSentimentConfig = (id) => api.delete(`/sentiment/configs/${id}`)
export const getSentimentLatest = () => api.get('/sentiment/latest')
export const getSentimentScores = (code, days = 30) =>
  api.get('/sentiment/scores', { params: { code, days } })
export const analyzeSentiment = (stock_code, forum_type = 'eastmoney') =>
  api.post('/sentiment/analyze', { stock_code, forum_type })
export const batchAnalyzeSentiment = () => api.post('/sentiment/batch_analyze')
