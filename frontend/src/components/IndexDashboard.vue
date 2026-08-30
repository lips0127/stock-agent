<template>
  <section class="index-dashboard">
    <header class="index-dashboard__header">
      <h2 class="index-dashboard__title">市场情绪仪表盘</h2>
      <span class="index-dashboard__date">{{ formatDate(props.date) }}</span>
    </header>

    <div v-if="loading" class="index-dashboard__loading">加载中...</div>

    <div v-else-if="!summary.length" class="index-dashboard__empty">
      暂无数据。后端每日 18:00 自动爬取，或在
      <code>POST /api/sentiment/universe/run/all</code> 手动触发。
    </div>

    <div v-else class="index-dashboard__grid">
      <article
        v-for="row in summary"
        :key="row.code"
        class="index-card"
        :class="{ 'index-card--panic': (row.panic_count || 0) > 0 }"
      >
        <div class="index-card__top">
          <span class="index-card__name">{{ row.name }}</span>
          <span class="index-card__total">{{ row.total_stocks || 0 }} 只</span>
        </div>

        <div class="index-card__score" :style="{ color: scoreColor(row.avg_score) }">
          <template v-if="row.avg_score != null">
            {{ row.avg_score.toFixed(1) }}
            <span
              v-if="row.vs_yesterday_score != null"
              class="index-card__delta"
              :class="deltaClass(row.vs_yesterday_score)"
            >
              {{ formatDelta(row.vs_yesterday_score) }}
            </span>
          </template>
          <template v-else>-</template>
        </div>

        <div class="index-card__badges">
          <span class="badge badge--bull">乐观 {{ row.bullish_count || 0 }}</span>
          <span class="badge badge--bear">悲观 {{ row.bearish_count || 0 }}</span>
          <span
            v-if="(row.panic_count || 0) > 0"
            class="badge badge--panic"
            :title="`今日 ${row.panic_count} 只触发恐慌信号`"
          >恐慌 {{ row.panic_count }}</span>
          <span
            v-if="(row.euphoria_count || 0) > 0"
            class="badge badge--euph"
          >狂热 {{ row.euphoria_count }}</span>
        </div>

        <div v-if="(row.analyzed_stocks || 0) === 0" class="index-card__hint">
          今日未分析
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { getUniverseSummary } from '../api/universe'

const props = defineProps({
  date: { type: String, default: () => new Date().toISOString().slice(0, 10) }
})
const emit = defineEmits(['refresh'])

const summary = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await getUniverseSummary(props.date)
    summary.value = Array.isArray(data) ? data : []
  } catch (e) {
    console.error('IndexDashboard load failed', e)
    summary.value = []
  } finally {
    loading.value = false
  }
}

function scoreColor(s) {
  if (s == null) return 'var(--color-text-tertiary)'
  if (s >= 60) return 'var(--color-success)'
  if (s <= 40) return 'var(--color-danger)'
  return 'var(--color-text-primary)'
}

function deltaClass(d) {
  if (d > 0) return 'delta--up'
  if (d < 0) return 'delta--down'
  return ''
}

function formatDelta(d) {
  if (d == null) return ''
  return d > 0 ? `+${d.toFixed(1)}` : d.toFixed(1)
}

function formatDate(d) {
  if (!d) return ''
  return d
}

onMounted(() => {
  load()
  // 监听 universe 批量分析完成事件，自动刷新
  window.addEventListener('sentiment-universe-finished', load)
})
watch(() => props.date, load)
onUnmounted(() => {
  window.removeEventListener('sentiment-universe-finished', load)
})
</script>

<style scoped>
.index-dashboard {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5) var(--space-6);
  margin-bottom: var(--space-4);
}

.index-dashboard__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.index-dashboard__title {
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  margin: 0;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
}

.index-dashboard__date {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
}

.index-dashboard__loading,
.index-dashboard__empty {
  padding: var(--space-6);
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--text-sm);
}
.index-dashboard__empty code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  padding: 1px 6px;
  background: var(--color-bg-muted);
  border-radius: var(--radius-sm);
}

.index-dashboard__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-3);
}

.index-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-page);
  transition: border-color var(--duration-fast) var(--ease);
}
.index-card:hover {
  border-color: var(--color-border-strong);
}

.index-card--panic {
  border-color: rgba(220, 38, 38, 0.4);
  background: var(--color-danger-soft);
}

.index-card__top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-1);
}

.index-card__name {
  font-weight: var(--weight-semibold);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}

.index-card__total {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.index-card__score {
  font-family: var(--font-mono);
  font-size: 28px;
  font-weight: var(--weight-bold);
  margin: var(--space-1) 0 var(--space-2);
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-variant-numeric: tabular-nums;
}

.index-card__delta {
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  font-variant-numeric: tabular-nums;
}

.delta--up {
  color: var(--color-success);
  background: var(--color-success-soft);
}

.delta--down {
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.index-card__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: var(--space-1);
}

.badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-weight: var(--weight-medium);
}

.badge--bull {
  color: var(--color-success);
  background: var(--color-success-soft);
}

.badge--bear {
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.badge--panic {
  color: var(--color-text-inverse);
  background: var(--color-danger);
  font-weight: var(--weight-semibold);
}

.badge--euph {
  color: var(--color-text-inverse);
  background: var(--color-success);
  font-weight: var(--weight-semibold);
}

.index-card__hint {
  margin-top: var(--space-1);
  font-size: 11px;
  color: var(--color-text-tertiary);
}
</style>
