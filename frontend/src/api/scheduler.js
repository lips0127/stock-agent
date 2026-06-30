import api from './index'

const base = '/scheduler/configs'

export const getSchedulerConfigs = () => api.get(base)

export const updateSchedulerConfig = (jobId, fields) =>
  api.patch(`${base}/${jobId}`, fields)

export const pauseSchedulerJob = (jobId) =>
  api.post(`${base}/${jobId}/pause`)

export const resumeSchedulerJob = (jobId) =>
  api.post(`${base}/${jobId}/resume`)

export const getSchedulerJobRuns = (jobId, limit = 20) =>
  api.get(`${base}/${jobId}/runs`, { params: { limit } })
