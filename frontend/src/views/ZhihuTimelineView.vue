<template>
  <div class="timeline-page">
    <PageHeader
      title="大V时间线"
      :subtitle="`近 ${days} 天已分析动态 · 共 ${posts.length} 条 · 对比 ${indexName}`"
    >
      <template #actions>
        <el-radio-group v-model="days" size="small" @change="refreshAll">
          <el-radio-button :value="3">3天</el-radio-button>
          <el-radio-button :value="7">7天</el-radio-button>
          <el-radio-button :value="14">14天</el-radio-button>
        </el-radio-group>
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
      </template>
    </PageHeader>

    <!-- 统计卡片 -->
    <div class="stat-row">
      <StatCard label="总动态" :value="posts.length" />
      <StatCard label="看多" :value="bullishCount" tone="up" />
      <StatCard label="看空" :value="bearishCount" tone="down" />
      <StatCard label="中性" :value="neutralCount" />
      <StatCard
        v-if="klineWarning"
        :label="indexName"
        :value="klineWarning"
        tone="warning"
      />
    </div>

    <!-- K线图 -->
    <ModernCard class="chart-card">
      <template #extra>
        <div class="chart-toolbar">
          <div class="legend-pills">
            <span class="legend-pill"><span class="pill-dot pill-dot--bullish" />看多</span>
            <span class="legend-pill"><span class="pill-dot pill-dot--bearish" />看空</span>
            <span class="legend-pill"><span class="pill-dot pill-dot--mixed" />混合</span>
            <span class="legend-pill"><span class="pill-dot pill-dot--neutral" />中性</span>
            <span class="legend-divider" />
            <span class="legend-pill"><span class="pill-candle pill-candle--up" />阳线</span>
            <span class="legend-pill"><span class="pill-candle pill-candle--down" />阴线</span>
          </div>
          <el-segmented
            v-model="selectedIndex"
            :options="indexOptions"
            size="small"
            @change="fetchKline"
          />
        </div>
      </template>
      <KLineChart
        :kline-data="klineData"
        :posts="posts"
        height="440px"
        :loading="klineLoading"
        :error="klineError"
        :highlight-post-id="highlightPostId"
        @post-click="onPostClick"
      />
    </ModernCard>

    <!-- 帖子时间线 -->
    <div class="timeline-section">
      <div class="timeline-section__header">
        <h3 class="timeline-section__title">动态时间线 ({{ filteredPosts.length }})</h3>
        <div class="timeline-section__filters">
          <el-select v-model="stanceFilter" size="small" clearable placeholder="按立场筛选" style="width: 120px">
            <el-option label="看多" value="bullish" />
            <el-option label="看空" value="bearish" />
            <el-option label="中性" value="neutral" />
            <el-option label="混合" value="mixed" />
          </el-select>
          <el-select v-model="userFilter" size="small" clearable placeholder="按大V筛选" style="width: 140px">
            <el-option v-for="u in uniqueUsers" :key="u" :label="u" :value="u" />
          </el-select>
        </div>
      </div>

      <div v-if="!filteredPosts.length" class="empty-posts">
        <EmptyHint icon="∅" title="无匹配动态" description="尝试调整筛选条件或增加时间范围" />
      </div>

      <div v-else class="timeline-list">
        <div v-for="(group, gIdx) in groupedPosts" :key="gIdx" class="day-group">
          <div class="day-divider">
            <span class="day-divider__line" />
            <span class="day-divider__label">{{ group.date }}</span>
            <span class="day-divider__meta">{{ group.items.length }} 条</span>
            <span class="day-divider__line" />
          </div>
          <div
            v-for="p in group.items"
            :key="p.post_id"
            :id="`post-${p.post_id}`"
            class="tl-card"
            :class="{ 'tl-card--active': highlightPostId === p.post_id }"
            :style="{ '--tl-accent': stanceColor(p.stance) }"
            @click="scrollToChart(p)"
          >
            <div class="tl-card__time">{{ formatTime(p.created_at_original) }}</div>
            <div class="tl-card__main">
              <div class="tl-card__header">
                <el-avatar :src="p.avatar_url" :size="24" class="tl-avatar">
                  {{ (p.display_name || p.url_token).slice(0, 1) }}
                </el-avatar>
                <span class="tl-author">{{ p.display_name || p.url_token }}</span>
                <span class="tl-stance" :style="{ background: stanceColor(p.stance) }">
                  {{ stanceLabel(p.stance) }} · {{ p.confidence || '?' }}
                </span>
                <span class="tl-type">{{ typeLabel(p.post_type) }}</span>
              </div>
              <a :href="p.url" target="_blank" class="tl-title">{{ p.title }}</a>
              <div v-if="p.summary" class="tl-summary">{{ p.summary }}</div>
              <div v-if="p.stance_assets && p.stance_assets.length" class="tl-assets">
                <span
                  v-for="(a, i) in p.stance_assets"
                  :key="i"
                  class="tl-asset-chip"
                  :style="{ background: stanceColor(a.stance) }"
                  :title="a.reason || ''"
                >
                  <span v-if="a.code" class="tl-asset-chip__code">{{ a.code }}</span>
                  <span class="tl-asset-chip__name">{{ a.asset }}</span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getZhihuTimeline, getMarketIntraday } from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import StatCard from '../components/ui/StatCard.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'
import KLineChart from '../components/KLineChart.vue'

const days = ref(7)
const posts = ref([])
const loading = ref(false)
const highlightPostId = ref(null)

// K-line state
const selectedIndex = ref('sh000001')
const klineData = ref({ bars: [] })
const klineLoading = ref(false)
const klineError = ref('')
const klineWarning = ref('')

// Filters
const stanceFilter = ref('')
const userFilter = ref('')

const indexOptions = [
  { label: '上证指数', value: 'sh000001' },
  { label: '深证成指', value: 'sz399001' },
  { label: '创业板指', value: 'sz399006' },
  { label: '科创50', value: 'sh000688' },
  { label: '沪深300', value: 'sh000300' },
]

const indexName = computed(() => {
  const m = indexOptions.find(o => o.value === selectedIndex.value)
  return m ? m.label : selectedIndex.value
})

// Stats
const bullishCount = computed(() => posts.value.filter(p => p.stance === 'bullish').length)
const bearishCount = computed(() => posts.value.filter(p => p.stance === 'bearish').length)
const neutralCount = computed(() => posts.value.filter(p => !p.stance || p.stance === 'neutral' || p.stance === 'mixed').length)

const uniqueUsers = computed(() => {
  const set = new Set()
  posts.value.forEach(p => { if (p.display_name) set.add(p.display_name) })
  return [...set].sort()
})

const filteredPosts = computed(() => {
  let arr = posts.value
  if (stanceFilter.value) arr = arr.filter(p => p.stance === stanceFilter.value)
  if (userFilter.value) arr = arr.filter(p => p.display_name === userFilter.value)
  return arr
})

// Group posts by date (ascending in source → reverse for display)
const groupedPosts = computed(() => {
  const groups = {}
  for (const p of [...filteredPosts.value].reverse()) {
    const date = (p.created_at_original || '').slice(0, 10) || '未知日期'
    if (!groups[date]) groups[date] = []
    groups[date].push(p)
  }
  return Object.entries(groups).map(([date, items]) => ({ date, items }))
})

const stanceLabel = (s) => ({
  bullish: '看多', bearish: '看空', neutral: '中性', mixed: '混合',
}[s] || '中性')

const stanceColor = (s) => ({
  bullish: '#34c759', bearish: '#ff3b30', neutral: '#aeaeb2', mixed: '#ff9f0a',
}[s] || '#aeaeb2')

const typeLabel = (t) => ({ article: '文章', answer: '回答', pin: '想法' }[t] || t || '其他')

const formatTime = (t) => {
  if (!t) return ''
  try {
    const d = new Date(t)
    if (isNaN(d.getTime())) return t
    return d.toLocaleString('zh-CN', { hour12: false,
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return t }
}

async function fetchTimeline() {
  loading.value = true
  try {
    const { data } = await getZhihuTimeline(days.value)
    posts.value = data || []
  } catch (e) {
    console.error('时间线加载失败:', e)
    posts.value = []
  } finally {
    loading.value = false
  }
}

async function fetchKline() {
  klineLoading.value = true
  klineError.value = ''
  klineWarning.value = ''
  try {
    const { data } = await getMarketIntraday(selectedIndex.value, '30min', days.value)
    klineData.value = data || { bars: [] }
    if (data.warning) klineWarning.value = data.warning
    if (data.error) klineError.value = data.error
  } catch (e) {
    console.error('K线加载失败:', e)
    klineError.value = 'K线数据加载失败'
    klineData.value = { bars: [] }
  } finally {
    klineLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([fetchTimeline(), fetchKline()])
}

function onPostClick(postData) {
  // Highlight the post in chart, then scroll to the matching timeline card
  highlightPostId.value = postData.postId
  setTimeout(() => { highlightPostId.value = null }, 3000)
  const el = document.getElementById(`post-${postData.postId}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function scrollToChart(post) {
  highlightPostId.value = post.post_id
  setTimeout(() => { highlightPostId.value = null }, 3000)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(refreshAll)
</script>

<style scoped>
.timeline-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: var(--space-3);
}

.chart-card {
  margin-top: var(--space-2);
}

.chart-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  flex-wrap: wrap;
}

.legend-pills {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.legend-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.pill-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}
.pill-dot--bullish { background: #34c759; }
.pill-dot--bearish { background: #ff3b30; }
.pill-dot--mixed   { background: #ff9f0a; }
.pill-dot--neutral { background: #aeaeb2; }

.legend-divider {
  width: 1px;
  height: 14px;
  background: var(--color-border);
  margin: 0 var(--space-1);
}

.pill-candle {
  width: 12px;
  height: 8px;
  border-radius: 1px;
  border: 1px solid var(--color-border-strong);
  flex-shrink: 0;
}
.pill-candle--up   { background: #ff3b30; }
.pill-candle--down { background: #34c759; }

/* ── Timeline section ── */
.timeline-section {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.timeline-section__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-divider);
  flex-wrap: wrap;
}

.timeline-section__title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
}

.timeline-section__filters {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.empty-posts {
  padding: var(--space-12) 0;
}

.timeline-list {
  padding: var(--space-2) var(--space-5) var(--space-5);
}

.day-group {
  margin-bottom: var(--space-2);
}

.day-divider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) 0 var(--space-3);
  position: sticky;
  top: 56px;
  background: var(--color-bg-elevated);
  z-index: 2;
}

.day-divider__line {
  flex: 1;
  height: 1px;
  background: var(--color-divider);
}

.day-divider__label {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  white-space: nowrap;
}

.day-divider__meta {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

/* ── Timeline card ── */
.tl-card {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-elevated);
  margin-bottom: 2px;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  border-left: 4px solid var(--tl-accent, #8c8c8c);
  transition: all var(--duration-fast) var(--ease);
  cursor: pointer;
  position: relative;
}

.tl-card:hover {
  background: var(--color-bg-subtle);
  border-color: var(--color-border);
  border-left-width: 4px;
  box-shadow: var(--shadow-xs);
  transform: translateX(2px);
}

.tl-card--active {
  background: var(--color-accent-soft);
  border-color: rgba(37, 99, 235, 0.15);
  box-shadow: var(--shadow-sm);
}

.tl-card__time {
  font-size: 11px;
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  min-width: 88px;
  padding-top: 5px;
}

.tl-card__main {
  flex: 1;
  min-width: 0;
}

.tl-card__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
  flex-wrap: wrap;
}

.tl-avatar {
  flex-shrink: 0;
}

.tl-author {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
}

.tl-stance {
  display: inline-block;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  color: #fff;
  font-size: 11px;
  font-weight: var(--weight-medium);
}

.tl-type {
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-left: auto;
}

.tl-title {
  display: block;
  font-size: var(--text-sm);
  color: var(--color-accent);
  text-decoration: none;
  margin-bottom: 4px;
  line-height: var(--leading-normal);
}
.tl-title:hover { text-decoration: underline; }

.tl-summary {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin-bottom: 4px;
}

.tl-assets {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tl-asset-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  color: #fff;
  font-size: 10px;
  line-height: 1.5;
  cursor: help;
}

.tl-asset-chip__code {
  font-weight: 600;
  letter-spacing: 0.02em;
  font-variant-numeric: tabular-nums;
  padding-right: 4px;
  border-right: 1px solid rgba(255, 255, 255, 0.35);
}

.tl-asset-chip__name {
  opacity: 0.95;
}
</style>
