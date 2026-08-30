import axios from 'axios'
import router from '../router'
import { useAuthStore } from '../stores/auth'

const api = axios.create({
  baseURL: '/api',
  // 大分页扫描表 / live 指数最坏 ~10s，30s 是安全上限；超时错误统一走 catch
  timeout: 30000,
})

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

// 当前运行中的任务（/vix 页加载时据此恢复重算/回填进度展示，防重复触发）
export const getTasksActive = () => api.get('/tasks/active')

export const getTask = (taskId) => api.get(`/tasks/${taskId}`)

export const getTaskProgress = (taskId) => api.get(`/tasks/${taskId}/progress`)

export const getTaskLogs = (taskId, sinceId = 0) =>
  api.get(`/tasks/${taskId}/logs`, { params: { since_id: sinceId } })

// q/min_yield 为服务端全量过滤（代码/名称子串、股息率下限），跨页生效
export const getAllStocks = (page, pageSize, scanType, q, minYield) =>
  api.get('/all_stocks', {
    params: {
      page,
      page_size: pageSize,
      ...(scanType ? { scan_type: scanType } : {}),
      ...(q ? { q } : {}),
      ...(minYield != null ? { min_yield: minYield } : {}),
    },
  })

// 自选股观察池（Core）：报价聚合带 source/as_of/coverage/degraded
export const getWatchlist = () => api.get('/watchlist')
export const addWatchStock = (code, note = '') =>
  api.post('/watchlist', { code, note })
export const updateWatchStock = (code, note) =>
  api.patch(`/watchlist/${code}`, { note })
export const deleteWatchStock = (code) => api.delete(`/watchlist/${code}`)

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
export const getBatchAnalyzeStatus = () => api.get('/sentiment/batch_analyze_status')
export const getBatchAnalyzeCount = () => api.get('/sentiment/batch_analyze_count')
export const getSentimentHealth = () => api.get('/sentiment/health')

// 舆情帖子过滤规则
export const getSentimentFilters = (filter_type) =>
  api.get('/sentiment/filters', { params: { filter_type } })
export const addSentimentFilter = (data) => api.post('/sentiment/filters', data)
export const deleteSentimentFilter = (id) => api.delete(`/sentiment/filters/${id}`)

// 网络韧性：仅拉取帖子（不调 LLM）+ 熔断器状态
export const fetchForumPostsOnly = (stock_code, opts = {}) =>
  api.post('/sentiment/fetch', { stock_code, ...opts })
export const getCircuitStatus = () => api.get('/sentiment/circuit_status')
export const resetCircuit = () => api.post('/sentiment/circuit_reset')

// 标题真实性审计（v1, 2026-06-04）
export const getSentimentAuditPosts = (code, opts = {}) =>
  api.get('/sentiment/audit', { params: { code, ...opts } })
export const rerunSentimentAudit = (code, opts = {}) =>
  api.post('/sentiment/audit/rerun', { code, ...opts })
export const acceptPostActualTitle = (postId) =>
  api.post(`/sentiment/posts/${postId}/accept_actual`)
export const markPostBroken = (postId, note = '') =>
  api.post(`/sentiment/posts/${postId}/mark_broken`, { note })
export const resetPostAudit = (postId) =>
  api.post(`/sentiment/posts/${postId}/reset`)
export const getSentimentAuditSummary = (code = null) =>
  api.get('/sentiment/audit/summary', { params: code ? { code } : {} })

// 站内查看缓存帖子（v3, 2026-06-04）：guba 不可达时避免外链跳转
export const getSentimentPost = (postId) =>
  api.get(`/sentiment/posts/${postId}`)
export const refreshSentimentPostContent = (postId) =>
  api.post(`/sentiment/posts/${postId}/refresh_content`)

// 市场分时K线
export const getMarketIntraday = (symbol, interval = '30min', days = 7) =>
  api.get('/market/intraday', { params: { symbol, interval, days } })

// VIX 恐慌指数 + 恐惧贪婪综合指数
// 重算/回填为异步任务，返回 task_id；状态用 getTask(taskId) 轮询（旧 *_status 端点已 410）
export const getVix = () => api.get('/vix')
export const getVixHistory = (days = 60) => api.get('/vix/history', { params: { days } })
export const getVixFactorStudy = (days = 365) => api.get('/vix/factor-study', { params: { days } })
export const getVixVolRisk = () => api.get('/vix/vol-risk')
export const recomputeVix = () => api.post('/vix/recompute')
export const backfillVix = (days = 30, skip_existing = true) =>
  api.post('/vix/backfill', { days, skip_existing })

// VIX 2.0（机器学习）— 与 v6.1 并行；train/backfill 异步返回 task_id
export const getVix2 = () => api.get('/vix2')
export const getVix2History = (days = 365) => api.get('/vix2/history', { params: { days } })
export const getVix2Model = () => api.get('/vix2/model')
export const trainVix2 = (params = {}) => api.post('/vix2/train', params)
export const backfillVix2 = (days = 0, skip_existing = false) =>
  api.post('/vix2/backfill', { days, skip_existing })
// 按时间顺序生成同日构造分的实验状态估计；不是未来收益预测
export const backfillVix2Walkforward = (days = 0, block_size = 60, skip_existing = false, cv_gap = 5) =>
  api.post('/vix2/backfill_walkforward', { days, block_size, skip_existing, cv_gap })

// 舆情 v3 升级（2026-06-06）：时序因子 + 热门股池
export const getSentimentIndicators = (code, days = 30) =>
  api.get('/sentiment/indicators', { params: { code, days } })
export const getExtremeSignals = (date = null) =>
  api.get('/sentiment/extreme_signals', { params: date ? { date } : {} })
export const recomputeSentimentIndicators = () =>
  api.post('/sentiment/indicators/recompute')
export const getTopPicks = (date = null) =>
  api.get('/sentiment/top_picks', { params: date ? { date } : {} })
export const refreshTopPicks = (top_n = 100, auto_add = false, analyze_limit = 0) =>
  api.post('/sentiment/top_picks/refresh', { top_n, auto_add, analyze_limit })
export const analyzeTopPicks = (limit = 20) =>
  api.post('/sentiment/top_picks/analyze', { limit })

// 财报解析
export const parseFinancialReport = (text) =>
  api.post('/financial/parse', { text })

export const analyzeFinancialReport = (text) =>
  api.post('/financial/analyze', { text })

// 公司增强看板（stock_metrics + 财务 + 情绪）
export const getStockDashboard = (code, opts = {}) =>
  api.get(`/stock/${code}/dashboard`, {
    params: { days: opts.days ?? 60, sentiment: opts.sentiment ? '1' : '0' },
  })

export default api
