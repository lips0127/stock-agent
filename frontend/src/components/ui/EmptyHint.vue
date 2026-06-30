<template>
  <div class="empty-hint" :class="{ 'empty-hint--carded': carded }">
    <div v-if="$slots.illustration" class="empty-hint__illustration">
      <slot name="illustration" />
    </div>
    <div v-else-if="icon || $slots.icon" class="empty-hint__icon">
      <slot name="icon">{{ icon || '∅' }}</slot>
    </div>
    <h4 v-if="title" class="empty-hint__title">{{ title }}</h4>
    <p v-if="description || $slots.default" class="empty-hint__desc">
      <slot>{{ description }}</slot>
    </p>
    <div v-if="$slots.action" class="empty-hint__action">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '' },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  carded: { type: Boolean, default: false },
})
</script>

<style scoped>
.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--space-12) var(--space-6);
  color: var(--color-text-tertiary);
}
.empty-hint--carded {
  border: 1.5px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: var(--color-bg-subtle);
  margin: var(--space-4) 0;
}

.empty-hint__illustration {
  margin-bottom: var(--space-5);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.85;
}
.empty-hint__illustration :deep(svg) {
  width: 120px;
  height: auto;
  max-height: 96px;
}

.empty-hint__icon {
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: var(--color-bg-muted);
  color: var(--color-text-tertiary);
  font-size: var(--text-xl);
  margin-bottom: var(--space-4);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.04);
}

.empty-hint__title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--space-1) 0;
  letter-spacing: -0.01em;
}

.empty-hint__desc {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  max-width: 380px;
  margin: 0;
  line-height: var(--leading-relaxed);
}

.empty-hint__action {
  margin-top: var(--space-5);
}
</style>
