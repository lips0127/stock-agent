<template>
  <div class="error-state" :class="{ 'error-state--carded': carded }">
    <div class="error-state__icon">
      <el-icon :size="26"><WarningFilled /></el-icon>
    </div>
    <h4 v-if="title" class="error-state__title">{{ title }}</h4>
    <p v-if="description" class="error-state__desc">{{ description }}</p>
    <div v-if="$slots.action || retry" class="error-state__action">
      <slot name="action">
        <el-button type="primary" :loading="loading" @click="$emit('retry')">
          {{ retryText }}
        </el-button>
      </slot>
    </div>
  </div>
</template>

<script setup>
import { WarningFilled } from '@element-plus/icons-vue'

defineProps({
  title: { type: String, default: '加载失败' },
  description: { type: String, default: '请求出现问题，请检查网络后重试' },
  carded: { type: Boolean, default: false },
  retry: { type: Boolean, default: true },
  retryText: { type: String, default: '重新加载' },
  loading: { type: Boolean, default: false },
})

defineEmits(['retry'])
</script>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--space-12) var(--space-6);
}
.error-state--carded {
  border: 1.5px dashed rgba(220, 38, 38, 0.25);
  border-radius: var(--radius-lg);
  background: var(--color-danger-soft);
  margin: var(--space-4) 0;
}

.error-state__icon {
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: rgba(220, 38, 38, 0.08);
  color: var(--color-danger);
  margin-bottom: var(--space-4);
}

.error-state__title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--space-1) 0;
  letter-spacing: -0.01em;
}

.error-state__desc {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  max-width: 380px;
  margin: 0;
  line-height: var(--leading-relaxed);
}

.error-state__action {
  margin-top: var(--space-5);
}
</style>
