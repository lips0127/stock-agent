<template>
  <div class="scan-progress-page">
    <PageHeader :title="`扫描进度${task ? ' · ' + (task.type === 'full' ? '全市场' : '红利指数') : ''}`">
      <template #actions>
        <el-button text @click="router.push({ name: 'Dashboard' })">
          <el-icon><ArrowLeft /></el-icon>
          <span style="margin-left: 4px">返回仪表盘</span>
        </el-button>
        <span
          v-if="task"
          class="status-pill"
          :class="`status-pill--${task.status}`"
        >{{ statusLabel }}</span>
      </template>
    </PageHeader>

    <div v-if="task" class="overview-grid">
      <StatCard label="总计" :value="task.total || '—'" icon="⊟" />
      <StatCard label="已处理" :value="task.done || 0" icon="✓" />
      <StatCard
        label="有效结果"
        :value="task.result_count ?? task.success_count ?? scannedCount"
        tone="accent"
        icon="★"
      />
      <StatCard
        :label="`失败 (${failRate})`"
        :value="failCount"
        :tone="failCount > 0 ? 'danger' : 'muted'"
        icon="!"
      />
      <StatCard
        label="进度"
        :value="`${task.total > 0 ? Math.round((task.done / task.total) * 100) : 0}%`"
        icon="↗"
      />
    </div>

    <ModernCard v-if="task && task.total > 0" padded>
      <div class="progress-bar">
        <div
          class="progress-bar__fill"
          :style="{ width: Math.round((task.done / task.total) * 100) + '%' }"
        />
      </div>
      <div class="progress-meta">
        <span>已完成 <strong>{{ task.done }}</strong> / {{ task.total }} 只</span>
        <span class="text-muted">剩余 {{ (task.total || 0) - (task.done || 0) }} 只</span>
      </div>
    </ModernCard>

    <ModernCard
      :title="`已扫描股票`"
    >
      <template #extra>
        <span class="count-pill">{{ scannedCount }} 只</span>
      </template>
      <el-table
        :data="scannedStocks"
        v-loading="loading"
        highlight-current-row
        :empty-text="'暂无扫描数据'"
        max-height="600"
      >
        <el-table-column type="index" label="#" width="60" />
        <el-table-column prop="code" label="代码" width="120">
          <template #default="{ row }">
            <span class="code-cell">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="price" label="最新价" width="120" align="right">
          <template #default="{ row }">
            <span class="num">{{ row.price != null ? Number(row.price).toFixed(2) : '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="dividend_per_share" label="每股分红" width="120" align="right">
          <template #default="{ row }">
            <span class="num">{{ row.dividend_per_share != null ? Number(row.dividend_per_share).toFixed(4) : '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="dividend_yield" label="股息率" width="140" align="right">
          <template #default="{ row }">
            <span
              v-if="row.dividend_yield != null"
              class="yield-pill"
              :class="row.dividend_yield >= 5 ? 'yield-pill--high' : 'yield-pill--low'"
            >
              {{ Number(row.dividend_yield).toFixed(2) }}%
            </span>
            <span v-else class="text-muted">--</span>
          </template>
        </el-table-column>
      </el-table>
    </ModernCard>

    <div v-if="task && task.status === 'running'" class="pending-hint">
      <span class="pending-hint__pulse" />
      <span>扫描进行中 · 已完成 <strong>{{ task.done }}</strong> / {{ task.total }}，剩余 <strong>{{ (task.total || 0) - (task.done || 0) }}</strong> 只</span>
    </div>

    <div v-if="task && task.status !== 'running' && task.status !== 'pending'" class="result-banner" :class="`result-banner--${bannerTone}`">
      <span class="result-banner__icon">{{ bannerIcon }}</span>
      <div class="result-banner__body">
        <div class="result-banner__title">{{ bannerTitle }}</div>
        <div class="result-banner__detail">{{ bannerDetail }}</div>
      </div>
      <el-button v-if="taskLogs.length > 0" text size="small" @click="showLogs = !showLogs">
        {{ showLogs ? '收起日志' : `查看 ${taskLogs.length} 条日志` }}
      </el-button>
    </div>

    <div v-if="showLogs && taskLogs.length > 0" class="logs-panel">
      <div v-for="log in taskLogs" :key="log.id" class="log-line" :class="`log-line--${log.level}`">
        <span class="log-line__time">{{ formatTime(log.created_at) }}</span>
        <span class="log-line__level">{{ log.level }}</span>
        <span class="log-line__msg">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getTaskProgress, getTaskLogs } from '../api'
import { ArrowLeft } from '@element-plus/icons-vue'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import StatCard from '../components/ui/StatCard.vue'

const router = useRouter()
const route = useRoute()

const task = ref(null)
const scannedStocks = ref([])
const scannedCount = ref(0)
const taskLogs = ref([])
const showLogs = ref(false)
const loading = ref(false)
let pollTimer = null

const taskId = computed(() => route.params.taskId)

const statusLabel = computed(() => {
  const map = { running: '扫描中', success: '已完成', failed: '失败', pending: '等待中', cancelled: '已取消' }
  return map[task.value?.status] || task.value?.status || '--'
})

const failCount = computed(() => {
  const t = task.value
  if (!t) return 0
  // 新表 (task_runs) 通过 result_json 解析得到 fail_count
  if (typeof t.fail_count === 'number') return t.fail_count
  // 旧表 (scan_tasks) 用 total - result_count 估算
  if (typeof t.total === 'number' && typeof t.result_count === 'number') {
    return Math.max(t.total - t.result_count, 0)
  }
  return 0
})

const failRate = computed(() => {
  const t = task.value
  if (!t || !t.total) return '0%'
  return `${Math.round((failCount.value / t.total) * 100)}%`
})

const bannerTone = computed(() => {
  if (!task.value) return 'muted'
  if (task.value.status === 'failed') return 'danger'
  if (failCount.value > (task.value.total || 0) / 2) return 'warning'
  if (task.value.status === 'cancelled') return 'muted'
  if (task.value.status === 'success') return 'success'
  return 'muted'
})

const bannerIcon = computed(() => {
  const map = { success: '✓', failed: '✕', warning: '!', danger: '✕', muted: '·' }
  return map[bannerTone.value] || '·'
})

const bannerTitle = computed(() => {
  const t = task.value
  if (!t) return ''
  if (t.status === 'failed') return `任务失败: ${t.error_message || '未知原因'}`
  if (t.status === 'cancelled') return '任务已取消'
  if (failCount.value === 0 && t.total > 0) return `扫描成功 · ${t.total} 只全部命中`
  if (failCount.value > (t.total || 0) / 2) {
    return `扫描完成但失败率过高 · ${failCount.value}/${t.total} (${failRate.value})`
  }
  return `扫描完成 · 成功 ${t.total - failCount.value}, 失败 ${failCount.value}`
})

const bannerDetail = computed(() => {
  const t = task.value
  if (!t) return ''
  if (t.status === 'failed' && t.error_message) return t.error_message
  if (failCount.value === 0) return '所有数据源均已成功获取行情与股息率'
  const sample = taskLogs.value.filter(l => l.level === 'warning' || l.level === 'error').slice(-3)
  if (sample.length === 0) return '检查数据源连通性 (腾讯/新浪/东方财富)'
  return `最近失败: ${sample.map(s => s.message).join(' / ')}`
})

function formatTime(iso) {
  if (!iso) return '--'
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return iso }
}

async function fetchProgress() {
  if (!taskId.value) return
  loading.value = true
  try {
    const { data } = await getTaskProgress(taskId.value)
    task.value = data.task
    scannedStocks.value = data.scanned || []
    scannedCount.value = data.scanned_count || 0

    if (data.task?.status === 'running' && !pollTimer) {
      pollTimer = setInterval(fetchProgress, 5000)
    }
    if (data.task?.status !== 'running' && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } catch {
    // ignore
  } finally {
    loading.value = false
  }
}

async function fetchLogs() {
  if (!taskId.value) return
  try {
    const { data } = await getTaskLogs(taskId.value)
    taskLogs.value = data.logs || []
  } catch {
    // ignore
  }
}

onMounted(() => {
  fetchProgress()
  fetchLogs()
})
onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.scan-progress-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.status-pill {
  font-size: var(--text-xs);
  padding: 4px 12px;
  border-radius: var(--radius-full);
  font-weight: var(--weight-medium);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}
.status-pill--running {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}
.status-pill--success {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.status-pill--failed {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-3);
}
@media (max-width: 1100px) {
  .overview-grid {
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  }
}
.progress-bar {
  height: 8px;
  background: var(--color-bg-muted);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.progress-bar__fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb 0%, #3b82f6 100%);
  border-radius: var(--radius-full);
  transition: width var(--duration-slow) var(--ease);
}
.progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.progress-meta strong {
  color: var(--color-text-primary);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
}
.count-pill {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  background: var(--color-bg-muted);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-variant-numeric: tabular-nums;
}
.code-cell {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  letter-spacing: 0.02em;
  color: var(--color-text-primary);
  font-weight: var(--weight-medium);
}
.num {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-medium);
}
.yield-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  font-variant-numeric: tabular-nums;
}
.yield-pill--high {
  background: var(--color-up-soft);
  color: var(--color-up);
}
.yield-pill--low {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.pending-hint {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--color-accent-soft);
  color: var(--color-accent-text);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  border: 1px solid rgba(37, 99, 235, 0.12);
  align-self: flex-start;
}
.pending-hint__pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-accent);
  animation: pulse 1.4s var(--ease) infinite;
}
.pending-hint strong {
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.4); }
}

/* 任务完成横幅（v2, 2026-06-11） */
.result-banner {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  border: 1px solid transparent;
}
.result-banner__icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: var(--weight-semibold);
  font-size: 14px;
  flex-shrink: 0;
}
.result-banner__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.result-banner__title {
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
}
.result-banner__detail {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  word-break: break-all;
}
.result-banner--success {
  background: var(--color-success-soft);
  border-color: rgba(16, 185, 129, 0.18);
}
.result-banner--success .result-banner__icon {
  background: var(--color-success);
  color: white;
}
.result-banner--warning {
  background: var(--color-warning-soft);
  border-color: rgba(245, 158, 11, 0.18);
}
.result-banner--warning .result-banner__icon {
  background: var(--color-warning);
  color: white;
}
.result-banner--danger {
  background: var(--color-danger-soft);
  border-color: rgba(239, 68, 68, 0.18);
}
.result-banner--danger .result-banner__icon {
  background: var(--color-danger);
  color: white;
}
.result-banner--muted {
  background: var(--color-bg-muted);
  border-color: var(--color-border);
}
.result-banner--muted .result-banner__icon {
  background: var(--color-text-tertiary);
  color: white;
}

/* 任务日志面板 */
.logs-panel {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 360px;
  overflow-y: auto;
  padding: var(--space-3);
  background: var(--color-bg-base);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}
.log-line {
  display: grid;
  grid-template-columns: 80px 60px 1fr;
  gap: var(--space-2);
  padding: 4px 8px;
  border-radius: 4px;
}
.log-line__time {
  color: var(--color-text-tertiary);
}
.log-line__level {
  font-weight: var(--weight-semibold);
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: 0.05em;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
  align-self: center;
}
.log-line__msg {
  color: var(--color-text-primary);
  word-break: break-all;
}
.log-line--warning {
  background: var(--color-warning-soft);
}
.log-line--warning .log-line__level {
  background: var(--color-warning);
  color: white;
}
.log-line--error {
  background: var(--color-danger-soft);
}
.log-line--error .log-line__level {
  background: var(--color-danger);
  color: white;
}
.log-line--milestone {
  background: var(--color-accent-soft);
}
.log-line--milestone .log-line__level {
  background: var(--color-accent);
  color: white;
}
</style>
