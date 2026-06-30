<template>
  <div v-if="hasAny" class="ttm-kpi-grid">
    <StatCard
      label="TTM 营收"
      :value="formatCurrency(ttmRevenue)"
      icon="💰"
      tone="accent"
      hint="滚动十二个月"
    />
    <StatCard
      label="TTM 净利润"
      :value="formatCurrency(ttmNetProfit)"
      icon="📊"
      :tone="ttmNetProfit > 0 ? 'up' : 'danger'"
      hint="滚动十二个月"
    />
    <StatCard
      label="TTM 毛利润"
      :value="formatCurrency(ttmGrossProfit)"
      icon="📈"
      tone="muted"
      hint="滚动十二个月"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import StatCard from '../ui/StatCard.vue'
import { formatCurrency } from './format.js'

const props = defineProps({
  ttmRevenue: { type: [Number, String], default: null },
  ttmNetProfit: { type: [Number, String], default: null },
  ttmGrossProfit: { type: [Number, String], default: null },
})

const hasAny = computed(() =>
  props.ttmRevenue != null
  || props.ttmNetProfit != null
  || props.ttmGrossProfit != null,
)
</script>

<style scoped>
.ttm-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
}
@media (max-width: 640px) {
  .ttm-kpi-grid {
    grid-template-columns: 1fr;
  }
}
</style>
