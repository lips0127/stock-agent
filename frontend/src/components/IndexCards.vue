<template>
  <!-- 纯网格：卡片外壳由父级 ModernCard 提供，避免双重嵌套 -->
  <div v-loading="loading" class="indices-grid">
    <template v-if="indices.length">
      <div
        v-for="idx in indices"
        :key="idx.symbol"
        :class="['index-item', idx.change_pct >= 0 ? 'is-up' : 'is-down']"
      >
        <div class="index-name">{{ idx.name || idx.symbol }}</div>
        <div class="index-value">{{ formatValue(idx.value) }}</div>
        <div class="index-change">
          <span class="change-arrow">{{ idx.change_pct >= 0 ? '▲' : '▼' }}</span>
          {{ formatChange(idx.change_pct) }}
        </div>
      </div>
    </template>
    <EmptyHint
      v-else-if="!loading"
      title="暂无指数数据"
      description="等待定时任务拉取，或点击右上角刷新"
    />
  </div>
</template>

<script setup>
import EmptyHint from './ui/EmptyHint.vue'

defineProps({
  indices: { type: Array, default: () => [] },
  loading: Boolean,
})

function formatValue(v) {
  return v != null ? Number(v).toFixed(2) : '--'
}

function formatChange(pct) {
  if (pct == null) return '--'
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${Number(pct).toFixed(2)}%`
}
</script>

<style scoped>
.indices-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--space-3);
}
.index-item {
  background: var(--color-bg-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-4) var(--space-4) var(--space-5);
  border-left: 3px solid transparent;
  transition: all var(--duration-base) var(--ease);
  cursor: default;
}
.index-item:hover {
  background: var(--color-bg-muted);
}
.index-item.is-up { border-left-color: var(--color-up); }
.index-item.is-down { border-left-color: var(--color-down); }

.index-name {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-bottom: 6px;
  font-weight: var(--weight-medium);
  letter-spacing: 0.02em;
}
.index-value {
  font-family: var(--font-mono);
  font-size: var(--text-2xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: -0.02em;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.index-change {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  margin-top: 4px;
  font-weight: var(--weight-medium);
  font-variant-numeric: tabular-nums;
}
.is-up .index-change { color: var(--color-up); }
.is-down .index-change { color: var(--color-down); }
.change-arrow {
  font-size: 10px;
  margin-right: 2px;
}
</style>
