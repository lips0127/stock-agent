<template>
  <div class="backtest-page">
    <PageHeader
      title="策略回测"
      subtitle="基于历史数据的策略表现评估"
    />

    <div class="backtest-grid">
      <!-- 左侧：配置表单 -->
      <ModernCard title="回测配置" description="选择策略、标的与时间区间">
        <el-form :model="form" label-position="top" size="default">
          <el-form-item label="策略名称">
            <el-select v-model="form.strategy_name" placeholder="选择策略" style="width: 100%">
              <el-option
                v-for="s in strategies"
                :key="s.name"
                :label="`${s.name} (${s.class_name})`"
                :value="s.name"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="股票代码">
            <el-select
              v-model="form.symbols"
              multiple
              filterable
              allow-create
              placeholder="输入或选择股票代码"
              style="width: 100%"
            >
              <el-option v-for="s in stockOptions" :key="s" :label="s" :value="s" />
            </el-select>
          </el-form-item>

          <div class="form-row">
            <el-form-item label="开始日期">
              <el-date-picker
                v-model="form.start"
                type="date"
                placeholder="开始"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="结束日期">
              <el-date-picker
                v-model="form.end"
                type="date"
                placeholder="结束"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </el-form-item>
          </div>

          <div class="form-row">
            <el-form-item label="初始资金">
              <el-input-number
                v-model="form.initial_capital"
                :min="10000"
                :max="10000000"
                :step="10000"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="K线周期">
              <el-select v-model="form.timeframe" style="width: 100%">
                <el-option label="日线 (1d)" value="1d" />
                <el-option label="周线 (1w)" value="1w" />
              </el-select>
            </el-form-item>
          </div>

          <el-collapse accordion>
            <el-collapse-item title="高级设置" name="advanced">
              <div class="form-row">
                <el-form-item label="佣金费率">
                  <el-input-number
                    v-model="form.commission_rate"
                    :min="0"
                    :max="0.01"
                    :step="0.0001"
                    :precision="4"
                    style="width: 100%"
                  />
                </el-form-item>
                <el-form-item label="滑点">
                  <el-input-number
                    v-model="form.slippage"
                    :min="0"
                    :max="0.1"
                    :step="0.001"
                    :precision="3"
                    style="width: 100%"
                  />
                </el-form-item>
              </div>
              <el-form-item label="策略参数">
                <div v-for="(v, k) in form.params" :key="k" class="param-row">
                  <span class="param-key">{{ k }}</span>
                  <el-input-number v-model="form.params[k]" :step="1" size="small" style="width: 120px" />
                </div>
                <span v-if="!Object.keys(form.params).length" class="text-muted">
                  选中策略后自动加载参数
                </span>
              </el-form-item>
            </el-collapse-item>
          </el-collapse>

          <el-button
            type="primary"
            :loading="running"
            :disabled="!canRun"
            class="run-btn"
            @click="handleRun"
          >
            {{ running ? '回测运行中…' : '开始回测' }}
          </el-button>
        </el-form>
      </ModernCard>

      <!-- 右侧：结果 -->
      <div class="right-panel">
        <!-- 历史记录列表 -->
        <ModernCard
          v-if="!selectedRun"
          title="历史回测记录"
          description="点击行查看详情"
        >
          <template #extra>
            <el-button text size="small" @click="loadRuns" :loading="loadingRuns">
              刷新
            </el-button>
          </template>
          <el-table
            :data="runs"
            highlight-current-row
            :empty-text="'暂无回测记录'"
            @row-click="selectRun"
            class="clickable-table"
          >
            <el-table-column prop="created_at" label="时间" width="170" />
            <el-table-column prop="strategy_name" label="策略" width="120" />
            <el-table-column label="区间" width="180">
              <template #default="{ row }">
                <span class="text-secondary">{{ row.start_date }} ~ {{ row.end_date }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <span class="status-pill" :class="`status-pill--${row.status}`">
                  {{ statusText(row.status) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="总收益" width="100" align="right">
              <template #default="{ row }">
                <span v-if="row.total_return != null" :class="row.total_return >= 0 ? 'num-up' : 'num-down'">
                  {{ (row.total_return * 100).toFixed(2) }}%
                </span>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="夏普" width="80" align="right">
              <template #default="{ row }">
                <span class="num">{{ row.sharpe_ratio != null ? row.sharpe_ratio.toFixed(2) : '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="回撤" width="90" align="right">
              <template #default="{ row }">
                <span v-if="row.max_drawdown != null" class="num-down">
                  {{ (row.max_drawdown * 100).toFixed(2) }}%
                </span>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="胜率" width="80" align="right">
              <template #default="{ row }">
                <span class="num">{{ row.win_rate != null ? (row.win_rate * 100).toFixed(1) + '%' : '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="交易" width="80" align="right">
              <template #default="{ row }">
                <span class="num">{{ row.total_trades ?? '—' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </ModernCard>

        <!-- 详情 -->
        <template v-else>
          <ModernCard>
            <template #title>
              <div class="detail-title">
                <span>回测详情 — {{ selectedRun.strategy_name }}</span>
                <span class="status-pill" :class="`status-pill--${selectedRun.status}`">
                  {{ statusText(selectedRun.status) }}
                </span>
              </div>
            </template>
            <template #extra>
              <el-button size="small" @click="selectedRun = null">返回列表</el-button>
            </template>

            <div class="stat-grid">
              <StatCard label="初始资金" :value="`¥${formatNum(selectedRun.initial_capital)}`" icon="¥" />
              <StatCard label="最终价值" :value="`¥${formatNum(selectedRun.final_value)}`" icon="∑" />
              <StatCard
                label="总收益率"
                :value="selectedRun.total_return != null ? (selectedRun.total_return * 100).toFixed(2) + '%' : '—'"
                :tone="selectedRun.total_return >= 0 ? 'up' : 'down'"
                icon="↗"
              />
              <StatCard
                label="年化收益"
                :value="selectedRun.annual_return != null ? (selectedRun.annual_return * 100).toFixed(2) + '%' : '—'"
                :tone="selectedRun.annual_return >= 0 ? 'up' : 'down'"
                icon="∝"
              />
              <StatCard
                label="夏普比率"
                :value="selectedRun.sharpe_ratio != null ? selectedRun.sharpe_ratio.toFixed(2) : '—'"
                icon="σ"
              />
              <StatCard
                label="最大回撤"
                :value="selectedRun.max_drawdown != null ? (selectedRun.max_drawdown * 100).toFixed(2) + '%' : '—'"
                tone="warning"
                icon="↘"
              />
              <StatCard
                label="胜率"
                :value="selectedRun.win_rate != null ? (selectedRun.win_rate * 100).toFixed(1) + '%' : '—'"
                icon="✓"
              />
              <StatCard label="交易总数" :value="selectedRun.total_trades || 0" icon="#" />
            </div>
          </ModernCard>

          <ModernCard
            v-if="selectedRun.trades && selectedRun.trades.length"
            :title="`交易明细 (${selectedRun.trades.length})`"
          >
            <el-table :data="selectedRun.trades" max-height="400" :empty-text="'暂无交易'">
              <el-table-column prop="entry_time" label="时间" width="170" />
              <el-table-column prop="symbol" label="标的" width="80">
                <template #default="{ row }">
                  <span class="code-cell">{{ row.symbol }}</span>
                </template>
              </el-table-column>
              <el-table-column label="方向" width="80">
                <template #default="{ row }">
                  <span
                    class="side-pill"
                    :class="row.side === 'BUY' ? 'side-pill--buy' : 'side-pill--sell'"
                  >{{ row.side === 'BUY' ? '买' : '卖' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="entry_price" label="价格" width="100" align="right">
                <template #default="{ row }">
                  <span class="num">{{ row.entry_price?.toFixed(2) ?? '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="quantity" label="数量" width="90" align="right">
                <template #default="{ row }">
                  <span class="num">{{ row.quantity ?? '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="盈亏" width="120" align="right">
                <template #default="{ row }">
                  <span :class="(row.pnl || 0) >= 0 ? 'num-up' : 'num-down'">
                    {{ (row.pnl || 0).toFixed(2) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="盈亏率" width="100" align="right">
                <template #default="{ row }">
                  <span :class="(row.pnl_pct || 0) >= 0 ? 'num-up' : 'num-down'">
                    {{ ((row.pnl_pct || 0) * 100).toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </ModernCard>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getStrategies, getBacktestRuns, getBacktestRun, runBacktest } from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import StatCard from '../components/ui/StatCard.vue'

const route = useRoute()

const strategies = ref([])
const runs = ref([])
const selectedRun = ref(null)
const running = ref(false)
const loadingRuns = ref(false)

const stockOptions = ['000001', '000002', '000858', '600000', '600036', '600519', '601318']

const form = ref({
  strategy_name: '',
  symbols: ['000001'],
  start: '2024-01-01',
  end: '2024-12-31',
  initial_capital: 100000,
  timeframe: '1d',
  commission_rate: 0.00025,
  slippage: 0,
  params: {},
})

const canRun = computed(() => form.value.strategy_name && form.value.symbols.length)

function statusText(s) {
  return s === 'completed' ? '已完成' : s === 'running' ? '运行中' : '失败'
}

function formatNum(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

watch(() => form.value.strategy_name, (name) => {
  const s = strategies.value.find(x => x.name === name)
  if (s) {
    form.value.params = { ...s.params }
    if (s.symbols.length && form.value.symbols.length === 1 && form.value.symbols[0] === '000001') {
      form.value.symbols = [...s.symbols]
    }
  }
})

async function handleRun() {
  running.value = true
  try {
    const { data } = await runBacktest({
      strategy_name: form.value.strategy_name,
      symbols: form.value.symbols,
      start: form.value.start,
      end: form.value.end,
      initial_capital: form.value.initial_capital,
      timeframe: form.value.timeframe,
      commission_rate: form.value.commission_rate,
      slippage: form.value.slippage,
      params: form.value.params,
    })
    ElMessage.success('回测已提交: ' + data.run_id)

    let attempts = 0
    const poll = setInterval(async () => {
      attempts++
      try {
        const { data: run } = await getBacktestRun(data.run_id)
        if (run.status !== 'running') {
          clearInterval(poll)
          selectedRun.value = run
          running.value = false
          loadRuns()
          ElMessage.success('回测完成')
        }
      } catch (e) {
        clearInterval(poll)
        running.value = false
      }
      if (attempts > 120) {
        clearInterval(poll)
        running.value = false
        ElMessage.warning('回测超时，请手动刷新')
      }
    }, 2000)
  } catch (e) {
    running.value = false
    ElMessage.error('回测启动失败: ' + (e.response?.data?.error || e.message))
  }
}

async function selectRun(row) {
  try {
    const { data } = await getBacktestRun(row.id)
    selectedRun.value = data
  } catch (e) {
    ElMessage.error('获取回测详情失败')
  }
}

async function loadRuns() {
  loadingRuns.value = true
  try {
    const { data } = await getBacktestRuns()
    runs.value = data
  } catch (e) {
    console.error('获取回测记录失败:', e)
  } finally {
    loadingRuns.value = false
  }
}

onMounted(async () => {
  try {
    const { data } = await getStrategies()
    strategies.value = data
  } catch (e) {
    console.error('获取策略列表失败:', e)
  }
  loadRuns()

  const preset = route.query.strategy
  if (preset) {
    form.value.strategy_name = preset
  }
})
</script>

<style scoped>
.backtest-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.backtest-grid {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: var(--space-4);
  align-items: start;
}
.right-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}
.run-btn {
  width: 100%;
  height: 44px;
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  margin-top: var(--space-2);
}
.param-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.param-key {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  min-width: 60px;
  color: var(--color-text-primary);
}
.detail-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}
.status-pill {
  font-size: var(--text-xs);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-weight: var(--weight-medium);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}
.status-pill--completed {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.status-pill--running {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}
.status-pill--failed {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}
.side-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
}
.side-pill--buy {
  background: var(--color-up-soft);
  color: var(--color-up);
}
.side-pill--sell {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.code-cell {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
}
.num {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
}
.num-up {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-semibold);
  color: var(--color-up);
}
.num-down {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-semibold);
  color: var(--color-down);
}
.clickable-table :deep(.el-table__row) {
  cursor: pointer;
}
</style>
