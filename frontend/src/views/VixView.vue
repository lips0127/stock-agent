<template>
  <div class="vix-page">
    <div class="vix-page__ambient" aria-hidden="true">
      <GradientBlob position="tr" size="md" :intensity="0.55" c1="#eef2ff" c3="rgba(199, 210, 254, 0.5)" />
      <GradientBlob position="bl" size="sm" :intensity="0.4" c1="#fef2f2" c3="rgba(252, 165, 165, 0.35)" />
    </div>

    <PageHeader
      title="VIX 恐慌指数"
      subtitle="5 ETF 代表性加权合成 VIX + 宽基/成长拆分 + Z-Score 动态中心 + PCR + 现货位置"
      size="lg"
    >
      <template #icon>
        <span class="welcome-glyph">🌡️</span>
      </template>
      <template #meta>
        <span class="meta-item">
          <span class="meta-dot" :class="{ 'meta-dot--pulse': !recomputing }" />
          {{ vix ? `数据已更新 · ${vix.date}` : '暂无数据' }}
        </span>
        <span class="meta-divider" />
        <span class="meta-item">
          <el-tag v-if="vix" :type="regimeTagType" size="small" effect="light">
            {{ regimeLabel }}
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
        <el-button type="primary" :icon="RefreshRight" @click="handleRecompute" :loading="recomputing" round>
          立即重算
        </el-button>
      </template>
    </PageHeader>

    <!-- v5 主指标：合成 VIX / 综合位置 / 滚动百分位 / 恐惧贪婪 / 涨跌停比 -->
    <section class="kpi-grid">
      <StatCard
        label="合成 VIX"
        :value="vix && vix.vix != null ? vix.vix.toFixed(2) : '—'"
        icon="📈"
        :tone="vixTone"
        :hint="vixHint"
      />
      <StatCard
        label="综合位置"
        :value="compositeDisplay"
        icon="🎯"
        :tone="compositeTone"
        :hint="compositeHint"
      />
      <StatCard
        label="滚动百分位"
        :value="vix && vix.composite_percentile != null ? vix.composite_percentile.toFixed(0) + '%' : '—'"
        icon="📊"
        :tone="percentileTone"
        hint="近 252 日排位（v5 统一口径）"
      />
      <StatCard
        label="恐惧贪婪"
        :value="vix && vix.fear_greed != null ? vix.fear_greed.toFixed(0) : '—'"
        icon="😨"
        :tone="fgTone"
        hint="0=极度恐惧 · 100=极度贪婪"
      />
      <StatCard
        label="涨跌停比"
        :value="vix ? `${vix.limit_up_count || 0} / ${vix.limit_down_count || 0}` : '—'"
        icon="⚖️"
        :tone="limitTone"
        hint="涨停 / 跌停"
      />
    </section>

    <!-- 数据质量提示 + 回填进度 -->
    <div v-if="vix?.data_quality" class="quality-banner" :class="{ 'quality-banner--warn': vix.data_quality.missing > 0 }">
      <span class="quality-banner__icon">{{ vix.data_quality.missing > 0 ? '⚠️' : '✅' }}</span>
      <span class="quality-banner__text">
        数据完整度 <strong>{{ vix.data_quality.real }} / {{ vix.data_quality.total }}</strong>
        <span class="quality-banner__detail">
          缺失分量：<el-tag
            v-for="k in missingSignals"
            :key="k"
            type="warning"
            size="small"
            effect="light"
            style="margin-left: 4px"
          >{{ missingLabel(k) }}</el-tag>
        </span>
      </span>
      <el-tag v-if="vix.vix_source && vix.vix_source !== 'multi_etf'" type="warning" size="small" effect="light">
        VIX 主体回退：{{ vixSourceLabel }}
      </el-tag>
    </div>

    <div v-if="backfillProgress" class="backfill-progress">
      <el-progress
        :percentage="backfillProgress.pct"
        :status="backfillProgress.running ? '' : 'success'"
        :stroke-width="10"
      />
      <span class="backfill-progress__text">
        回填进度：{{ backfillProgress.done }} / {{ backfillProgress.total }}
        <span v-if="backfillProgress.skipped" class="text-muted">（跳过 {{ backfillProgress.skipped }}）</span>
        <span v-if="backfillProgress.failed" class="text-warn">（失败 {{ backfillProgress.failed }}）</span>
      </span>
    </div>

    <!-- 主趋势图 -->
    <ModernCard
      title="VIX + 恐惧贪婪 + 综合位置 + 百分位 趋势"
      :description="`近 ${historyDays} 天 · 绝对值看阈值，敏感视图看离散度`"
      variant="bordered"
    >
      <VixTrendChart :history="history" :height="320" />
    </ModernCard>

    <!-- v5 多 ETF 隐含波动率 -->
    <ModernCard
      title="多 ETF 隐含波动率"
      :description="`5 个 ETF 期权 QVIX 代表性加权 (50/300/500/创业板/科创 = 20/30/20/15/15%) · 当前 ${vix?.vix_etf_count ?? 0} 个有效`"
      variant="bordered"
    >
      <div class="etf-iv-grid">
        <div v-for="etf in etfIvList" :key="etf.label" class="etf-iv-item">
          <span class="etf-iv-label">{{ etf.label }}</span>
          <div class="etf-iv-bar-wrap">
            <div class="etf-iv-bar" :style="{ width: etf.pct + '%', background: etf.color }" />
          </div>
          <span class="etf-iv-value">{{ etf.value != null ? etf.value.toFixed(2) : '—' }}</span>
        </div>
      </div>
    </ModernCard>

    <!-- v2 市场位置信号（v5 连续化） -->
    <ModernCard
      title="市场位置信号"
      :description="`基于上证综指 ma60 偏离度 + 5/20 日动量 + 20 日新高比例`"
      variant="bordered"
    >
      <div class="spot-grid">
        <div class="spot-metric" :class="`spot-metric--${devTone}`">
          <div class="spot-metric__label">ma60 偏离度</div>
          <div class="spot-metric__value">
            {{ spotDevDisplay }}<span class="spot-metric__unit">%</span>
          </div>
          <div class="spot-metric__hint">当前位置 vs 60 日均线</div>
        </div>
        <div class="spot-metric" :class="`spot-metric--${mom5Tone}`">
          <div class="spot-metric__label">5 日动量</div>
          <div class="spot-metric__value">
            {{ spotMom5Display }}<span class="spot-metric__unit">%</span>
          </div>
          <div class="spot-metric__hint">短期趋势</div>
        </div>
        <div class="spot-metric" :class="`spot-metric--${mom20Tone}`">
          <div class="spot-metric__label">20 日动量</div>
          <div class="spot-metric__value">
            {{ spotMom20Display }}<span class="spot-metric__unit">%</span>
          </div>
          <div class="spot-metric__hint">中期趋势</div>
        </div>
        <div class="spot-metric" :class="`spot-metric--${hi20Tone}`">
          <div class="spot-metric__label">20 日新高比例</div>
          <div class="spot-metric__value">
            {{ spotNewHighDisplay }}<span class="spot-metric__unit">×</span>
          </div>
          <div class="spot-metric__hint">趋势强度 0-1</div>
        </div>
      </div>
      <div class="spot-verdict" :class="`spot-verdict--${verdictTone}`">
        <div class="spot-verdict__label">{{ verdictLabel }}</div>
        <div class="spot-verdict__text">{{ verdictText }}</div>
      </div>
    </ModernCard>

    <!-- v5 分项明细：5 格（删除北向 + PCR 真实数据） -->
    <div class="subgrid">
      <ModernCard title="合成 VIX" description="5 ETF QVIX 代表性加权">
        <div class="big-num">{{ fmt(vix?.vix, 2) }}</div>
        <div class="big-num__sub">
          Z={{ vix?.vix_zscore != null ? vix.vix_zscore.toFixed(2) : '—' }}
          · {{ vix?.vix_etf_count ?? 0 }} ETF
        </div>
        <div class="big-num__sub" v-if="vix?.vix_broad != null || vix?.vix_growth != null">
          宽基 <strong>{{ fmt(vix?.vix_broad, 1) }}</strong>
          · 成长 <strong>{{ fmt(vix?.vix_growth, 1) }}</strong>
          <span v-if="vix?.vix_growth_premium != null">
            · 溢价 <strong :class="vix.vix_growth_premium > 0 ? 'text-down' : 'text-up'">{{ fmtSpot(vix.vix_growth_premium, 1) }}</strong>
          </span>
        </div>
        <div class="big-num__sub" v-if="vix?.vix_change_pct != null || vix?.vix_swing_pct != null">
          日变化 <strong :class="vix?.vix_change_pct > 0 ? 'text-down' : 'text-up'">{{ fmtSpot(vix?.vix_change_pct, 1, '%') }}</strong>
          · 冲击 {{ vix?.vix_swing_pct != null ? vix.vix_swing_pct.toFixed(1) + '%' : '—' }}
        </div>
      </ModernCard>
      <ModernCard title="已实现波动率" description="Garman-Klass 估计">
        <div class="big-num-row">
          <div>
            <div class="big-num-mini">{{ fmt(vix?.rv_hs300, 2) }}</div>
            <div class="big-num-mini-label">沪深300</div>
          </div>
          <div>
            <div class="big-num-mini">{{ fmt(vix?.rv_zz1000, 2) }}</div>
            <div class="big-num-mini-label">中证1000</div>
          </div>
        </div>
        <div class="big-num__sub">% 年化</div>
      </ModernCard>
      <ModernCard title="PCR (Put/Call)" description="上交所 50ETF 期权">
        <div class="big-num-row">
          <div>
            <div class="big-num-mini">{{ fmt(vix?.pcr_volume, 2) }}</div>
            <div class="big-num-mini-label">成交量</div>
          </div>
          <div>
            <div class="big-num-mini">{{ fmt(vix?.pcr_oi, 2) }}</div>
            <div class="big-num-mini-label">持仓量</div>
          </div>
        </div>
        <div class="big-num__sub">
          call {{ vix?.pcr_call_volume ?? 0 }} / put {{ vix?.pcr_put_volume ?? 0 }}
        </div>
      </ModernCard>
      <ModernCard title="融资余额" description="上交所 + 深交所">
        <div class="big-num">
          {{ vix?.margin_balance != null ? (vix.margin_balance / 10000).toFixed(2) : '—' }}
        </div>
        <div class="big-num__sub">万亿元</div>
      </ModernCard>
      <ModernCard title="涨跌停" description="全市场">
        <div class="big-num-row">
          <div>
            <div class="big-num-mini text-up">{{ vix?.limit_up_count ?? 0 }}</div>
            <div class="big-num-mini-label">涨停</div>
          </div>
          <div>
            <div class="big-num-mini text-down">{{ vix?.limit_down_count ?? 0 }}</div>
            <div class="big-num-mini-label">跌停</div>
          </div>
        </div>
        <div class="big-num__sub">家</div>
      </ModernCard>
    </div>

    <!-- v5 阈值参考表：基于百分位 -->
    <ModernCard title="综合位置 阈值参考" description="regime 分级（基于近 252 日滚动百分位）">
      <el-table :data="thresholdRows" stripe>
        <el-table-column prop="range" label="百分位区间" width="120" />
        <el-table-column prop="label" label="情绪" width="140" />
        <el-table-column prop="color" label="信号" width="120">
          <template #default="{ row }">
            <el-tag :type="row.tagType" size="small" effect="light">{{ row.color }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="strategy" label="策略含义" />
      </el-table>
    </ModernCard>

    <EmptyHint
      v-if="!vix && !loading"
      title="还没有 VIX 数据"
      description="点击右上角「立即重算」开始计算，或等待每日 16:30 自动任务"
      carded
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, RefreshRight, Histogram } from '@element-plus/icons-vue'
import { getVix, getVixHistory, recomputeVix, backfillVix, getTask } from '../api'

import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import StatCard from '../components/ui/StatCard.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'
import GradientBlob from '../components/ui/GradientBlob.vue'
import VixTrendChart from '../components/VixTrendChart.vue'

const vix = ref(null)
const history = ref([])
const historyDays = ref(60)
const loading = ref(false)
const recomputing = ref(false)
const backfilling = ref(false)
const backfillDays = ref(90)
const backfillProgress = ref(null)
const dbDataDays = ref(0)   // 当前 DB 实际有多少天的数据
let pollTimer = null
let backfillTimer = null

// 根据 DB 实际数据范围动态生成下拉 label
const daysOptions = computed(() => {
  const db = dbDataDays.value
  return [30, 60, 90, 120, 250, 360].map((d) => {
    const enough = db >= d
    return {
      value: d,
      label: enough
        ? `近 ${d} 天`
        : `近 ${d} 天（DB 仅 ${db} 天，需回填）`,
    }
  })
})

async function onDaysChange(newDays) {
  // 如果选了超出 DB 范围的窗口，自动触发回填
  if (dbDataDays.value < newDays) {
    ElMessage.info(`DB 仅有 ${dbDataDays.value} 天数据，自动触发 ${newDays} 天回填`)
    backfillDays.value = newDays
    await handleBackfill()
  }
  await fetchHistory()
}

const SIGNAL_LABELS = {
  vix: 'VIX 主体', rv_chg: 'RV 变化', pcr: 'PCR',
  margin: '融资余额', limit: '涨跌停', spot: '现货位置',
}
const missingSignals = computed(() => {
  const sigs = vix.value?.data_quality?.signals || {}
  return Object.keys(sigs).filter((k) => !sigs[k])
})
function missingLabel(k) { return SIGNAL_LABELS[k] || k }

const vixSourceLabel = computed(() => {
  const m = {
    multi_etf: '5 ETF 等权',
    '50etf_only': '单 50ETF（其余 ETF 失败）',
    rv_fallback: '已实现波动率',
    none: '无数据',
  }
  return m[vix.value?.vix_source] || vix.value?.vix_source
})

const regimeLabel = computed(() => {
  if (!vix.value) return ''
  const map = {
    extreme_greed: '极度贪婪', greed: '贪婪', neutral: '中性',
    fear: '恐慌', extreme_fear: '极度恐慌', unknown: '暂无数据',
  }
  return map[vix.value.regime] || '中性'
})
const regimeTagType = computed(() => {
  if (!vix.value) return 'info'
  // v5: 贪婪=顶部风险 → danger/warning；恐慌=底部机会 → success
  const t = { extreme_greed: 'danger', greed: 'warning', neutral: 'info',
              fear: 'success', extreme_fear: 'success' }
  return t[vix.value.regime] || 'info'
})

const vixTone = computed(() => {
  if (!vix.value) return 'default'
  const z = vix.value.vix_zscore
  if (z == null) return 'default'
  if (z >= 2) return 'down'
  if (z >= 1) return 'down-soft'
  if (z <= -2) return 'up-soft'
  if (z <= -1) return 'up-soft'
  return 'default'
})

const vixHint = computed(() => {
  if (!vix.value) return '合成 VIX'
  const z = vix.value.vix_zscore
  const zText = z != null ? `Z=${z.toFixed(1)}` : ''
  const etfText = vix.value.vix_etf_count ? `· ${vix.value.vix_etf_count} ETF` : ''
  return [zText, etfText].filter(Boolean).join(' ') || '合成 VIX'
})

const fgTone = computed(() => {
  const v = vix.value?.fear_greed
  if (v == null) return 'default'
  if (v < 25) return 'down'
  if (v < 50) return 'down-soft'
  if (v < 75) return 'default'
  return 'up-soft'
})

const percentileTone = computed(() => {
  const p = vix.value?.composite_percentile
  if (p == null) return 'default'
  if (p < 10) return 'up'           // 极度恐慌 → 底部机会
  if (p < 30) return 'up-soft'
  if (p <= 70) return 'default'
  if (p <= 90) return 'down-soft'   // 贪婪 → 顶部风险
  return 'down'
})

const limitTone = computed(() => {
  if (!vix.value) return 'default'
  const u = vix.value.limit_up_count || 0
  const d = vix.value.limit_down_count || 0
  if (u >= 50) return 'up-soft'
  if (d >= 30) return 'down'
  return 'default'
})

// v5 阈值参考表（基于 composite 滚动百分位）
const thresholdRows = [
  { range: '0-10%',   label: '极度恐慌',  color: '底部机会', tagType: 'success', strategy: '市场极度悲观，往往是中长期底部区域；分批布局' },
  { range: '10-30%',  label: '恐慌',     color: '偏悲观',  tagType: 'success', strategy: '市场情绪偏弱，关注是否进入超跌区域' },
  { range: '30-70%',  label: '中性',     color: '均衡',    tagType: 'info',    strategy: '正常交易区间，按策略信号执行' },
  { range: '70-90%',  label: '贪婪',     color: '偏乐观',  tagType: 'warning', strategy: '市场情绪偏高，警惕冲顶风险，适度止盈' },
  { range: '90-100%', label: '极度贪婪', color: '顶部风险', tagType: 'danger',  strategy: '市场情绪极度乐观，谨慎追高；建议减仓 / 收紧止损' },
]

// ── v2 综合位置（VIX×40% + 现货×60%）────
const compositeDisplay = computed(() => {
  const c = vix.value?.composite
  if (c?.score == null) return '—'
  return c.score.toFixed(1)
})
const compositeTone = computed(() => {
  const s = vix.value?.composite?.score
  if (s == null) return 'default'
  if (s < 25) return 'up'             // 极度恐慌 → 机会
  if (s < 45) return 'up-soft'
  if (s < 55) return 'default'
  if (s < 75) return 'down-soft'      // 贪婪 → 风险
  return 'down'
})
const compositeHint = computed(() => {
  const c = vix.value?.composite
  if (!c) return 'VIX 类 + 现货位置 联合判读'
  const fg = c.vix_fg != null ? c.vix_fg.toFixed(0) : '—'
  const spot = c.spot_score != null ? c.spot_score.toFixed(0) : '—'
  return `VIX 类 ${fg} × 40% + 现货 ${spot} × 60%`
})

// ── v5 多 ETF IV 柱状条数据 ────
const etfIvList = computed(() => [
  { label: '50ETF',  value: vix.value?.iv_50etf,  pct: Math.min(100, ((vix.value?.iv_50etf  || 0) / 50) * 100), color: '#6366f1' },
  { label: '300ETF', value: vix.value?.iv_300etf, pct: Math.min(100, ((vix.value?.iv_300etf || 0) / 50) * 100), color: '#8b5cf6' },
  { label: '500ETF', value: vix.value?.iv_500etf, pct: Math.min(100, ((vix.value?.iv_500etf || 0) / 50) * 100), color: '#a78bfa' },
  { label: '创业板',  value: vix.value?.iv_cyb,    pct: Math.min(100, ((vix.value?.iv_cyb    || 0) / 50) * 100), color: '#c4b5fd' },
  { label: '科创50', value: vix.value?.iv_kcb,    pct: Math.min(100, ((vix.value?.iv_kcb    || 0) / 50) * 100), color: '#ddd6fe' },
])

// ── v2 现货位置 4 子信号 + 文案 ────
function fmtSpot(v, digits = 2, suffix = '') {
  if (v == null || Number.isNaN(v)) return '—'
  return (v >= 0 ? '+' : '') + Number(v).toFixed(digits) + suffix
}
const spotDevDisplay = computed(() => fmtSpot(vix.value?.spot?.ma60_dev))
const spotMom5Display = computed(() => fmtSpot(vix.value?.spot?.mom_5d))
const spotMom20Display = computed(() => fmtSpot(vix.value?.spot?.mom_20d))
const spotNewHighDisplay = computed(() => {
  const v = vix.value?.spot?.new_high_ratio
  if (v == null) return '—'
  return v.toFixed(2)
})

function toneForDev(dev) {
  if (dev == null) return 'muted'
  if (dev <= -3) return 'extreme-down'
  if (dev <= -1.5) return 'down'
  if (dev >= 6) return 'extreme-up'
  if (dev >= 3) return 'up'
  return 'neutral'
}
function toneForMom(mom, low = -3, high = 6) {
  if (mom == null) return 'muted'
  if (mom <= low) return 'extreme-down'
  if (mom <= -1.5) return 'down'
  if (mom >= high) return 'extreme-up'
  if (mom >= 3) return 'up'
  return 'neutral'
}
const devTone = computed(() => toneForDev(vix.value?.spot?.ma60_dev))
const mom5Tone = computed(() => {
  const v = vix.value?.spot?.mom_5d
  if (v == null) return 'muted'
  if (v <= -5) return 'extreme-down'
  if (v <= -1.5) return 'down'
  if (v >= 5) return 'extreme-up'
  if (v >= 2) return 'up'
  return 'neutral'
})
const mom20Tone = computed(() => toneForMom(vix.value?.spot?.mom_20d, -3, 6))
const hi20Tone = computed(() => {
  const v = vix.value?.spot?.new_high_ratio
  if (v == null) return 'muted'
  if (v >= 0.55) return 'extreme-up'
  if (v >= 0.45) return 'up'
  if (v <= 0.15) return 'extreme-down'
  if (v <= 0.25) return 'down'
  return 'neutral'
})

const VERDICT = {
  extreme_fear: { tone: 'extreme-down', label: '极度恐慌 · 强烈买入信号', text: '现货超跌 + 期权 IV 飙升，是中长期分批布局的时机。' },
  fear:         { tone: 'down',         label: '恐慌区间 · 谨慎观察',     text: '期权市场转悲观，关注是否进入超跌区域。' },
  neutral:      { tone: 'neutral',      label: '中性震荡',                 text: '无明确方向，按策略信号执行。' },
  greed:        { tone: 'up',           label: '贪婪区间 · 警惕风险',     text: '市场偏热，警惕冲顶风险，适度止盈。' },
  extreme_greed:{ tone: 'extreme-up',   label: '极度贪婪 · 顶部风险',     text: '现货已显著偏离均线 + 期权 IV 上升，高位风险确认，建议减仓。' },
  unknown:      { tone: 'muted',        label: '数据收集中',               text: '现货数据不足，等待 ma60 窗口形成。' },
}
const verdictLabel = computed(() => VERDICT[vix.value?.regime || 'unknown']?.label || VERDICT.unknown.label)
const verdictText = computed(() => VERDICT[vix.value?.regime || 'unknown']?.text || VERDICT.unknown.text)
const verdictTone = computed(() => VERDICT[vix.value?.regime || 'unknown']?.tone || 'muted')

function fmt(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—'
  return Number(v).toFixed(digits)
}

async function fetchLatest() {
  loading.value = true
  try {
    const { data } = await getVix()
    vix.value = data
  } catch {
    vix.value = null
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

async function handleRecompute() {
  if (recomputing.value) return
  recomputing.value = true
  try {
    const { data } = await recomputeVix()
    const taskId = data?.task_id
    ElMessage.success('VIX 重算已提交')
    if (!taskId) { recomputing.value = false; return }
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = setInterval(async () => {
      try {
        const { data: task } = await getTask(taskId)
        if (['completed', 'failed', 'cancelled'].includes(task?.status)) {
          clearInterval(pollTimer)
          pollTimer = null
          recomputing.value = false
          await Promise.all([fetchLatest(), fetchHistory()])
        }
      } catch {
        clearInterval(pollTimer)
        pollTimer = null
        recomputing.value = false
      }
    }, 2000)
  } catch (e) {
    ElMessage.error('VIX 重算失败: ' + (e.response?.data?.error || e.message))
    recomputing.value = false
  }
}

async function confirmBackfill() {
  if (backfilling.value) return
  try {
    await ElMessageBox.confirm(
      `将回填最近 ${backfillDays.value} 个交易日的 VIX 数据，并覆盖这些日期已有的记录。` +
      `期间会持续抓取行情，耗时约 ${Math.ceil(backfillDays.value * 2.5 / 60)} 分钟，请勿重复触发。`,
      '确认回填',
      {
        confirmButtonText: `确认回填 ${backfillDays.value} 天`,
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return  // 用户取消
  }
  await handleBackfill()
}

async function handleBackfill() {
  if (backfilling.value) return
  backfilling.value = true
  backfillProgress.value = { running: true, done: 0, total: 0, skipped: 0, failed: 0, pct: 0 }
  try {
    const { data } = await backfillVix(backfillDays.value, false)
    const taskId = data?.task_id
    ElMessage.success(`回填任务已提交（${backfillDays.value} 天，覆盖旧值）`)
    if (!taskId) { backfilling.value = false; backfillProgress.value = null; return }
    if (backfillTimer) clearInterval(backfillTimer)
    backfillTimer = setInterval(async () => {
      try {
        const { data: task } = await getTask(taskId)
        const total = task?.total || 0
        const done = task?.done || 0
        const payload = task?.result_payload || {}
        backfillProgress.value = {
          running: !['completed', 'failed', 'cancelled'].includes(task?.status),
          done,
          total,
          skipped: payload.skipped || 0,
          failed: payload.failed || 0,
          pct: task?.progress_pct ?? (total > 0 ? Math.round((done / total) * 100) : 0),
        }
        if (['completed', 'failed', 'cancelled'].includes(task?.status)) {
          clearInterval(backfillTimer)
          backfillTimer = null
          backfilling.value = false
          setTimeout(() => { backfillProgress.value = null }, 3000)
          await Promise.all([fetchLatest(), fetchHistory()])
        }
      } catch {
        clearInterval(backfillTimer)
        backfillTimer = null
        backfilling.value = false
      }
    }, 1500)
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.message || '已有回填任务在进行中')
    } else {
      ElMessage.error('回填提交失败: ' + (e.response?.data?.error || e.message))
    }
    backfilling.value = false
    backfillProgress.value = null
  }
}

onMounted(async () => {
  await fetchLatest()
  await fetchHistory()
  // 如果 DB 数据不足以支撑当前窗口（默认 60 天），自动回填到 90 天
  if (dbDataDays.value < historyDays.value) {
    ElMessage.info(`DB 仅有 ${dbDataDays.value} 天数据，自动触发 90 天回填`)
    backfillDays.value = 90
    await handleBackfill()
    await fetchHistory()
  }
})
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

.vix-page__ambient {
  position: fixed;
  top: 0; right: 0; bottom: 0; left: var(--layout-sidebar-width);
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}
.vix-page > :not(.vix-page__ambient) {
  position: relative;
  z-index: 1;
}

.welcome-glyph {
  font-size: 22px;
  line-height: 1;
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

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-5);
  margin-bottom: var(--space-6);
}
.vix-page > .modern-card,
.vix-page > .kpi-grid,
.vix-page > .subgrid,
.vix-page > .quality-banner,
.vix-page > .backfill-progress {
  margin-bottom: var(--space-6);
}
.vix-page > .modern-card:last-of-type {
  margin-bottom: 0;
}

.subgrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-4);
}

.big-num {
  font-size: 32px;
  font-weight: var(--weight-bold);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
  line-height: 1.1;
}
.big-num-row {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  margin-bottom: 6px;
}
.big-num-mini {
  font-size: 24px;
  font-weight: var(--weight-bold);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.big-num-mini-label {
  font-size: 11px;
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
  margin-top: 2px;
}
.text-up   { color: var(--color-up); }
.text-down { color: var(--color-down); }
.quality-banner {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px 16px;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(16,185,129,0.06), rgba(16,185,129,0.02));
  border: 1px solid rgba(16,185,129,0.18);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-weight: var(--weight-medium);
  flex-wrap: wrap;
}
.quality-banner--warn {
  background: linear-gradient(135deg, rgba(245,158,11,0.07), rgba(245,158,11,0.02));
  border-color: rgba(245,158,11,0.22);
}
.quality-banner__icon {
  font-size: 16px;
  line-height: 1;
}
.quality-banner__text strong {
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
  margin: 0 2px;
}
.quality-banner__detail {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-left: 8px;
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}

.backfill-progress {
  padding: 14px 18px;
  border-radius: var(--radius-lg);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.backfill-progress__text {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
}
.text-muted { color: var(--color-text-tertiary); margin-left: 6px; }
.text-warn  { color: var(--color-down); margin-left: 6px; font-weight: var(--weight-semibold); }

.big-num__sub {
  margin-top: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
}

/* ── v5 多 ETF 隐含波动率柱状条 ── */
.etf-iv-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.etf-iv-item {
  display: grid;
  grid-template-columns: 70px 1fr 60px;
  align-items: center;
  gap: 12px;
}
.etf-iv-label {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
}
.etf-iv-bar-wrap {
  height: 10px;
  background: var(--color-bg-muted);
  border-radius: var(--radius-full);
  overflow: hidden;
  position: relative;
}
.etf-iv-bar {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 600ms var(--ease);
  min-width: 4px;
}
.etf-iv-value {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

/* ── v2 市场位置信号卡片 ── */
.spot-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
.spot-metric {
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: background var(--duration-base) var(--ease);
}
.spot-metric__label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
  letter-spacing: 0.01em;
}
.spot-metric__value {
  font-size: 26px;
  font-weight: var(--weight-bold);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.spot-metric__unit {
  font-size: 14px;
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
  margin-left: 2px;
}
.spot-metric__hint {
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-top: 2px;
}
.spot-metric--muted .spot-metric__value { color: var(--color-text-tertiary); }
.spot-metric--neutral .spot-metric__value { color: var(--color-text-primary); }
.spot-metric--down { background: rgba(225, 29, 72, 0.04); border-color: rgba(225, 29, 72, 0.18); }
.spot-metric--down .spot-metric__value { color: var(--color-up); }
.spot-metric--extreme-down { background: rgba(225, 29, 72, 0.08); border-color: rgba(225, 29, 72, 0.28); }
.spot-metric--extreme-down .spot-metric__value { color: var(--color-up); }
.spot-metric--up { background: rgba(5, 150, 105, 0.04); border-color: rgba(5, 150, 105, 0.18); }
.spot-metric--up .spot-metric__value { color: var(--color-down); }
.spot-metric--extreme-up { background: rgba(5, 150, 105, 0.08); border-color: rgba(5, 150, 105, 0.28); }
.spot-metric--extreme-up .spot-metric__value { color: var(--color-down); }

.spot-verdict {
  padding: var(--space-4) var(--space-5);
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  border: 1px solid;
}
.spot-verdict__label {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.spot-verdict__text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: 1.5;
}
.spot-verdict--muted { background: var(--color-bg-muted); border-color: var(--color-border); }
.spot-verdict--muted .spot-verdict__label { color: var(--color-text-tertiary); }
.spot-verdict--neutral { background: var(--color-bg-muted); border-color: var(--color-border); }
.spot-verdict--neutral .spot-verdict__label { color: var(--color-text-primary); }
.spot-verdict--down { background: rgba(225, 29, 72, 0.06); border-color: rgba(225, 29, 72, 0.22); }
.spot-verdict--down .spot-verdict__label { color: var(--color-up); }
.spot-verdict--extreme-down { background: rgba(225, 29, 72, 0.10); border-color: rgba(225, 29, 72, 0.32); }
.spot-verdict--extreme-down .spot-verdict__label { color: var(--color-up); }
.spot-verdict--up { background: rgba(5, 150, 105, 0.06); border-color: rgba(5, 150, 105, 0.22); }
.spot-verdict--up .spot-verdict__label { color: var(--color-down); }
.spot-verdict--extreme-up { background: rgba(5, 150, 105, 0.10); border-color: rgba(5, 150, 105, 0.32); }
.spot-verdict--extreme-up .spot-verdict__label { color: var(--color-down); }

@media (max-width: 1024px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .subgrid  { grid-template-columns: repeat(2, 1fr); }
  .spot-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .kpi-grid { grid-template-columns: 1fr; }
  .subgrid  { grid-template-columns: 1fr; }
  .spot-grid { grid-template-columns: 1fr; }
}
</style>
