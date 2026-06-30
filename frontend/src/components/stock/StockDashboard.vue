<template>
  <div class="stock-dashboard" :class="{ 'stock-dashboard--inline': inline }">
    <div v-if="include.includes('header')" class="stock-dashboard__row">
      <StockHeaderCard
        :code="code"
        :name="name"
        :price="price"
        :sentiment="sentiment"
        :show-price="include.includes('price')"
      />
      <slot name="header-extra" />
    </div>

    <div v-if="context" class="stock-dashboard__context">
      <el-icon :size="14"><ChatLineSquare /></el-icon>
      <span>{{ context }}</span>
    </div>

    <ValuationBar
      v-if="include.includes('valuation')"
      :total-market-cap="totalMarketCap"
      :float-market-cap="floatMarketCap"
      :ttm-pe="ttmPe"
      :pe-percentile="pePercentile"
      :basis="pePercentileBasis"
    />

    <TtmKpiGrid
      v-if="include.includes('kpi')"
      :ttm-revenue="ttmRevenue"
      :ttm-net-profit="ttmNetProfit"
      :ttm-gross-profit="ttmGrossProfit"
    />

    <div v-if="showPriceSection" class="stock-dashboard__section">
      <div class="section-title">
        <span>股价走势</span>
        <span class="section-hint">近 1 年日 K</span>
      </div>
      <PriceTrendChart
        :price-history="priceHistory"
        :current-price="price"
        :markers="markers"
        :marker-label="markerLabel"
      />
    </div>

    <QuarterlyTable
      v-if="include.includes('quarterly') && quarters && quarters.length"
      :quarters="quarters"
    />

    <div
      v-if="include.includes('pe') && peHistory && peHistory.length && ttmPe != null"
      class="stock-dashboard__section"
    >
      <div class="section-title">
        <span>TTM PE 历史走势</span>
        <span class="section-hint">近 1 年</span>
      </div>
      <PeHistoryChart :pe-history="peHistory" :current-pe="ttmPe" />
    </div>

    <div
      v-if="!hasAnyData && include.includes('kpi')"
      class="stock-dashboard__empty"
    >
      暂无财务数据（akshare 可能暂不可用，请稍后重试）
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ChatLineSquare } from '@element-plus/icons-vue'
import StockHeaderCard from './StockHeaderCard.vue'
import ValuationBar from './ValuationBar.vue'
import TtmKpiGrid from './TtmKpiGrid.vue'
import QuarterlyTable from './QuarterlyTable.vue'
import PriceTrendChart from '../PriceTrendChart.vue'
import PeHistoryChart from '../PeHistoryChart.vue'

const props = defineProps({
  code: { type: String, default: '' },
  name: { type: String, default: '' },
  price: { type: [Number, String], default: null },
  sentiment: { type: String, default: '' },
  context: { type: String, default: '' },

  // 财务
  totalMarketCap: { type: [Number, String], default: null },
  floatMarketCap: { type: [Number, String], default: null },
  ttmPe: { type: [Number, String], default: null },
  pePercentile: { type: [Number, String], default: null },
  pePercentileBasis: { type: String, default: 'pe' },
  ttmRevenue: { type: [Number, String], default: null },
  ttmNetProfit: { type: [Number, String], default: null },
  ttmGrossProfit: { type: [Number, String], default: null },
  quarters: { type: Array, default: () => [] },
  priceHistory: { type: Array, default: () => [] },
  peHistory: { type: Array, default: () => [] },

  // 舆情叠加（SentimentView 用）
  markers: { type: Array, default: () => [] },
  markerLabel: { type: String, default: '舆情分数' },

  // include: 启用哪些子模块
  // - header / valuation / kpi / price / quarterly / pe
  include: {
    type: Array,
    default: () => ['header', 'valuation', 'kpi', 'price', 'quarterly', 'pe'],
  },
  // inline 模式：无内边距/边框/阴影（用于 SentimentView 嵌入，避免和原面板重复样式）
  inline: { type: Boolean, default: false },
})

const hasAnyData = computed(() =>
  props.ttmRevenue != null
  || props.ttmNetProfit != null
  || props.ttmGrossProfit != null
  || (props.quarters && props.quarters.length > 0),
)

const showPriceSection = computed(() =>
  props.include.includes('price')
  && props.priceHistory
  && props.priceHistory.length > 0,
)
</script>

<style scoped>
.stock-dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.stock-dashboard--inline {
  gap: var(--space-2);
}

.stock-dashboard__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.stock-dashboard__context {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg-muted);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  line-height: 1.6;
}

.stock-dashboard__section { width: 100%; }
.stock-dashboard__empty {
  padding: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  text-align: center;
  background: var(--color-bg-muted);
  border-radius: var(--radius-sm);
}

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
</style>
