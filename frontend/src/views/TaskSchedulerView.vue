<template>
  <div class="task-page">
    <PageHeader
      title="任务调度"
      subtitle="可视化配置 10 个 APScheduler 任务的执行时间与启停状态；保存后立即生效"
    >
      <template #actions>
        <el-button @click="load" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </template>
    </PageHeader>

    <div v-if="loading && !tasks.length" class="task-page__loading">加载中…</div>

    <div v-else>
      <!-- 顶部统计 -->
      <div class="task-page__stats">
        <StatCard label="总任务" :value="stats.total" variant="primary" />
        <StatCard label="已启用" :value="stats.enabled" variant="success" />
        <StatCard label="已暂停" :value="stats.disabled" variant="warning" />
      </div>

      <div v-if="!tasks.length" class="task-page__empty">
        暂无任务配置。请重启 Flask 让 init_scheduler() 自动 seed 10 行。
      </div>

      <div v-else class="task-page__grid">
        <SchedulerTaskCard
          v-for="t in tasks" :key="t.job_id"
          :task="t" @saved="onSaved" @toggle="onToggle"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import PageHeader from '../components/ui/PageHeader.vue'
import StatCard from '../components/ui/StatCard.vue'
import SchedulerTaskCard from '../components/SchedulerTaskCard.vue'
import { getSchedulerConfigs } from '../api/scheduler'

const tasks = ref([])
const loading = ref(false)

const stats = computed(() => {
  const total = tasks.value.length
  const enabled = tasks.value.filter(t => t.enabled).length
  return { total, enabled, disabled: total - enabled }
})

async function load() {
  loading.value = true
  try {
    const { data } = await getSchedulerConfigs()
    tasks.value = Array.isArray(data) ? data : []
  } catch (e) {
    ElMessage.error('加载任务配置失败')
    tasks.value = []
  } finally { loading.value = false }
}

function onSaved(updated) {
  const i = tasks.value.findIndex(t => t.job_id === updated.job_id)
  if (i >= 0) tasks.value[i] = { ...tasks.value[i], ...updated }
}

function onToggle(payload) {
  const i = tasks.value.findIndex(t => t.job_id === payload.job_id)
  if (i >= 0) {
    tasks.value[i] = {
      ...tasks.value[i],
      enabled: payload.enabled,
      next_run_time: payload.next_run_time,
    }
  }
}

onMounted(load)
</script>

<style scoped>
.task-page__loading {
  padding: 60px 0;
  text-align: center;
  color: var(--text-tertiary, #6b7280);
}
.task-page__empty {
  padding: 40px 0;
  text-align: center;
  color: var(--text-tertiary, #6b7280);
  font-size: 13px;
}
.task-page__stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
.task-page__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
}
@media (max-width: 768px) {
  .task-page__stats { grid-template-columns: 1fr; }
}
</style>
