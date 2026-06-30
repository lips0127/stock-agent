<template>
  <div class="position-page">
    <PageHeader
      title="持仓快照"
      subtitle="按日期归档的持仓记录"
    >
      <template #actions>
        <el-button :icon="Back" @click="$router.push('/nav')">返回净值管理</el-button>
        <el-button type="primary" :icon="Document" @click="openBatchDialog">
          批量导入
        </el-button>
        <el-button type="primary" :icon="Plus" @click="openAddDialog">
          新增持仓
        </el-button>
      </template>
    </PageHeader>

    <ModernCard>
      <div class="filter-bar">
        <el-select v-model="selectedDate" placeholder="选择快照日期" style="width: 180px" @change="loadPositions">
          <el-option v-for="d in snapshotDates" :key="d" :label="d" :value="d" />
        </el-select>
        <el-button @click="loadSnapshotDates">刷新日期</el-button>
      </div>
    </ModernCard>

    <ModernCard padded>
      <el-table :data="positions" v-loading="loading" :empty-text="'暂无持仓数据'">
        <el-table-column prop="symbol" label="代码" width="120">
          <template #default="{ row }">
            <span class="code-cell">{{ row.symbol }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="持仓数量" width="120" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatNum(row.quantity) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成本价" width="120" align="right">
          <template #default="{ row }">
            <span class="num">¥{{ (row.avg_cost || 0).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="现价" width="120" align="right">
          <template #default="{ row }">
            <span class="num">¥{{ (row.current_price || 0).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="市值" width="160" align="right">
          <template #default="{ row }">
            <span class="num money">¥{{ formatNum(row.market_value) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="盈亏" width="160" align="right">
          <template #default="{ row }">
            <template v-if="row.quantity && row.avg_cost">
              <span :class="profitClass(row)">
                {{ profitSign(row) }}¥{{ Math.abs(profit(row)).toFixed(2) }}
              </span>
            </template>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="数据来源" width="110">
          <template #default="{ row }">
            <span class="source-pill">{{ row.source === 'manual' ? '手动' : 'OCR' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="center" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="editPosition(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="deletePosition(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="positions.length" class="position-summary">
        <span class="text-muted">合计持仓</span>
        <span class="position-summary__num">¥{{ formatNum(totalMarketValue) }}</span>
      </div>
    </ModernCard>

    <el-dialog v-model="showDialog" :title="editMode ? '编辑持仓' : '新增持仓'" width="500px">
      <el-form :model="positionForm" label-position="top">
        <el-form-item label="快照日期">
          <el-date-picker v-model="positionForm.snapshot_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="股票代码">
          <el-input v-model="positionForm.symbol" placeholder="如: 000001" />
        </el-form-item>
        <el-form-item label="股票名称">
          <el-input v-model="positionForm.name" placeholder="如: 平安银行" />
        </el-form-item>
        <el-form-item label="持仓数量">
          <el-input-number v-model="positionForm.quantity" :min="0" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="成本价">
          <el-input-number v-model="positionForm.avg_cost" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="现价">
          <el-input-number v-model="positionForm.current_price" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="submitPosition" :loading="submitting">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showBatchDialog" title="批量导入持仓" width="600px">
      <div class="batch-hint">
        <div class="batch-hint__title">数据格式</div>
        <code>代码 名称 数量 成本价 现价</code> · 每行一条，空格或制表符分隔
      </div>

      <el-form label-position="top">
        <el-form-item label="快照日期">
          <el-date-picker v-model="batchForm.snapshot_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="粘贴数据">
          <el-input
            v-model="batchForm.rawText"
            type="textarea"
            :rows="10"
            placeholder="000001 平安银行 100 12.50 13.20&#10;000002 万科A 200 8.00 7.50"
          />
        </el-form-item>
      </el-form>

      <div v-if="batchParsed.length" class="batch-preview">
        <div class="batch-preview__title">预览 · {{ batchParsed.length }} 条</div>
        <el-table :data="batchParsed" max-height="200" :empty-text="'无'">
          <el-table-column prop="symbol" label="代码" width="100" />
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column prop="quantity" label="数量" width="80" align="right" />
          <el-table-column prop="avg_cost" label="成本" width="80" align="right" />
          <el-table-column prop="current_price" label="现价" width="80" align="right" />
        </el-table>
      </div>

      <template #footer>
        <el-button @click="showBatchDialog = false">取消</el-button>
        <el-button @click="parseBatch">解析数据</el-button>
        <el-button type="primary" @click="submitBatch" :loading="submitting" :disabled="!batchParsed.length">
          确认导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Document, Back } from '@element-plus/icons-vue'
import {
  getNavPositions,
  getNavPositionDates,
  addNavPosition,
} from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'

const loading = ref(false)
const submitting = ref(false)

const positions = ref([])
const snapshotDates = ref([])
const selectedDate = ref('')

const showDialog = ref(false)
const editMode = ref(false)
const positionForm = ref({
  snapshot_date: new Date().toISOString().slice(0, 10),
  symbol: '',
  name: '',
  quantity: 0,
  avg_cost: 0,
  current_price: 0,
})

const showBatchDialog = ref(false)
const batchForm = ref({
  snapshot_date: new Date().toISOString().slice(0, 10),
  rawText: '',
})
const batchParsed = ref([])

const totalMarketValue = computed(() =>
  positions.value.reduce((sum, p) => sum + (p.market_value || 0), 0)
)

function formatNum(v) {
  if (v == null) return '0'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function profit(row) {
  return (row.market_value || 0) - (row.quantity || 0) * (row.avg_cost || 0)
}
function profitSign(row) {
  return profit(row) >= 0 ? '+' : '−'
}
function profitClass(row) {
  return profit(row) >= 0 ? 'num-up' : 'num-down'
}

async function loadSnapshotDates() {
  try {
    const res = await getNavPositionDates()
    snapshotDates.value = res.data
    if (snapshotDates.value.length && !selectedDate.value) {
      selectedDate.value = snapshotDates.value[0]
      loadPositions()
    }
  } catch (e) {
    console.error('加载快照日期失败:', e)
  }
}

async function loadPositions() {
  if (!selectedDate.value) return
  loading.value = true
  try {
    const res = await getNavPositions(selectedDate.value)
    positions.value = res.data
    positions.value.forEach(p => {
      if (p.quantity && p.current_price) {
        p.market_value = p.quantity * p.current_price
      }
    })
  } catch (e) {
    console.error('加载持仓失败:', e)
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  editMode.value = false
  positionForm.value = {
    snapshot_date: selectedDate.value || new Date().toISOString().slice(0, 10),
    symbol: '',
    name: '',
    quantity: 0,
    avg_cost: 0,
    current_price: 0,
  }
  showDialog.value = true
}

function editPosition(row) {
  editMode.value = true
  positionForm.value = { ...row }
  showDialog.value = true
}

async function submitPosition() {
  if (!positionForm.value.symbol) {
    ElMessage.warning('请输入股票代码')
    return
  }
  if (positionForm.value.quantity <= 0) {
    ElMessage.warning('请输入持仓数量')
    return
  }
  submitting.value = true
  try {
    const data = {
      snapshot_date: positionForm.value.snapshot_date,
      positions: [{
        symbol: positionForm.value.symbol,
        name: positionForm.value.name,
        quantity: positionForm.value.quantity,
        avg_cost: positionForm.value.avg_cost,
        current_price: positionForm.value.current_price,
        market_value: positionForm.value.quantity * positionForm.value.current_price,
        source: 'manual',
      }],
    }
    await addNavPosition(data)
    ElMessage.success(editMode.value ? '已更新' : '已添加')
    showDialog.value = false
    await loadPositions()
    await loadSnapshotDates()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.error || e.message))
  } finally {
    submitting.value = false
  }
}

async function deletePosition(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除 ${row.name || row.symbol} 吗？`,
      '确认删除',
      { type: 'warning' }
    )
    ElMessage.info('单个删除功能待实现，可手动重新导入')
  } catch (e) { /* cancel */ }
}

function openBatchDialog() {
  batchForm.value = {
    snapshot_date: selectedDate.value || new Date().toISOString().slice(0, 10),
    rawText: '',
  }
  batchParsed.value = []
  showBatchDialog.value = true
}

function parseBatch() {
  const lines = batchForm.value.rawText.trim().split('\n')
  const parsed = []
  for (const line of lines) {
    const parts = line.trim().split(/\s+/)
    if (parts.length >= 5) {
      parsed.push({
        symbol: parts[0],
        name: parts[1],
        quantity: parseFloat(parts[2]) || 0,
        avg_cost: parseFloat(parts[3]) || 0,
        current_price: parseFloat(parts[4]) || 0,
      })
    }
  }
  batchParsed.value = parsed
  if (!parsed.length) {
    ElMessage.warning('未解析到有效数据，请检查格式')
  }
}

async function submitBatch() {
  if (!batchParsed.value.length) {
    ElMessage.warning('请先解析数据')
    return
  }
  submitting.value = true
  try {
    const data = {
      snapshot_date: batchForm.value.snapshot_date,
      positions: batchParsed.value.map(p => ({
        ...p,
        market_value: p.quantity * p.current_price,
        source: 'manual',
      })),
    }
    await addNavPosition(data)
    ElMessage.success(`已导入 ${batchParsed.value.length} 条持仓`)
    showBatchDialog.value = false
    selectedDate.value = batchForm.value.snapshot_date
    await loadPositions()
    await loadSnapshotDates()
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.error || e.message))
  } finally {
    submitting.value = false
  }
}

onMounted(loadSnapshotDates)
</script>

<style scoped>
.position-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.filter-bar {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}
.position-summary {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-divider);
  font-size: var(--text-md);
  margin-top: var(--space-3);
}
.position-summary__num {
  font-size: var(--text-2xl);
  font-weight: var(--weight-semibold);
  color: var(--color-accent);
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.code-cell {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
}
.num {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
}
.money {
  color: var(--color-text-primary);
  font-weight: var(--weight-semibold);
}
.num-up {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-semibold);
  color: var(--color-up);
}
.num-down {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-semibold);
  color: var(--color-down);
}
.source-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}
.batch-hint {
  background: var(--color-bg-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.batch-hint__title {
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
  margin-bottom: var(--space-1);
}
.batch-hint code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--color-bg-elevated);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--color-border);
}
.batch-preview {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-divider);
}
.batch-preview__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
  margin-bottom: var(--space-2);
}
</style>
