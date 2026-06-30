<template>
  <div v-if="hasAny" class="valuation-bar">
    <div v-if="totalMarketCap != null" class="valuation-item">
      <span class="valuation-label">总市值</span>
      <span class="valuation-value">{{ formatCap(totalMarketCap) }}</span>
    </div>
    <div v-if="floatMarketCap != null" class="valuation-item">
      <span class="valuation-label">流通市值</span>
      <span class="valuation-value">{{ formatCap(floatMarketCap) }}</span>
    </div>
    <div class="valuation-item">
      <span class="valuation-label">TTM 市盈率</span>
      <span
        class="valuation-value"
        :class="ttmPe == null ? 'valuation-value--muted' : ''"
      >
        <el-tooltip
          v-if="ttmPe == null"
          :content="ttmLossHint"
          placement="top"
        >
          <span>亏损</span>
        </el-tooltip>
        <span v-else>{{ ttmPe.toFixed(1) }}</span>
      </span>
    </div>
    <div v-if="pePercentile != null" class="valuation-item">
      <span class="valuation-label">
        {{ basis === 'price' ? '股价 1Y 百分位' : 'PE 历史百分位' }}
      </span>
      <span
        class="valuation-value"
        :class="pePercentileClass(pePercentile)"
      >
        {{ pePercentile.toFixed(0) }}%
      </span>
      <span class="valuation-hint">近 1 年</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatCap, pePercentileClass } from './format.js'

const props = defineProps({
  totalMarketCap: { type: [Number, String], default: null },
  floatMarketCap: { type: [Number, String], default: null },
  ttmPe: { type: [Number, String], default: null },
  pePercentile: { type: [Number, String], default: null },
  basis: { type: String, default: 'pe' },  // 'pe' | 'price' | null
})

const hasAny = computed(() =>
  props.totalMarketCap != null
  || props.floatMarketCap != null
  || props.ttmPe != null
  || props.pePercentile != null,
)

const ttmLossHint = computed(() =>
  props.basis === 'price'
    ? '公司 TTM 亏损，PE 暂无意义（百分位已退化为股价百分位）'
    : '公司 TTM 亏损，PE 暂无意义',
)
</script>

<style scoped>
.valuation-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-5);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-glass);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}
.valuation-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-1);
}
.valuation-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.valuation-value {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.valuation-hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.valuation-value--cheap { color: var(--color-down, #059669); }
.valuation-value--expensive { color: var(--color-up, #e11d48); }
.valuation-value--muted {
  color: var(--color-text-tertiary);
  font-weight: var(--weight-regular);
  cursor: help;
}
</style>
