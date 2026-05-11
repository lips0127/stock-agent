<template>
  <el-card shadow="never" class="section-card">
    <template #header>
      <span class="section-title">大盘指数</span>
    </template>
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
      <el-empty v-else description="暂无指数数据" :image-size="60" />
    </div>
  </el-card>
</template>

<script setup>
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
  gap: 14px;
}
.index-item {
  background: #f8f9fb;
  border-radius: 10px;
  padding: 16px 16px 16px 20px;
  border-left: 4px solid transparent;
  transition: box-shadow 0.25s ease, transform 0.15s ease;
  cursor: default;
}
.index-item:hover {
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}
.index-item.is-up {
  border-left-color: var(--color-up);
}
.index-item.is-down {
  border-left-color: var(--color-down);
}
.index-name {
  font-size: 13px;
  color: var(--color-text-muted);
  margin-bottom: 6px;
}
.index-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text-primary);
}
.index-change {
  font-size: 13px;
  margin-top: 4px;
  font-weight: 500;
}
.is-up .index-change {
  color: var(--color-up);
}
.is-down .index-change {
  color: var(--color-down);
}
.change-arrow {
  font-size: 10px;
  margin-right: 2px;
}
</style>
