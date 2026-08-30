<template>
  <div class="vix-page">
    <PageHeader
      title="恐慌贪婪指数"
      subtitle="0=极度恐慌 100=极度贪婪 · 标签按滚动百分位划分"
      size="lg"
    >
      <template #meta>
        <span class="meta-item">
          <span class="meta-dot" :class="{ 'meta-dot--pulse': !recomputing }" />
          {{ vix ? `数据已更新 · ${vix.date}` : '暂无数据' }}
        </span>
        <span class="meta-divider" />
        <span class="meta-item">
          <el-tag v-if="aggregateRegime !== 'unknown'" :type="regimeTagType" size="small" effect="light">
            {{ regimeLabel(aggregateRegime) }}
          </el-tag>
        </span>
      </template>
      <template #actions>
        <el-select v-model="historyDays" size="default" style="width: 140px" @change="onDaysChange">
          <el-option
            v-for="opt in daysOptions"
            :key="opt.value"
            :value="opt.value"
            :label="opt.label"
          />
        </el-select>
        <el-button :icon="Refresh" @click="fetchLatest" :loading="loading">刷新</el-button>
        <el-button :icon="Histogram" @click="confirmBackfill" :loading="backfilling">
          回填 {{ backfillDays }} 天
        </el-button>
        <el-button type="primary" :icon="RefreshRight" @click="handleRecompute" :loading="recomputing">
          立即重算
        </el-button>
      </template>
    </PageHeader>

    <!-- 视图切换：聚合（单一指数）/ 大小盘拆分（五条轨道同屏） -->
    <div class="view-switch">
      <el-segmented
        v-model="viewMode"
        :options="[
          { label: '聚合', value: 'aggregate' },
          { label: '大小盘拆分', value: 'split' },
        ]"
        size="default"
      />
    </div>

    <!-- ── 聚合态：单一恐慌贪婪指数 ── -->
    <template v-if="viewMode === 'aggregate'">
      <ModernCard
        title="当前读数"
        description="恐慌贪婪指数 = v7 构造真实情绪分的贪婪方向口径（100 − 构造恐惧分）"
        variant="bordered"
      >
        <div class="hero">
          <VixGauge
            :value="vix?.fear_greed_v7 ?? null"
            :percentile="vix?.fg7_percentile ?? null"
            :regime="vix?.fg7_regime || 'unknown'"
          />
          <div class="hero-side">
            <div class="hero-regime" :class="`hero-regime--${vix?.fg7_regime || 'unknown'}`">
              {{ regimeLabel(vix?.fg7_regime) }}
            </div>
            <div class="hero-percent">
              近 252 日百分位
              <strong>{{ vix?.fg7_percentile != null ? vix.fg7_percentile.toFixed(0) + '%' : '-' }}</strong>
            </div>
            <div class="hero-legend">
              标签按滚动百分位划分：&lt;10% 极度恐慌 · 10-30% 恐慌 · 30-70% 中性 · 70-90% 贪婪 · &gt;90% 极度贪婪
            </div>
            <div v-if="vix && vix.fear_greed_v7 == null" class="hero-missing">
              最新交易日构造分缺失（外部数据不足或当日未重算）。页面如实显示缺口，不做插值；可点击「立即重算」。
            </div>
          </div>
        </div>
      </ModernCard>

      <ModernCard
        title="走势"
        :description="`近 ${historyDays} 天 · 量程恒定 0-100 · 断点如实留空`"
        variant="bordered"
      >
        <VixTrendChart :history="aggregateSeries" :label="'恐慌贪婪指数'" :height="300" />
      </ModernCard>
    </template>

    <!-- ── 拆分态：五条单指数轨道同屏 ── -->
    <template v-else>
      <ModernCard
        title="大小盘拆分"
        description="同一构造在五条指数上的读数并列对比；每条轨道的 IV 锚与价格一一对应（50ETF/300ETF/500ETF/创业板ETF/科创50ETF 期权）"
        variant="bordered"
      >
        <div class="split-grid">
          <div v-for="t in trackCards" :key="t.key" class="split-card">
            <div class="split-card__name">{{ t.name }}</div>
            <div class="split-card__score" :class="regimeClass(t.regime)">
              {{ t.greed != null ? t.greed.toFixed(0) : '-' }}
            </div>
            <div class="split-card__regime" :class="regimeClass(t.regime)">
              {{ regimeLabel(t.regime) }}
            </div>
            <div class="split-card__pct">
              百分位 {{ t.percentile != null ? t.percentile.toFixed(0) + '%' : '-' }}
            </div>
            <div class="split-card__iv">{{ t.iv_label }}</div>
          </div>
        </div>
        <div v-if="!trackCards.some((t) => t.greed != null)" class="split-missing">
          拆分轨道暂无数据（未重算或外部数据不足）。页面如实显示缺口，不做插值。
        </div>
      </ModernCard>

      <ModernCard
        title="走势对比"
        :description="`近 ${historyDays} 天 · 每条轨道一条线 · 断点如实留空`"
        variant="bordered"
      >
        <VixTrendChart :history="history" :track-keys="TRACK_DEFS" :height="320" />
      </ModernCard>
    </template>

    <!-- 重算进展（进行中常驻，刷新页面后经 /api/tasks/active 恢复） -->
    <div v-if="recomputeTask" class="task-progress" :class="{ 'task-progress--done': !recomputing }">
      <el-progress
        :percentage="100"
        :indeterminate="recomputing"
        :duration="3"
        :show-text="false"
        :status="recomputeTask.status === 'failed' ? 'exception' : 'success'"
        :stroke-width="10"
      />
      <div class="task-progress__row">
        <span class="task-progress__title">重算任务</span>
        <span class="task-progress__step">
          {{ recomputeTask.current_step || recomputeTask.latest_milestone || (recomputing ? '排队中…' : '已结束') }}
        </span>
        <span class="task-progress__elapsed">已进行 {{ fmtElapsed(recomputeTask.elapsed_seconds) }}</span>
      </div>
    </div>

    <!-- 回填进展 -->
    <div v-if="backfillTask" class="task-progress" :class="{ 'task-progress--done': !backfilling }">
      <el-progress
        :percentage="backfillPct"
        :status="backfillTask.status === 'failed' ? 'exception' : 'success'"
        :stroke-width="10"
      />
      <div class="task-progress__row">
        <span class="task-progress__title">回填任务</span>
        <span class="task-progress__step">
          {{ backfillTask.done || 0 }} / {{ backfillTask.total || 0 }} 天
          <template v-if="backfillTask.current_step"> · {{ backfillTask.current_step }}</template>
        </span>
        <span class="task-progress__elapsed">已进行 {{ fmtElapsed(backfillTask.elapsed_seconds) }}</span>
      </div>
    </div>

    <EmptyHint
      v-if="!vix && !loading"
      title="还没有恐慌贪婪指数数据"
      description="点击右上角「立即重算」开始计算，或等待每日自动任务"
      carded
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, RefreshRight, Histogram } from '@element-plus/icons-vue'
import {
  getVix, getVixHistory, recomputeVix, backfillVix, getTask, getTasksActive,
} from '../api'

import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'
import VixGauge from '../components/VixGauge.vue'
import VixTrendChart from '../components/VixTrendChart.vue'

const vix = ref(null)
const history = ref([])
const historyDays = ref(365)
const loading = ref(false)
// 最近一次快照请求是否成功（401/网络失败时不做自动回填，避免登录跳转前误触发）
const latestFetchOk = ref(false)
const recomputing = ref(false)
const backfilling = ref(false)
const backfillDays = ref(90)
const dbDataDays = ref(0)
// 聚合（单一指数）/ 拆分（五条轨道同屏）
const viewMode = ref('aggregate')

// 进行中的任务（含刷新前提交的任务：加载时经 /api/tasks/active 恢复）
const recomputeTask = ref(null)
const backfillTask = ref(null)
let pollTimer = null
let backfillTimer = null

// 窗口单位是「交易日」（后端 get_vix_history 按行 LIMIT）。允许 15 个交易日
// 容差：节假日/周末导致的零头差额不应触发回填，避免每次加载都误判“数据不足”。
const BACKFILL_TOLERANCE = 15
// 最新快照距今超过该日历天数视为断档（2026-07~08 断档两个月即为反例）
const STALE_GAP_DAYS = 5

// 拆分轨道定义（IV 锚与价格一一对应：50/300/500/创业板/科创50）
const TRACK_DEFS = [
  { key: 'sh50', label: '上证50' },
  { key: 'hs300', label: '沪深300' },
  { key: 'zz500', label: '中证500' },
  { key: 'cyb', label: '创业板' },
  { key: 'kcb', label: '科创50' },
]

const REGIME_LABEL_MAP = {
  extreme_greed: '极度贪婪', greed: '贪婪', neutral: '中性',
  fear: '恐慌', extreme_fear: '极度恐慌', unknown: '暂无数据',
}
function regimeLabel(regime) {
  return REGIME_LABEL_MAP[regime] || '暂无数据'
}
function regimeClass(regime) {
  return `hero-regime--${regime || 'unknown'}`
}
const regimeTagType = computed(() => {
  const t = {
    extreme_greed: 'danger', greed: 'warning', neutral: 'info',
    fear: 'success', extreme_fear: 'success',
  }
  return t[vix.value?.fg7_regime] || 'info'
})
const aggregateRegime = computed(() => vix.value?.fg7_regime || 'unknown')

// 拆分卡片（按 大→小 排序）
const trackCards = computed(() => TRACK_DEFS.map((def) => {
  const t = vix.value?.size_tracks?.[def.key]
  return {
    key: def.key,
    name: def.label,
    greed: t?.greed ?? null,
    percentile: t?.percentile ?? null,
    regime: t?.regime || 'unknown',
    iv_label: t?.iv_label || '',
  }
}))

// 聚合态图表序列
const aggregateSeries = computed(() => (history.value || []).map((d) => ({
  date: d.date,
  score: d.fear_greed_v7,
  percentile: d.fg7_percentile,
  regime: d.fg7_regime,
})))

const daysOptions = computed(() => {
  const db = dbDataDays.value
  return [60, 120, 250, 365].map((d) => {
    const enough = db >= d - BACKFILL_TOLERANCE
    return {
      value: d,
      label: enough
        ? `近 ${d} 天`
        : `近 ${d} 天（DB 仅 ${db} 天，需回填）`,
    }
  })
})

async function onDaysChange(newDays) {
  if (dbDataDays.value < newDays - BACKFILL_TOLERANCE) {
    ElMessage.info(`DB 仅有 ${dbDataDays.value} 天数据，自动触发 ${newDays} 天回填`)
    backfillDays.value = newDays
    await handleBackfill()
  }
  await fetchHistory()
}

function fmtElapsed(seconds) {
  if (seconds == null || seconds < 0) return '-'
  if (seconds < 60) return `${seconds} 秒`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s > 0 ? `${m} 分 ${s} 秒` : `${m} 分钟`
}

const backfillPct = computed(() => {
  const t = backfillTask.value
  if (!t) return 0
  if (t.total > 0) return Math.min(100, Math.round((t.done || 0) / t.total * 100))
  return t.status && t.status !== 'running' ? 100 : 0
})

async function fetchLatest() {
  loading.value = true
  try {
    const { data } = await getVix()
    vix.value = data
    latestFetchOk.value = true
  } catch {
    vix.value = null
    latestFetchOk.value = false
  } finally {
    loading.value = false
  }
}

async function fetchHistory() {
  try {
    const { data } = await getVixHistory(historyDays.value)
    const arr = data?.data || []
    history.value = arr
    if (typeof data?.db_total_days === 'number') {
      dbDataDays.value = data.db_total_days
    } else {
      dbDataDays.value = arr.length
    }
  } catch {
    history.value = []
  }
}

// ── 重算任务：提交 / 409 接管 / 刷新后恢复 ──

function applyTaskSnapshot(target, task) {
  // latest_milestone 是任务日志行对象，展示层只取 message
  const milestone = task.latest_milestone
  target.value = {
    id: task.id,
    status: task.status,
    current_step: task.current_step,
    latest_milestone: typeof milestone === "string"
      ? milestone
      : (milestone?.message || null),
    elapsed_seconds: task.elapsed_seconds,
    total: task.total,
    done: task.done,
  }
}

function startRecomputePoll(taskId) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const { data: task } = await getTask(taskId)
      applyTaskSnapshot(recomputeTask, { id: taskId, ...task })
      // TaskRunner 终态是 success/failed/cancelled（不是 completed）
      if (['success', 'failed', 'cancelled'].includes(task?.status)) {
        clearInterval(pollTimer)
        pollTimer = null
        recomputing.value = false
        if (task?.status === 'success') ElMessage.success('重算完成')
        else ElMessage.error('重算未完成: ' + (task?.error_message || task?.status))
        setTimeout(() => { if (!recomputing.value) recomputeTask.value = null }, 5000)
        await Promise.all([fetchLatest(), fetchHistory()])
      }
    } catch {
      clearInterval(pollTimer)
      pollTimer = null
      recomputing.value = false
    }
  }, 2000)
}

function adoptRecomputeTask(task) {
  if (!task?.id) return
  applyTaskSnapshot(recomputeTask, task)
  recomputing.value = true
  startRecomputePoll(task.id)
}

async function handleRecompute() {
  if (recomputing.value) return
  try {
    const { data } = await recomputeVix()
    ElMessage.success('重算已提交，进展见下方任务面板')
    adoptRecomputeTask({ id: data?.task_id, status: 'running' })
  } catch (e) {
    if (e.response?.status === 409 && e.response?.data?.task_id) {
      // 已有同 kind 任务在跑：接管它而不是报错了事
      ElMessage.info('已有重算任务在进行中，已接入其进度')
      adoptRecomputeTask({ id: e.response.data.task_id, status: 'running' })
    } else {
      ElMessage.error('重算提交失败: ' + (e.response?.data?.error || e.message))
    }
  }
}

// ── 回填任务：提交 / 409 接管 / 刷新后恢复 ──

function startBackfillPoll(taskId) {
  if (backfillTimer) clearInterval(backfillTimer)
  backfillTimer = setInterval(async () => {
    try {
      const { data: task } = await getTask(taskId)
      applyTaskSnapshot(backfillTask, { id: taskId, ...task })
      if (['success', 'failed', 'cancelled'].includes(task?.status)) {
        clearInterval(backfillTimer)
        backfillTimer = null
        backfilling.value = false
        if (task?.status === 'success') ElMessage.success('回填完成')
        else ElMessage.error('回填未完成: ' + (task?.error_message || task?.status))
        setTimeout(() => { if (!backfilling.value) backfillTask.value = null }, 5000)
        await Promise.all([fetchLatest(), fetchHistory()])
      }
    } catch {
      clearInterval(backfillTimer)
      backfillTimer = null
      backfilling.value = false
    }
  }, 1500)
}

function adoptBackfillTask(task) {
  if (!task?.id) return
  applyTaskSnapshot(backfillTask, task)
  backfilling.value = true
  startBackfillPoll(task.id)
}

async function confirmBackfill() {
  if (backfilling.value) return
  try {
    await ElMessageBox.confirm(
      `将回填最近 ${backfillDays.value} 个交易日的数据，并覆盖这些日期已有的记录。` +
      `期间会持续抓取行情，耗时可能较长，请勿重复触发；进展显示在页面下方任务面板。`,
      '确认回填',
      {
        confirmButtonText: `确认回填 ${backfillDays.value} 天`,
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await handleBackfill()
}

async function handleBackfill() {
  if (backfilling.value) return
  backfilling.value = true
  applyTaskSnapshot(backfillTask, { id: null, status: 'running' })
  try {
    const { data } = await backfillVix(backfillDays.value, false)
    ElMessage.success(`回填任务已提交（${backfillDays.value} 天，覆盖旧值）`)
    if (!data?.task_id) {
      backfilling.value = false
      backfillTask.value = null
      return
    }
    adoptBackfillTask({ id: data.task_id, status: 'running' })
  } catch (e) {
    if (e.response?.status === 409 && e.response?.data?.task_id) {
      ElMessage.info('已有回填任务在进行中，已接入其进度')
      adoptBackfillTask({ id: e.response.data.task_id, status: 'running' })
    } else {
      ElMessage.error('回填提交失败: ' + (e.response?.data?.error || e.message))
    }
    backfilling.value = false
    backfillTask.value = null
  }
}

// 页面加载时恢复进行中的任务（刷新/重开页面不再丢失进展）
async function adoptActiveTasks() {
  try {
    const { data } = await getTasksActive()
    const arr = Array.isArray(data) ? data : []
    const rec = arr.find((t) => t.kind === 'vix_recompute')
    const bf = arr.find((t) => t.kind === 'vix_backfill')
    if (rec) {
      adoptRecomputeTask(rec)
      ElMessage.info('检测到正在进行的重算任务，已接入进度')
    }
    if (bf) {
      adoptBackfillTask(bf)
      ElMessage.info('检测到正在进行的回填任务，已接入进度')
    }
  } catch {
    // 查询失败不阻塞页面
  }
}

function calendarGapDays(dateStr) {
  if (!dateStr) return Infinity
  const latest = new Date(dateStr + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((today - latest) / 86400000)
}

onMounted(async () => {
  // 先接管进行中任务，再判断缺口，避免与已在跑的任务重复触发
  await adoptActiveTasks()
  await fetchLatest()
  await fetchHistory()

  if (recomputing.value || backfilling.value) return
  // 快照请求本身失败（未登录/网络问题）时不触发自动回填，等用户登录后正常加载
  if (!latestFetchOk.value) return
  const gap = vix.value?.date ? calendarGapDays(vix.value.date) : Infinity
  if (gap > STALE_GAP_DAYS) {
    // 数据断档：按缺口自动回填（skip_existing 只补缺失日期，不覆盖已有）
    const days = Math.min(90, Math.max(5, Math.ceil(gap * 5 / 7) + 2))
    ElMessage.info(`最新数据为 ${vix.value?.date || '无'}，自动回填约 ${days} 个交易日缺口`)
    backfillDays.value = days
    await handleAutoBackfill()
  } else if (dbDataDays.value < historyDays.value - BACKFILL_TOLERANCE) {
    ElMessage.info(`DB 仅有 ${dbDataDays.value} 天数据，自动触发 ${historyDays.value} 天回填`)
    backfillDays.value = historyDays.value
    await handleAutoBackfill()
  }
  await fetchHistory()
})

// 自动回填走 skip_existing=true（只补缺失，不覆盖），无需确认框
async function handleAutoBackfill() {
  if (backfilling.value) return
  backfilling.value = true
  applyTaskSnapshot(backfillTask, { id: null, status: 'running' })
  try {
    const { data } = await backfillVix(backfillDays.value, true)
    if (!data?.task_id) {
      backfilling.value = false
      backfillTask.value = null
      return
    }
    adoptBackfillTask({ id: data.task_id, status: 'running' })
  } catch (e) {
    if (e.response?.status === 409 && e.response?.data?.task_id) {
      ElMessage.info('已有回填任务在进行中，已接入其进度')
      adoptBackfillTask({ id: e.response.data.task_id, status: 'running' })
    } else {
      ElMessage.error('自动回填提交失败: ' + (e.response?.data?.error || e.message))
    }
    backfilling.value = false
    backfillTask.value = null
  }
}

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (backfillTimer) clearInterval(backfillTimer)
})
</script>

<style scoped>
.vix-page {
  position: relative;
  min-height: calc(100vh - var(--space-12));
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
}
.meta-divider {
  width: 1px; height: 12px;
  background: var(--color-border-strong);
  display: inline-block;
}
.meta-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  display: inline-block;
  position: relative;
}
.meta-dot--pulse::after {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  border-radius: 50%;
  background: var(--color-success);
  animation: pulse-ring 1.8s var(--ease) infinite;
  z-index: -1;
}
@keyframes pulse-ring {
  0%   { transform: scale(1);   opacity: 0.6; }
  100% { transform: scale(2.8); opacity: 0;   }
}

.vix-page > .modern-card,
.vix-page > .task-progress {
  margin-bottom: var(--space-6);
}
.vix-page > .modern-card:last-of-type {
  margin-bottom: 0;
}

/* ── 视图切换 ── */
.view-switch {
  margin-bottom: var(--space-6);
}

/* ── 聚合态 hero ── */
.hero {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  flex-wrap: wrap;
}
.hero-side {
  flex: 1;
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.hero-regime--extreme_fear { color: #047857; }
.hero-regime--fear         { color: #059669; }
.hero-regime--neutral      { color: #b45309; }
.hero-regime--greed        { color: #ea580c; }
.hero-regime--extreme_greed{ color: #dc2626; }
.hero-regime--unknown      { color: var(--color-text-tertiary); }
.hero-regime {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
}
.hero-percent {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-weight: var(--weight-medium);
}
.hero-percent strong {
  color: var(--color-text-primary);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
  margin-left: 4px;
}
.hero-legend {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  line-height: 1.7;
}
.hero-missing {
  margin-top: var(--space-1);
  padding: 8px 12px;
  border-radius: var(--radius-lg);
  background: var(--color-warning-soft, rgba(245, 158, 11, 0.08));
  border: 1px solid rgba(180, 83, 9, 0.22);
  font-size: var(--text-xs);
  color: #b45309;
  line-height: 1.6;
}

/* ── 拆分态：五张轨道卡 ── */
.split-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-3);
}
.split-card {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-muted);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  text-align: center;
}
.split-card__name {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
}
.split-card__score {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.split-card__regime {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
}
.split-card__pct {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
}
.split-card__iv {
  margin-top: 4px;
  font-size: 0.68rem;
  color: var(--color-text-tertiary);
  line-height: 1.4;
}
.split-missing {
  margin-top: var(--space-4);
  padding: 8px 12px;
  border-radius: var(--radius-lg);
  background: var(--color-warning-soft, rgba(245, 158, 11, 0.08));
  border: 1px solid rgba(180, 83, 9, 0.22);
  font-size: var(--text-xs);
  color: #b45309;
  line-height: 1.6;
}

/* ── 任务进展面板（重算/回填共用）── */
.task-progress {
  padding: 14px 18px;
  border-radius: var(--radius-lg);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.task-progress--done {
  opacity: 0.75;
}
.task-progress__row {
  display: flex;
  align-items: baseline;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.task-progress__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
}
.task-progress__step {
  flex: 1;
  min-width: 120px;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}
.task-progress__elapsed {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 960px) {
  .split-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 640px) {
  .split-grid { grid-template-columns: repeat(2, 1fr); }
  .hero { gap: var(--space-4); }
}
</style>
