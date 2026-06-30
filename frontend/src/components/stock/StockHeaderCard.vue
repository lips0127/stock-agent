<template>
  <div class="stock-header">
    <div class="stock-header__identity">
      <a
        v-if="eastmoneyHref"
        :href="eastmoneyHref"
        target="_blank"
        rel="noopener"
        class="stock-header__name stock-header__name--link"
        :title="`在东方财富查看 ${name || code}`"
      >
        {{ name || code }}
        <el-icon :size="12" class="stock-header__ext"><Promotion /></el-icon>
      </a>
      <span v-else class="stock-header__name">{{ name || code || '—' }}</span>

      <el-tag v-if="code" type="info" size="small" class="stock-header__code">
        {{ code }}
      </el-tag>
      <el-tag
        v-if="sentiment"
        :type="tagType"
        size="small"
        effect="plain"
      >
        {{ tagLabel }}
      </el-tag>
    </div>
    <div v-if="showPrice && price != null" class="stock-header__price">
      <span class="stock-header__price-value">{{ formatPrice(price) }}</span>
      <span class="stock-header__price-label">最新价</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Promotion } from '@element-plus/icons-vue'
import {
  formatPrice, eastmoneyUrl, sentimentTagType, sentimentLabel,
} from './format.js'

const props = defineProps({
  code: { type: String, default: '' },
  name: { type: String, default: '' },
  price: { type: [Number, String], default: null },
  sentiment: { type: String, default: '' },
  showPrice: { type: Boolean, default: true },
})

const eastmoneyHref = computed(() => (props.code ? eastmoneyUrl(props.code) : ''))
const tagType = computed(() => sentimentTagType(props.sentiment))
const tagLabel = computed(() => sentimentLabel(props.sentiment))
</script>

<style scoped>
.stock-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.stock-header__identity {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.stock-header__name {
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.stock-header__name--link {
  text-decoration: none;
  border-bottom: 1px dashed var(--color-text-tertiary);
  transition: color var(--duration-base) var(--ease),
    border-color var(--duration-base) var(--ease);
}
.stock-header__name--link:hover {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}
.stock-header__ext {
  opacity: 0.5;
  transition: opacity var(--duration-base) var(--ease);
}
.stock-header__name--link:hover .stock-header__ext {
  opacity: 1;
}
.stock-header__code {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: var(--text-xs);
}
.stock-header__price {
  display: flex;
  align-items: baseline;
  gap: var(--space-1);
}
.stock-header__price-value {
  font-size: var(--text-xl);
  font-weight: var(--weight-bold);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.stock-header__price-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
</style>
