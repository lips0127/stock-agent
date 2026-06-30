<template>
  <div class="nav-page">
    <PageHeader
      title="净值管理"
      subtitle="多方共池基金的净值、份额与转账记录"
    >
      <template #actions>
        <el-button @click="$router.push('/nav/transfers')" :icon="Tickets">转账记录</el-button>
        <el-button @click="$router.push('/nav/positions')" :icon="Box">持仓快照</el-button>
        <el-button type="primary" @click="showCalculateDialog = true" :icon="Setting">记录净值</el-button>
        <el-button type="primary" @click="showTransferDialog = true" :icon="Plus">新增转账</el-button>
      </template>
    </PageHeader>

    <div class="nav-grid">
      <!-- 当前净值 -->
      <ModernCard title="当前净值">
        <div class="nav-display">
          <div class="nav-value">{{ (currentNav.nav || 1).toFixed(4) }}</div>
          <div class="nav-label">单位净值 (NAV)</div>
        </div>

        <div class="nav-fields">
          <div class="nav-field">
            <span class="nav-field__label">总资产</span>
            <span class="nav-field__value">¥{{ formatNum(currentNav.total_asset) }}</span>
          </div>
          <div class="nav-field">
            <span class="nav-field__label">总份额</span>
            <span class="nav-field__value">{{ formatNum(currentNav.total_shares) }}</span>
          </div>
          <div class="nav-field">
            <span class="nav-field__label">记录日期</span>
            <span class="nav-field__value text-secondary">{{ latestRecordDate || '未记录' }}</span>
          </div>
        </div>
      </ModernCard>

      <!-- 各方权益 -->
      <ModernCard :title="`各方权益 (${currentNav.parties?.length || 0})`">
        <el-table :data="currentNav.parties || []" :empty-text="'暂无参与方'">
          <el-table-column prop="name" label="参与方" width="120">
            <template #default="{ row }">
              <span class="party-name">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="初始份额" width="140" align="right">
            <template #default="{ row }">
              <span class="num">{{ formatNum(row.initial_shares) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="当前份额" width="140" align="right">
            <template #default="{ row }">
              <span class="num">{{ formatNum(row.current_shares) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="当前权益" width="160" align="right">
            <template #default="{ row }">
              <span class="num money">¥{{ formatNum(row.equity) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="盈亏" width="160" align="right">
            <template #default="{ row }">
              <span :class="(row.profit || 0) >= 0 ? 'num-up' : 'num-down'">
                {{ (row.profit || 0) >= 0 ? '+' : '' }}{{ formatNum(row.profit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openWithdrawDialog(row)">
                提取
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </ModernCard>
    </div>

    <ModernCard title="净值历史" :description="`共 ${navHistory.length} 条记录`">
      <el-table :data="navHistory" max-height="300" :empty-text="'暂无历史记录'">
        <el-table-column prop="record_date" label="日期" width="140">
          <template #default="{ row }">
            <span class="num">{{ row.record_date }}</span>
          </template>
        </el-table-column>
        <el-table-column label="总资产" width="180" align="right">
          <template #default="{ row }">
            <span class="num money">¥{{ formatNum(row.total_asset) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="总份额" width="160" align="right">
          <template #default="{ row }">
            <span class="num">{{ formatNum(row.total_shares) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="净值" width="140" align="right">
          <template #default="{ row }">
            <span class="num nav-num">{{ (row.nav || 1).toFixed(4) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" />
      </el-table>
    </ModernCard>

    <!-- 新增转账对话框 -->
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

    <!-- 记录净值对话框 -->
    <el-dialog v-model="showCalculateDialog" title="记录当前净值" width="450px">
      <el-form :model="calculateForm" label-position="top">
        <el-form-item label="记录日期">
          <el-date-picker v-model="calculateForm.record_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="总资产">
          <el-input-number v-model="calculateForm.total_asset" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="calculateForm.note" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCalculateDialog = false">取消</el-button>
        <el-button type="primary" @click="submitCalculate" :loading="submitting">计算并保存</el-button>
      </template>
    </el-dialog>

    <!-- 提取对话框 -->
    <el-dialog v-model="showWithdrawDialog" title="提取计算" width="450px">
      <el-form :model="withdrawForm" label-position="top">
        <div class="withdraw-info">
          <div class="withdraw-info__row">
            <span class="text-muted">参与方</span>
            <span class="withdraw-info__val">{{ withdrawForm.party_name }}</span>
          </div>
          <div class="withdraw-info__row">
            <span class="text-muted">当前权益</span>
            <span class="withdraw-info__val">¥{{ formatNum(withdrawForm.party_equity) }}</span>
          </div>
          <div class="withdraw-info__row">
            <span class="text-muted">当前净值</span>
            <span class="withdraw-info__val">{{ (withdrawForm.nav || 1).toFixed(4) }}</span>
          </div>
        </div>

        <el-form-item label="提取方式">
          <el-radio-group v-model="withdrawForm.type">
            <el-radio label="amount">按金额提取</el-radio>
            <el-radio label="shares">按份额提取</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="withdrawForm.type === 'amount' ? '提取金额' : '提取份额'">
          <el-input-number v-model="withdrawForm.value" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="提取日期">
          <el-date-picker v-model="withdrawForm.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="withdrawForm.note" placeholder="可选" />
        </el-form-item>
      </el-form>

      <div v-if="withdrawPreview" class="withdraw-preview" :class="{ 'withdraw-preview--error': !withdrawPreview.can_withdraw }">
        <div v-if="withdrawForm.type === 'amount'">
          需兑换 <strong>{{ formatNum(withdrawPreview.shares_to_redeem) }}</strong> 份额
        </div>
        <div v-else>
          可提取 <strong>¥{{ formatNum(withdrawPreview.amount_to_receive) }}</strong>
        </div>
        <div v-if="!withdrawPreview.can_withdraw" class="withdraw-preview__error">
          ⚠ 余额不足，无法提取
        </div>
      </div>

      <template #footer>
        <el-button @click="showWithdrawDialog = false">取消</el-button>
        <el-button @click="previewWithdraw" :loading="previewing">预览</el-button>
        <el-button type="primary" @click="confirmWithdraw" :loading="submitting" :disabled="!withdrawPreview?.can_withdraw">
          确认提取
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Setting, Tickets, Box } from '@element-plus/icons-vue'
import {
  getCurrentNav,
  getNavHistory,
  getNavParties,
  initNavParties,
  addNavTransfer,
  previewWithdraw as apiPreviewWithdraw,
  confirmWithdraw as apiConfirmWithdraw,
  calculateNav,
} from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'

const loading = ref(false)
const submitting = ref(false)
const previewing = ref(false)

const currentNav = ref({})
const navHistory = ref([])
const parties = ref([])

const latestRecordDate = computed(() => {
  if (navHistory.value.length > 0) return navHistory.value[0].record_date
  return null
})

const showTransferDialog = ref(false)
const transferForm = ref({
  date: new Date().toISOString().slice(0, 10),
  party_code: '',
  direction: 'IN',
  amount: 0,
  note: '',
})

const showCalculateDialog = ref(false)
const calculateForm = ref({
  record_date: new Date().toISOString().slice(0, 10),
  total_asset: 0,
  note: '',
})

const showWithdrawDialog = ref(false)
const withdrawForm = ref({
  party_code: '',
  party_name: '',
  party_equity: 0,
  nav: 1,
  type: 'amount',
  value: 0,
  date: new Date().toISOString().slice(0, 10),
  note: '',
})
const withdrawPreview = ref(null)

function formatNum(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

async function loadData() {
  loading.value = true
  try {
    const [navRes, historyRes, partiesRes] = await Promise.all([
      getCurrentNav(),
      getNavHistory(),
      getNavParties(),
    ])
    currentNav.value = navRes.data
    navHistory.value = historyRes.data
    parties.value = partiesRes.data

    if (!partiesRes.data.length) {
      await initDefaultParties()
    }
  } catch (e) {
    console.error('加载净值数据失败:', e)
  } finally {
    loading.value = false
  }
}

async function initDefaultParties() {
  await initNavParties({
    parties: [
      { code: 'A', name: '朋友A', initial_shares: 17614.15, description: '2025年底亏损清仓结转' },
      { code: 'B', name: '弟弟B', initial_shares: 10000, description: '2026年1月初始投入' },
      { code: 'USER', name: '用户本人', initial_shares: 0, description: '用户自有资金' },
    ],
  })
  const partiesRes = await getNavParties()
  parties.value = partiesRes.data
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
    await loadData()
  } catch (e) {
    ElMessage.error('添加失败: ' + (e.response?.data?.error || e.message))
  } finally {
    submitting.value = false
  }
}

async function submitCalculate() {
  if (calculateForm.value.total_asset <= 0) {
    ElMessage.warning('请输入总资产')
    return
  }
  submitting.value = true
  try {
    await calculateNav(calculateForm.value)
    ElMessage.success('净值已记录')
    showCalculateDialog.value = false
    await loadData()
  } catch (e) {
    ElMessage.error('记录失败: ' + (e.response?.data?.error || e.message))
  } finally {
    submitting.value = false
  }
}

function openWithdrawDialog(party) {
  withdrawForm.value = {
    party_code: party.code,
    party_name: party.name,
    party_equity: party.equity,
    nav: currentNav.value.nav || 1,
    type: 'amount',
    value: 0,
    date: new Date().toISOString().slice(0, 10),
    note: '',
  }
  withdrawPreview.value = null
  showWithdrawDialog.value = true
}

async function previewWithdraw() {
  if (withdrawForm.value.value <= 0) {
    ElMessage.warning('请输入提取金额或份额')
    return
  }
  previewing.value = true
  try {
    const params = { party_code: withdrawForm.value.party_code }
    if (withdrawForm.value.type === 'amount') {
      params.target_amount = withdrawForm.value.value
    } else {
      params.target_shares = withdrawForm.value.value
    }
    const res = await apiPreviewWithdraw(params)
    withdrawPreview.value = res.data
  } catch (e) {
    ElMessage.error('预览失败: ' + (e.response?.data?.error || e.message))
  } finally {
    previewing.value = false
  }
}

async function confirmWithdraw() {
  if (!withdrawPreview.value?.can_withdraw) {
    ElMessage.warning('余额不足，无法提取')
    return
  }
  submitting.value = true
  try {
    const data = {
      party_code: withdrawForm.value.party_code,
      date: withdrawForm.value.date,
      note: withdrawForm.value.note,
    }
    if (withdrawForm.value.type === 'amount') {
      data.target_amount = withdrawForm.value.value
    } else {
      data.target_shares = withdrawForm.value.value
    }
    await apiConfirmWithdraw(data)
    ElMessage.success('提取成功')
    showWithdrawDialog.value = false
    await loadData()
  } catch (e) {
    ElMessage.error('提取失败: ' + (e.response?.data?.error || e.message))
  } finally {
    submitting.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.nav-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.nav-grid {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: var(--space-4);
  align-items: start;
}
.nav-display {
  text-align: center;
  padding: var(--space-4) 0;
}
.nav-value {
  font-size: 56px;
  font-weight: var(--weight-semibold);
  color: var(--color-accent);
  letter-spacing: -0.03em;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.nav-label {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin-top: var(--space-2);
}
.nav-fields {
  margin-top: var(--space-4);
  display: flex;
  flex-direction: column;
}
.nav-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-divider);
}
.nav-field:last-child { border-bottom: none; }
.nav-field__label {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}
.nav-field__value {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.party-name {
  font-weight: var(--weight-medium);
}
.num {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-medium);
}
.money {
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

.withdraw-info {
  background: var(--color-bg-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.withdraw-info__row {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-sm);
}
.withdraw-info__val {
  font-weight: var(--weight-medium);
  font-variant-numeric: tabular-nums;
}
.withdraw-preview {
  background: var(--color-accent-soft);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-accent-text);
  margin-top: var(--space-2);
}
.withdraw-preview strong {
  font-weight: var(--weight-semibold);
}
.withdraw-preview--error {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}
.withdraw-preview__error {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
}
</style>
