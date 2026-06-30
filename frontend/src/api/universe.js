import api from './index'

const base = '/sentiment/universe'

export const getUniverseIndices = () => api.get(`${base}/indices`)
export const getUniverseSummary = (date) =>
  api.get(`${base}/summary`, { params: { date } })
export const getUniverseHistory = (code, days = 60) =>
  api.get(`${base}/history/${code}`, { params: { days } })
export const getUniverseConstituents = (code, params = {}) =>
  api.get(`${base}/constituents/${code}`, { params })
export const getUniverseJobs = (date) =>
  api.get(`${base}/jobs`, { params: { date } })
export const refreshUniverseConstituents = (indexCode = null) =>
  api.post(`${base}/refresh_constituents`, { index_code: indexCode })
export const runUniverseCrawl = (code = 'all', maxWorkers = 8) =>
  api.post(`${base}/run/${code}`, { max_workers: maxWorkers })
export const getUniverseProgress = (date) =>
  api.get(`${base}/progress`, { params: { date } })
export const getUniverseCount = (date) =>
  api.get(`${base}/count`, { params: { date } })
