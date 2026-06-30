<template>
  <div ref="wrapperRef" class="kline-chart-wrapper" @mousedown.capture="onWrapperMouseDown">
    <div v-if="loading" class="kline-loading">
      <div class="kline-loading__skeleton">
        <div class="skeleton-bar" v-for="i in 8" :key="i" :style="{ width: (60 + Math.random() * 40) + '%' }" />
      </div>
    </div>
    <div v-else-if="error" class="kline-error">
      <el-icon :size="20"><Warning /></el-icon>
      <span>{{ error }}</span>
    </div>
    <v-chart
      v-else-if="option"
      ref="chartRef"
      :option="option"
      :style="{ height: height }"
      autoresize
      @click="onChartClick"
    />

    <Teleport to="body">
      <div
        v-if="popup.visible"
        class="kline-popup-overlay"
        @click.self="closePopup"
      >
        <div
          class="kline-popup"
          :style="popupStyle"
          @click.stop
        >
          <div class="kline-popup__header">
            <span class="kline-popup__title">{{ popup.barTime }}</span>
            <button class="kline-popup__close" @click="closePopup" title="关闭">&times;</button>
          </div>

          <table class="kline-popup__ohlc">
            <tr>
              <td>开盘</td><td :class="{ 'num-up': popup.isUp, 'num-down': !popup.isUp }">{{ popup.bar?.open }}</td>
              <td>收盘</td><td :class="{ 'num-up': popup.isUp, 'num-down': !popup.isUp }">{{ popup.bar?.close }}</td>
            </tr>
            <tr>
              <td>最高</td><td :class="{ 'num-up': popup.isUp, 'num-down': !popup.isUp }">{{ popup.bar?.high }}</td>
              <td>最低</td><td :class="{ 'num-up': popup.isUp, 'num-down': !popup.isUp }">{{ popup.bar?.low }}</td>
            </tr>
            <tr>
              <td>涨跌</td>
              <td :class="{ 'num-up': popup.isUp, 'num-down': !popup.isUp }" colspan="3">
                {{ popup.change >= 0 ? '+' : '' }}{{ popup.changeText }}
              </td>
            </tr>
          </table>

          <div v-if="popup.posts.length" class="kline-popup__section">
            <div class="kline-popup__section-title">
              大V观点 <span class="kline-popup__count">{{ popup.posts.length }}</span>
            </div>
            <div class="kline-popup__posts">
              <div
                v-for="p in popup.posts"
                :key="p.postId"
                class="kline-popup__post"
                :style="{ borderLeftColor: stanceColor(p.stance) }"
              >
                <div class="popup-post__head">
                  <span class="popup-post__name">{{ p.name }}</span>
                  <span class="popup-post__stance" :style="{ background: stanceColor(p.stance) }">
                    {{ stanceLabel(p.stance) }} · {{ p.confidence || '?' }}
                  </span>
                </div>
                <a v-if="p.title && p.url" :href="p.url" target="_blank" class="popup-post__title">{{ p.title }} &#x2197;</a>
                <span v-else-if="p.title" class="popup-post__title">{{ p.title }}</span>
                <div v-if="p.stanceAssets && p.stanceAssets.length" class="popup-post__assets">
                  <span
                    v-for="(a, i) in p.stanceAssets"
                    :key="i"
                    class="popup-post__asset"
                    :style="{
                      background: stanceColor(a.stance),
                      color: '#fff',
                    }"
                    :title="a.reason || ''"
                  >
                    <span v-if="a.code" class="popup-post__asset-code">{{ a.code }}</span>
                    <span class="popup-post__asset-name">{{ a.asset }}</span>
                    <span class="popup-post__asset-stance">{{ stanceLabel(a.stance) }}</span>
                  </span>
                </div>
                <div v-if="p.summary" class="popup-post__summary">{{ p.summary }}</div>
              </div>
            </div>
          </div>

          <div v-else class="kline-popup__empty">
            该时间点暂无大V观点
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { use } from 'echarts/core'
import { CandlestickChart, ScatterChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, MarkPointComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { Warning } from '@element-plus/icons-vue'

use([CandlestickChart, ScatterChart, LineChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, MarkPointComponent, MarkLineComponent, CanvasRenderer])

const props = defineProps({
  klineData: { type: Object, default: () => ({ bars: [] }) },
  posts: { type: Array, default: () => [] },
  height: { type: String, default: '420px' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  highlightPostId: { type: [String, Number], default: null },
})

const emit = defineEmits(['postClick'])

const DS = {
  // Apple-style design tokens
  textPrimary: '#1d1d1f',
  textSecondary: '#6e6e73',
  textTertiary: '#aeaeb2',
  border: '#e5e5ea',
  borderStrong: '#d1d1d6',
  divider: '#f2f2f7',
  bgElevated: '#ffffff',
  bgMuted: '#f5f5f7',
  accent: '#0071e3',
  // Candlestick colors: A-share convention (red up, green down)
  candleUp: '#ff3b30',
  candleDown: '#34c759',
  candleUpBg: 'rgba(255,59,48,0.08)',
  candleDownBg: 'rgba(52,199,89,0.08)',
  radiusSm: 6,
  radiusMd: 10,
  radiusLg: 16,
  fontSm: 11,
  fontMd: 13,
  shadowSm: '0 1px 3px rgba(0,0,0,0.04)',
  shadowMd: '0 4px 16px rgba(0,0,0,0.08), 0 1px 4px rgba(0,0,0,0.04)',
  shadowLg: '0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.04)',
}

const stanceColor = (s) => ({
  bullish: '#34c759', bearish: '#ff3b30', neutral: '#aeaeb2', mixed: '#ff9f0a',
}[s] || '#aeaeb2')

const stanceLabel = (s) => ({
  bullish: '看多', bearish: '看空', neutral: '中性', mixed: '混合',
}[s] || '中性')

const stanceSymbolRotate = (s) => s === 'bearish' ? 180 : 0

// ── Asset label extraction ──
// Backwards-compat: 老数据没 `code` 字段，尝试从 `asset` 文本里提取引用号内的代码
// 如 "中际旭创(300308)" → "300308"，"Apple (AAPL)" → "AAPL"
function extractCodeFromName(name) {
  if (!name) return ''
  const m = String(name).match(/[（(]\s*([0-9]{4,6}|[A-Z]{1,6})\s*[)）]/)
  return m ? m[1] : ''
}

// 从 stance_assets 里挑出用于图表标签的"主资产"：
// 优先级：cn_stock / hk_stock / us_stock 个股（有 code） > 任意有 code 的 > 第一个
function pickPrimaryAsset(assets) {
  if (!assets || !assets.length) return null
  const stockCat = ['cn_stock', 'hk_stock', 'us_stock']
  const withCode = assets.find(a => a.code)
  if (withCode) return withCode
  const stock = assets.find(a => stockCat.includes(a.category))
  if (stock) return stock
  return assets[0]
}

function assetLabel(p) {
  const primary = pickPrimaryAsset(p.stance_assets)
  if (!primary) return ''
  if (primary.code) return primary.code
  // 老数据：从名称里提
  const fromName = extractCodeFromName(primary.asset)
  if (fromName) return fromName
  // 都没有：截前 4 个字符
  return (primary.asset || '').slice(0, 4)
}

// ── Click popup state ──
const popup = reactive({
  visible: false,
  barIdx: -1,
  bar: null,
  barTime: '',
  isUp: false,
  change: 0,
  changeText: '',
  posts: [],
  x: 0,
  y: 0,
})

const POPUP_W = 380
const POPUP_MAX_H = 520

const popupStyle = computed(() => {
  const vw = window.innerWidth
  const vh = window.innerHeight
  let left = popup.x + 16
  let top = popup.y - 120
  if (left + POPUP_W > vw - 16) left = vw - POPUP_W - 16
  if (left < 16) left = 16
  if (top < 16) top = 16
  if (top + POPUP_MAX_H > vh - 16) top = vh - POPUP_MAX_H - 16
  return {
    left: `${left}px`,
    top: `${top}px`,
    maxHeight: `${POPUP_MAX_H}px`,
  }
})

function openPopup(barIdx, bar, mouseX, mouseY) {
  const change = bar.close - bar.open
  const changePct = bar.open ? ((change / bar.open) * 100).toFixed(2) : 0
  const bars = props.klineData.bars || []
  const times = bars.map(b => b.time)
  const allMarks = []
  for (const p of props.posts) {
    const pt = p.created_at_original || ''
    if (!pt) continue
    const idx = findNearestBarIdx(times, pt)
    if (idx !== barIdx) continue
    allMarks.push({
      postId: p.post_id,
      name: p.display_name || p.url_token,
          url: p.url,
      title: p.title,
      summary: p.summary,
      stance: p.stance,
      confidence: p.confidence,
      stanceAssets: p.stance_assets || [],
    })
  }
  popup.visible = true
  popup.barIdx = barIdx
  popup.bar = bar
  popup.barTime = bar.time
  popup.isUp = change >= 0
  popup.change = change
  popup.changeText = `${change >= 0 ? '+' : ''}${change.toFixed(2)} (${changePct >= 0 ? '+' : ''}${changePct}%)`
  popup.posts = allMarks
  popup.x = mouseX
  popup.y = mouseY
}

function closePopup() {
  popup.visible = false
}

const option = computed(() => {
  const bars = props.klineData.bars || []
  if (!bars.length) return null

  const ohlc = bars.map(b => [b.open, b.close, b.low, b.high])
  const times = bars.map(b => b.time)
  const isHighlighted = (postId) => props.highlightPostId != null && String(props.highlightPostId) === String(postId)

  const bullishMarks = []
  const bearishMarks = []
  const neutralMarks = []
  const mixedMarks = []

  for (const p of props.posts) {
    const pt = p.created_at_original || ''
    if (!pt) continue
    const barIdx = findNearestBarIdx(times, pt)
    if (barIdx < 0) continue
    const closeVal = bars[barIdx]?.close || 0
    if (!closeVal) continue

    const hl = isHighlighted(p.post_id)
    const label = assetLabel(p)
    const mark = {
      value: [barIdx, closeVal],
      name: p.display_name || p.url_token,
      symbolSize: hl ? 22 : 16,
      itemStyle: {
        color: stanceColor(p.stance),
        borderColor: hl ? '#fff' : 'transparent',
        borderWidth: hl ? 2 : 0,
        shadowBlur: hl ? 8 : 0,
        shadowColor: stanceColor(p.stance),
      },
      postId: p.post_id,
      title: p.title,
      stance: p.stance,
      confidence: p.confidence,
      summary: p.summary,
      stanceAssets: p.stance_assets || [],
      assetLabel: label,
    }

    if (p.stance === 'bullish') bullishMarks.push(mark)
    else if (p.stance === 'bearish') bearishMarks.push(mark)
    else if (p.stance === 'mixed') mixedMarks.push(mark)
    else neutralMarks.push(mark)
  }

  return {
    backgroundColor: DS.bgElevated,
    animation: true,
    animationDuration: 400,
    animationEasing: 'cubicOut',
    tooltip: {
      trigger: 'axis',
      confine: true,
      axisPointer: {
        type: 'cross',
        lineStyle: { color: DS.border, type: 'dashed', width: 1 },
        crossStyle: { color: DS.textTertiary },
        label: {
          backgroundColor: DS.textPrimary,
          color: '#fff',
          fontSize: 10,
          fontWeight: 500,
          padding: [2, 6],
          borderRadius: 4,
        },
      },
      backgroundColor: 'rgba(255,255,255,0.97)',
      borderColor: 'transparent',
      borderWidth: 0,
      borderRadius: DS.radiusMd,
      padding: [12, 16],
      textStyle: { color: DS.textPrimary, fontSize: DS.fontMd, fontFamily: 'inherit' },
      extraCssText: `box-shadow: ${DS.shadowLg}; backdrop-filter: blur(20px); max-height: 380px; overflow-y: auto;`,
      formatter(params) {
        if (!params || !params.length) return ''
        const d = params[0]
        if (!d) return ''
        const idx = d.dataIndex
        const bar = bars[idx]
        if (!bar) return ''
        const change = bar.close - bar.open
        const changePct = bar.open ? ((change / bar.open) * 100).toFixed(2) : 0
        const isUp = change >= 0
        const color = isUp ? DS.candleUp : DS.candleDown
        let html = `<div style="font-weight:600;font-size:13px;margin-bottom:8px;color:${DS.textPrimary};letter-spacing:-0.01em">${bar.time}</div>`
        html += `<table style="font-size:12px;line-height:2;color:${DS.textSecondary};border-collapse:collapse">`
        html += `<tr><td style="padding-right:16px">开盘</td><td style="font-variant-numeric:tabular-nums;font-weight:500;color:${DS.textPrimary}">${bar.open}</td></tr>`
        html += `<tr><td style="padding-right:16px">收盘</td><td style="font-variant-numeric:tabular-nums;font-weight:600;color:${color}">${bar.close}</td></tr>`
        html += `<tr><td style="padding-right:16px">最高</td><td style="font-variant-numeric:tabular-nums;font-weight:500;color:${DS.textPrimary}">${bar.high}</td></tr>`
        html += `<tr><td style="padding-right:16px">最低</td><td style="font-variant-numeric:tabular-nums;font-weight:500;color:${DS.textPrimary}">${bar.low}</td></tr>`
        html += `<tr><td style="padding-right:16px">涨跌</td><td style="font-variant-numeric:tabular-nums;font-weight:600;color:${color}">${change >= 0 ? '+' : ''}${change.toFixed(2)}&nbsp;<span style="font-size:11px;opacity:0.8">${changePct >= 0 ? '+' : ''}${changePct}%</span></td></tr>`
        html += `</table>`
        const allMarks = [...bullishMarks, ...bearishMarks, ...neutralMarks, ...mixedMarks]
        const atIdx = allMarks.filter(m => m.value[0] === idx)
        if (atIdx.length) {
          html += `<div style="margin-top:10px;padding-top:10px;border-top:1px solid ${DS.divider}">`
          for (const m of atIdx) {
            html += `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:12px">`
            html += `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${stanceColor(m.stance)};flex-shrink:0"></span>`
            html += `<span style="font-weight:600;color:${DS.textPrimary};letter-spacing:-0.01em">${m.name}</span>`
            html += `<span style="color:${stanceColor(m.stance)};font-size:10px;font-weight:600">${stanceLabel(m.stance)}</span>`
            html += `</div>`
            // 资产 chips（最多展示前 3 个）
            const assets = (m.stanceAssets || []).slice(0, 3)
            for (const a of assets) {
              const ac = stanceColor(a.stance)
              html += `<div style="margin-left:16px;margin-bottom:3px;font-size:11px;line-height:1.5;display:flex;align-items:center;gap:6px">`
              html += `<span style="display:inline-block;padding:1px 6px;border-radius:4px;background:${ac}15;color:${ac};font-size:10px;font-weight:600">${stanceLabel(a.stance)}</span>`
              html += `<span style="color:${DS.textPrimary};font-weight:500">${a.code ? `<span style="font-family:SF Mono,monospace;font-weight:600">${a.code}</span> ` : ''}${a.asset}</span>`
              html += `</div>`
            }
            if ((m.stanceAssets || []).length > 3) {
              html += `<div style="margin-left:14px;font-size:10px;color:${DS.textTertiary}">…还有 ${(m.stanceAssets || []).length - 3} 个资产</div>`
            }
            if (m.title) html += `<div style="font-size:11px;color:${DS.textTertiary};margin-left:14px;margin-top:2px">${m.title.slice(0, 60)}</div>`
          }
          html += `</div>`
        }
        html += `<div style="margin-top:8px;font-size:10px;color:${DS.textTertiary};text-align:center;letter-spacing:0.02em">点击固定此面板</div>`
        return html
      },
    },
    grid: { left: 56, right: 20, top: 28, bottom: 52 },
    xAxis: {
      type: 'category',
      data: times,
      boundaryGap: true,
      axisLine: { lineStyle: { color: DS.border, width: 1 } },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10,
        fontWeight: 500,
        color: DS.textTertiary,
        margin: 10,
        formatter: v => v.slice(5).replace(' ', '\n'),
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: DS.divider, type: 'solid', width: 0.5 } },
      axisLabel: {
        fontSize: 10,
        fontWeight: 500,
        color: DS.textTertiary,
        margin: 10,
        formatter: v => v.toFixed(v >= 100 ? 0 : 2),
      },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100, minValueSpan: 10 },
      {
        type: 'slider', start: 0, end: 100, height: 24, bottom: 8,
        borderColor: 'transparent',
        backgroundColor: 'transparent',
        fillerColor: 'rgba(0,113,227,0.08)',
        borderRadius: 12,
        dataBackground: {
          lineStyle: { color: DS.border, width: 0.5 },
          areaStyle: { color: 'rgba(0,113,227,0.02)' },
        },
        selectedDataBackground: {
          lineStyle: { color: DS.accent, width: 0.5 },
          areaStyle: { color: 'rgba(0,113,227,0.08)' },
        },
        handleStyle: {
          color: DS.accent, borderColor: '#fff', borderWidth: 2,
          size: '90%', shadowBlur: 4, shadowColor: 'rgba(0,113,227,0.2)',
        },
        textStyle: { color: DS.textTertiary, fontSize: 9, fontWeight: 500 },
        moveHandleSize: 0,
        showDetail: false,
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: DS.candleUp, color0: DS.candleDown,
          borderColor: DS.candleUp, borderColor0: DS.candleDown,
          borderWidth: 1,
        },
        barMaxWidth: 20,
        barMinWidth: 4,
      },
      ...(bullishMarks.length ? [{
        name: '看多', type: 'scatter', data: bullishMarks,
        symbol: 'triangle', symbolSize: 14,
        itemStyle: { color: stanceColor('bullish'), opacity: 0.9 }, z: 10,
        label: scatterLabel(bullishMarks),
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
      }] : []),
      ...(bearishMarks.length ? [{
        name: '看空', type: 'scatter', data: bearishMarks,
        symbol: 'triangle', symbolSize: 14, symbolRotate: 180,
        itemStyle: { color: stanceColor('bearish'), opacity: 0.9 }, z: 10,
        label: scatterLabel(bearishMarks),
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
      }] : []),
      ...(neutralMarks.length ? [{
        name: '中性', type: 'scatter', data: neutralMarks,
        symbol: 'circle', symbolSize: 8,
        itemStyle: { color: stanceColor('neutral'), opacity: 0.7 }, z: 10,
        label: scatterLabel(neutralMarks),
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
      }] : []),
      ...(mixedMarks.length ? [{
        name: '混合', type: 'scatter', data: mixedMarks,
        symbol: 'diamond', symbolSize: 10,
        itemStyle: { color: stanceColor('mixed'), opacity: 0.85 }, z: 10,
        label: scatterLabel(mixedMarks),
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
      }] : []),
    ],
  }
})

// 散点 label 配置：显示主资产 code/简称
function scatterLabel(marks) {
  return {
    show: true,
    position: 'top',
    distance: 6,
    formatter: (params) => params.data?.assetLabel || '',
    color: DS.textPrimary,
    fontSize: 10,
    fontWeight: 600,
    textBorderColor: '#fff',
    textBorderWidth: 3,
  }
}

function findNearestBarIdx(times, targetTime) {
  if (!times.length) return -1
  for (let i = 0; i < times.length; i++) {
    if (times[i] >= targetTime) return i
  }
  return times.length - 1
}

function onChartClick(e) {
  if (!e) return
  console.log('[KLine] ECharts click', e.componentType, e.dataIndex, e.data?.postId)
  lastClickTime = Date.now()

  // Click on scatter marker → emit post click
  if (e.componentType === 'series' && e.data && e.data.postId) {
    emit('postClick', e.data)
    return
  }

  // Get bar index: from series click or from pixel coordinates
  const bars = props.klineData.bars || []
  let idx = null
  const mouseX = e.event?.event?.clientX ?? 0
  const mouseY = e.event?.event?.clientY ?? 0

  if (e.componentType === 'series' && e.dataIndex != null) {
    idx = e.dataIndex
  } else {
    // Click on empty area — resolve via pixel position
    idx = resolveBarFromEvent(e, bars.length)
  }

  if (idx == null || idx < 0 || idx >= bars.length || !bars[idx]) return
  openPopup(idx, bars[idx], mouseX, mouseY)
}

function resolveBarFromEvent(e, barCount, chartInstance) {
  try {
    const chart = chartInstance || getChartInstance()
    if (!chart) return null
    let x
    if (e.offsetX != null) {
      x = e.offsetX
    } else {
      const canvas = chart.getDom()
      if (!canvas) return null
      const rect = canvas.getBoundingClientRect()
      const native = e.event?.event ?? e.event
      if (!native) return null
      x = native.clientX - rect.left
    }
    if (x < 0) return null
    const point = chart.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [x, 10])
    if (!point || point[0] == null) return null
    const idx = Math.round(point[0])
    if (idx < 0 || idx >= barCount) return null
    return idx
  } catch {
    return null
  }
}

function getChartInstance() {
  const cr = chartRef.value
  if (!cr) return null
  // vue-echarts v8: expose({ chart: shallowRef, ...publicApi })
  // cr.chart is a shallowRef → need .value for the raw ECharts instance
  const raw = cr.chart?.value ?? cr.chart
  if (raw && typeof raw.convertFromPixel === 'function') return raw
  // Fallback: publicApi methods bound directly on the component proxy
  if (typeof cr.convertFromPixel === 'function') return cr
  return null
}

const chartRef = ref(null)
const wrapperRef = ref(null)
let lastClickTime = 0
let mouseDownInfo = null

// Capture mousedown on wrapper — capture phase fires before zrender can intercept
function onWrapperMouseDown(e) {
  console.log('[KLine] mousedown captured on wrapper', e.target.tagName, e.clientX, e.clientY)
  mouseDownInfo = { clientX: e.clientX, clientY: e.clientY, time: Date.now() }
}

// Detect clicks via mouseup (bypasses dataZoom's click suppression on blank grid)
function onDocMouseUp(e) {
  if (!mouseDownInfo) return
  console.log('[KLine] mouseup — mousedown was recorded')
  const down = mouseDownInfo
  mouseDownInfo = null

  const dx = e.clientX - down.clientX
  const dy = e.clientY - down.clientY
  const dt = Date.now() - down.time
  // Not a click — was a drag (dataZoom pan) or too slow
  if (Math.abs(dx) > 5 || Math.abs(dy) > 5 || dt > 500) return

  // Delay to let ECharts' own click handler fire first (sets lastClickTime for dedup)
  setTimeout(() => {
    if (Date.now() - lastClickTime < 200) {
      console.log('[KLine] skipped — ECharts already handled this click')
      return
    }
    const chart = getChartInstance()
    if (!chart) { console.log('[KLine] mouseup: getChartInstance() returned null'); return }
    const dom = chart.getDom()
    if (!dom) { console.log('[KLine] mouseup: getDom() returned null'); return }
    const rect = dom.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    if (x < 0 || x > chart.getWidth() || y < 0 || y > chart.getHeight()) {
      console.log('[KLine] mouseup: click outside chart area', { x, y, w: chart.getWidth(), h: chart.getHeight() })
      return
    }
    const bars = props.klineData.bars || []
    if (!bars.length) return
    const idx = resolveBarFromEvent({ offsetX: x }, bars.length, chart)
    console.log('[KLine] mouseup click → x:', x, 'idx:', idx, 'bars:', bars.length)
    if (idx == null || idx < 0 || idx >= bars.length || !bars[idx]) return
    lastClickTime = Date.now()
    openPopup(idx, bars[idx], e.clientX, e.clientY)
  }, 30)
}

// Attach mouseup listener on mount (not dependent on option watch)
onMounted(() => {
  document.addEventListener('mouseup', onDocMouseUp)
  console.log('[KLine] mounted — mouseup listener attached')
})

onBeforeUnmount(() => {
  document.removeEventListener('mouseup', onDocMouseUp)
  mouseDownInfo = null
})
</script>

<style scoped>
.kline-chart-wrapper {
  width: 100%;
  min-height: 200px;
  background: var(--color-bg-elevated);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.kline-loading {
  height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.kline-loading__skeleton {
  width: 100%;
  padding: var(--space-8);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-bar {
  height: 10px;
  background: var(--color-bg-muted);
  border-radius: var(--radius-full);
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.kline-error {
  height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: var(--color-text-tertiary);
  font-size: var(--text-sm);
}
</style>

<style>
.kline-popup-overlay {
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: rgba(0, 0, 0, 0.12);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.kline-popup {
  position: fixed;
  width: 380px;
  max-height: 520px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 16px;
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.12),
    0 2px 8px rgba(0, 0, 0, 0.04),
    0 0 0 0.5px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.kline-popup__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px 12px;
  border-bottom: 0.5px solid rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
}

.kline-popup__title {
  font-size: 14px;
  font-weight: 600;
  color: #1d1d1f;
  letter-spacing: -0.01em;
}

.kline-popup__close {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: #aeaeb2;
  font-size: 18px;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.15s ease;
  line-height: 1;
}
.kline-popup__close:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}

.kline-popup__ohlc {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  padding: 14px 18px;
  flex-shrink: 0;
}

.kline-popup__ohlc td {
  padding: 5px 8px;
  color: #6e6e73;
  text-align: left;
  font-size: 12px;
}

.kline-popup__ohlc td.num-up {
  color: #ff3b30;
  font-weight: 600;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.kline-popup__ohlc td.num-down {
  color: #34c759;
  font-weight: 600;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.kline-popup__section {
  border-top: 0.5px solid rgba(0, 0, 0, 0.06);
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.kline-popup__section-title {
  padding: 12px 18px 6px;
  font-size: 11px;
  font-weight: 600;
  color: #6e6e73;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  position: sticky;
  top: 0;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.kline-popup__count {
  display: inline-block;
  background: rgba(0, 0, 0, 0.06);
  color: #6e6e73;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 9999px;
  margin-left: 6px;
  font-weight: 600;
}

.kline-popup__posts {
  padding: 6px 18px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.kline-popup__post {
  padding: 10px 14px;
  border-left: 3px solid #aeaeb2;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 0 10px 10px 0;
  transition: background 0.15s ease;
}
.kline-popup__post:hover {
  background: rgba(0, 0, 0, 0.04);
}

.popup-post__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.popup-post__name {
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
  letter-spacing: -0.01em;
}

.popup-post__stance {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 9999px;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
}

.popup-post__title {
  display: inline-block;
  font-size: 12px;
  color: #0071e3;
  text-decoration: none;
  margin-bottom: 2px;
  line-height: 1.5;
  transition: color 0.12s;
}
.popup-post__title:hover {
  color: #0060c7;
  text-decoration: underline;
}

.popup-post__summary {
  font-size: 11px;
  color: #6e6e73;
  line-height: 1.5;
}

.popup-post__assets {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 4px 0;
}

.popup-post__asset {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  line-height: 1.4;
  max-width: 100%;
  cursor: help;
}

.popup-post__asset-code {
  font-weight: 600;
  letter-spacing: 0.02em;
  font-variant-numeric: tabular-nums;
}

.popup-post__asset-name {
  font-weight: 500;
}

.popup-post__asset-stance {
  opacity: 0.75;
  font-size: 9px;
  padding-left: 4px;
  border-left: 1px solid rgba(255, 255, 255, 0.3);
  font-weight: 500;
}

.kline-popup__empty {
  padding: 28px;
  text-align: center;
  color: #aeaeb2;
  font-size: 12px;
}
</style>
