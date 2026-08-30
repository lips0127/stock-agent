<template>
  <div class="scan-table">
    <ModernCard>
      <div class="filter-bar">
        <el-input
          v-model="searchText"
          :placeholder="searchPlaceholder"
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
        <span v-if="searchText || yieldFilter" class="filter-summary">
          命中 {{ total }} 只（服务端全量过滤）
        </span>
      </div>
    </ModernCard>

    <ModernCard padded>
      <ErrorState
        v-if="error && !loading"
        carded
        title="扫描数据加载失败"
        :description="error"
        @retry="fetchStocks(1)"
      />
      <template v-else>
        <el-table
          :data="stocks"
          v-loading="loading"
          highlight-current-row
          :empty-text="emptyText"
          @row-click="handleRowClick"
        >
          <el-table-column type="index" label="#" width="60" :index="indexMethod" />
          <el-table-column prop="code" label="代码" width="120">
            <template #default="{ row }">
              <span class="code-cell">{{ row.code }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column prop="price" label="最新价" width="120" align="right" sortable>
            <template #default="{ row }">
              <span class="num">{{ row.price != null ? Number(row.price).toFixed(2) : '--' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="dividend_per_share" label="每股分红" width="120" align="right">
            <template #default="{ row }">
              <span class="num">{{ row.dividend_per_share != null ? Number(row.dividend_per_share).toFixed(4) : '--' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="dividend_yield" label="股息率" width="140" align="right" sortable>
            <template #default="{ row }">
              <span
                class="yield-pill"
                :class="row.dividend_yield >= 5 ? 'yield-pill--high' : 'yield-pill--low'"
              >
                {{ row.dividend_yield != null ? Number(row.dividend_yield).toFixed(2) + '%' : '--' }}
              </span>
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
      </template>
    </ModernCard>

    <StockSearch v-model:visible="searchVisible" :symbol="searchSymbol" />
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useTaskStore } from '../stores/task'
import { getAllStocks } from '../api'
import { Search } from '@element-plus/icons-vue'
import ModernCard from './ui/ModernCard.vue'
import ErrorState from './ui/ErrorState.vue'
import StockSearch from './StockSearch.vue'

const props = defineProps({
  /** 'index' / 'full' / ''（默认优先 full 回退全部） */
  scanType: { type: String, default: '' },
  searchPlaceholder: { type: String, default: '搜索代码或名称' },
  emptyText: { type: String, default: '暂无扫描数据' },
})

const emit = defineEmits(['meta'])

const taskStore = useTaskStore()

const loading = ref(false)
const error = ref('')
const stocks = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(100)
const searchText = ref('')
const yieldFilter = ref('')
const searchVisible = ref(false)
const searchSymbol = ref('')

let searchDebounce = null
watch(searchText, () => {
  clearTimeout(searchDebounce)
  searchDebounce = setTimeout(() => fetchStocks(1), 350)
})
watch(yieldFilter, () => fetchStocks(1))

function indexMethod(index) {
  return (currentPage.value - 1) * pageSize.value + index + 1
}

async function fetchStocks(page) {
  if (page) currentPage.value = page
  loading.value = true
  error.value = ''
  try {
    const { data } = await getAllStocks(
      currentPage.value,
      pageSize.value,
      props.scanType || undefined,
      searchText.value || undefined,
      yieldFilter.value ? Number(yieldFilter.value) : undefined,
    )
    stocks.value = data.stocks || []
    total.value = data.total || 0
    emit('meta', { total: total.value, date: data.date || '' })
  } catch (e) {
    stocks.value = []
    total.value = 0
    emit('meta', { total: 0, date: '' })
    const status = e.response?.status
    error.value = status
      ? `服务器返回 ${status}${e.response?.data?.error ? '：' + e.response.data.error : ''}`
      : (e.message || '网络异常，无法连接服务器')
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
    if (status === 'success') fetchStocks(1)
  }
)

onMounted(() => fetchStocks(1))

defineExpose({ refresh: () => fetchStocks(1) })
</script>

<style scoped>
.scan-table {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.filter-summary {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.code-cell {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  letter-spacing: 0.02em;
  color: var(--color-text-primary);
  font-weight: var(--weight-medium);
}
.num {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-medium);
}
.yield-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  font-variant-numeric: tabular-nums;
}
.yield-pill--high {
  background: var(--color-up-soft);
  color: var(--color-up);
}
.yield-pill--low {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.pagination-bar {
  padding: var(--space-4) var(--space-5);
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--color-divider);
}
</style>
