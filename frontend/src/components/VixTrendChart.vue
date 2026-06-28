<template>
  <div class="vix-trend-wrap">
    <div class="vix-trend-toolbar" aria-label="chart scale">
      <button
        v-for="mode in modes"
        :key="mode.value"
        class="mode-btn"
        :class="{ active: viewMode === mode.value }"
        type="button"
        @click="viewMode = mode.value"
      >
        {{ mode.label }}
      </button>
    </div>
    <div ref="chartEl" class="vix-trend" />
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, watch, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, GridComponent, TooltipComponent,
  MarkLineComponent, MarkAreaComponent, LegendComponent, CanvasRenderer,
])

const props = defineProps({
  history: { type: Array, default: () => [] },
  height: { type: Number, default: 220 },
  // v5: 阈值带改为 composite 百分位 10/30/70/90（在右 Y 轴 0-100 范围内）
  bands: {
    type: Array,
    default: () => [
      { from: 0,  to: 10, color: 'rgba(220,38,38,0.06)' },
      { from: 10, to: 30, color: 'rgba(249,115,22,0.06)' },
      { from: 30, to: 70, color: 'rgba(250,204,21,0.05)' },
      { from: 70, to: 90, color: 'rgba(132,204,22,0.06)' },
      { from: 90, to: 100, color: 'rgba(16,185,129,0.06)' },
    ],
  },
})

const chartEl = ref(null)
const chart = shallowRef(null)
const viewMode = ref('absolute')
const modes = [
  { value: 'absolute', label: '绝对' },
  { value: 'sensitive', label: '敏感' },
]

function cleanNumbers(values) {
  return values.filter((v) => typeof v === 'number' && Number.isFinite(v))
}

function quantile(values, q) {
  const nums = cleanNumbers(values).sort((a, b) => a - b)
  if (!nums.length) return null
  const pos = (nums.length - 1) * q
  const base = Math.floor(pos)
  const rest = pos - base
  if (nums[base + 1] == null) return nums[base]
  return nums[base] + rest * (nums[base + 1] - nums[base])
}

function median(values) {
  return quantile(values, 0.5)
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v))
}

function stretchSeries(values) {
  const nums = cleanNumbers(values)
  if (nums.length < 2) return values.map((v) => (v == null ? null : 50))
  const lo = quantile(nums, 0.05)
  const hi = quantile(nums, 0.95)
  if (lo == null || hi == null || Math.abs(hi - lo) < 0.0001) {
    return values.map((v) => (v == null ? null : 50))
  }
  return values.map((v) => (v == null ? null : clamp(((v - lo) / (hi - lo)) * 100, 0, 100)))
}

function robustPressure(values) {
  const nums = cleanNumbers(values)
  const med = median(nums)
  if (med == null) return values.map((v) => (v == null ? null : 50))
  const deviations = nums.map((v) => Math.abs(v - med))
  const mad = median(deviations) || 1
  return values.map((v) => {
    if (v == null) return null
    const z = (v - med) / (mad * 1.4826)
    return clamp(50 + z * 18, 0, 100)
  })
}

function fmt(value, digits = 1) {
  return value == null || Number.isNaN(value) ? '-' : Number(value).toFixed(digits)
}

function regimeForComposite(pct) {
  if (pct == null) return '暂无数据'
  if (pct < 10) return '极度恐慌'
  if (pct < 30) return '恐慌'
  if (pct <= 70) return '中性'
  if (pct <= 90) return '贪婪'
  return '极度贪婪'
}

function buildOption() {
  const dates = props.history.map((d) => d.date)
  // 仅把多 ETF 合成的 VIX 当作可信值；降级(单50ETF)/缺失显示为断线，不画假直线
  const values = props.history.map((d) =>
    d.vix != null && d.vix_source === 'multi_etf' ? d.vix : null)
  const fg = props.history.map((d) => d.fear_greed)
  const composite = props.history.map((d) => d.composite_score)
  const percentile = props.history.map((d) => d.composite_percentile)
  const sensitive = viewMode.value === 'sensitive'
  const displayVix = sensitive ? robustPressure(values) : values
  const displayFg = sensitive ? stretchSeries(fg) : fg
  const displayComposite = sensitive ? stretchSeries(composite) : composite
  const displayPercentile = sensitive ? stretchSeries(percentile) : percentile

  return {
    legend: {
      data: ['VIX', 'FG', 'Composite', 'Percentile'],
      top: 0,
      right: 0,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: '#71717a', fontSize: 11 },
    },
    grid: { left: 36, right: 36, top: 30, bottom: 28, containLabel: false },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e4e4e7',
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: '#18181b', fontSize: 12 },
      extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(15,15,15,0.08);',
      formatter: (params) => {
        const [v, g, c, p] = params
        const idx = v ? v.dataIndex : (g ? g.dataIndex : 0)
        const rawVix = values[idx]
        const rawFg = fg[idx]
        const rawComposite = composite[idx]
        const rawPct = percentile[idx]
        const rawZ = props.history[idx]?.vix_zscore
        const zText = rawZ != null ? ` (Z=${rawZ.toFixed(1)})` : ''
        const rawLine = sensitive
          ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid #f4f4f5;color:#71717a;font-size:11px;">
              原始 VIX ${fmt(rawVix, 2)}${zText} · FG ${fmt(rawFg, 0)} · 综合 ${fmt(rawComposite, 1)} · 百分位 ${fmt(rawPct, 0)}%
            </div>`
          : ''
        return `
          <div style="font-weight:600;margin-bottom:4px;">${(v || g || c || p).axisValue}</div>
          <div style="display:flex;justify-content:space-between;gap:16px;">
            <span style="color:#71717a;">${sensitive ? 'VIX压力' : '合成VIX'}</span>
            <span style="font-weight:600;font-variant-numeric:tabular-nums;">${v ? fmt(v.value, sensitive ? 0 : 2) : '-'}${!sensitive && rawZ != null ? ` <span style="color:#a1a1aa;font-weight:400;">Z=${rawZ.toFixed(1)}</span>` : ''}</span>
          </div>
          <div style="display:flex;justify-content:space-between;gap:16px;">
            <span style="color:#71717a;">恐惧贪婪</span>
            <span style="font-weight:600;font-variant-numeric:tabular-nums;">${g ? fmt(g.value, 0) : '-'}</span>
          </div>
          <div style="display:flex;justify-content:space-between;gap:16px;">
            <span style="color:#1e1b4b;">综合位置</span>
            <span style="font-weight:600;font-variant-numeric:tabular-nums;">${c ? fmt(c.value, 1) : '-'}</span>
          </div>
          <div style="display:flex;justify-content:space-between;gap:16px;">
            <span style="color:#7c3aed;">滚动百分位</span>
            <span style="font-weight:600;font-variant-numeric:tabular-nums;">${p ? fmt(p.value, 0) + '%' : '-'}</span>
          </div>
          ${rawLine}
          <div style="margin-top:4px;font-size:11px;color:#a1a1aa;">${regimeForComposite(rawPct)}</div>
        `
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: '#a1a1aa',
        fontSize: 10,
        formatter: (v) => v.slice(5),
      },
    },
    yAxis: [
      {
        // 左轴：合成 VIX 原始值（绝对模式）
        type: 'value',
        name: sensitive ? '压力' : 'VIX',
        position: 'left',
        min: sensitive ? 0 : (val) => Math.max(0, Math.floor(val.min - 2)),
        max: sensitive ? 100 : (val) => Math.ceil(val.max + 2),
        splitLine: { lineStyle: { color: '#f4f4f5' } },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#a1a1aa', fontSize: 10 },
        nameTextStyle: { color: '#a1a1aa', fontSize: 10, padding: [0, 0, 0, -20] },
      },
      {
        // 右轴：composite / percentile / FG 共享 0-100
        type: 'value',
        name: sensitive ? '相对' : '综合/百分位',
        position: 'right',
        min: 0,
        max: 100,
        splitLine: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#a1a1aa', fontSize: 10 },
      },
    ],
    series: [
      {
        name: 'VIX',
        type: 'line',
        data: displayVix,
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2, color: '#4f46e5' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(79,70,229,0.18)' },
            { offset: 1, color: 'rgba(79,70,229,0)' },
          ]),
        },
      },
      {
        name: 'FG',
        type: 'line',
        yAxisIndex: 1,
        data: displayFg,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#a1a1aa', type: 'dashed' },
      },
      {
        name: 'Composite',
        type: 'line',
        yAxisIndex: 1,
        data: displayComposite,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#1e1b4b' },
        // v5: 百分位阈值带 + 阈值线（仅绝对模式 + Composite 线上叠加）
        markArea: !sensitive ? {
          silent: true,
          itemStyle: { opacity: 0.6 },
          data: props.bands.map((b) => [
            { yAxis: b.from, itemStyle: { color: b.color } },
            { yAxis: b.to },
          ]),
        } : undefined,
        markLine: !sensitive ? {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#d4d4d8', type: 'dashed', width: 1 },
          data: [
            { yAxis: 30, label: { show: false } },
            { yAxis: 70, label: { show: false } },
          ],
        } : undefined,
      },
      {
        // v5 新增：composite 滚动百分位（右轴）
        name: 'Percentile',
        type: 'line',
        yAxisIndex: 1,
        data: displayPercentile,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#7c3aed', type: 'dotted' },
      },
    ],
  }
}

function render() {
  if (!chartEl.value) return
  if (!chart.value) {
    chart.value = echarts.init(chartEl.value)
  }
  chart.value.setOption(buildOption(), true)
}

function resize() {
  chart.value?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart.value?.dispose()
  chart.value = null
})

watch(() => props.history, render, { deep: true })
watch(viewMode, render)
</script>

<style scoped>
.vix-trend-wrap {
  position: relative;
}

.vix-trend-toolbar {
  position: absolute;
  top: 0;
  right: 4px;
  z-index: 2;
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid #e4e4e7;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(10px);
}

.mode-btn {
  height: 24px;
  padding: 0 10px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #71717a;
  font-size: 12px;
  cursor: pointer;
}

.mode-btn.active {
  background: #4f46e5;
  color: #fff;
  box-shadow: 0 1px 4px rgba(79, 70, 229, 0.25);
}

.vix-trend {
  width: 100%;
  height: v-bind('props.height + "px"');
  min-height: 200px;
}
</style>
