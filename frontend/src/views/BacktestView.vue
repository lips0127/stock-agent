<template>
  <div class="backtest-page">
    <el-page-header @back="$router.push('/dashboard')" title="返回" />
    <h2 class="page-title">策略回测</h2>

    <el-row :gutter="20">
      <!-- 左侧：回测配置表单 -->
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>
            <span class="card-title">回测配置</span>
          </template>

          <el-form :model="form" label-width="90px" size="small">
            <el-form-item label="策略名称">
              <el-select v-model="form.strategy_name" placeholder="选择策略" style="width:100%">
                <el-option
                  v-for="s in strategies"
                  :key="s.name"
                  :label="s.name + ' (' + s.class_name + ')'"
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
                style="width:100%"
              >
                <el-option
                  v-for="s in stockOptions"
                  :key="s"
                  :label="s"
                  :value="s"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="开始日期">
              <el-date-picker
                v-model="form.start"
                type="date"
                placeholder="选择开始日期"
                value-format="YYYY-MM-DD"
                style="width:100%"
              />
            </el-form-item>

            <el-form-item label="结束日期">
              <el-date-picker
                v-model="form.end"
                type="date"
                placeholder="选择结束日期"
                value-format="YYYY-MM-DD"
                style="width:100%"
              />
            </el-form-item>

            <el-form-item label="初始资金">
              <el-input-number
                v-model="form.initial_capital"
                :min="10000"
                :max="10000000"
                :step="10000"
                style="width:100%"
              />
            </el-form-item>

            <el-form-item label="K线周期">
              <el-select v-model="form.timeframe" style="width:100%">
                <el-option label="日线 (1d)" value="1d" />
                <el-option label="周线 (1w)" value="1w" />
              </el-select>
            </el-form-item>

            <el-collapse accordion style="margin-bottom: 12px">
              <el-collapse-item title="高级设置" name="advanced">
                <el-form-item label="佣金费率">
                  <el-input-number
                    v-model="form.commission_rate"
                    :min="0"
                    :max="0.01"
                    :step="0.0001"
                    :precision="4"
                    style="width:100%"
                  />
                </el-form-item>
                <el-form-item label="滑点">
                  <el-input-number
                    v-model="form.slippage"
                    :min="0"
                    :max="0.1"
                    :step="0.001"
                    :precision="3"
                    style="width:100%"
                  />
                </el-form-item>

                <el-form-item label="策略参数">
                  <div v-for="(v, k) in form.params" :key="k" class="param-row">
                    <span class="param-key">{{ k }}</span>
                    <el-input-number
                      v-model="form.params[k]"
                      :step="1"
                      size="small"
                      style="width: 120px"
                    />
                  </div>
                  <span v-if="!Object.keys(form.params).length" class="text-muted">
                    选中策略后自动加载参数
                  </span>
                </el-form-item>
              </el-collapse-item>
            </el-collapse>

            <el-form-item>
              <el-button
                type="primary"
                :loading="running"
                :disabled="!canRun"
                @click="handleRun"
              >
                {{ running ? '回测运行中...' : '开始回测' }}
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <!-- 右侧：回测结果 -->
      <el-col :span="16">
        <!-- 历史回测记录列表 -->
        <el-card v-if="!selectedRun" shadow="hover">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">历史回测记录</span>
              <el-button size="small" @click="loadRuns" :loading="loadingRuns">
                刷新
              </el-button>
            </div>
          </template>

          <el-table :data="runs" stripe size="small" highlight-current-row
                    @row-click="selectRun" style="cursor:pointer">
            <el-table-column prop="created_at" label="时间" width="160" />
            <el-table-column prop="strategy_name" label="策略" width="120" />
            <el-table-column label="区间" width="180">
              <template #default="{ row }">
                {{ row.start_date }} ~ {{ row.end_date }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="statusTag(row.status)" size="small">
                  {{ statusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="总收益" width="90">
              <template #default="{ row }">
                <span v-if="row.total_return != null"
                      :class="row.total_return >= 0 ? 'profit' : 'loss'">
                  {{ (row.total_return * 100).toFixed(2) }}%
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="夏普" width="70">
              <template #default="{ row }">
                {{ row.sharpe_ratio != null ? row.sharpe_ratio.toFixed(2) : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="最大回撤" width="90">
              <template #default="{ row }">
                <span v-if="row.max_drawdown != null" class="loss">
                  {{ (row.max_drawdown * 100).toFixed(2) }}%
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="胜率" width="70">
              <template #default="{ row }">
                {{ row.win_rate != null ? (row.win_rate * 100).toFixed(1) + '%' : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="交易数" width="70">
              <template #default="{ row }">
                {{ row.total_trades ?? '-' }}
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="!runs.length" description="暂无回测记录" />
        </el-card>

        <!-- 单次回测详情 -->
        <div v-else>
          <el-card shadow="hover" style="margin-bottom: 16px">
            <template #header>
              <div class="card-header-row">
                <span class="card-title">
                  回测详情 — {{ selectedRun.strategy_name }}
                  <el-tag :type="statusTag(selectedRun.status)" size="small" style="margin-left:8px">
                    {{ statusText(selectedRun.status) }}
                  </el-tag>
                </span>
                <el-button size="small" @click="selectedRun = null">返回列表</el-button>
              </div>
            </template>

            <el-row :gutter="16">
              <el-col :span="6">
                <el-statistic title="初始资金" :value="selectedRun.initial_capital"
                              prefix="¥" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="最终价值" :value="selectedRun.final_value?.toFixed(0)"
                              prefix="¥" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="总收益率"
                              :value="selectedRun.total_return != null ? (selectedRun.total_return * 100).toFixed(2) : 0"
                              suffix="%" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="年化收益"
                              :value="selectedRun.annual_return != null ? (selectedRun.annual_return * 100).toFixed(2) : 0"
                              suffix="%" />
              </el-col>
            </el-row>

            <el-row :gutter="16" style="margin-top: 16px">
              <el-col :span="6">
                <el-statistic title="夏普比率" :value="selectedRun.sharpe_ratio?.toFixed(2) || '0'" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="最大回撤"
                              :value="selectedRun.max_drawdown != null ? (selectedRun.max_drawdown * 100).toFixed(2) : '0'"
                              suffix="%" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="胜率"
                              :value="selectedRun.win_rate != null ? (selectedRun.win_rate * 100).toFixed(1) : '0'"
                              suffix="%" />
              </el-col>
              <el-col :span="6">
                <el-statistic title="交易总数" :value="selectedRun.total_trades || 0" />
              </el-col>
            </el-row>
          </el-card>

          <!-- 交易明细 -->
          <el-card v-if="selectedRun.trades && selectedRun.trades.length" shadow="hover">
            <template #header>
              <span class="card-title">交易明细 ({{ selectedRun.trades.length }})</span>
            </template>
            <el-table :data="selectedRun.trades" stripe size="small" max-height="400">
              <el-table-column prop="entry_time" label="时间" width="170" />
              <el-table-column prop="symbol" label="标的" width="80" />
              <el-table-column label="方向" width="60">
                <template #default="{ row }">
                  <el-tag :type="row.side === 'BUY' ? 'danger' : 'success'" size="small">
                    {{ row.side === 'BUY' ? '买' : '卖' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="entry_price" label="价格" width="80" />
              <el-table-column prop="quantity" label="数量" width="70" />
              <el-table-column label="盈亏" width="100">
                <template #default="{ row }">
                  <span :class="(row.pnl || 0) >= 0 ? 'profit' : 'loss'">
                    {{ (row.pnl || 0).toFixed(2) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="盈亏率" width="80">
                <template #default="{ row }">
                  <span :class="(row.pnl_pct || 0) >= 0 ? 'profit' : 'loss'">
                    {{ ((row.pnl_pct || 0) * 100).toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getStrategies, getBacktestRuns, getBacktestRun, runBacktest } from '../api'

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

function statusTag(s) {
  return s === 'completed' ? 'success' : s === 'running' ? 'warning' : 'danger'
}
function statusText(s) {
  return s === 'completed' ? '已完成' : s === 'running' ? '运行中' : '失败'
}

// 选策略时自动加载默认参数
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

    // 轮询等待完成
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

  // 从路由参数预选策略
  const preset = route.query.strategy
  if (preset) {
    form.value.strategy_name = preset
  }
})
</script>

<style scoped>
.page-title {
  margin: 16px 0;
  font-size: 20px;
  font-weight: 600;
}
.card-title {
  font-weight: 600;
}
.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.profit {
  color: #e32525;
  font-weight: 600;
}
.loss {
  color: #1ca01c;
  font-weight: 600;
}
.param-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.param-key {
  font-family: monospace;
  font-size: 13px;
  min-width: 60px;
}
.text-muted {
  color: #999;
  font-size: 12px;
}
</style>
