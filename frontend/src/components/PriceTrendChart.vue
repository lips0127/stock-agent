<template>
  <div ref="chartEl" class="price-trend-chart" />
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import {
  LineChart, BarChart, ScatterChart,
} from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkPointComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, BarChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent,
  MarkLineComponent, MarkPointComponent, CanvasRenderer,
])

// markers: [{ date, value, label, kind: 'extreme' | 'normal' }]
// - kind='extreme'  → 在 K 线上画 markPoint（大点 + label）
// - kind='normal'   → 在副 y 轴画 scatter（小点）
// 同一组件内 extreme/normal 共存，但 typical 用例是「舆情分数叠加 K 线」。
const props = defineProps({
  priceHistory: { type: Array, default: () => [] },
  currentPrice: { type: Number, default: null },
  markers: { type: Array, default: () => [] },
  markerMin: { type: Number, default: 0 },
  markerMax: { type: Number, default: 100 },
  markerLabel: { type: String, default: '舆情分数' },
  height: { type: Number, default: 220 },
})

const chartEl = ref(null)
const chart = shallowRef(null)

function buildOption() {
  const dates = props.priceHistory.map((r) => r.date)
  const closes = props.priceHistory.map((r) => r.close)
  const volumes = props.priceHistory.map((r) => r.volume)

  // MA20
  const ma20 = closes.map((_, i) => {
    if (i < 19) return null
    const slice = closes.slice(i - 19, i + 1)
    return +(slice.reduce((a, b) => a + b, 0) / 20).toFixed(2)
  })

  const dateIndex = new Map(dates.map((d, i) => [d, i]))

  // 极端事件：markPoint（不占数据 series）
  const extremeMarkers = props.markers
    .filter((m) => m.kind === 'extreme' && dateIndex.has(m.date))
    .map((m) => ({
      name: m.label || '极端',
      coord: [m.date, closes[dateIndex.get(m.date)]],
      value: m.value,
      label: { formatter: m.label || '✱', color: m.color || '#e11d48' },
      itemStyle: { color: m.color || '#e11d48' },
    }))

  // 普通事件：scatter on 副 y 轴
  const normalScatter = props.markers
    .filter((m) => m.kind !== 'extreme' && dateIndex.has(m.date))
    .map((m) => ({
      name: m.label || '情绪',
      value: [m.date, m.value],
      itemStyle: { color: m.color || '#6366f1', opacity: 0.6 },
    }))

  const hasMarkers = props.markers.length > 0
  const hasNormal = normalScatter.length > 0

  return {
    grid: [
      { left: 60, right: hasMarkers ? 60 : 50, top: 20, height: '60%' },
      { left: 60, right: hasMarkers ? 60 : 50, top: '72%', height: '20%' },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderColor: 'rgba(99, 102, 241, 0.4)',
      textStyle: { color: '#f1f5f9', fontSize: 12 },
    },
    legend: {
      data: ['收盘价', 'MA20'].concat(hasMarkers ? [props.markerLabel] : []),
      top: 0,
      right: 10,
      textStyle: { color: '#64748b', fontSize: 11 },
      itemWidth: 14,
      itemHeight: 8,
    },
    xAxis: [
      {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        axisTick: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { show: false },
        axisTick: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        splitLine: { lineStyle: { color: 'rgba(226, 232, 240, 0.5)', type: 'dashed' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      {
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: {
          color: '#94a3b8',
          fontSize: 10,
          formatter: (v) => v >= 1e8 ? `${(v / 1e8).toFixed(1)}亿` : v >= 1e4 ? `${(v / 1e4).toFixed(0)}万` : v,
        },
        splitLine: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      ...(hasNormal ? [{
        scale: true,
        min: props.markerMin,
        max: props.markerMax,
        position: 'right',
        splitLine: { show: false },
        axisLabel: { color: '#6366f1', fontSize: 10 },
        axisLine: { show: false },
        axisTick: { show: false },
        name: props.markerLabel,
        nameTextStyle: { color: '#6366f1', fontSize: 10, padding: [0, 0, 0, -28] },
      }] : []),
    ],
    series: [
      {
        name: '收盘价',
        type: 'line',
        data: closes,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#4f46e5', width: 1.6 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(79, 70, 229, 0.18)' },
              { offset: 1, color: 'rgba(79, 70, 229, 0)' },
            ],
          },
        },
        markLine: props.currentPrice ? {
          symbol: 'none',
          data: [{
            yAxis: props.currentPrice,
            label: { formatter: '当前价', position: 'end', color: '#e11d48' },
            lineStyle: { color: '#e11d48', type: 'dashed' },
          }],
        } : undefined,
        markPoint: extremeMarkers.length ? {
          symbol: 'pin',
          symbolSize: 38,
          data: extremeMarkers,
        } : undefined,
      },
      {
        name: 'MA20',
        type: 'line',
        data: ma20,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#f59e0b', width: 1.2, opacity: 0.8 },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: { color: 'rgba(99, 102, 241, 0.35)' },
      },
      ...(hasNormal ? [{
        name: props.markerLabel,
        type: 'scatter',
        yAxisIndex: 2,
        symbolSize: 7,
        data: normalScatter,
        tooltip: {
          formatter: (p) => `${p.value[0]}<br/>${props.markerLabel}: ${p.value[1]}`,
        },
      }] : []),
    ],
  }
}

function resize() {
  chart.value?.resize()
}

onMounted(() => {
  chart.value = echarts.init(chartEl.value, null, { renderer: 'canvas' })
  chart.value.setOption(buildOption())
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart.value?.dispose()
})

watch(
  () => [props.priceHistory, props.currentPrice, props.markers],
  () => chart.value?.setOption(buildOption(), true),
  { deep: true },
)
</script>

<style scoped>
.price-trend-chart {
  width: 100%;
  height: 220px;
}
</style>
