<template>
  <div class="portfolio-page">
    <PageHeader
      title="组合管理"
      subtitle="实时持仓、收益与风控规则参考"
    >
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="loadData">
          刷新
        </el-button>
      </template>
    </PageHeader>

    <div class="portfolio-grid">
      <!-- 左侧：概览 -->
      <div class="left-panel">
        <ModernCard title="组合概览">
          <div class="total-value">
            <div class="total-value__label">总资产</div>
            <div class="total-value__num">¥{{ formatNum(portfolio.total_value) }}</div>
          </div>

          <el-divider />

          <div class="overview-fields">
            <div class="overview-field">
              <div class="overview-field__label">可用资金</div>
              <div class="overview-field__value">¥{{ formatNum(portfolio.cash) }}</div>
            </div>
            <div class="overview-field">
              <div class="overview-field__label">持仓市值</div>
              <div class="overview-field__value">¥{{ formatNum(portfolio.positions_value) }}</div>
            </div>
            <div class="overview-field">
              <div class="overview-field__label">累计盈亏</div>
              <div
                class="overview-field__value"
                :class="(portfolio.cumulative_pnl || 0) >= 0 ? 'num-up' : 'num-down'"
              >
                ¥{{ formatNum(portfolio.cumulative_pnl) }}
              </div>
            </div>
            <div class="overview-field">
              <div class="overview-field__label">日度收益</div>
              <div class="overview-field__value">
                {{ portfolio.daily_return != null ? (portfolio.daily_return * 100).toFixed(4) + '%' : '—' }}
              </div>
            </div>
            <div class="overview-field overview-field--full">
              <div class="overview-field__label">快照日期</div>
              <div class="overview-field__value text-secondary">{{ portfolio.date || '无数据' }}</div>
            </div>
          </div>
        </ModernCard>
      </div>

      <!-- 右侧：持仓 + 风控 -->
      <div class="right-panel">
        <ModernCard :title="`当前持仓 (${positions.length})`">
          <el-table :data="positions" :empty-text="'暂无持仓'">
            <el-table-column prop="symbol" label="代码" width="120">
              <template #default="{ row }">
                <span class="code-cell">{{ row.symbol }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="quantity" label="持仓数量" width="120" align="right">
              <template #default="{ row }">
                <span class="num">{{ row.quantity ?? 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column label="持仓成本" width="120" align="right">
              <template #default="{ row }">
                <span class="num">¥{{ formatNum(row.avg_cost) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="现价" width="120" align="right">
              <template #default="{ row }">
                <span class="num">¥{{ formatNum(row.current_price) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="未实现盈亏" width="140" align="right">
              <template #default="{ row }">
                <span :class="(row.unrealized_pnl || 0) >= 0 ? 'num-up' : 'num-down'">
                  ¥{{ formatNum(row.unrealized_pnl) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="已实现盈亏" width="140" align="right">
              <template #default="{ row }">
                <span :class="(row.realized_pnl || 0) >= 0 ? 'num-up' : 'num-down'">
                  ¥{{ formatNum(row.realized_pnl) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="strategy_id" label="策略ID" min-width="120" />
          </el-table>
        </ModernCard>

        <ModernCard title="风控规则参考" description="系统内置的默认风控规则">
          <el-table :data="riskRules" :empty-text="'暂无规则'">
            <el-table-column prop="name" label="规则名称" width="180" />
            <el-table-column prop="description" label="说明" />
            <el-table-column label="参数" width="240">
              <template #default="{ row }">
                <span
                  v-for="(v, k) in row.params"
                  :key="k"
                  class="param-chip"
                >{{ k }}: {{ v }}</span>
              </template>
            </el-table-column>
          </el-table>
        </ModernCard>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getPortfolio, getPositions, getRiskRules } from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'

const portfolio = ref({})
const positions = ref([])
const riskRules = ref([])
const loading = ref(false)

function formatNum(v) {
  if (v == null) return '0'
  return Number(v).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

async function loadData() {
  loading.value = true
  try {
    const [pRes, posRes, rRes] = await Promise.all([
      getPortfolio(),
      getPositions(),
      getRiskRules(),
    ])
    portfolio.value = pRes.data
    positions.value = posRes.data
    riskRules.value = rRes.data
  } catch (e) {
    console.error('加载组合数据失败:', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.portfolio-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.portfolio-grid {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: var(--space-4);
  align-items: start;
}
.right-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.total-value {
  text-align: center;
  padding: var(--space-3) 0;
}
.total-value__label {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-1);
}
.total-value__num {
  font-size: var(--text-4xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.overview-fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.overview-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-divider);
}
.overview-field:last-child { border-bottom: none; }
.overview-field--full {
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
}
.overview-field__label {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}
.overview-field__value {
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  font-weight: var(--weight-medium);
  font-variant-numeric: tabular-nums;
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
.param-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  margin-right: 4px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}
</style>
