<template>
  <div class="vix-gauge">
    <!-- 半圆弧 SVG -->
    <svg :viewBox="`0 0 ${size} ${size / 2 + 10}`" class="vix-gauge__svg" :aria-label="`恐慌贪婪指数 ${value ?? '-'}`">
      <!-- 背景弧 -->
      <path
        :d="arcPath(bgRadius)"
        fill="none"
        :stroke="bgStroke"
        stroke-width="14"
        stroke-linecap="round"
      />
      <!-- 渐变定义：0（恐慌，绿）→ 100（贪婪，红） -->
      <defs>
        <linearGradient :id="`gauge-grad-${uid}`" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%"   stop-color="#059669" />
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
      <!-- 指针（三角箭头） -->
      <g v-if="value != null" :transform="`translate(${pointerX}, ${pointerY}) rotate(${pointerAngle})`" class="vix-gauge__pointer">
        <circle r="6" :fill="pointerColor" />
        <path d="M 0 -3 L 14 0 L 0 3 Z" :fill="pointerColor" />
      </g>
    </svg>

    <!-- 中心数值 -->
    <div class="vix-gauge__readout">
      <div class="vix-gauge__value">
        <span class="vix-gauge__num">{{ value != null ? value.toFixed(0) : '-' }}</span>
        <span class="vix-gauge__suffix">分</span>
      </div>
      <div class="vix-gauge__regime" :class="`vix-gauge__regime--${regimeKey}`">
        {{ regimeLabel }}
      </div>
      <div v-if="percentile != null" class="vix-gauge__percentile">
        近 252 日百分位
        <strong>{{ percentile.toFixed(0) }}%</strong>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // 恐慌贪婪指数（fear_greed_v7，0=极度恐慌 100=极度贪婪）
  value: { type: Number, default: null },
  // 近 252 日滚动百分位（regime 依据，非固定阈值）
  percentile: { type: Number, default: null },
  // extreme_fear/fear/neutral/greed/extreme_greed/unknown
  regime: { type: String, default: 'unknown' },
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
  return Math.max(0, Math.min(1, props.value / 100))
})

const dashOffset = computed(() => arcLength.value * (1 - progress.value))

// SVG 半圆弧 path (从左到右)
function arcPath(r) {
  const cx = centerX.value
  const cy = centerY.value
  return `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`
}

// 指针：当前分数位置（圆点 + 箭头）
const pointerAngle = computed(() => {
  const t = (props.value != null ? props.value : 0) / 100
  const angle = Math.PI - t * Math.PI
  return ((angle * 180) / Math.PI - 90).toFixed(1)
})
const pointerX = computed(() => {
  const t = (props.value != null ? props.value : 0) / 100
  const angle = Math.PI - t * Math.PI
  return centerX.value + Math.cos(angle) * (bgRadius.value - 18)
})
const pointerY = computed(() => {
  const t = (props.value != null ? props.value : 0) / 100
  const angle = Math.PI - t * Math.PI
  return centerY.value - Math.sin(angle) * (bgRadius.value - 18)
})

// 指针颜色按 regime（滚动百分位分档）取色，与 A 股红涨绿跌习惯一致：
// 恐慌=绿、贪婪=红；不按绝对分数取色，避免与分档标签互相矛盾。
const pointerColor = computed(() => {
  const map = {
    extreme_fear: '#047857',
    fear: '#059669',
    neutral: '#d97706',
    greed: '#ea580c',
    extreme_greed: '#dc2626',
  }
  return map[props.regime] || '#a1a1aa'
})

const bgStroke = 'rgba(228, 228, 231, 0.7)'

const regimeKey = computed(() => {
  if (props.regime === 'extreme_greed') return 'risk-high'
  if (props.regime === 'greed') return 'risk-elevated'
  if (props.regime === 'extreme_fear') return 'stress-high'
  if (props.regime === 'fear') return 'stress-elevated'
  if (props.regime === 'neutral') return 'neutral'
  return 'muted'
})

const regimeLabel = computed(() => {
  const map = {
    extreme_greed: '极度贪婪',
    greed: '贪婪',
    neutral: '中性',
    fear: '恐慌',
    extreme_fear: '极度恐慌',
    unknown: '暂无数据',
  }
  return map[props.regime] || '暂无数据'
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
.vix-gauge__regime--stress-elevated { background: #dbeafe; color: #1d4ed8; } /* fear */
.vix-gauge__regime--stress-high     { background: #bfdbfe; color: #1e40af; } /* extreme_fear */
.vix-gauge__regime--risk-elevated   { background: #fee2e2; color: #b91c1c; } /* greed */
.vix-gauge__regime--risk-high       { background: #fecaca; color: #991b1b; } /* extreme_greed */
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
</style>
