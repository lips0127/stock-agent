<template>
  <div ref="chartEl" class="pe-history-chart" />
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer,
])

const props = defineProps({
  peHistory: { type: Array, default: () => [] },
  currentPe: { type: Number, default: null },
  height: { type: Number, default: 160 },
})

const chartEl = ref(null)
const chart = shallowRef(null)

function buildOption() {
  const dates = props.peHistory.map((p) => p.date)
  const pes = props.peHistory.map((p) => p.pe)
  // 百分位 band
  const valid = pes.filter((v) => v != null && Number.isFinite(v))
  let p10 = null, p90 = null
  if (valid.length) {
    const sorted = [...valid].sort((a, b) => a - b)
    p10 = sorted[Math.floor(sorted.length * 0.1)]
    p90 = sorted[Math.floor(sorted.length * 0.9)]
  }

  return {
    grid: { left: 50, right: 30, top: 20, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderColor: 'rgba(99, 102, 241, 0.4)',
      textStyle: { color: '#f1f5f9', fontSize: 12 },
      valueFormatter: (v) => v != null ? v.toFixed(1) : '--',
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#94a3b8', fontSize: 10 },
      axisTick: { show: false },
    },
    yAxis: {
      scale: true,
      splitLine: { lineStyle: { color: 'rgba(226, 232, 240, 0.5)', type: 'dashed' } },
      axisLabel: { color: '#94a3b8', fontSize: 10 },
    },
    series: [
      {
        type: 'line',
        data: pes,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#2563eb', width: 1.4 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(139, 92, 246, 0.18)' },
              { offset: 1, color: 'rgba(139, 92, 246, 0)' },
            ],
          },
        },
        markLine: {
          symbol: 'none',
          data: [
            props.currentPe != null ? { yAxis: props.currentPe, label: { formatter: `当前 ${props.currentPe.toFixed(1)}`, position: 'end', color: '#e11d48' }, lineStyle: { color: '#e11d48', type: 'dashed' } } : null,
            p10 != null ? { yAxis: p10, label: { formatter: `P10 ${p10.toFixed(1)}`, position: 'start', color: '#059669' }, lineStyle: { color: '#059669', type: 'dotted' } } : null,
            p90 != null ? { yAxis: p90, label: { formatter: `P90 ${p90.toFixed(1)}`, position: 'start', color: '#dc2626' }, lineStyle: { color: '#dc2626', type: 'dotted' } } : null,
          ].filter(Boolean),
        },
      },
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
  () => [props.peHistory, props.currentPe],
  () => chart.value?.setOption(buildOption(), true),
  { deep: true },
)
</script>

<style scoped>
.pe-history-chart {
  width: 100%;
  height: 160px;
}
</style>
