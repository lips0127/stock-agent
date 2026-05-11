<template>
  <el-card shadow="never" class="section-card">
    <template #header>
      <div class="stock-header">
        <span class="section-title">高股息股票 TOP 20</span>
        <el-input
          v-model="searchInput"
          placeholder="输入股票代码查询"
          style="width: 200px"
          size="small"
          clearable
          @keyup.enter="handleSearch"
        >
          <template #append>
            <el-button :icon="Search" @click="handleSearch" />
          </template>
        </el-input>
      </div>
    </template>
    <el-table
      :data="stocks"
      v-loading="loading"
      stripe
      highlight-current-row
      style="width: 100%"
      @row-click="handleRowClick"
      empty-text="暂无股票数据"
    >
      <el-table-column type="index" label="#" width="60" />
      <el-table-column prop="code" label="代码" width="110">
        <template #default="{ row }">
          <el-link type="primary" :underline="false" class="code-link">{{ row.code }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="price" label="最新价" width="110" align="right">
        <template #default="{ row }">
          {{ row.price != null ? Number(row.price).toFixed(2) : '--' }}
        </template>
      </el-table-column>
      <el-table-column prop="dividend_yield" label="股息率" width="120" align="right" sortable>
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
  </el-card>
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
.stock-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.code-link {
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  letter-spacing: 0.5px;
}
</style>
