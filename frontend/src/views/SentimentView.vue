<template>
  <div class="sentiment-page">
    <div class="page-header">
      <h2 class="page-title">舆情监控</h2>
      <el-button type="primary" :icon="Refresh" :loading="analyzing" @click="handleBatchAnalyze">
        批量分析
      </el-button>
    </div>

    <div class="content-grid">
      <!-- 左侧：配置面板 -->
      <div class="left-panel">
        <el-card shadow="never">
          <template #header><span class="card-title">监控配置</span></template>

          <div class="add-form">
            <el-select
              v-model="selectedStock"
              filterable
              remote
              reserve-keyword
              :remote-method="searchStocks"
              :loading="searching"
              placeholder="输入代码或名称搜索"
              value-key="code"
              style="flex:1"
              clearable
            >
              <el-option
                v-for="s in searchResults"
                :key="s.code"
                :label="`${s.code}  ${s.name}`"
                :value="s"
              />
            </el-select>
            <el-button type="primary" @click="handleAdd" :disabled="!selectedStock">
              添加
            </el-button>
          </div>

          <el-table :data="configs" style="width:100%;margin-top:12px" max-height="360" stripe size="small">
            <el-table-column prop="stock_code" label="代码" width="90" />
            <el-table-column prop="stock_name" label="名称" min-width="100">
              <template #default="{ row }">
                <span v-if="row.stock_name">{{ row.stock_name }}</span>
                <span v-else class="text-muted">--</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="70" align="center">
              <template #default="{ row }">
                <el-button type="danger" link size="small" @click="handleDelete(row.id)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="!configs.length" description="暂无监控股票，请搜索添加" :image-size="60" />
        </el-card>
      </div>

      <!-- 右侧：情绪面板 -->
      <div class="right-panel">
        <el-card shadow="never">
          <template #header>
            <div class="card-header-row">
              <span class="card-title">最新情绪</span>
              <el-button text size="small" @click="fetchLatest">刷新</el-button>
            </div>
          </template>

          <div v-loading="latestLoading">
            <el-empty v-if="!latest.length" description="添加股票后点击批量分析" :image-size="60" />

            <div v-for="item in latest" :key="item.stock_code" class="sentiment-row"
                 @click="fetchHistory(item.stock_code)"
                 :class="{ active: selectedCode === item.stock_code }">
              <div class="sentiment-main">
                <div class="sentiment-info">
                  <span class="stock-code">{{ item.stock_code }}</span>
                  <span class="stock-name">{{ item.stock_name || '--' }}</span>
                  <a v-if="item.guba_url" :href="item.guba_url" target="_blank" class="guba-link">股吧 →</a>
                </div>
                <div class="sentiment-score-wrap">
                  <el-tag v-if="item.sentiment" :type="tagType(item.sentiment)" size="small" effect="dark">
                    {{ item.sentiment }}
                  </el-tag>
                  <span v-else class="text-muted">--</span>
                  <span v-if="item.score != null" class="score-num"
                        :style="{ color: scoreColor(item.score) }">{{ item.score }}</span>
                </div>
              </div>
              <div v-if="item.summary && item.summary !== '暂无数据'" class="sentiment-desc">
                {{ item.summary }}
              </div>
            </div>
          </div>
        </el-card>

        <el-card v-if="selectedCode" shadow="never" style="margin-top:16px">
          <template #header>
            <span class="card-title">{{ selectedCode }} 情绪历史</span>
          </template>
          <div v-loading="historyLoading">
            <el-empty v-if="!history.length" description="暂无历史数据" :image-size="60" />
            <div v-for="h in history" :key="h.date" class="history-row">
              <span class="h-date">{{ h.date }}</span>
              <el-tag :type="tagType(h.sentiment)" size="small" effect="plain">{{ h.sentiment }}</el-tag>
              <span class="h-score" :style="{ color: scoreColor(h.score) }">{{ h.score }}</span>
              <span class="h-summary">{{ h.summary }}</span>
            </div>
          </div>
        </el-card>

        <el-card v-if="selectedCode && selectedPosts.length" shadow="never" style="margin-top:16px">
          <template #header>
            <span class="card-title">
              相关帖子 ({{ selectedPosts.length }})
              <a :href="gubaUrl" target="_blank" class="guba-link" style="margin-left:8px">打开股吧 →</a>
            </span>
          </template>
          <div v-for="(p, i) in selectedPosts" :key="i" class="post-link-row">
            <span class="post-title-text">{{ p.title }}</span>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import {
  getSentimentConfigs, addSentimentConfig, deleteSentimentConfig,
  getSentimentLatest, getSentimentScores, batchAnalyzeSentiment, searchStocks as searchStocksApi,
} from '../api'

const configs = ref([])
const latest = ref([])
const history = ref([])
const selectedStock = ref(null)
const searchResults = ref([])
const searching = ref(false)
const selectedCode = ref('')
const selectedPosts = ref([])
const analyzing = ref(false)
const latestLoading = ref(false)
const historyLoading = ref(false)

const gubaUrl = computed(() => {
  return selectedCode.value
    ? `https://guba.eastmoney.com/list,${selectedCode.value}.html`
    : ''
})

function tagType(s) {
  if (s === '乐观') return 'success'
  if (s === '悲观') return 'danger'
  return 'warning'
}
function scoreColor(s) {
  if (s >= 60) return '#67c23a'
  if (s >= 40) return '#e6a23c'
  return '#f56c6c'
}

async function searchStocks(q) {
  if (!q || q.length < 2) { searchResults.value = []; return }
  searching.value = true
  try {
    const { data } = await searchStocksApi(q)
    searchResults.value = data || []
  } catch { searchResults.value = [] }
  finally { searching.value = false }
}

async function fetchConfigs() {
  try {
    const { data } = await getSentimentConfigs()
    configs.value = data || []
  } catch { /* noop */ }
}

async function fetchLatest() {
  latestLoading.value = true
  try {
    const { data } = await getSentimentLatest()
    latest.value = data || []
  } catch { /* noop */ }
  finally { latestLoading.value = false }
}

async function fetchHistory(code) {
  selectedCode.value = code
  historyLoading.value = true
  // 从 latest 中找到该股票的帖子列表
  const item = latest.value.find(l => l.stock_code === code)
  selectedPosts.value = item?.posts || []
  try {
    const { data } = await getSentimentScores(code)
    history.value = data || []
  } catch { /* noop */ }
  finally { historyLoading.value = false }
}

async function handleAdd() {
  if (!selectedStock.value) return
  const { code, name } = selectedStock.value
  try {
    await addSentimentConfig(code, name)
    ElMessage.success(`已添加 ${code} ${name}`)
    selectedStock.value = null
    searchResults.value = []
    fetchConfigs()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '添加失败')
  }
}

async function handleDelete(id) {
  try {
    await deleteSentimentConfig(id)
    ElMessage.success('已删除')
    fetchConfigs()
  } catch { ElMessage.error('删除失败') }
}

async function handleBatchAnalyze() {
  if (!configs.value.length) { ElMessage.warning('请先添加监控股票'); return }
  analyzing.value = true
  try {
    await batchAnalyzeSentiment()
    ElMessage.success('分析已启动，稍后刷新查看结果')
    setTimeout(fetchLatest, 6000)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '分析失败')
  } finally { analyzing.value = false }
}

onMounted(() => { fetchConfigs(); fetchLatest() })
</script>

<style scoped>
.sentiment-page { display:flex; flex-direction:column; gap:16px; }
.page-header { display:flex; align-items:center; justify-content:space-between; }
.page-title { font-size:22px; font-weight:700; }
.content-grid { display:grid; grid-template-columns:360px 1fr; gap:16px; align-items:start; }
.card-title { font-weight:600; font-size:15px; }
.card-header-row { display:flex; align-items:center; justify-content:space-between; }
.add-form { display:flex; gap:8px; }

.sentiment-row {
  padding:10px 0; border-bottom:1px solid #ebeef5; cursor:pointer;
  border-left:3px solid transparent; padding-left:12px; transition:.15s;
}
.sentiment-row:hover { background:#f5f7fa; }
.sentiment-row.active { border-left-color:var(--el-color-primary); background:#ecf5ff; }
.sentiment-main { display:flex; align-items:center; justify-content:space-between; }
.sentiment-info { display:flex; align-items:center; gap:8px; }
.stock-code { font-family:monospace; font-weight:600; font-size:14px; }
.stock-name { font-size:13px; color:#909399; }
.sentiment-score-wrap { display:flex; align-items:center; gap:8px; }
.score-num { font-weight:700; font-size:16px; }
.sentiment-desc { font-size:13px; color:#909399; margin-top:4px; }

.history-row { display:flex; align-items:center; gap:12px; padding:6px 0; border-bottom:1px solid #f5f5f5; }
.h-date { font-size:13px; color:#909399; min-width:90px; }
.h-score { font-weight:700; min-width:30px; }
.h-summary { font-size:13px; color:#909399; }
.guba-link { font-size:12px; color:#909399; text-decoration:none; margin-left:4px; }
.guba-link:hover { color:#409eff; }
.post-link-row { padding:6px 0; border-bottom:1px solid #f5f5f5; }
.post-link { font-size:13px; color:#409eff; text-decoration:none; }
.post-link:hover { text-decoration:underline; }
.text-muted { color:#909399; }
</style>
