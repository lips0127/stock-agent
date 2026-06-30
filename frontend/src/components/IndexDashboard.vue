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
          <template v-else>—</template>
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
  if (s == null) return 'var(--text-tertiary, #999)'
  if (s >= 60) return 'var(--color-bull, #16a34a)'
  if (s <= 40) return 'var(--color-bear, #dc2626)'
  return 'var(--text-primary, #1a1a1a)'
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
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-soft, #e5e7eb);
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 16px;
}

.index-dashboard__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 16px;
}

.index-dashboard__title {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary, #1a1a1a);
}

.index-dashboard__date {
  font-size: 12px;
  color: var(--text-tertiary, #6b7280);
}

.index-dashboard__loading,
.index-dashboard__empty {
  padding: 24px;
  text-align: center;
  color: var(--text-tertiary, #6b7280);
  font-size: 13px;
}

.index-dashboard__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.index-card {
  border: 1px solid var(--border-soft, #e5e7eb);
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--bg-elevated, #fafafa);
  transition: border-color 0.15s;
}

.index-card--panic {
  border-color: var(--color-bear, #dc2626);
  background: var(--bg-panic, #fef2f2);
}

.index-card__top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.index-card__name {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary, #1a1a1a);
}

.index-card__total {
  font-size: 11px;
  color: var(--text-tertiary, #6b7280);
}

.index-card__score {
  font-size: 28px;
  font-weight: 700;
  margin: 4px 0 8px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.index-card__delta {
  font-size: 12px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
}

.delta--up {
  color: var(--color-bull, #16a34a);
  background: var(--bg-bull-soft, #dcfce7);
}

.delta--down {
  color: var(--color-bear, #dc2626);
  background: var(--bg-bear-soft, #fee2e2);
}

.index-card__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.badge--bull {
  color: var(--color-bull, #16a34a);
  background: var(--bg-bull-soft, #dcfce7);
}

.badge--bear {
  color: var(--color-bear, #dc2626);
  background: var(--bg-bear-soft, #fee2e2);
}

.badge--panic {
  color: #fff;
  background: var(--color-bear, #dc2626);
  font-weight: 600;
}

.badge--euph {
  color: #fff;
  background: var(--color-bull, #16a34a);
  font-weight: 600;
}

.index-card__hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
  font-style: italic;
}
</style>
