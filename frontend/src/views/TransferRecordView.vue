<template>
  <div class="transfer-page">
    <PageHeader
      title="转账记录"
      subtitle="所有参与方的入金与出金流水"
    >
      <template #actions>
        <el-button :icon="Back" @click="$router.push('/nav')">返回净值管理</el-button>
        <el-button type="primary" :icon="Plus" @click="showTransferDialog = true">
          新增转账
        </el-button>
      </template>
    </PageHeader>

    <ModernCard>
      <div class="filter-bar">
        <el-date-picker
          v-model="filter.dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          style="width: 280px"
          @change="loadTransfers"
        />
        <el-select v-model="filter.party" placeholder="参与方" clearable style="width: 150px" @change="loadTransfers">
          <el-option v-for="p in parties" :key="p.code" :label="p.name" :value="p.code" />
        </el-select>
        <el-select v-model="filter.direction" placeholder="方向" clearable style="width: 120px" @change="loadTransfers">
          <el-option label="入金" value="IN" />
          <el-option label="出金" value="OUT" />
        </el-select>
        <el-button @click="resetFilter">重置</el-button>
      </div>
    </ModernCard>

    <ModernCard padded>
      <el-table :data="transfers" v-loading="loading" :empty-text="'暂无转账记录'">
        <el-table-column prop="date" label="日期" width="120" sortable>
          <template #default="{ row }">
            <span class="num">{{ row.date }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="party_name" label="参与方" width="120" />
        <el-table-column label="方向" width="100">
          <template #default="{ row }">
            <span
              class="side-pill"
              :class="row.direction === 'IN' ? 'side-pill--in' : 'side-pill--out'"
            >{{ row.direction === 'IN' ? '入金' : '出金' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="160" align="right">
          <template #default="{ row }">
            <span :class="row.direction === 'IN' ? 'num-up' : 'num-down'">
              {{ row.direction === 'IN' ? '+' : '-' }}¥{{ formatNum(row.amount) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="净值" width="120" align="right">
          <template #default="{ row }">
            <span class="num nav-num">{{ row.nav_at_time.toFixed(4) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="份额变化" width="140" align="right">
          <template #default="{ row }">
            <span :class="row.shares_delta >= 0 ? 'num-up' : 'num-down'">
              {{ row.shares_delta >= 0 ? '+' : '' }}{{ row.shares_delta.toFixed(2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="160" />
        <el-table-column label="操作" width="100" align="center" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" link @click="deleteTransfer(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.pageSize"
          :total="pagination.total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @size-change="loadTransfers"
          @current-change="loadTransfers"
        />
      </div>
    </ModernCard>

    <el-dialog v-model="showTransferDialog" title="新增转账记录" width="450px">
      <el-form :model="transferForm" label-position="top">
        <el-form-item label="转账日期">
          <el-date-picker v-model="transferForm.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="参与方">
          <el-select v-model="transferForm.party_code" placeholder="请选择" style="width: 100%">
            <el-option v-for="p in parties" :key="p.code" :label="p.name" :value="p.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="转账方向">
          <el-radio-group v-model="transferForm.direction">
            <el-radio label="IN">入金</el-radio>
            <el-radio label="OUT">出金</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="金额">
          <el-input-number v-model="transferForm.amount" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="transferForm.note" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTransferDialog = false">取消</el-button>
        <el-button type="primary" @click="submitTransfer" :loading="submitting">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Back } from '@element-plus/icons-vue'
import {
  getNavTransfers,
  getNavParties,
  addNavTransfer,
  deleteNavTransfer,
} from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'

const loading = ref(false)
const submitting = ref(false)

const transfers = ref([])
const parties = ref([])

const filter = ref({
  dateRange: [],
  party: '',
  direction: '',
})

const pagination = ref({
  page: 1,
  pageSize: 20,
  total: 0,
})

const showTransferDialog = ref(false)
const transferForm = ref({
  date: new Date().toISOString().slice(0, 10),
  party_code: '',
  direction: 'IN',
  amount: 0,
  note: '',
})

function formatNum(v) {
  if (v == null) return '0'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

async function loadTransfers() {
  loading.value = true
  try {
    const params = {
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
    }
    if (filter.value.dateRange?.length === 2) {
      params.start_date = filter.value.dateRange[0]
      params.end_date = filter.value.dateRange[1]
    }
    if (filter.value.party) params.party = filter.value.party
    if (filter.value.direction) params.direction = filter.value.direction

    const res = await getNavTransfers(params)
    transfers.value = res.data.transfers
    pagination.value.total = res.data.total
  } catch (e) {
    console.error('加载转账记录失败:', e)
  } finally {
    loading.value = false
  }
}

async function loadParties() {
  try {
    const res = await getNavParties()
    parties.value = res.data
  } catch (e) {
    console.error('加载参与方失败:', e)
  }
}

function resetFilter() {
  filter.value = { dateRange: [], party: '', direction: '' }
  loadTransfers()
}

async function submitTransfer() {
  if (!transferForm.value.party_code || transferForm.value.amount <= 0) {
    ElMessage.warning('请填写完整信息')
    return
  }
  submitting.value = true
  try {
    await addNavTransfer(transferForm.value)
    ElMessage.success('转账记录已添加')
    showTransferDialog.value = false
    await loadTransfers()
  } catch (e) {
    ElMessage.error('添加失败: ' + (e.response?.data?.error || e.message))
  } finally {
    submitting.value = false
  }
}

async function deleteTransfer(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除 ${row.date} ${row.party_name} ${row.direction === 'IN' ? '入金' : '出金'} ¥${row.amount} 这条记录吗？`,
      '确认删除',
      { type: 'warning' }
    )
    await deleteNavTransfer(row.id)
    ElMessage.success('已删除')
    await loadTransfers()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message))
    }
  }
}

onMounted(() => {
  loadParties()
  loadTransfers()
})
</script>

<style scoped>
.transfer-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.filter-bar {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  flex-wrap: wrap;
}
.pagination-bar {
  padding: var(--space-4) var(--space-5);
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--color-divider);
  margin-top: var(--space-3);
}
.num {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
}
.nav-num {
  color: var(--color-accent);
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
.side-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
}
.side-pill--in {
  background: var(--color-up-soft);
  color: var(--color-up);
}
.side-pill--out {
  background: var(--color-success-soft);
  color: var(--color-success);
}
</style>
