<template>
  <header class="page-header" :class="`page-header--${size}`">
    <div v-if="$slots.icon" class="page-header__icon">
      <slot name="icon" />
    </div>
    <div class="page-header__main">
      <div class="page-header__title-row">
        <h1 v-if="title" class="page-header__title">{{ title }}</h1>
        <slot name="title" />
      </div>
      <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
      <div v-if="$slots.meta" class="page-header__meta">
        <slot name="meta" />
      </div>
    </div>
    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  margin-bottom: var(--space-8);
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-divider);
}

.page-header__icon {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  border-radius: var(--radius-lg);
  background: var(--color-accent-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  line-height: 1;
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.08);
}

.page-header__main {
  flex: 1;
  min-width: 0;
  padding-top: 2px;
}

.page-header__title-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.page-header__title {
  font-size: var(--text-2xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: -0.025em;
  line-height: var(--leading-tight);
  margin: 0;
}

.page-header--lg .page-header__title {
  font-size: var(--text-3xl);
  font-weight: var(--weight-bold);
  letter-spacing: -0.03em;
}

.page-header--sm .page-header__title {
  font-size: var(--text-xl);
}

.page-header__subtitle {
  margin: var(--space-2) 0 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  letter-spacing: -0.005em;
}

.page-header__meta {
  margin-top: var(--space-3);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.page-header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  padding-top: 2px;
}
</style>
