// 公司增强看板的格式化工具，供 stock/ 子组件复用。

export function formatPrice(val) {
  if (val == null) return '--'
  return Number(val).toFixed(2)
}

export function formatCurrency(val) {
  if (val == null) return '--'
  const abs = Math.abs(val)
  if (abs >= 1e8) return (val / 1e8).toFixed(2) + ' 亿'
  if (abs >= 1e4) return (val / 1e4).toFixed(2) + ' 万'
  return val.toFixed(2)
}

export function formatCap(val) {
  if (val == null) return '--'
  if (val >= 10000) return (val / 10000).toFixed(2) + ' 万亿'
  if (val >= 1) return val.toFixed(1) + ' 亿'
  return (val * 1e8).toFixed(0)
}

export function formatPercent(val, digits = 1) {
  if (val == null) return '--'
  return Number(val).toFixed(digits) + '%'
}

export function pePercentileClass(pct) {
  if (pct == null) return ''
  if (pct < 20) return 'valuation-value--cheap'
  if (pct > 80) return 'valuation-value--expensive'
  return 'valuation-value--mid'
}

export function eastmoneyUrl(symbol) {
  if (!symbol) return ''
  if (symbol.startsWith('4') || symbol.startsWith('8')) return `https://quote.eastmoney.com/bj${symbol}.html`
  if (symbol.startsWith('5') || symbol.startsWith('6') || symbol.startsWith('9')) {
    return `https://quote.eastmoney.com/sh${symbol}.html`
  }
  return `https://quote.eastmoney.com/sz${symbol}.html`
}

export function formatChange(val) {
  if (val == null) return '--'
  const sign = val > 0 ? '+' : ''
  return `${sign}${Number(val).toFixed(1)}%`
}

export function formatChangePp(val) {
  if (val == null) return '--'
  const sign = val > 0 ? '+' : ''
  return `${sign}${Number(val).toFixed(1)}pp`
}

export function changeClass(val) {
  if (val == null) return ''
  if (val > 0) return 'change-up'
  if (val < 0) return 'change-down'
  return 'change-flat'
}

export function sentimentTagType(s) {
  if (s === 'bullish' || s === '乐观') return 'danger'
  if (s === 'bearish' || s === '悲观') return 'success'
  return 'info'
}

export function sentimentLabel(s) {
  if (s === 'bullish' || s === '乐观') return '看多'
  if (s === 'bearish' || s === '悲观') return '看空'
  if (s === 'neutral' || s === '中性') return '中性'
  return s || '—'
}
