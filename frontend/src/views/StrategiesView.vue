<template>
  <div class="strategies-page">
    <PageHeader
      title="策略管理"
      subtitle="已注册的事件驱动策略（来自 strategy.registry）"
    />

    <div v-if="strategies.length" class="strategies-grid">
      <ModernCard
        v-for="s in strategies"
        :key="s.name"
      >
        <template #title>
          <div class="strategy-title">
            <span class="strategy-name">{{ s.name }}</span>
            <el-tag size="small" type="info" effect="plain">{{ s.class_name }}</el-tag>
          </div>
        </template>
        <template #extra>
          <el-button type="primary" size="small" @click="goBacktest(s)">
            去回测
          </el-button>
        </template>

        <div class="strategy-fields">
          <div class="field">
            <div class="field-label">关注标的</div>
            <div class="field-value">
              <span
                v-for="sym in s.symbols"
                :key="sym"
                class="sym-chip"
              >{{ sym }}</span>
              <span v-if="!s.symbols.length" class="text-muted">未指定</span>
            </div>
          </div>
          <div class="field">
            <div class="field-label">K线周期</div>
            <div class="field-value">{{ s.timeframes.join(', ') || '—' }}</div>
          </div>
          <div v-if="Object.keys(s.params).length" class="field field--full">
            <div class="field-label">参数</div>
            <div class="field-value">
              <span
                v-for="(v, k) in s.params"
                :key="k"
                class="param-chip"
              >{{ k }}: {{ v }}</span>
            </div>
          </div>
          <div v-if="s.doc" class="field field--full">
            <div class="field-label">说明</div>
            <div class="field-value doc-text">{{ s.doc }}</div>
          </div>
        </div>
      </ModernCard>
    </div>

    <EmptyHint
      v-else
      icon="∅"
      title="暂无已注册的策略"
      description="请检查 backend/strategy/registry.py"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getStrategies } from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'

const router = useRouter()
const strategies = ref([])

function goBacktest(s) {
  router.push({ name: 'Backtest', query: { strategy: s.name } })
}

onMounted(async () => {
  try {
    const { data } = await getStrategies()
    strategies.value = data
  } catch (e) {
    console.error('获取策略列表失败:', e)
  }
})
</script>

<style scoped>
.strategies-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.strategies-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: var(--space-4);
}
.strategy-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.strategy-name {
  font-weight: var(--weight-semibold);
  font-size: var(--text-md);
  color: var(--color-text-primary);
  font-family: var(--font-mono);
  letter-spacing: -0.01em;
}
.strategy-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}
.field--full {
  grid-column: 1 / -1;
}
.field-label {
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: var(--space-1);
}
.field-value {
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-1);
  line-height: var(--leading-relaxed);
}
.sym-chip,
.param-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
}
.sym-chip {
  background: var(--color-accent-soft);
  color: var(--color-accent-text);
}
.param-chip {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}
.doc-text {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  white-space: pre-wrap;
}
</style>
