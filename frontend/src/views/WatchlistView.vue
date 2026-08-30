<template>
  <div class="watchlist-page">
    <PageHeader
      title="自选股观察池"
      :subtitle="metaSubtitle"
    >
      <template #actions>
        <span v-if="stocks.length > 0" class="total-pill">{{ stocks.length }} 只</span>
        <el-button :icon="Refresh" :loading="loading" @click="fetchList">刷新报价</el-button>
      </template>
    </PageHeader>

    <!-- 添加观察标的 -->
    <ModernCard>
      <div class="add-bar">
        <el-input
          v-model="newCode"
          placeholder="输入 6 位股票代码，如 600519"
          style="width: 260px"
          maxlength="6"
          clearable
          @keyup.enter="handleAdd"
        >
          <template #prefix>
            <el-icon><Plus /></el-icon>
          </template>
        </el-input>
        <el-input
          v-model="newNote"
          placeholder="备注（可选），如：高股息观察 / 等回调"
          style="width: 280px"
          maxlength="80"
          clearable
        />
        <el-button type="primary" :loading="adding" @click="handleAdd">加入观察池</el-button>
        <span class="add-hint">仅个人研究用途 · 数据来自腾讯行情，不构成投资建议</span>
      </div>
    </ModernCard>

    <!-- 数据可信状态条 -->
    <div v-if="meta && stocks.length > 0" class="meta-line" :class="{ 'meta-line--degraded': meta.degraded || meta.unavailable }">
      <span class="meta-line__dot" />
      <template v-if="meta.unavailable">行情源不可用 · 显示观察池清单（无报价）</template>
      <template v-else-if="meta.degraded">
        部分报价获取失败（成功 {{ meta.coverage?.ok }}/{{ meta.coverage?.expected }}）
      </template>
      <template v-else>实时报价 · {{ meta.source }} · as-of {{ meta.as_of }}</template>
    </div>

    <ModernCard padded>
      <ErrorState
        v-if="error && !loading"
        carded
        title="观察池加载失败"
        :description="error"
        @retry="fetchList"
      />
      <el-table
        v-else
        :data="stocks"
        v-loading="loading"
        highlight-current-row
        empty-text="观察池为空 · 在上方输入代码加入第一只自选股"
      >
        <el-table-column prop="code" label="代码" width="110">
          <template #default="{ row }">
            <span class="code-cell">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="130">
          <template #default="{ row }">
            <span :class="{ 'name--missing': !row.name }">{{ row.name || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="最新价" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.quote_error" class="quote-error">获取失败</span>
            <span v-else class="num">{{ row.price != null ? Number(row.price).toFixed(2) : '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="change_pct" label="涨跌幅" width="110" align="right">
          <template #default="{ row }">
            <span
              v-if="row.change_pct != null"
              class="pct-pill"
              :class="row.change_pct >= 0 ? 'pct-pill--up' : 'pct-pill--down'"
            >
              {{ row.change_pct >= 0 ? '+' : '' }}{{ Number(row.change_pct).toFixed(2) }}%
            </span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="180">
          <template #default="{ row }">
            <template v-if="editingCode === row.code">
              <div class="note-edit">
                <el-input
                  v-model="editingNote"
                  size="small"
                  maxlength="80"
                  @keyup.enter="saveNote(row)"
                />
                <el-button size="small" type="primary" :loading="savingNote" @click="saveNote(row)">保存</el-button>
                <el-button size="small" @click="cancelEdit">取消</el-button>
              </div>
            </template>
            <span v-else class="note-cell" :class="{ 'name--missing': !row.note }">
              {{ row.note || '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="right">
          <template #default="{ row }">
            <el-button text size="small" type="primary" @click.stop="startEdit(row)">备注</el-button>
            <el-button text size="small" type="danger" @click.stop="handleRemove(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </ModernCard>

    <StockSearch v-model:visible="searchVisible" :symbol="searchSymbol" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { getWatchlist, addWatchStock, updateWatchStock, deleteWatchStock } from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import ErrorState from '../components/ui/ErrorState.vue'
import StockSearch from '../components/StockSearch.vue'

const loading = ref(false)
const error = ref('')
const stocks = ref([])
const meta = ref(null)
const adding = ref(false)
const newCode = ref('')
const newNote = ref('')
const editingCode = ref('')
const editingNote = ref('')
const savingNote = ref(false)
const searchVisible = ref(false)
const searchSymbol = ref('')

const metaSubtitle = computed(() => {
  if (!meta.value) return '集中跟踪你关注的标的 · 加入后自动带出实时报价'
  if (meta.value.unavailable) return '行情源暂时不可用 · 清单仍可管理，稍后刷新恢复报价'
  if (meta.value.degraded) return `部分报价获取失败（${meta.value.coverage?.ok}/${meta.value.coverage?.expected}）· 失败项可在恢复后刷新`
  return `实时报价来自 ${meta.value.source} · as-of ${meta.value.as_of}`
})

async function fetchList() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await getWatchlist()
    stocks.value = data?.data || []
    meta.value = data && 'coverage' in data ? data : null
  } catch (e) {
    stocks.value = []
    const status = e.response?.status
    error.value = status
      ? `服务器返回 ${status}${e.response?.data?.error ? '：' + e.response.data.error : ''}`
      : (e.message || '网络异常，无法连接服务器')
  } finally {
    loading.value = false
  }
}

async function handleAdd() {
  const code = newCode.value.trim()
  if (!/^\d{6}$/.test(code)) {
    ElMessage.warning('请输入 6 位数字股票代码')
    return
  }
  adding.value = true
  try {
    const { data } = await addWatchStock(code, newNote.value.trim())
    if (data.created) {
      ElMessage.success(`已加入观察池${data.stock?.name ? `：${data.stock.name}` : ''}`)
    } else {
      ElMessage.info('该代码已在观察池中')
    }
    newCode.value = ''
    newNote.value = ''
    await fetchList()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '加入失败')
  } finally {
    adding.value = false
  }
}

function startEdit(row) {
  editingCode.value = row.code
  editingNote.value = row.note || ''
}

function cancelEdit() {
  editingCode.value = ''
  editingNote.value = ''
}

async function saveNote(row) {
  savingNote.value = true
  try {
    await updateWatchStock(row.code, editingNote.value.trim())
    row.note = editingNote.value.trim()
    ElMessage.success('备注已更新')
    cancelEdit()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '备注更新失败')
  } finally {
    savingNote.value = false
  }
}

async function handleRemove(row) {
  try {
    await ElMessageBox.confirm(
      `确定将 ${row.name || row.code} 移出观察池吗？备注将一并删除。`,
      '移出自选股',
      { confirmButtonText: '移除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await deleteWatchStock(row.code)
    ElMessage.success('已移除')
    await fetchList()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '移除失败')
  }
}

onMounted(fetchList)
</script>

<style scoped>
.watchlist-page {
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
.add-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.add-hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.meta-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  padding: 0 var(--space-1);
}
.meta-line--degraded {
  color: var(--color-warning);
}
.meta-line__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-success);
}
.meta-line--degraded .meta-line__dot {
  background: var(--color-warning);
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
.name--missing {
  color: var(--color-text-disabled);
}
.quote-error {
  font-size: var(--text-xs);
  color: var(--color-danger);
}
.text-muted {
  color: var(--color-text-disabled);
}
.pct-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  font-variant-numeric: tabular-nums;
}
.pct-pill--up {
  background: var(--color-up-soft);
  color: var(--color-up);
}
.pct-pill--down {
  background: var(--color-down-soft);
  color: var(--color-down);
}
.note-cell {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.note-edit {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
</style>
