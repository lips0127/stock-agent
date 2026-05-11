<template>
  <transition name="slide-up">
    <div v-if="task" class="scan-bar">
      <div class="scan-bar__inner">
        <div class="scan-bar__info">
          <span class="scan-bar__label">
            {{ task.type === 'full' ? '全市场扫描' : '指数扫描' }}
          </span>
          <el-tag :type="statusType" size="small" effect="dark">{{ statusLabel }}</el-tag>
        </div>

        <div v-if="task.status === 'running' && task.total > 0" class="scan-bar__progress">
          <el-progress
            :percentage="Math.round((task.done / task.total) * 100)"
            :stroke-width="8"
            :show-text="false"
            color="#409eff"
          />
          <span class="scan-bar__count">{{ task.done }} / {{ task.total }}</span>
          <el-link type="primary" :underline="false" @click="goProgress">详情 →</el-link>
        </div>

        <div v-if="task.status === 'running' && (!task.total || task.total === 0)" class="scan-bar__progress">
          <span class="scan-bar__count">正在获取股票列表...</span>
        </div>

        <div v-if="task.status === 'success'" class="scan-bar__result">
          <span>扫描完成，共 {{ task.result_count ?? 0 }} 只股票</span>
          <el-link type="primary" :underline="false" @click="goProgress">查看详情 →</el-link>
        </div>

        <div v-if="task.status === 'failed'" class="scan-bar__error">
          {{ task.error_message || '扫描失败' }}
        </div>
      </div>

      <el-button text size="small" class="scan-bar__close" @click="taskStore.dismissTask()">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>
  </transition>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Close } from '@element-plus/icons-vue'
import { useTaskStore } from '../stores/task'

const router = useRouter()
const taskStore = useTaskStore()

const task = computed(() => taskStore.currentTask)

const statusType = computed(() => {
  const map = { running: 'warning', success: 'success', failed: 'danger', pending: 'info' }
  return map[task.value?.status] || 'info'
})

const statusLabel = computed(() => {
  const map = { running: '扫描中', success: '已完成', failed: '失败', pending: '等待中' }
  return map[task.value?.status] || task.value?.status
})

function goStocks() {
  taskStore.dismissTask()
  router.push({ name: 'Stocks' })
}

function goProgress() {
  if (taskStore.taskId) {
    router.push({ name: 'ScanProgress', params: { taskId: taskStore.taskId } })
  }
}
</script>

<style scoped>
.scan-bar {
  position: sticky;
  bottom: 0;
  z-index: 100;
  background: #fff;
  border-top: 1px solid var(--color-border);
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.08);
  padding: 10px 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.scan-bar__inner {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}
.scan-bar__info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.scan-bar__label {
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
}
.scan-bar__progress {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.scan-bar__progress .el-progress {
  flex: 1;
}
.scan-bar__count {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.scan-bar__result {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: var(--color-text-primary);
}
.scan-bar__error {
  color: #f56c6c;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scan-bar__close {
  flex-shrink: 0;
  color: var(--color-text-muted);
}
</style>
