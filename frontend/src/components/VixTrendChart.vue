<template>
  <div class="vix-trend-wrap">
    <div ref="chartEl" class="vix-trend" />
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, watch, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, GridComponent, TooltipComponent, LegendComponent,
  VisualMapComponent, CanvasRenderer,
])

const props = defineProps({
  // 历史行：单序列模式 { date, score, percentile, regime }；
  // 多轨道模式额外读取 row.size_tracks[key].greed / .regime。
  history: { type: Array, default: () => [] },
  // 单序列名（tooltip 标题）
  label: { type: String, default: '恐慌贪婪指数' },
  // 多轨道模式：[{ key, label }]；设置后按轨道画多条固定配色线
  trackKeys: { type: Array, default: null },
  height: { type: Number, default: 300 },
})

const chartEl = ref(null)
const chart = shallowRef(null)

const REGIME_LABELS = {
  extreme_fear: '极度恐慌', fear: '恐慌', neutral: '中性',
  greed: '贪婪', extreme_greed: '极度贪婪', unknown: '暂无数据',
}
// 拆分模式固定配色（按轨道身份，不按数值——数值语义色会和线身份冲突）
const TRACK_COLORS = {
  sh50: '#2563eb', hs300: '#7c3aed', zz500: '#ea580c',
  cyb: '#0d9488', kcb: '#d946ef',
}

function fmt(value, digits = 0) {
  return value == null || Number.isNaN(value) ? '-' : Number(value).toFixed(digits)
}

// 非交易日（周末）过滤：category 轴只渲染数组里的日期，混入周末行会
// 多出一个 x 槽。绘图前先剔除。
function isTradingDay(dateStr) {
  const d = new Date(dateStr + 'T00:00:00')
  const wd = d.getDay()
  return wd !== 0 && wd !== 6
}

function buildOption() {
  const rows = (props.history || [])
    .filter((d) => d && d.date && isTradingDay(d.date))
    .sort((a, b) => (a.date < b.date ? -1 : 1))
  const dates = rows.map((d) => d.date)

  if (props.trackKeys && props.trackKeys.length) {
    return buildMultiOption(rows, dates)
  }
  return buildSingleOption(rows, dates)
}

// 单序列（聚合）：量程固定 0-100，颜色随分值从绿（恐慌）过渡到红（贪婪）
function buildSingleOption(rows, dates) {
  // 缺失日保持 null 且不连线：不得把断点伪装成连续数据
  const scores = rows.map((d) => {
    const v = d.score
    return v != null && Number.isFinite(Number(v)) ? Number(v) : null
  })
  const pcts = rows.map((d) => (d.percentile != null ? d.percentile : null))

  return {
    grid: { left: 36, right: 20, top: 20, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e4e4e7', borderWidth: 1, padding: [8, 12],
      textStyle: { color: '#18181b', fontSize: 12 },
      extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(15,15,15,0.08);',
      formatter: (params) => {
        const idx = params[0] ? params[0].dataIndex : 0
        const score = scores[idx]
        const pct = pcts[idx]
        const regime = REGIME_LABELS[rows[idx]?.regime] || '暂无数据'
        return `
          <div style="font-weight:600;margin-bottom:4px;">${dates[idx]}</div>
          <div style="display:flex;justify-content:space-between;gap:16px;">
            <span style="color:#71717a;">${props.label}</span>
            <span style="font-weight:600;font-variant-numeric:tabular-nums;">${fmt(score)}</span>
          </div>
          <div style="display:flex;justify-content:space-between;gap:16px;">
            <span style="color:#71717a;">近 252 日百分位</span>
            <span style="font-weight:600;font-variant-numeric:tabular-nums;">${pct != null ? fmt(pct) + '%' : '-'}</span>
          </div>
          <div style="margin-top:4px;font-size:11px;color:#a1a1aa;">${regime}</div>
        `
      },
    },
    xAxis: {
      type: 'category', data: dates, boundaryGap: false,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: '#a1a1aa', fontSize: 10, formatter: (v) => v.slice(5) },
    },
    yAxis: {
      type: 'value', min: 0, max: 100,
      splitLine: { lineStyle: { color: '#f4f4f5' } },
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: '#a1a1aa', fontSize: 10 },
    },
    visualMap: {
      show: false, min: 0, max: 100,
      inRange: { color: ['#059669', '#facc15', '#dc2626'] },
    },
    series: [
      {
        name: props.label, type: 'line', data: scores,
        smooth: true, showSymbol: false, connectNulls: false,
        lineStyle: { width: 2.5 },
      },
    ],
  }
}

// 多轨道（大小盘拆分）：每条轨道一条固定配色线
function buildMultiOption(rows, dates) {
  const keys = props.trackKeys
  const series = keys.map((tk) => ({
    name: tk.label,
    type: 'line',
    data: rows.map((r) => {
      const v = r.size_tracks?.[tk.key]?.greed
      return v != null && Number.isFinite(Number(v)) ? Number(v) : null
    }),
    smooth: true, showSymbol: false, connectNulls: false,
    lineStyle: { width: 2 },
    color: TRACK_COLORS[tk.key] || '#71717a',
  }))

  return {
    grid: { left: 36, right: 20, top: 34, bottom: 28 },
    legend: {
      top: 0, icon: 'circle', itemWidth: 8, itemHeight: 8,
      textStyle: { color: '#71717a', fontSize: 11 },
      itemGap: 14,
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e4e4e7', borderWidth: 1, padding: [8, 12],
      textStyle: { color: '#18181b', fontSize: 12 },
      extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(15,15,15,0.08);',
      formatter: (params) => {
        const idx = params[0] ? params[0].dataIndex : 0
        const row = rows[idx]
        const lines = params
          .map((p) => {
            const t = row?.size_tracks?.[keys[p.seriesIndex]?.key]
            const regime = REGIME_LABELS[t?.regime] || ''
            const color = TRACK_COLORS[keys[p.seriesIndex]?.key] || '#71717a'
            return `<div style="display:flex;justify-content:space-between;gap:16px;">
              <span style="color:#71717a;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:6px;"></span>${p.seriesName}</span>
              <span style="font-weight:600;font-variant-numeric:tabular-nums;">${fmt(p.value)}${regime ? ` <span style="font-weight:400;color:#a1a1aa;font-size:11px;">${regime}</span>` : ''}</span>
            </div>`
          })
          .join('')
        return `<div style="font-weight:600;margin-bottom:4px;">${dates[idx]}</div>${lines}`
      },
    },
    xAxis: {
      type: 'category', data: dates, boundaryGap: false,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: '#a1a1aa', fontSize: 10, formatter: (v) => v.slice(5) },
    },
    yAxis: {
      type: 'value', min: 0, max: 100,
      splitLine: { lineStyle: { color: '#f4f4f5' } },
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: '#a1a1aa', fontSize: 10 },
    },
    series,
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

watch(() => [props.history, props.trackKeys], render, { deep: true })
</script>

<style scoped>
.vix-trend-wrap {
  position: relative;
}

.vix-trend {
  width: 100%;
  height: v-bind('props.height + "px"');
  min-height: 200px;
}
</style>
