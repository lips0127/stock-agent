<template>
  <div class="vix-page">
    <div class="vix-page__ambient" aria-hidden="true">
      <GradientBlob position="tr" size="md" :intensity="0.55" c1="#eef2ff" c3="rgba(199, 210, 254, 0.5)" />
      <GradientBlob position="bl" size="sm" :intensity="0.4" c1="#fef2f2" c3="rgba(252, 165, 165, 0.35)" />
    </div>

    <PageHeader
      title="VIX 恐慌指数"
      subtitle="合成 VIX · 恐惧贪婪 · 市场情绪位置"
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

    <!-- 概览 KPI -->
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
        hint="近 252 日排位"
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

    <!-- 数据质量 -->
    <div v-if="vix?.data_quality" class="quality-banner" :class="{ 'quality-banner--warn': vix.data_quality.missing > 0 }">
      <span class="quality-banner__icon">{{ vix.data_quality.missing > 0 ? '⚠️' : '✅' }}</span>
      <span class="quality-banner__text">
        数据完整度 <strong>{{ vix.data_quality.real }} / {{ vix.data_quality.total }}</strong>
        <span class="quality-banner__detail" v-if="missingSignals.length">
          缺失：<el-tag
            v-for="k in missingSignals"
            :key="k"
            type="warning"
            size="small"
            effect="light"
            style="margin-left: 4px"
          >{{ missingLabel(k) }}</el-tag>
        </span>
      </span>
    </div>

    <div v-if="backfillProgress" class="backfill-progress">
      <el-progress
        :percentage="backfillProgress.pct"
        :status="backfillProgress.running ? '' : 'success'"
        :stroke-width="10"
      />
      <span class="backfill-progress__text">
        回填进度：{{ backfillProgress.done }} / {{ backfillProgress.total }}
      </span>
    </div>

    <!-- 趋势图 -->
    <ModernCard
      title="VIX · 恐惧贪婪 · 综合位置 趋势"
      :description="`近 ${historyDays} 天`"
      variant="bordered"
    >
      <VixTrendChart :history="history" :height="320" />
    </ModernCard>

    <!-- 市场情绪位置：v7.0 为主，v6.1 / VIX2 对照 -->
    <ModernCard
      title="市场情绪位置"
      description="恐惧贪婪 · 0=平静 100=极度恐惧"
      variant="bordered"
    >
      <div v-if="!vix" class="factor-loading">数据加载中…</div>
      <template v-else>
        <div class="emotion-grid">
          <div class="emotion-main" :class="`emotion-main--${v7Tone}`">
            <span class="emotion-main__label">v7.0 真实情绪</span>
            <strong class="emotion-main__value">{{ fmt(vix?.fear_truth_v7, 0) }}</strong>
            <span class="emotion-main__regime">{{ regimeLabel }}</span>
          </div>
          <div class="emotion-side">
            <div class="emotion-chip">
              <span>v6.1 恐惧贪婪</span>
              <strong>{{ fmt(vix?.fear_greed, 0) }}</strong>
            </div>
            <div class="emotion-chip">
              <span>VIX 2.0 ML</span>
              <strong>{{ vix2TruthPrediction ? fmt(vix2TruthPrediction.fear_truth_vix2, 0) : '—' }}</strong>
            </div>
          </div>
        </div>
        <div class="v7-components">
          <div class="v7-comp">
            <span>价格回撤</span><strong>{{ fmt(vix?.v7_components?.drawdown, 0) }}</strong>
          </div>
          <div class="v7-comp">
            <span>跌停广度</span><strong>{{ vix?.v7_components?.breadth == null ? '缺' : fmt(vix?.v7_components?.breadth, 0) }}</strong>
          </div>
          <div class="v7-comp">
            <span>IV 飙升</span><strong>{{ vix?.v7_components?.iv_surge == null ? '缺' : fmt(vix?.v7_components?.iv_surge, 0) }}</strong>
          </div>
          <div class="v7-comp">
            <span>IV 水平</span><strong>{{ vix?.v7_components?.iv_level == null ? '缺' : fmt(vix?.v7_components?.iv_level, 0) }}</strong>
          </div>
        </div>
      </template>
    </ModernCard>

    <!-- VIX 2.0（机器学习）：只展示读数与操作，研究细节折叠 -->
    <ModernCard
      title="VIX 2.0（机器学习）"
      description="ML 学习因子权重 · 仅作研究观察"
      variant="bordered"
    >
      <template #actions>
        <el-button size="small" :icon="MagicStick" @click="handleTrainVix2" :loading="vix2Training">
          重新训练
        </el-button>
        <el-button size="small" :icon="Histogram" @click="handleBackfillVix2" :loading="vix2Backfilling">
          回填
        </el-button>
      </template>

      <div class="vix2-slim">
        <div class="vix2-slim__main">
          <span>重定向版情绪读数</span>
          <strong>{{ vix2TruthPrediction ? fmt(vix2TruthPrediction.fear_truth_vix2, 0) : '—' }}</strong>
          <em>0=平静 · 100=极恐</em>
        </div>
        <div class="vix2-slim__stats" v-if="vix2Latest">
          <span>旧版 score {{ vix2Latest.score != null ? vix2Latest.score.toFixed(1) : '—' }}</span>
          <span>P(上) {{ vix2Latest.p_up != null ? (vix2Latest.p_up * 100).toFixed(0) + '%' : '—' }}</span>
          <span>百分位 {{ vix2Latest.percentile != null ? vix2Latest.percentile.toFixed(0) + '%' : '—' }}</span>
        </div>
      </div>

      <el-collapse v-if="vix2Model?.trained" class="vix2-research-details">
        <el-collapse-item title="模型与因子权重" name="details">
          <div class="vix2-modelinfo vix2-modelinfo--inline">
            <div><span>模型</span> {{ vix2Model.model_version }}</div>
            <div><span>OOS-AUC</span> {{ vix2Model.oos_auc != null ? vix2Model.oos_auc.toFixed(3) : '—' }}</div>
            <div><span>样本</span> {{ vix2Model.n_samples }}</div>
          </div>
          <div class="vix2-weights">
            <div v-for="w in vix2Weights" :key="w.name" class="vix2-weight-row">
              <span class="vix2-weight-name">{{ w.label }}</span>
              <div class="vix2-weight-track">
                <div
                  class="vix2-weight-bar"
                  :class="w.value >= 0 ? 'vix2-weight-bar--pos' : 'vix2-weight-bar--neg'"
                  :style="{ width: w.pct + '%', [w.value >= 0 ? 'left' : 'right']: '50%' }"
                />
                <div class="vix2-weight-axis" />
              </div>
              <span class="vix2-weight-val">{{ w.value >= 0 ? '+' : '' }}{{ w.value.toFixed(3) }}</span>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </ModernCard>

    <!-- 波动率风险预算：单行 -->
    <ModernCard
      v-if="volRisk && volRisk.status === 'ok'"
      title="波动率风险预算"
      description="未来 10/20 日实现波动率风险 · 仓位上限参考"
      variant="bordered"
    >
      <div class="volrisk-row">
        <div class="volrisk-cell" :class="`volrisk-cell--${volRiskLevel?.tone || 'info'}`">
          <span>风险等级</span><strong>{{ volRiskLevel?.label || '—' }}</strong>
        </div>
        <div class="volrisk-cell">
          <span>风险分数</span><strong>{{ volRiskScoreText }}</strong>
        </div>
        <div class="volrisk-cell">
          <span>权益仓位上限</span><strong>{{ volRiskEquityMaxText }}</strong>
        </div>
      </div>
    </ModernCard>

    <!-- 市场位置参考 -->
    <ModernCard
      title="市场位置参考"
      description="上证综指 ma60 偏离 + 动量 + 新高比例"
      variant="bordered"
    >
      <div class="spot-grid">
        <div class="spot-metric" :class="`spot-metric--${devTone}`">
          <div class="spot-metric__label">ma60 偏离</div>
          <div class="spot-metric__value">
            {{ spotDevDisplay }}<span class="spot-metric__unit">%</span>
          </div>
        </div>
        <div class="spot-metric" :class="`spot-metric--${mom5Tone}`">
          <div class="spot-metric__label">5 日动量</div>
          <div class="spot-metric__value">
            {{ spotMom5Display }}<span class="spot-metric__unit">%</span>
          </div>
        </div>
        <div class="spot-metric" :class="`spot-metric--${mom20Tone}`">
          <div class="spot-metric__label">20 日动量</div>
          <div class="spot-metric__value">
            {{ spotMom20Display }}<span class="spot-metric__unit">%</span>
          </div>
        </div>
        <div class="spot-metric" :class="`spot-metric--${hi20Tone}`">
          <div class="spot-metric__label">20 日新高比例</div>
          <div class="spot-metric__value">
            {{ spotNewHighDisplay }}<span class="spot-metric__unit">×</span>
          </div>
        </div>
      </div>
      <div class="spot-verdict" :class="`spot-verdict--${verdictTone}`">
        <div class="spot-verdict__label">{{ verdictLabel }}</div>
        <div class="spot-verdict__text">{{ verdictText }}</div>
      </div>
    </ModernCard>

    <!-- 分项明细 -->
    <div class="subgrid">
      <ModernCard title="多 ETF 隐含波动率" :description="`${vix?.vix_etf_count ?? 0} 个有效 · 代表性加权`">
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
      <ModernCard title="合成 VIX 明细" description="Z-Score · 宽基/成长拆分">
        <div class="big-num">{{ fmt(vix?.vix, 2) }}</div>
        <div class="big-num__sub">
          Z={{ fmt(vix?.vix_zscore, 2) }} · {{ vix?.vix_etf_count ?? 0 }} ETF
        </div>
        <div class="big-num__sub" v-if="vix?.vix_broad != null || vix?.vix_growth != null">
          宽基 <strong>{{ fmt(vix?.vix_broad, 1) }}</strong>
          · 成长 <strong>{{ fmt(vix?.vix_growth, 1) }}</strong>
        </div>
      </ModernCard>
      <ModernCard title="已实现波动率" description="Garman-Klass 年化">
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
      </ModernCard>
      <ModernCard title="PCR" description="50ETF 期权">
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
      </ModernCard>
      <ModernCard title="融资余额" description="沪深两市">
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
      </ModernCard>
    </div>

    <!-- 阈值参考 -->
    <ModernCard title="综合位置 阈值参考" description="基于近 252 日滚动百分位" variant="bordered">
      <el-table :data="thresholdRows" stripe>
        <el-table-column prop="range" label="百分位" width="110" />
        <el-table-column prop="label" label="情绪" width="120" />
        <el-table-column prop="color" label="位置" width="110">
          <template #default="{ row }">
            <el-tag :type="row.tagType" size="small" effect="light">{{ row.color }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="strategy" label="含义" />
      </el-table>
    </ModernCard>

    <!-- 历史事件研究（折叠） -->
    <el-collapse class="research-collapse">
      <el-collapse-item title="历史事件研究：恐慌/贪婪状态的未来收益统计" name="study">
        <div v-if="factorStudyLoading" class="factor-loading">正在计算…</div>
        <div v-else-if="!factorStudy || factorStudy.status !== 'ok'" class="factor-loading">
          暂无足够历史数据。
        </div>
        <template v-else>
          <div class="factor-summary-grid">
            <div class="factor-summary-card factor-summary-card--current">
              <span>当前状态</span>
              <strong>{{ factorCurrentBucket }}</strong>
              <p>综合位置百分位 {{ factorCurrentPct }}</p>
            </div>
            <div class="factor-summary-card">
              <span>历史最优候选</span>
              <strong>{{ factorBestRule }}</strong>
              <p>20 日均值 {{ factorBest20dAvg }}</p>
            </div>
            <div class="factor-summary-card" :class="productionRules.length ? 'factor-summary-card--pass' : 'factor-summary-card--blocked'">
              <span>可回测规则</span>
              <strong>{{ productionRules.length }}</strong>
              <p>{{ productionRules.length ? productionRules.join('、') : '暂无' }}</p>
            </div>
          </div>
          <el-table :data="factorBucketRows" stripe class="factor-table">
            <el-table-column prop="label" label="状态" width="110" />
            <el-table-column prop="range" label="百分位" width="100" />
            <el-table-column prop="n20" label="样本" width="80" />
            <el-table-column label="20日均值" width="100">
              <template #default="{ row }">
                <span :class="row.avg20 > 0 ? 'text-up' : 'text-down'">{{ row.avg20 != null ? `${row.avg20 > 0 ? '+' : ''}${row.avg20}%` : '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="20日胜率" width="90">
              <template #default="{ row }">{{ row.win20 != null ? `${row.win20}%` : '—' }}</template>
            </el-table-column>
            <el-table-column label="60日均值">
              <template #default="{ row }">
                <span :class="row.avg60 > 0 ? 'text-up' : 'text-down'">{{ row.avg60 != null ? `${row.avg60 > 0 ? '+' : ''}${row.avg60}%` : '—' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </el-collapse-item>
    </el-collapse>

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
import { Refresh, RefreshRight, Histogram, MagicStick } from '@element-plus/icons-vue'
import {
  getVix, getVixHistory, recomputeVix, backfillVix, getTask, getVixFactorStudy, getVixVolRisk,
  getVix2, getVix2Model, trainVix2, backfillVix2,
} from '../api'

import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import StatCard from '../components/ui/StatCard.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'
import GradientBlob from '../components/ui/GradientBlob.vue'
import VixTrendChart from '../components/VixTrendChart.vue'

const vix = ref(null)
const history = ref([])
const historyDays = ref(365)
const loading = ref(false)
const volRisk = ref(null)
const factorStudy = ref(null)
const factorStudyLoading = ref(false)
const recomputing = ref(false)
const backfilling = ref(false)
const backfillDays = ref(90)
const backfillProgress = ref(null)
const dbDataDays = ref(0)
let pollTimer = null
let backfillTimer = null

// ── VIX 2.0（机器学习）状态 ──
const vix2Latest = ref(null)
const vix2Model = ref(null)
const vix2TruthPrediction = ref(null)
const vix2Training = ref(false)
const vix2Backfilling = ref(false)
let vix2Timer = null

const VIX2_FEATURE_LABELS = {
  qvix_50: 'QVIX 水平', qvix_50_z: 'QVIX Z-Score', qvix_50_chg5: 'QVIX 5日变化',
  rv_hs300: '沪深300 RV', rv_qvix_spread: '方差风险溢价', ma60_dev: 'ma60 偏离',
  mom_20d: '20日动量', mom_60d: '60日动量', new_high_ratio: '20日新高比例',
  drawdown_252: '距顶回撤', dist_low_252: '距底涨幅',
}
const vix2Weights = computed(() => {
  const w = vix2Model.value?.weights
  if (!w) return []
  const entries = Object.entries(w)
  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v)), 1e-6)
  return entries
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .map(([name, value]) => ({
      name,
      label: VIX2_FEATURE_LABELS[name] || name,
      value,
      pct: (Math.abs(value) / maxAbs) * 50,
    }))
})

const factorCurrentBucket = computed(() => factorStudy.value?.current?.bucket_label || '暂无')
const factorCurrentPct = computed(() => {
  const v = factorStudy.value?.current?.composite_percentile
  return v == null ? '—' : `${v.toFixed(1)}%`
})
const factorBestRule = computed(() => factorStudy.value?.summary?.best_long_rule || '暂无')
const factorBest20dAvg = computed(() => {
  const v = factorStudy.value?.summary?.best_long_20d_avg
  return v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
})
const productionRules = computed(() => factorStudy.value?.summary?.production_ready_rules || [])
const factorBucketRows = computed(() => {
  const buckets = factorStudy.value?.buckets || []
  return buckets.map((b) => ({
    label: b.label,
    range: b.range,
    n20: b.metrics?.['20']?.n ?? 0,
    avg20: b.metrics?.['20']?.avg_ret,
    win20: b.metrics?.['20']?.win_rate,
    avg60: b.metrics?.['60']?.avg_ret,
  }))
})

const volRiskLatest = computed(() => volRisk.value?.latest || null)
const volRiskScoreText = computed(() => {
  const v = volRiskLatest.value?.score
  return v == null ? '—' : v.toFixed(0)
})
const volRiskLevel = computed(() => volRiskLatest.value?.risk_level || null)
const volRiskEquityMaxText = computed(() => {
  const v = volRiskLevel.value?.suggested_equity_max
  return v == null ? '—' : `${Math.round(v * 100)}%`
})

const v7Tone = computed(() => {
  const v = vix.value?.fear_truth_v7
  if (v == null) return 'info'
  if (v >= 70) return 'danger'
  if (v >= 45) return 'warning'
  if (v <= 15) return 'success'
  return 'info'
})

async function fetchVolRisk() {
  try {
    const { data } = await getVixVolRisk()
    volRisk.value = data
  } catch {
    volRisk.value = null
  }
}

async function fetchFactorStudy() {
  factorStudyLoading.value = true
  try {
    const { data } = await getVixFactorStudy(365)
    factorStudy.value = data
  } catch {
    factorStudy.value = null
  } finally {
    factorStudyLoading.value = false
  }
}

async function fetchVix2() {
  try {
    const [{ data: latest }, { data: model }] = await Promise.all([getVix2(), getVix2Model()])
    vix2Latest.value = latest?.latest || null
    vix2Model.value = model || { trained: false }
    vix2TruthPrediction.value = latest?.truth_prediction || null
  } catch {
    vix2Model.value = { trained: false }
  }
}

function pollVix2Task(taskId, flagRef) {
  if (vix2Timer) clearInterval(vix2Timer)
  vix2Timer = setInterval(async () => {
    try {
      const { data: task } = await getTask(taskId)
      if (['completed', 'failed', 'cancelled'].includes(task?.status)) {
        clearInterval(vix2Timer); vix2Timer = null
        flagRef.value = false
        if (task.status === 'completed') ElMessage.success('VIX 2.0 任务完成')
        else ElMessage.warning(`VIX 2.0 任务${task.status === 'failed' ? '失败' : '取消'}`)
        await fetchVix2()
      }
    } catch {
      clearInterval(vix2Timer); vix2Timer = null
      flagRef.value = false
    }
  }, 2500)
}

async function handleTrainVix2() {
  if (vix2Training.value) return
  vix2Training.value = true
  try {
    const { data } = await trainVix2()
    ElMessage.success('VIX 2.0 训练已提交')
    if (data?.task_id) pollVix2Task(data.task_id, vix2Training)
    else vix2Training.value = false
  } catch (e) {
    ElMessage.error('训练提交失败: ' + (e.response?.data?.error || e.message))
    vix2Training.value = false
  }
}

async function handleBackfillVix2() {
  if (vix2Backfilling.value) return
  vix2Backfilling.value = true
  try {
    const { data } = await backfillVix2(0, false)
    ElMessage.success('VIX 2.0 回填已提交')
    if (data?.task_id) pollVix2Task(data.task_id, vix2Backfilling)
    else vix2Backfilling.value = false
  } catch (e) {
    if (e.response?.status === 409) ElMessage.warning(e.response?.data?.error || '已有任务在进行中')
    else ElMessage.error('回填提交失败: ' + (e.response?.data?.error || e.message))
    vix2Backfilling.value = false
  }
}

// 窗口单位是「交易日」（后端 get_vix_history 按行 LIMIT）。允许 15 个交易日
// 容差：节假日/周末导致的零头差额不应触发回填，避免每次加载都误判“数据不足”。
const BACKFILL_TOLERANCE = 15

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

const SIGNAL_LABELS = {
  vix: 'VIX 主体', rv_chg: 'RV 变化', pcr: 'PCR',
  margin: '融资余额', limit: '涨跌停', spot: '现货位置',
}
const missingSignals = computed(() => {
  const sigs = vix.value?.data_quality?.signals || {}
  return Object.keys(sigs).filter((k) => !sigs[k])
})
function missingLabel(k) { return SIGNAL_LABELS[k] || k }

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
  if (p < 10) return 'up'
  if (p < 30) return 'up-soft'
  if (p <= 70) return 'default'
  if (p <= 90) return 'down-soft'
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
  { range: '0-10%',   label: '极度恐慌',  color: '低位压力', tagType: 'success', strategy: '市场极度悲观，可能处于中长期低位区域；仅作为风险位置参考' },
  { range: '10-30%',  label: '恐慌',     color: '偏悲观',  tagType: 'success', strategy: '市场情绪偏弱，关注是否进入超跌区域' },
  { range: '30-70%',  label: '中性',     color: '均衡',    tagType: 'info',    strategy: '正常交易区间，仓位由独立策略决定' },
  { range: '70-90%',  label: '贪婪',     color: '偏乐观',  tagType: 'warning', strategy: '市场情绪偏高，警惕冲顶风险，收紧风险预算' },
  { range: '90-100%', label: '极度贪婪', color: '高位风险', tagType: 'danger',  strategy: '市场情绪极度乐观，谨慎追高；适合作为降低风险暴露的提示' },
]

// ── 综合位置（VIX×40% + 现货×60%）────
const compositeDisplay = computed(() => {
  const c = vix.value?.composite
  if (c?.score == null) return '—'
  return c.score.toFixed(1)
})
const compositeTone = computed(() => {
  const s = vix.value?.composite?.score
  if (s == null) return 'default'
  if (s < 25) return 'up'
  if (s < 45) return 'up-soft'
  if (s < 55) return 'default'
  if (s < 75) return 'down-soft'
  return 'down'
})
const compositeHint = computed(() => {
  const c = vix.value?.composite
  if (!c) return 'VIX 类 + 现货位置 联合判读'
  const fg = c.vix_fg != null ? c.vix_fg.toFixed(0) : '—'
  const spot = c.spot_score != null ? c.spot_score.toFixed(0) : '—'
  return `VIX 类 ${fg} × 40% + 现货 ${spot} × 60%`
})

// ── 多 ETF IV 柱状条数据 ────
const etfIvList = computed(() => [
  { label: '50ETF',  value: vix.value?.iv_50etf,  pct: Math.min(100, ((vix.value?.iv_50etf  || 0) / 50) * 100), color: '#6366f1' },
  { label: '300ETF', value: vix.value?.iv_300etf, pct: Math.min(100, ((vix.value?.iv_300etf || 0) / 50) * 100), color: '#8b5cf6' },
  { label: '500ETF', value: vix.value?.iv_500etf, pct: Math.min(100, ((vix.value?.iv_500etf || 0) / 50) * 100), color: '#a78bfa' },
  { label: '创业板',  value: vix.value?.iv_cyb,    pct: Math.min(100, ((vix.value?.iv_cyb    || 0) / 50) * 100), color: '#c4b5fd' },
  { label: '科创50', value: vix.value?.iv_kcb,    pct: Math.min(100, ((vix.value?.iv_kcb    || 0) / 50) * 100), color: '#ddd6fe' },
])

// ── 现货位置 4 子信号 ────
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
  extreme_fear: { tone: 'extreme-down', label: '极度恐慌 · 低位压力', text: '现货超跌 + 期权 IV 飙升，市场处于高压力低位区域。' },
  fear:         { tone: 'down',         label: '恐慌区间 · 谨慎观察', text: '期权市场转悲观，关注是否进入超跌区域。' },
  neutral:      { tone: 'neutral',      label: '中性震荡', text: '无明确方向，仓位由独立策略决定。' },
  greed:        { tone: 'up',           label: '贪婪区间 · 警惕风险', text: '市场偏热，适合作为收紧风险预算的提示。' },
  extreme_greed:{ tone: 'extreme-up',   label: '极度贪婪 · 高位风险', text: '现货显著偏离均线 + IV 上升，高位波动风险抬升。' },
  unknown:      { tone: 'muted',        label: '数据收集中', text: '现货数据不足，等待 ma60 窗口形成。' },
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
          await Promise.all([fetchLatest(), fetchHistory(), fetchFactorStudy(), fetchVolRisk()])
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
    return
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
          await Promise.all([fetchLatest(), fetchHistory(), fetchFactorStudy(), fetchVolRisk()])
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
  await Promise.all([fetchHistory(), fetchFactorStudy(), fetchVolRisk()])
  fetchVix2()
  if (dbDataDays.value < historyDays.value - BACKFILL_TOLERANCE) {
    ElMessage.info(`DB 仅有 ${dbDataDays.value} 天数据，自动触发 ${historyDays.value} 天回填`)
    backfillDays.value = historyDays.value
    await handleBackfill()
    await fetchHistory()
  }
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (backfillTimer) clearInterval(backfillTimer)
  if (vix2Timer) clearInterval(vix2Timer)
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
.vix-page > .backfill-progress,
.vix-page > .research-collapse {
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

.big-num__sub {
  margin-top: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
}

/* ── 多 ETF 隐含波动率柱状条 ── */
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

/* ── 市场位置信号 ── */
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

/* ── 市场情绪位置（v7.0 为主）── */
.emotion-grid {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(220px, 1fr);
  gap: var(--space-4);
  margin-bottom: var(--space-4);
  align-items: stretch;
}
.emotion-main {
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  background: rgba(255, 255, 255, 0.74);
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  justify-content: center;
}
.emotion-main__label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-semibold);
}
.emotion-main__value {
  font-size: 2.6rem;
  font-weight: 700;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
  line-height: 1;
}
.emotion-main__regime {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-weight: var(--weight-medium);
}
.emotion-main--danger { background: linear-gradient(135deg, rgba(239, 68, 68, 0.12), rgba(255, 255, 255, 0.78)); border-color: rgba(239, 68, 68, 0.24); }
.emotion-main--warning { background: linear-gradient(135deg, rgba(245, 158, 11, 0.12), rgba(255, 255, 255, 0.78)); border-color: rgba(245, 158, 11, 0.24); }
.emotion-main--success { background: linear-gradient(135deg, rgba(5, 150, 105, 0.10), rgba(255, 255, 255, 0.78)); border-color: rgba(5, 150, 105, 0.22); }
.emotion-side {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  justify-content: center;
}
.emotion-chip {
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-muted);
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}
.emotion-chip span {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-medium);
}
.emotion-chip strong {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.v7-components {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
}
.v7-comp {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: rgba(255, 255, 255, 0.6);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.v7-comp span {
  font-size: 0.75rem;
  color: var(--color-text-tertiary);
}
.v7-comp strong {
  font-size: 1.25rem;
  font-weight: 600;
}

/* ── VIX 2.0 精简卡 ── */
.vix2-slim {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-5);
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  background: rgba(255, 255, 255, 0.72);
  box-shadow: var(--shadow-xs);
}
.vix2-slim__main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.vix2-slim__main span {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-semibold);
}
.vix2-slim__main strong {
  font-size: 2.2rem;
  font-weight: 700;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
  line-height: 1;
}
.vix2-slim__main em {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-style: normal;
}
.vix2-slim__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.vix2-slim__stats span {
  padding: 7px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
}
.vix2-research-details {
  border-top: 1px solid var(--color-border);
  margin-top: var(--space-3);
}
.vix2-modelinfo {
  font-size: 11px;
  color: var(--color-text-tertiary);
  line-height: 1.7;
}
.vix2-modelinfo--inline {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin-bottom: var(--space-4);
  text-align: left;
}
.vix2-modelinfo span {
  color: var(--color-text-secondary);
  font-weight: var(--weight-semibold);
}
.vix2-weight-row {
  display: grid;
  grid-template-columns: 110px 1fr 64px;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.vix2-weight-name {
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--color-text-secondary);
}
.vix2-weight-track {
  position: relative;
  height: 12px;
  background: var(--color-bg-muted);
  border-radius: var(--radius-sm);
}
.vix2-weight-axis {
  position: absolute;
  left: 50%; top: -2px; bottom: -2px;
  width: 1px;
  background: var(--color-border-strong);
}
.vix2-weight-bar {
  position: absolute;
  top: 0; bottom: 0;
  border-radius: var(--radius-sm);
  transition: width 500ms var(--ease);
}
.vix2-weight-bar--pos { background: var(--color-up); }
.vix2-weight-bar--neg { background: var(--color-down); }
.vix2-weight-val {
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  text-align: right;
}

/* ── 波动率风险预算 单行 ── */
.volrisk-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}
.volrisk-cell {
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-muted);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.volrisk-cell span {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-weight: var(--weight-semibold);
}
.volrisk-cell strong {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.volrisk-cell--danger { background: linear-gradient(135deg, rgba(239, 68, 68, 0.10), rgba(255, 255, 255, 0.78)); border-color: rgba(239, 68, 68, 0.24); }
.volrisk-cell--warning { background: linear-gradient(135deg, rgba(245, 158, 11, 0.10), rgba(255, 255, 255, 0.78)); border-color: rgba(245, 158, 11, 0.24); }
.volrisk-cell--success { background: linear-gradient(135deg, rgba(5, 150, 105, 0.08), rgba(255, 255, 255, 0.78)); border-color: rgba(5, 150, 105, 0.22); }

/* ── 历史事件研究 折叠 ── */
.research-collapse {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  background: var(--color-bg-card);
  padding: 0 var(--space-4);
}
.factor-loading {
  padding: var(--space-6);
  color: var(--color-text-tertiary);
  text-align: center;
}
.factor-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.factor-summary-card {
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  background: rgba(255, 255, 255, 0.72);
  box-shadow: var(--shadow-xs);
}
.factor-summary-card span {
  display: block;
  margin-bottom: 8px;
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
}
.factor-summary-card strong {
  display: block;
  margin-bottom: 8px;
  color: var(--color-text-primary);
  font-size: 24px;
  font-weight: var(--weight-bold);
  letter-spacing: -0.02em;
}
.factor-summary-card p {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
  line-height: 1.65;
}
.factor-summary-card--current {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.10), rgba(255, 255, 255, 0.78));
  border-color: rgba(99, 102, 241, 0.22);
}
.factor-summary-card--pass {
  background: rgba(5, 150, 105, 0.07);
  border-color: rgba(5, 150, 105, 0.22);
}
.factor-summary-card--blocked {
  background: rgba(245, 158, 11, 0.07);
  border-color: rgba(245, 158, 11, 0.22);
}
.factor-table { margin-top: var(--space-2); }

@media (max-width: 1024px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .subgrid  { grid-template-columns: repeat(2, 1fr); }
  .spot-grid { grid-template-columns: repeat(2, 1fr); }
  .emotion-grid { grid-template-columns: 1fr; }
  .volrisk-row { grid-template-columns: 1fr; }
  .factor-summary-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .kpi-grid { grid-template-columns: 1fr; }
  .subgrid  { grid-template-columns: 1fr; }
  .spot-grid { grid-template-columns: 1fr; }
  .v7-components { grid-template-columns: repeat(2, 1fr); }
  .vix2-weight-row { grid-template-columns: 92px 1fr 56px; }
  .factor-summary-card strong { font-size: 21px; }
}
</style>
