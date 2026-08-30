<template>
  <div class="dashboard">
    <!-- 欢迎头部 -->
    <PageHeader
      :title="greeting"
      :subtitle="`实时指数、高股息榜单与扫描任务日志 · 共 ${stocks.length} 只高股息标的`"
      size="lg"
    >
      <template #meta>
        <span class="meta-item">
          <span class="meta-dot" :class="{ 'meta-dot--ok': !anyLoading }" />
          数据已同步 {{ lastSyncLabel }}
        </span>
        <span class="meta-divider" />
        <span class="meta-item">
          <el-icon class="meta-icon"><Clock /></el-icon>
          {{ clockLabel }}
        </span>
        <span class="meta-divider" />
        <span class="meta-item">
          {{ auth.username }}
        </span>
      </template>
      <template #actions>
        <el-button :icon="RefreshRight" @click="refreshAll" :loading="anyLoading">
          刷新数据
        </el-button>
        <el-button type="primary" :icon="Search" @click="handleFullRefresh" :loading="fullRefreshing">
          全市场扫描
        </el-button>
      </template>
    </PageHeader>

    <!-- 关键指标 -->
    <section class="kpi-grid">
      <StatCard
        label="监控指数"
        :value="indices.length"
        tone="default"
        hint="覆盖上证/深证/创业板/科创50/沪深300"
      >
        <template #badge>
          <el-tag v-if="indices.length" type="success" size="small" effect="light">实时</el-tag>
        </template>
      </StatCard>

      <StatCard
        label="高股息标的"
        :value="stocks.length"
        tone="accent"
        :hint="`按股息率倒序 TOP ${stocks.length}`"
      />

      <StatCard
        label="今日任务"
        :value="logs.length"
        tone="default"
        :hint="`最近 ${logs.length} 条扫描记录`"
      >
        <template #badge>
          <el-tag v-if="runningTaskCount" type="warning" size="small" effect="light">
            {{ runningTaskCount }} 运行中
          </el-tag>
        </template>
      </StatCard>

    </section>

    <!-- VIX 恐慌指数 + 恐惧贪婪 -->
    <ModernCard
      title="恐慌贪婪指数"
      description="单一情绪读数 · 0=极度恐慌 100=极度贪婪"
      variant="bordered"
    >
      <template #extra>
        <el-button text type="primary" size="small" @click="router.push('/vix')">
          详情
          <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </template>

      <div v-if="vix" class="vix-row">
        <VixGauge
          :value="vix.fear_greed_v7"
          :percentile="vix.fg7_percentile"
          :regime="vix.fg7_regime || 'unknown'"
        />
        <div class="vix-subgrid">
            <div class="vix-sub">
              <div class="vix-sub__label">50ETF IV</div>
              <div class="vix-sub__val">{{ fmt(vix.iv_50etf, 2) }}</div>
            </div>
            <div class="vix-sub">
              <div class="vix-sub__label">RV 沪深300</div>
              <div class="vix-sub__val">{{ fmt(vix.rv_hs300, 2) }}</div>
            </div>
            <div class="vix-sub">
              <div class="vix-sub__label">RV 中证1000</div>
              <div class="vix-sub__val">{{ fmt(vix.rv_zz1000, 2) }}</div>
            </div>
            <div class="vix-sub">
              <div class="vix-sub__label">涨跌停比</div>
              <div class="vix-sub__val">
                <span class="text-up">{{ vix.limit_up_count || 0 }}</span>
                <span class="vix-sub__sep">/</span>
                <span class="text-down">{{ vix.limit_down_count || 0 }}</span>
              </div>
            </div>
            <div class="vix-sub">
              <div class="vix-sub__label">融资余额</div>
              <div class="vix-sub__val">
                {{ vix.margin_balance != null ? (vix.margin_balance / 10000).toFixed(2) + ' 万亿' : '-' }}
              </div>
            </div>
            <div class="vix-sub">
              <div class="vix-sub__label">PCR 成交量</div>
              <div class="vix-sub__val">
                {{ fmt(vix.pcr_volume, 2) }}
              </div>
            </div>
          </div>
        <div class="vix-trend-wrap">
          <VixTrendChart :history="vixHistory" />
        </div>
      </div>
      <div v-if="vix && vix.fear_greed_v7 == null" class="vix-quality vix-quality--warn">
        <el-icon class="vix-quality__icon is-warn"><WarningFilled /></el-icon>
        <span>最新交易日构造分缺失，读数与走势按缺口如实显示；可到「恐慌贪婪指数」页重算。</span>
      </div>
      <EmptyHint
        v-if="!vix"
        title="暂无恐慌贪婪指数数据"
        description="可点击下方按钮手动触发计算"
        carded
      >
        <template #action>
          <el-button :icon="Refresh" type="primary" :loading="vixRecomputing" @click="handleRecomputeVix">
            立即计算
          </el-button>
        </template>
      </EmptyHint>
    </ModernCard>

    <!-- 大盘指数 -->
    <ModernCard
      title="大盘指数"
      :description="indicesMeta?.degraded
        ? `部分指数获取失败（成功 ${indicesMeta.coverage?.ok ?? indices.length}/${indicesMeta.coverage?.expected ?? '-'}），数据可能不完整`
        : '打开页面时从新浪实时抓取'"
    >
      <template #extra>
        <el-tag
          v-if="indicesMeta?.degraded || indicesMeta?.unavailable"
          type="warning"
          size="small"
          effect="light"
          style="margin-right: 8px"
        >
          {{ indicesMeta?.unavailable ? '源不可用' : '部分降级' }}
        </el-tag>
        <el-button
          :icon="Refresh"
          size="small"
          text
          :loading="refreshing"
          @click="handleIndexScan"
        >
          红利指数扫描
        </el-button>
      </template>
      <IndexCards :indices="indices" :loading="indicesLoading" />
    </ModernCard>

    <!-- 高股息股票 -->
    <ModernCard
      title="高股息股票"
      description="按股息率倒序（Top 20）· A 股惯例：红涨绿跌"
      variant="bordered"
    >
      <template #extra>
        <el-button text type="primary" size="small" @click="router.push({ name: 'Stocks' })">
          查看全量
          <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </template>
      <StockTable :stocks="stocks" :loading="stocksLoading" @search="openStockSearch" />
    </ModernCard>

    <!-- 任务日志 -->
    <ModernCard
      title="任务执行日志"
      description="最近 50 条扫描任务记录"
    >
      <TaskLogs :logs="logs" :loading="logsLoading" />
    </ModernCard>

    <StockSearch v-model:visible="searchVisible" :symbol="searchSymbol" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useAuthStore } from '../stores/auth'
import {
  getLiveIndices, getTopStocks, getLogs, indexScan, fullRefreshData,
  getVix, getVixHistory, recomputeVix, getTask,
} from '../api'
import { ElMessage } from 'element-plus'
import {
  Refresh, Search, RefreshRight, ArrowRight, Clock,
  WarningFilled,
} from '@element-plus/icons-vue'

import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import StatCard from '../components/ui/StatCard.vue'
import IndexCards from '../components/IndexCards.vue'
import StockTable from '../components/StockTable.vue'
import StockSearch from '../components/StockSearch.vue'
import TaskLogs from '../components/TaskLogs.vue'
import VixGauge from '../components/VixGauge.vue'
import VixTrendChart from '../components/VixTrendChart.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'

const router = useRouter()
const taskStore = useTaskStore()
const auth = useAuthStore()

const indices = ref([])
const indicesMeta = ref(null)
const stocks = ref([])
const logs = ref([])
const indicesLoading = ref(false)
const stocksLoading = ref(false)
const logsLoading = ref(false)
const searchVisible = ref(false)
const searchSymbol = ref('')
const refreshing = ref(false)
const fullRefreshing = ref(false)

const now = ref(new Date())
let clockTimer = null

const vix = ref(null)
const vixHistory = ref([])
const vixRecomputing = ref(false)
let vixPollTimer = null

const anyLoading = computed(
  () => indicesLoading.value || stocksLoading.value || logsLoading.value
)
const runningTaskCount = computed(
  () => logs.value.filter((l) => l.status === 'running').length
)

const greeting = computed(() => {
  const h = now.value.getHours()
  const u = (auth.username || '朋友').trim()
  if (h < 6)  return `夜深了，${u}，注意休息`
  if (h < 11) return `早上好，${u}`
  if (h < 14) return `中午好，${u}`
  if (h < 18) return `下午好，${u}`
  return `晚上好，${u}`
})

const lastSyncLabel = computed(() => {
  const d = now.value
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})

const clockLabel = computed(() => {
  const d = now.value
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
})

// ── 恐慌贪婪指数 ──

function fmt(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '-'
  return Number(v).toFixed(digits)
}

async function fetchVix() {
  try {
    const { data } = await getVix()
    vix.value = data
  } catch {
    vix.value = null
  }
}
async function fetchVixHistory() {
  try {
    const { data } = await getVixHistory(60)
    vixHistory.value = data?.data || []
  } catch {
    vixHistory.value = []
  }
}

function pollVixTask(taskId) {
  if (vixPollTimer) clearInterval(vixPollTimer)
  vixPollTimer = setInterval(async () => {
    try {
      const { data: task } = await getTask(taskId)
      // TaskRunner 终态是 success/failed/cancelled（不是 completed）
      if (['success', 'failed', 'cancelled'].includes(task?.status)) {
        clearInterval(vixPollTimer)
        vixPollTimer = null
        vixRecomputing.value = false
        await fetchVix()
        await fetchVixHistory()
      }
    } catch {
      clearInterval(vixPollTimer)
      vixPollTimer = null
      vixRecomputing.value = false
    }
  }, 2000)
}

async function handleRecomputeVix() {
  if (vixRecomputing.value) return
  vixRecomputing.value = true
  try {
    const { data } = await recomputeVix()
    ElMessage.success('VIX 重算已提交')
    if (!data?.task_id) { vixRecomputing.value = false; return }
    pollVixTask(data.task_id)
  } catch (err) {
    if (err?.response?.status === 409 && err.response?.data?.task_id) {
      // 已有同 kind 任务在跑：接管它而不是报错了事
      ElMessage.info('已有 VIX 重算任务在进行中，已接入其进度')
      pollVixTask(err.response.data.task_id)
    } else {
      ElMessage.error('VIX 重算失败: ' + (err?.response?.data?.error || err.message))
      vixRecomputing.value = false
    }
  }
}

async function fetchIndices() {
  indicesLoading.value = true
  try {
    const { data } = await getLiveIndices()
    // /api/indices/live 返回 {data, source, as_of, coverage, degraded, errors}
    indices.value = data?.data || []
    indicesMeta.value = data && Array.isArray(data.data) ? data : null
  } catch {
    indices.value = []
    indicesMeta.value = null
  } finally {
    indicesLoading.value = false
  }
}
async function fetchStocks() {
  stocksLoading.value = true
  try {
    const { data } = await getTopStocks(20)
    stocks.value = data || []
  } catch {
    stocks.value = []
  } finally {
    stocksLoading.value = false
  }
}
async function fetchLogs() {
  logsLoading.value = true
  try {
    const { data } = await getLogs()
    logs.value = data || []
  } catch {
    logs.value = []
  } finally {
    logsLoading.value = false
  }
}
function refreshAll() {
  fetchIndices(); fetchStocks(); fetchLogs()
}
function openStockSearch(symbol) {
  if (typeof symbol === 'object' && symbol !== null) symbol = symbol.code || ''
  if (!symbol) return
  searchSymbol.value = String(symbol)
  searchVisible.value = true
}
async function handleIndexScan() {
  if (taskStore.currentTask?.status === 'running') {
    ElMessage.warning('已有扫描任务在运行'); return
  }
  refreshing.value = true
  try {
    const { data } = await indexScan()
    ElMessage.success('红利指数扫描已提交')
    taskStore.startPolling(data.task_id)
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.error || '已有扫描任务在运行')
    } else {
      ElMessage.error('刷新失败: ' + (e.response?.data?.error || e.message))
    }
  } finally { refreshing.value = false }
}
async function handleFullRefresh() {
  if (taskStore.currentTask?.status === 'running') {
    ElMessage.warning('已有扫描任务在运行'); return
  }
  fullRefreshing.value = true
  try {
    const { data } = await fullRefreshData()
    ElMessage.success(data.message || '全市场扫描已启动')
    taskStore.startPolling(data.task_id)
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.error || '已有扫描任务在运行')
    } else {
      ElMessage.error('全市场扫描启动失败: ' + (e.response?.data?.error || e.message))
    }
  } finally { fullRefreshing.value = false }
}

watch(
  () => taskStore.currentTask?.status,
  (status) => {
    if (status === 'success' || status === 'failed') refreshAll()
  }
)

onMounted(() => {
  fetchIndices(); fetchStocks(); fetchLogs()
  fetchVix(); fetchVixHistory()
  clockTimer = setInterval(() => { now.value = new Date() }, 1000)
})
onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
  if (vixPollTimer) clearInterval(vixPollTimer)
})
</script>

<style scoped>
.dashboard {
  min-height: calc(100vh - var(--space-12));
}

/* ── PageHeader 内的 meta 元素 ── */
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
  font-variant-numeric: tabular-nums;
}
.meta-divider {
  width: 1px;
  height: 12px;
  background: var(--color-border-strong);
  display: inline-block;
}
.meta-icon {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

/* 数据同步状态点：语义状态指示（非装饰），静态不脉冲 */
.meta-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-text-disabled);
  display: inline-block;
}
.meta-dot--ok {
  background: var(--color-success);
}

/* ── KPI 网格 ── */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-5);
  margin-bottom: var(--space-6);
}

/* ModernCard 之间的呼吸感 */
.dashboard > .modern-card,
.dashboard > .kpi-grid {
  margin-bottom: var(--space-6);
}
.dashboard > .vix-quality {
  margin-top: calc(var(--space-2) * -1);
  margin-bottom: var(--space-6);
}
.dashboard > .modern-card:last-of-type {
  margin-bottom: 0;
}

.vix-quality {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
  border-top: 1px dashed var(--color-border);
  margin-top: -8px;
  flex-wrap: wrap;
}
.vix-quality__icon {
  font-size: 14px;
}
.vix-quality__icon.is-ok { color: var(--color-success); }
.vix-quality__icon.is-warn { color: var(--color-warning); }
.vix-quality strong {
  color: var(--color-text-secondary);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
  margin: 0 2px;
}
.vix-quality--warn {
  color: #b45309;
  background: rgba(245, 158, 11, 0.07);
  border: 1px solid rgba(180, 83, 9, 0.22);
  border-radius: var(--radius-lg);
  margin-top: 0;
}

/* 响应式：窄屏收紧间距 */
@media (max-width: 1024px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 640px) {
  .kpi-grid {
    grid-template-columns: 1fr;
  }
}

/* ── 恐慌贪婪指数行 ── */
.vix-row {
  display: grid;
  grid-template-columns: 280px 1fr 1.2fr;
  gap: var(--space-6);
  align-items: stretch;
}

.vix-subgrid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
  margin-top: var(--space-2);
}
.vix-sub {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  min-width: 0;
}
.vix-sub__label {
  font-size: 11px;
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
  letter-spacing: 0.02em;
}
.vix-sub__val {
  font-family: var(--font-mono);
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.vix-sub__sep {
  margin: 0 4px;
  color: var(--color-text-tertiary);
  font-weight: var(--weight-regular);
}
.text-up   { color: var(--color-up);   font-weight: var(--weight-semibold); }
.text-down { color: var(--color-down); font-weight: var(--weight-semibold); }

.vix-trend-wrap {
  min-width: 0;
  padding: var(--space-2) 0 0;
  border-left: 1px solid var(--color-border);
  padding-left: var(--space-5);
  /* 不加 display:flex / align-items:center：
     Vue scoped CSS 会把父级 .vix-trend-wrap 的 data-v 透传到 <VixTrendChart />
     的根元素，使其也变成 flex item；toolbar 是 absolute 不占位，
     唯一在流的子元素 .vix-trend（width:100%）就会因 flex 收缩到 0，
     导致图表不可见、toolbar 漂浮在空区域里，看起来「点了没反应」。 */
}

@media (max-width: 1280px) {
  .vix-row {
    grid-template-columns: 240px 1fr;
  }
  .vix-trend-wrap {
    grid-column: 1 / -1;
    border-left: 0;
    border-top: 1px solid var(--color-border);
    padding-left: 0;
    padding-top: var(--space-3);
  }
}
@media (max-width: 768px) {
  .vix-row {
    grid-template-columns: 1fr;
  }
  .vix-trend-wrap {
    border-top: 1px solid var(--color-border);
    padding-left: 0;
    padding-top: var(--space-3);
  }
  .vix-subgrid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
