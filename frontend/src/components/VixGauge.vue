<template>
  <div class="vix-gauge">
    <!-- 半圆弧 SVG -->
    <svg :viewBox="`0 0 ${size} ${size / 2 + 10}`" class="vix-gauge__svg" :aria-label="`综合 ${value}`">
      <!-- 背景弧 -->
      <path
        :d="arcPath(bgRadius)"
        fill="none"
        :stroke="bgStroke"
        stroke-width="14"
        stroke-linecap="round"
      />
      <!-- 渐变定义 -->
      <defs>
        <linearGradient :id="`gauge-grad-${uid}`" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%"   stop-color="#10b981" />
          <stop offset="35%"  stop-color="#facc15" />
          <stop offset="70%"  stop-color="#f97316" />
          <stop offset="100%" stop-color="#dc2626" />
        </linearGradient>
      </defs>
      <!-- 进度弧 -->
      <path
        :d="arcPath(bgRadius)"
        fill="none"
        :stroke="`url(#gauge-grad-${uid})`"
        stroke-width="14"
        stroke-linecap="round"
        :stroke-dasharray="arcLength"
        :stroke-dashoffset="dashOffset"
        class="vix-gauge__arc"
      />
      <!-- 阈值刻度（基于百分位 10/30/70/90） -->
      <g class="vix-gauge__ticks">
        <line v-for="t in ticks" :key="t.value"
          :x1="t.x1" :y1="t.y1" :x2="t.x2" :y2="t.y2"
          :stroke="t.color" stroke-width="2" stroke-linecap="round" />
      </g>
      <!-- 指针（三角箭头） -->
      <g v-if="value != null" :transform="`translate(${pointerX}, ${pointerY}) rotate(${pointerAngle})`" class="vix-gauge__pointer">
        <circle r="6" :fill="pointerColor" />
        <path d="M 0 -3 L 14 0 L 0 3 Z" :fill="pointerColor" />
      </g>
    </svg>

    <!-- 中心数值 -->
    <div class="vix-gauge__readout">
      <div class="vix-gauge__value">
        <span class="vix-gauge__num">{{ value != null ? value.toFixed(1) : '—' }}</span>
        <span class="vix-gauge__suffix">分</span>
      </div>
      <div class="vix-gauge__regime" :class="`vix-gauge__regime--${regimeKey}`">
        {{ regimeLabel }}
      </div>
      <div v-if="percentile != null" class="vix-gauge__percentile">
        历史百分位
        <strong>{{ percentile.toFixed(0) }}%</strong>
      </div>
      <div v-if="vix != null" class="vix-gauge__vix-sub">
        合成VIX {{ vix.toFixed(2) }}
        <span v-if="vixZscore != null" class="vix-gauge__zscore">
          Z={{ vixZscore.toFixed(1) }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // v5: 综合位置 composite_score（0-100）
  value: { type: Number, default: null },
  // 历史百分位（基于 composite，0-100）
  percentile: { type: Number, default: null },
  // v5: composite_regime（extreme_fear/fear/neutral/greed/extreme_greed）
  regime: { type: String, default: 'neutral' },
  // v5 新增：合成 VIX 原始值（用于副标题）
  vix: { type: Number, default: null },
  // v5 新增：Z-Score
  vixZscore: { type: Number, default: null },
  // 仪表盘量程（v5 改为 0-100）
  min: { type: Number, default: 0 },
  max: { type: Number, default: 100 },
  size: { type: Number, default: 220 },
})

const uid = Math.random().toString(36).slice(2, 8)

const bgRadius = computed(() => props.size / 2 - 16)
const centerX = computed(() => props.size / 2)
const centerY = computed(() => props.size / 2)

// 弧的总长（半圆）
const arcLength = computed(() => Math.PI * bgRadius.value)

// 进度：值 → 0-1
const progress = computed(() => {
  if (props.value == null) return 0
  const t = (props.value - props.min) / (props.max - props.min)
  return Math.max(0, Math.min(1, t))
})

const dashOffset = computed(() => arcLength.value * (1 - progress.value))

// SVG 半圆弧 path (从左到右)
function arcPath(r) {
  const cx = centerX.value
  const cy = centerY.value
  return `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`
}

// 阈值刻度：基于百分位 10/30/70/90（v5）
const ticks = computed(() => {
  const stops = [
    { value: 10, color: '#dc2626' },   // extreme_fear 边界
    { value: 30, color: '#f97316' },   // fear 边界
    { value: 70, color: '#facc15' },   // greed 边界
    { value: 90, color: '#10b981' },   // extreme_greed 边界
  ]
  return stops.map((s) => {
    const t = (s.value - props.min) / (props.max - props.min)
    const angle = Math.PI - t * Math.PI   // 从 π (左) 顺时针到 0 (右)
    const r1 = bgRadius.value + 6
    const r2 = bgRadius.value + 14
    return {
      value: s.value,
      color: s.color,
      x1: centerX.value + Math.cos(angle) * r1,
      y1: centerY.value - Math.sin(angle) * r1,
      x2: centerX.value + Math.cos(angle) * r2,
      y2: centerY.value - Math.sin(angle) * r2,
    }
  })
})

// 指针：当前 composite_score 位置（圆点 + 箭头）
const pointerAngle = computed(() => {
  const t = (props.value != null ? props.value - props.min : 0) / (props.max - props.min)
  const angle = Math.PI - t * Math.PI
  return ((angle * 180) / Math.PI - 90).toFixed(1)
})
const pointerX = computed(() => {
  const t = (props.value != null ? props.value - props.min : 0) / (props.max - props.min)
  const angle = Math.PI - t * Math.PI
  return centerX.value + Math.cos(angle) * (bgRadius.value - 18)
})
const pointerY = computed(() => {
  const t = (props.value != null ? props.value - props.min : 0) / (props.max - props.min)
  const angle = Math.PI - t * Math.PI
  return centerY.value - Math.sin(angle) * (bgRadius.value - 18)
})
// v5: 颜色基于百分位 5 档
const pointerColor = computed(() => {
  if (props.value == null) return '#a1a1aa'
  if (props.value < 10) return '#dc2626'   // extreme_fear
  if (props.value < 30) return '#f97316'   // fear
  if (props.value <= 70) return '#facc15'  // neutral
  if (props.value <= 90) return '#84cc16'  // greed
  return '#10b981'                          // extreme_greed
})

const bgStroke = 'rgba(228, 228, 231, 0.7)'

const regimeKey = computed(() => {
  // v5: 语义反转——贪婪是风险（warning 色调），恐慌是机会（success 色调）
  if (props.regime === 'extreme_greed') return 'warning'
  if (props.regime === 'greed') return 'warning-soft'
  if (props.regime === 'extreme_fear') return 'success'
  if (props.regime === 'fear') return 'success-soft'
  if (props.regime === 'neutral') return 'neutral'
  return 'muted'
})

const regimeLabel = computed(() => {
  const map = {
    extreme_greed: '极度贪婪 · 顶部风险',
    greed: '贪婪 · 警惕风险',
    neutral: '中性',
    fear: '恐慌 · 关注机会',
    extreme_fear: '极度恐慌 · 底部机会',
    unknown: '暂无数据',
  }
  return map[props.regime] || '中性'
})
</script>

<style scoped>
.vix-gauge {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}
.vix-gauge__svg {
  width: 220px;
  height: 130px;
  display: block;
}
.vix-gauge__arc {
  transition: stroke-dashoffset 800ms var(--ease);
}
.vix-gauge__pointer {
  transition: transform 800ms var(--ease);
}

.vix-gauge__readout {
  text-align: center;
  margin-top: -28px;       /* 拉进半圆内 */
  position: relative;
  z-index: 1;
}
.vix-gauge__value {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 4px;
  line-height: 1;
}
.vix-gauge__num {
  font-size: var(--text-4xl);
  font-weight: var(--weight-bold);
  color: var(--color-text-primary);
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum';
}
.vix-gauge__suffix {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-tertiary);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.vix-gauge__regime {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 10px;
  margin-top: 6px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.02em;
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}
.vix-gauge__regime--neutral     { background: #fef3c7; color: #b45309; }
.vix-gauge__regime--success-soft { background: #d1fae5; color: #047857; }  /* fear → 机会 */
.vix-gauge__regime--success     { background: #a7f3d0; color: #065f46; }  /* extreme_fear */
.vix-gauge__regime--warning-soft { background: #fee2e2; color: #b91c1c; }  /* greed → 风险 */
.vix-gauge__regime--warning     { background: #fecaca; color: #991b1b; }  /* extreme_greed */
.vix-gauge__regime--muted       { background: var(--color-bg-muted); color: var(--color-text-tertiary); }
.vix-gauge__percentile {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  letter-spacing: 0.01em;
}
.vix-gauge__percentile strong {
  color: var(--color-text-primary);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
  margin-left: 4px;
}
.vix-gauge__vix-sub {
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.vix-gauge__zscore {
  margin-left: 6px;
  font-family: var(--font-mono);
  color: var(--color-text-secondary);
}
</style>
