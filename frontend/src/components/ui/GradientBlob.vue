<template>
  <div
    class="blob"
    :class="[`blob--${position}`, `blob--${size}`]"
    :style="cssVars"
    aria-hidden="true"
  />
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  position: {
    type: String,
    default: 'tr',
    validator: (v) => ['tr', 'tl', 'br', 'bl'].includes(v),
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
  c1: { type: String, default: '#eef2ff' },
  c2: { type: String, default: 'rgba(238, 242, 255, 0)' },
  c3: { type: String, default: 'rgba(199, 210, 254, 0.5)' },
  intensity: { type: Number, default: 1 },
})

const cssVars = computed(() => ({
  '--c1': props.c1,
  '--c2': props.c2,
  '--c3': props.c3,
  '--intensity': props.intensity,
}))
</script>

<style scoped>
.blob {
  position: absolute;
  border-radius: 50%;
  background: radial-gradient(
    circle at center,
    var(--c1) 0%,
    var(--c3) 35%,
    var(--c2) 70%
  );
  filter: blur(40px);
  pointer-events: none;
  z-index: 0;
  opacity: var(--intensity);
  will-change: transform;
}

/* 位置 */
.blob--tr { top: -120px;    right: -120px; }
.blob--tl { top: -120px;    left: -120px;  }
.blob--br { bottom: -120px; right: -120px; }
.blob--bl { bottom: -120px; left: -120px;  }

/* 尺寸 */
.blob--sm { width: 280px; height: 280px; }
.blob--md { width: 420px; height: 420px; }
.blob--lg { width: 560px; height: 560px; }
</style>
