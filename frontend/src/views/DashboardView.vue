<template>
  <div class="dashboard">
    <IndexCards :indices="indices" :loading="indicesLoading" />

    <div class="stock-table-header">
      <span class="section-title">高股息股票</span>
      <el-button text size="small" type="primary" @click="router.push({ name: 'Stocks' })">
        查看全量 →
      </el-button>
    </div>
    <StockTable :stocks="stocks" :loading="stocksLoading" @search="openStockSearch" />
    <StockSearch v-model:visible="searchVisible" :symbol="searchSymbol" />

    <TaskLogs :logs="logs" :loading="logsLoading" />
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { getLiveIndices, getTopStocks, getLogs } from '../api'
import IndexCards from '../components/IndexCards.vue'
import StockTable from '../components/StockTable.vue'
import StockSearch from '../components/StockSearch.vue'
import TaskLogs from '../components/TaskLogs.vue'

const router = useRouter()
const taskStore = useTaskStore()

const indices = ref([])
const stocks = ref([])
const logs = ref([])
const indicesLoading = ref(false)
const stocksLoading = ref(false)
const logsLoading = ref(false)
const searchVisible = ref(false)
const searchSymbol = ref('')

async function fetchIndices() {
  indicesLoading.value = true
  try {
    const { data } = await getLiveIndices()
    indices.value = data || []
  } catch {
    indices.value = []
  } finally {
    indicesLoading.value = false
  }
}

async function fetchStocks() {
  stocksLoading.value = true
  try {
    const { data } = await getTopStocks(20)
    stocks.value = data || []
  } catch {
    stocks.value = []
  } finally {
    stocksLoading.value = false
  }
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const { data } = await getLogs()
    logs.value = data || []
  } catch {
    logs.value = []
  } finally {
    logsLoading.value = false
  }
}

function openStockSearch(symbol) {
  if (typeof symbol === 'object' && symbol !== null) {
    symbol = symbol.code || ''
  }
  if (!symbol) return
  searchSymbol.value = String(symbol)
  searchVisible.value = true
}

// scan 完成时自动刷新数据
watch(
  () => taskStore.currentTask?.status,
  (status) => {
    if (status === 'success' || status === 'failed') {
      fetchIndices()
      fetchStocks()
      fetchLogs()
    }
  }
)

onMounted(() => {
  fetchIndices()
  fetchStocks()
  fetchLogs()
})
</script>

<style scoped>
.stock-table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
</style>
