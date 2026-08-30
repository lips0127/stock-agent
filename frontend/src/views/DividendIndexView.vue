<template>
  <div class="stocks-page">
    <PageHeader
      title="红利指数"
      :subtitle="scanDate
        ? `中证红利成分股 · 扫描日期：${scanDate}`
        : '中证红利成分股 · 轻量扫描，快速观测高股息'"
    >
      <template #actions>
        <span v-if="total > 0" class="total-pill">共 {{ total }} 只</span>
        <el-button
          type="primary"
          :icon="Refresh"
          :loading="scanning"
          @click="handleScan"
        >
          运行红利指数扫描
        </el-button>
      </template>
    </PageHeader>

    <StockScanTable
      scan-type="index"
      empty-text="暂无红利指数扫描数据，点击右上角运行扫描"
      @meta="onMeta"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { indexScan } from '../api'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useTaskStore } from '../stores/task'
import PageHeader from '../components/ui/PageHeader.vue'
import StockScanTable from '../components/StockScanTable.vue'

const taskStore = useTaskStore()
const scanning = ref(false)
const total = ref(0)
const scanDate = ref('')

function onMeta({ total: t, date }) {
  total.value = t
  scanDate.value = date
}

async function handleScan() {
  if (taskStore.currentTask?.status === 'running') {
    ElMessage.warning('已有扫描任务在运行')
    return
  }
  scanning.value = true
  try {
    const { data } = await indexScan()
    ElMessage.success('红利指数扫描已提交')
    taskStore.startPolling(data.task_id, 'index')
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.error || '已有扫描任务在运行')
    } else {
      ElMessage.error('扫描启动失败: ' + (e.response?.data?.error || e.message))
    }
  } finally {
    scanning.value = false
  }
}
</script>

<style scoped>
.stocks-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.total-pill {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  background: var(--color-bg-muted);
  padding: 4px 12px;
  border-radius: var(--radius-full);
  font-variant-numeric: tabular-nums;
}
</style>
