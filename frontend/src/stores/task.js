import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getTask, getTasks } from '../api'

export const useTaskStore = defineStore('task', () => {
  const currentTask = ref(null)
  const taskId = ref(null)
  let pollTimer = null

  function startPolling(id, type = 'full') {
    taskId.value = id
    currentTask.value = { type, status: 'running', done: 0, total: 0 }
    stopPolling()
    pollTimer = setInterval(async () => {
      try {
        const { data } = await getTask(id)
        currentTask.value = data
        if (data.status === 'success' || data.status === 'failed') {
          stopPolling()
        }
      } catch {
        // ignore polling errors
      }
    }, 3000)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function dismissTask() {
    stopPolling()
    currentTask.value = null
    taskId.value = null
  }

  async function init() {
    try {
      const { data } = await getTasks()
      const running = (data || []).find(t => t.status === 'running')
      if (running) {
        startPolling(running.id, running.type)
      }
    } catch {
      // ignore
    }
  }

  return { currentTask, taskId, startPolling, stopPolling, dismissTask, init }
})
