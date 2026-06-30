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

export const getTaskLogs = (taskId, sinceId = 0) =>
  api.get(`/tasks/${taskId}/logs`, { params: { since_id: sinceId } })

export const getAllStocks = (page, pageSize, scanType) =>
  api.get('/all_stocks', { params: { page, page_size: pageSize, ...(scanType ? { scan_type: scanType } : {}) } })

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

// 量化交易系统
export const getStrategies = () => api.get('/strategies')
export const getStrategy = (name) => api.get(`/strategies/${name}`)

export const runBacktest = (config) => api.post('/backtest/run', config)
export const getBacktestRuns = (limit) => api.get('/backtest/runs', { params: { limit } })
export const getBacktestRun = (id) => api.get(`/backtest/runs/${id}`)

export const getPortfolio = () => api.get('/quant/portfolio')
export const getPositions = () => api.get('/quant/positions')
export const getSnapshots = () => api.get('/quant/snapshots')
export const getRiskRules = () => api.get('/quant/risk/rules')

// 净值管理系统
export const getNavParties = () => api.get('/nav/parties')
export const initNavParties = (data) => api.post('/nav/parties/init', data)
export const getNavTransfers = (params) => api.get('/nav/transfers', { params })
export const addNavTransfer = (data) => api.post('/nav/transfers', data)
export const deleteNavTransfer = (id) => api.delete(`/nav/transfers/${id}`)
export const calculateNav = (data) => api.post('/nav/calculate', data)
export const getCurrentNav = () => api.get('/nav/current')
export const getNavHistory = () => api.get('/nav/history')
export const getNavPositions = (date) => api.get('/nav/positions', { params: { date } })
export const addNavPosition = (data) => api.post('/nav/positions', data)
export const getNavPositionDates = () => api.get('/nav/positions/dates')
export const previewWithdraw = (data) => api.post('/nav/withdraw/preview', data)
export const confirmWithdraw = (data) => api.post('/nav/withdraw/confirm', data)

// 知乎大V监控
export const getZhihuUsers = () => api.get('/zhihu/users')
export const addZhihuUser = (url) => api.post('/zhihu/users', { url })
export const deleteZhihuUser = (id) => api.delete(`/zhihu/users/${id}`)
export const patchZhihuUser = (id, data) => api.patch(`/zhihu/users/${id}`, data)
export const refreshZhihuUser = (id, opts = {}) =>
  api.post(`/zhihu/users/${id}/refresh`, null, { params: opts })
export const getZhihuRefreshStatus = (taskId) => api.get(`/zhihu/refresh_status/${taskId}`)
export const analyzeRecentZhihuUser = (id, limit = 10) =>
  api.post(`/zhihu/users/${id}/analyze_recent`, null, { params: { limit } })
export const getZhihuAnalyzeStatus = (taskId) => api.get(`/zhihu/analyze_status/${taskId}`)
export const getZhihuUserPosts = (id, limit = 30) => api.get(`/zhihu/users/${id}/posts`, { params: { limit } })
export const getZhihuAnalysis = (postId) => api.get(`/zhihu/posts/${postId}/analysis`)
export const reanalyzeZhihuPost = (postId) => api.post(`/zhihu/posts/${postId}/reanalyze`)

export const getZhihuSubscriptions = () => api.get('/zhihu/subscriptions')
export const addZhihuSubscription = (data) => api.post('/zhihu/subscriptions', data)
export const deleteZhihuSubscription = (id) => api.delete(`/zhihu/subscriptions/${id}`)
export const patchZhihuSubscription = (id, data) => api.patch(`/zhihu/subscriptions/${id}`, data)

export const getZhihuEmailSettings = () => api.get('/zhihu/email_settings')
export const saveZhihuEmailSettings = (data) => api.post('/zhihu/email_settings', data)
export const testZhihuEmail = (email) => api.post('/zhihu/email_test', { email })
export const getZhihuEmailLogs = (limit = 50) => api.get('/zhihu/logs', { params: { limit } })

// 大V时间线报表
export const getZhihuTimeline = (days = 7) => api.get('/zhihu/timeline', { params: { days } })

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
