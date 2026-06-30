<template>
  <div v-if="quarters && quarters.length" class="quarterly-table">
    <div class="section-title">
      <span>{{ title || '最近季度财务指标' }}</span>
      <span class="section-hint">单季度 · 同比/环比</span>
    </div>
    <el-table :data="quarters" size="small" stripe>
      <el-table-column prop="quarter" label="报告期" width="100" />
      <el-table-column label="营收" align="right" min-width="160">
        <template #default="{ row }">
          <div class="cell-value">{{ formatCurrency(row.revenue) }}</div>
          <div class="cell-changes">
            <span :class="['change-tag', changeClass(row.revenue_yoy)]" title="同比">
              同比 {{ formatChange(row.revenue_yoy) }}
            </span>
            <span :class="['change-tag', changeClass(row.revenue_qoq)]" title="环比">
              环比 {{ formatChange(row.revenue_qoq) }}
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="净利润" align="right" min-width="160">
        <template #default="{ row }">
          <div class="cell-value">
            <span :class="row.net_profit > 0 ? 'text-up' : 'text-down'">
              {{ formatCurrency(row.net_profit) }}
            </span>
          </div>
          <div class="cell-changes">
            <span :class="['change-tag', changeClass(row.net_profit_yoy)]" title="同比">
              同比 {{ formatChange(row.net_profit_yoy) }}
            </span>
            <span :class="['change-tag', changeClass(row.net_profit_qoq)]" title="环比">
              环比 {{ formatChange(row.net_profit_qoq) }}
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="毛利润" align="right" min-width="140">
        <template #default="{ row }">{{ formatCurrency(row.gross_profit) }}</template>
      </el-table-column>
      <el-table-column label="毛利率" align="right" min-width="160">
        <template #default="{ row }">
          <div class="cell-value">
            <span v-if="row.gross_margin != null">{{ row.gross_margin.toFixed(1) }}%</span>
            <span v-else>--</span>
          </div>
          <div class="cell-changes">
            <span :class="['change-tag', changeClass(row.gross_margin_yoy)]" title="同比（百分点）">
              同比 {{ formatChangePp(row.gross_margin_yoy) }}
            </span>
            <span :class="['change-tag', changeClass(row.gross_margin_qoq)]" title="环比（百分点）">
              环比 {{ formatChangePp(row.gross_margin_qoq) }}
            </span>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { formatCurrency, formatChange, formatChangePp, changeClass } from './format.js'

defineProps({
  quarters: { type: Array, default: () => [] },
  title: { type: String, default: '' },
})
</script>

<style scoped>
.quarterly-table { width: 100%; }
.section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}
.section-hint {
  font-size: var(--text-xs);
  font-weight: var(--weight-regular);
  color: var(--color-text-tertiary);
}
.text-up { color: var(--color-up); font-weight: var(--weight-medium); }
.text-down { color: var(--color-down); font-weight: var(--weight-medium); }

.cell-value {
  font-weight: var(--weight-medium);
  margin-bottom: 2px;
}
.cell-changes {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.change-tag {
  font-size: 11px;
  padding: 0 4px;
  border-radius: 3px;
  line-height: 1.6;
  white-space: nowrap;
}
.change-up {
  color: var(--color-up);
  background: #fce4ec;
  background: color-mix(in srgb, var(--color-up) 8%, transparent);
}
.change-down {
  color: var(--color-down);
  background: #e8f5e9;
  background: color-mix(in srgb, var(--color-down) 8%, transparent);
}
.change-flat {
  color: var(--color-text-tertiary);
  background: var(--color-bg-muted);
}
</style>
