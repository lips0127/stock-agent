<template>
  <div class="stocks-page">
    <PageHeader
      title="全量扫描结果"
      :subtitle="scanDate ? `扫描日期：${scanDate}` : '等待扫描结果'"
    >
      <template #actions>
        <span v-if="total > 0" class="total-pill">共 {{ total }} 只</span>
      </template>
    </PageHeader>

    <StockScanTable
      scan-type=""
      empty-text="暂无扫描数据"
      @meta="onMeta"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import PageHeader from '../components/ui/PageHeader.vue'
import StockScanTable from '../components/StockScanTable.vue'

const total = ref(0)
const scanDate = ref('')

function onMeta({ total: t, date }) {
  total.value = t
  scanDate.value = date
}
</script>

<style scoped>
.stocks-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.total-pill {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  background: var(--color-bg-muted);
  padding: 4px 12px;
  border-radius: var(--radius-full);
  font-variant-numeric: tabular-nums;
}
</style>
