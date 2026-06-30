<template>
  <div>
    <div class="stock-toolbar">
      <el-input
        v-model="searchInput"
        placeholder="输入股票代码回车查询"
        style="width: 240px"
        size="default"
        clearable
        @keyup.enter="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
    </div>
    <el-table
      :data="stocks"
      v-loading="loading"
      highlight-current-row
      :empty-text="'暂无股票数据'"
      @row-click="handleRowClick"
    >
      <el-table-column type="index" label="#" width="60" />
      <el-table-column prop="code" label="代码" width="120">
        <template #default="{ row }">
          <span class="code-cell">{{ row.code }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="price" label="最新价" width="120" align="right">
        <template #default="{ row }">
          <span class="num">{{ row.price != null ? Number(row.price).toFixed(2) : '--' }}</span>
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
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Search } from '@element-plus/icons-vue'

const props = defineProps({
  stocks: { type: Array, default: () => [] },
  loading: Boolean,
})

const emit = defineEmits(['search'])
const searchInput = ref('')

function handleSearch() {
  const code = searchInput.value.trim()
  if (code) emit('search', code)
}

function handleRowClick(row) {
  emit('search', row.code)
}
</script>

<style scoped>
.stock-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
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
</style>
