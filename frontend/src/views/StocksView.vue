<template>
  <div class="stocks-page">
    <PageHeader
      title="全量扫描结果"
      :subtitle="scanDate ? `扫描日期：${scanDate}` : '等待扫描结果'"
    >
      <template #actions>
        <span v-if="total > 0" class="total-pill">共 {{ total }} 只</span>
      </template>
    </PageHeader>

    <ModernCard>
      <div class="filter-bar">
        <el-input
          v-model="searchText"
          placeholder="搜索代码或名称"
          clearable
          style="width: 220px"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select v-model="yieldFilter" placeholder="股息率筛选" style="width: 140px" clearable>
          <el-option label="全部" value="" />
          <el-option label="> 3%" value="3" />
          <el-option label="> 5%" value="5" />
          <el-option label="> 7%" value="7" />
        </el-select>
      </div>
    </ModernCard>

    <ModernCard padded>
      <el-table
        :data="filteredStocks"
        v-loading="loading"
        highlight-current-row
        :empty-text="'暂无扫描数据'"
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
    </ModernCard>

    <StockSearch v-model:visible="searchVisible" :symbol="searchSymbol" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useTaskStore } from '../stores/task'
import { getAllStocks } from '../api'
import { Search } from '@element-plus/icons-vue'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
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
  gap: var(--space-4);
}
.total-pill {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  background: var(--color-bg-muted);
  padding: 4px 12px;
  border-radius: var(--radius-full);
  font-variant-numeric: tabular-nums;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
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
