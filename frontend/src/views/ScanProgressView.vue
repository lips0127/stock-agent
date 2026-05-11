<template>
  <div class="scan-progress-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-header__left">
        <el-button text @click="router.push({ name: 'Dashboard' })">
          <el-icon><ArrowLeft /></el-icon> 返回
        </el-button>
        <h2 class="page-title">扫描进度</h2>
      </div>
      <el-tag v-if="task" :type="statusType" size="large" effect="dark">
        {{ statusLabel }}
      </el-tag>
    </div>

    <!-- 进度概览 -->
    <el-card v-if="task" shadow="never" class="overview-card">
      <div class="overview-grid">
        <div class="overview-item">
          <div class="overview-label">总计</div>
          <div class="overview-value">{{ task.total || '--' }}</div>
        </div>
        <div class="overview-item">
          <div class="overview-label">已处理</div>
          <div class="overview-value">{{ task.done || 0 }}</div>
        </div>
        <div class="overview-item">
          <div class="overview-label">有效结果</div>
          <div class="overview-value highlight">{{ task.result_count ?? scannedCount }}</div>
        </div>
        <div class="overview-item">
          <div class="overview-label">进度</div>
          <div class="overview-value">
            {{ task.total > 0 ? Math.round((task.done / task.total) * 100) : 0 }}%
          </div>
        </div>
      </div>
      <el-progress
        v-if="task.total > 0"
        :percentage="Math.round((task.done / task.total) * 100)"
        :stroke-width="12"
        :color="task.status === 'running' ? '#409eff' : '#67c23a'"
        style="margin-top: 16px"
      />
    </el-card>

    <!-- 已扫描股票列表 -->
    <el-card shadow="never" class="table-card">
      <template #header>
        <span class="section-title">已扫描股票</span>
        <el-tag type="info" size="small" effect="plain" style="margin-left: 8px">
          {{ scannedCount }} 只
        </el-tag>
      </template>
      <el-table
        :data="scannedStocks"
        v-loading="loading"
        stripe
        highlight-current-row
        style="width: 100%"
        max-height="600"
        empty-text="暂无扫描数据"
      >
        <el-table-column type="index" label="#" width="60" />
        <el-table-column prop="code" label="代码" width="110">
          <template #default="{ row }">
            <span class="code-text">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="price" label="最新价" width="100" align="right">
          <template #default="{ row }">
            {{ row.price != null ? Number(row.price).toFixed(2) : '--' }}
          </template>
        </el-table-column>
        <el-table-column prop="dividend_per_share" label="每股分红" width="100" align="right">
          <template #default="{ row }">
            {{ row.dividend_per_share != null ? Number(row.dividend_per_share).toFixed(4) : '--' }}
          </template>
        </el-table-column>
        <el-table-column prop="dividend_yield" label="股息率" width="100" align="right">
          <template #default="{ row }">
            <el-tag
              v-if="row.dividend_yield != null"
              :type="row.dividend_yield >= 5 ? 'danger' : 'success'"
              size="small"
              effect="light"
            >
              {{ Number(row.dividend_yield).toFixed(2) }}%
            </el-tag>
            <span v-else class="text-muted">--</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 未完成提示 -->
    <el-card v-if="task && task.status === 'running'" shadow="never" class="pending-card">
      <div class="pending-info">
        <el-icon class="is-loading" :size="20" color="#409eff"><Loading /></el-icon>
        <span>扫描进行中，已完成 <strong>{{ task.done }}</strong> / {{ task.total }}，
          剩余约 <strong>{{ (task.total || 0) - (task.done || 0) }}</strong> 只待处理</span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getTaskProgress } from '../api'
import { ArrowLeft, Loading } from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()

const task = ref(null)
const scannedStocks = ref([])
const scannedCount = ref(0)
const loading = ref(false)
let pollTimer = null

const taskId = computed(() => route.params.taskId)

const statusType = computed(() => {
  const map = { running: 'warning', success: 'success', failed: 'danger', pending: 'info' }
  return map[task.value?.status] || 'info'
})

const statusLabel = computed(() => {
  const map = { running: '扫描中', success: '已完成', failed: '失败', pending: '等待中' }
  return map[task.value?.status] || task.value?.status || '--'
})

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

onMounted(fetchProgress)
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
  gap: 16px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-header__left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text-primary);
}
.overview-card {
  border-radius: var(--radius-card);
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  text-align: center;
}
.overview-label {
  font-size: 13px;
  color: var(--color-text-muted);
  margin-bottom: 4px;
}
.overview-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-text-primary);
}
.overview-value.highlight {
  color: var(--color-primary);
}
.table-card {
  border-radius: var(--radius-card);
}
.code-text {
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  letter-spacing: 0.5px;
}
.pending-card {
  border-radius: var(--radius-card);
}
.pending-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--color-text-secondary);
}
.text-muted {
  color: var(--color-text-muted);
}
</style>
