<template>
  <div class="stat-card" :class="`stat-card--${tone}`">
    <div class="stat-card__top-line" />
    <div v-if="label || icon || $slots.label" class="stat-card__head">
      <span v-if="icon" class="stat-card__icon" :aria-hidden="true">{{ icon }}</span>
      <span v-if="label || $slots.label" class="stat-card__label">
        <slot name="label">{{ label }}</slot>
      </span>
      <span v-if="$slots.badge" class="stat-card__badge">
        <slot name="badge" />
      </span>
    </div>
    <div class="stat-card__value">{{ value }}</div>
    <div v-if="hint || $slots.hint" class="stat-card__hint">
      <slot name="hint">
        <span v-if="hint">{{ hint }}</span>
      </slot>
    </div>
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '—' },
  hint: { type: String, default: '' },
  icon: { type: String, default: '' },
  tone: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'up', 'down', 'accent', 'warning', 'glass', 'danger', 'muted'].includes(v),
  },
})
</script>

<style scoped>
.stat-card {
  position: relative;
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5) var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  overflow: hidden;
  transition: all var(--duration-page) var(--ease);
}

/* 顶部色线：保留原有设计亮点 */
.stat-card__top-line {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: transparent;
  transition: background var(--duration-page) var(--ease);
}
.stat-card--up      .stat-card__top-line { background: var(--color-up); }
.stat-card--down    .stat-card__top-line { background: var(--color-down); }
.stat-card--accent  .stat-card__top-line { background: var(--color-accent); }
.stat-card--warning .stat-card__top-line { background: var(--color-warning); }
.stat-card--danger  .stat-card__top-line { background: var(--color-danger); }
.stat-card--muted   .stat-card__top-line { background: var(--color-text-tertiary); }

.stat-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-sm);
  transform: translateY(-2px);
}
.stat-card--accent:hover {
  box-shadow: var(--shadow-glow);
}
.stat-card--glass:hover {
  box-shadow: var(--shadow-md);
}

/* ── Head ── */
.stat-card__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.stat-card__icon {
  font-size: var(--text-base);
  line-height: 1;
  flex-shrink: 0;
}
.stat-card__label {
  font-weight: var(--weight-medium);
  letter-spacing: -0.005em;
  color: var(--color-text-secondary);
}
.stat-card__badge {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
}

/* ── Value ── */
.stat-card__value {
  font-size: var(--text-3xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  line-height: var(--leading-tight);
  letter-spacing: -0.025em;
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum';
}

.stat-card__hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-top: var(--space-1);
  line-height: var(--leading-normal);
}

/* ── Tone variants ── */
.stat-card--up .stat-card__value      { color: var(--color-up); }
.stat-card--down .stat-card__value    { color: var(--color-down); }
.stat-card--warning .stat-card__value { color: var(--color-warning); }
.stat-card--danger .stat-card__value  { color: var(--color-danger); }
.stat-card--muted .stat-card__value   { color: var(--color-text-tertiary); }

.stat-card--accent {
  background: linear-gradient(135deg, #eef2ff 0%, #ffffff 60%);
  border-color: rgba(79, 70, 229, 0.12);
}
.stat-card--accent .stat-card__value { color: var(--color-accent-text); }
.stat-card--accent .stat-card__label { color: var(--color-accent-text); }

.stat-card--glass {
  background: var(--color-bg-glass);
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%);
  border-color: rgba(228, 228, 231, 0.7);
}
</style>
