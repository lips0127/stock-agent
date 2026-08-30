<template>
  <section
    class="modern-card"
    :class="[
      `modern-card--${variant}`,
      { 'modern-card--padded': padded, 'modern-card--hoverable': hoverable },
    ]"
  >
    <header v-if="title || $slots.header || $slots.title || $slots.extra" class="modern-card__header">
      <div v-if="title || $slots.title" class="modern-card__title-wrap">
        <h3 v-if="title" class="modern-card__title">{{ title }}</h3>
        <slot name="title" />
        <p v-if="description" class="modern-card__description">{{ description }}</p>
      </div>
      <div v-if="$slots.extra" class="modern-card__extra">
        <slot name="extra" />
      </div>
    </header>
    <div class="modern-card__body">
      <slot />
    </div>
  </section>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  padded: { type: Boolean, default: true },
  variant: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'glass', 'bordered'].includes(v),
  },
  hoverable: { type: Boolean, default: false },
})
</script>

<style scoped>
.modern-card {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: box-shadow var(--duration-page) var(--ease),
              border-color var(--duration-page) var(--ease),
              transform var(--duration-page) var(--ease),
              background var(--duration-page) var(--ease);
}

/* ── Variants ── */
.modern-card--glass {
  background: var(--color-bg-elevated);
}
.modern-card--bordered {
  border-width: 2px;
  box-shadow: none;
}
.modern-card--hoverable {
  cursor: pointer;
}
.modern-card--hoverable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--color-border-strong);
}

/* ── Header ── */
.modern-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--color-divider);
  min-height: 64px;
}
.modern-card__title-wrap {
  flex: 1;
  min-width: 0;
}
.modern-card__title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: -0.015em;
  margin: 0;
  line-height: var(--leading-tight);
}
.modern-card__description {
  margin: var(--space-1) 0 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  line-height: var(--leading-normal);
}
.modern-card__extra {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* ── Body ── */
.modern-card__body {
  width: 100%;
}
.modern-card--padded > .modern-card__body {
  padding: var(--space-6);
}
</style>
