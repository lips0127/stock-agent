<template>
  <div class="stocks-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-header__left">
        <h2 class="page-title">全量扫描结果</h2>
        <span v-if="scanDate" class="scan-date">扫描日期：{{ scanDate }}</span>
      </div>
      <el-tag v-if="total > 0" type="info" effect="plain" size="large">
        共 {{ total }} 只
      </el-tag>
    </div>

    <!-- 筛选栏 -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-bar">
        <el-input
          v-model="searchText"
          placeholder="搜索代码或名称"
          clearable
          style="width: 220px"
          :prefix-icon="Search"
        />
        <el-select v-model="yieldFilter" placeholder="股息率筛选" style="width: 140px" clearable>
          <el-option label="全部" value="" />
          <el-option label="> 3%" value="3" />
          <el-option label="> 5%" value="5" />
          <el-option label="> 7%" value="7" />
        </el-select>
      </div>
    </el-card>

    <!-- 数据表格 -->
    <el-card shadow="never" class="table-card">
      <el-table
        :data="filteredStocks"
        v-loading="loading"
        stripe
        highlight-current-row
        style="width: 100%"
        @row-click="handleRowClick"
        empty-text="暂无扫描数据"
      >
        <el-table-column type="index" label="#" width="60" :index="indexMethod" />
        <el-table-column prop="code" label="代码" width="110">
          <template #default="{ row }">
            <span class="code-text">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="price" label="最新价" width="100" align="right" sortable>
          <template #default="{ row }">
            {{ row.price != null ? Number(row.price).toFixed(2) : '--' }}
          </template>
        </el-table-column>
        <el-table-column prop="dividend_per_share" label="每股分红" width="100" align="right">
          <template #default="{ row }">
            {{ row.dividend_per_share != null ? Number(row.dividend_per_share).toFixed(4) : '--' }}
          </template>
        </el-table-column>
        <el-table-column prop="dividend_yield" label="股息率" width="100" align="right" sortable>
          <template #default="{ row }">
            <el-tag
              :type="row.dividend_yield >= 5 ? 'danger' : 'success'"
              size="small"
              effect="light"
            >
              {{ row.dividend_yield != null ? Number(row.dividend_yield).toFixed(2) + '%' : '--' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="fetchStocks"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <StockSearch v-model:visible="searchVisible" :symbol="searchSymbol" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useTaskStore } from '../stores/task'
import { getAllStocks } from '../api'
import { Search } from '@element-plus/icons-vue'
import StockSearch from '../components/StockSearch.vue'

const taskStore = useTaskStore()

const loading = ref(false)
const stocks = ref([])
const total = ref(0)
const scanDate = ref('')
const currentPage = ref(1)
const pageSize = ref(100)
const searchText = ref('')
const yieldFilter = ref('')
const searchVisible = ref(false)
const searchSymbol = ref('')

const filteredStocks = computed(() => {
  let list = stocks.value
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(s => s.code?.includes(q) || s.name?.toLowerCase().includes(q))
  }
  if (yieldFilter.value) {
    const min = Number(yieldFilter.value)
    list = list.filter(s => s.dividend_yield != null && s.dividend_yield >= min)
  }
  return list
})

function indexMethod(index) {
  return (currentPage.value - 1) * pageSize.value + index + 1
}

async function fetchStocks(page) {
  if (page) currentPage.value = page
  loading.value = true
  try {
    const { data } = await getAllStocks(currentPage.value, pageSize.value)
    stocks.value = data.stocks || []
    total.value = data.total || 0
    scanDate.value = data.date || ''
  } catch {
    stocks.value = []
  } finally {
    loading.value = false
  }
}

function handleSizeChange() {
  currentPage.value = 1
  fetchStocks(1)
}

function handleRowClick(row) {
  const code = row.code || ''
  if (!code) return
  searchSymbol.value = String(code)
  searchVisible.value = true
}

watch(
  () => taskStore.currentTask?.status,
  (status) => {
    if (status === 'success') {
      fetchStocks(1)
    }
  }
)

onMounted(() => {
  fetchStocks(1)
})
</script>

<style scoped>
.stocks-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-header__left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text-primary);
}
.scan-date {
  font-size: 13px;
  color: var(--color-text-muted);
}
.filter-card {
  border-radius: var(--radius-card);
}
.filter-card :deep(.el-card__body) {
  padding: 12px 20px;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.table-card {
  border-radius: var(--radius-card);
}
.table-card :deep(.el-card__body) {
  padding: 0;
}
.table-card :deep(.el-table) {
  border-radius: var(--radius-card) var(--radius-card) 0 0;
}
.code-text {
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  letter-spacing: 0.5px;
}
.pagination-bar {
  padding: 16px 20px;
  display: flex;
  justify-content: flex-end;
}
</style>
