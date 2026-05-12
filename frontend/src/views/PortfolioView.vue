<template>
  <div class="portfolio-page">
    <el-page-header @back="$router.push('/dashboard')" title="返回" />
    <h2 class="page-title">组合管理</h2>

    <el-row :gutter="20">
      <!-- 组合概览 -->
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>
            <span class="card-title">组合概览</span>
          </template>

          <el-statistic title="总资产" :value="portfolio.total_value?.toFixed(2) || '0'" prefix="¥" />
          <el-divider />

          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="可用资金">
              ¥{{ (portfolio.cash || 0).toFixed(2) }}
            </el-descriptions-item>
            <el-descriptions-item label="持仓市值">
              ¥{{ (portfolio.positions_value || 0).toFixed(2) }}
            </el-descriptions-item>
            <el-descriptions-item label="累计盈亏">
              <span :class="(portfolio.cumulative_pnl || 0) >= 0 ? 'profit' : 'loss'">
                ¥{{ (portfolio.cumulative_pnl || 0).toFixed(2) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="日度收益">
              {{ portfolio.daily_return != null ? (portfolio.daily_return * 100).toFixed(4) + '%' : '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="快照日期">
              {{ portfolio.date || '无数据' }}
            </el-descriptions-item>
          </el-descriptions>

          <el-button style="margin-top:12px" size="small" @click="loadData" :loading="loading">
            刷新
          </el-button>
        </el-card>
      </el-col>

      <!-- 持仓列表 -->
      <el-col :span="16">
        <el-card shadow="hover">
          <template #header>
            <span class="card-title">当前持仓 ({{ positions.length }})</span>
          </template>

          <el-table :data="positions" stripe size="small">
            <el-table-column prop="symbol" label="代码" width="100" />
            <el-table-column prop="quantity" label="持仓数量" width="100" />
            <el-table-column label="持仓成本" width="100">
              <template #default="{ row }">
                ¥{{ (row.avg_cost || 0).toFixed(2) }}
              </template>
            </el-table-column>
            <el-table-column label="现价" width="100">
              <template #default="{ row }">
                ¥{{ (row.current_price || 0).toFixed(2) }}
              </template>
            </el-table-column>
            <el-table-column label="未实现盈亏" width="120">
              <template #default="{ row }">
                <span :class="(row.unrealized_pnl || 0) >= 0 ? 'profit' : 'loss'">
                  ¥{{ (row.unrealized_pnl || 0).toFixed(2) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="已实现盈亏" width="120">
              <template #default="{ row }">
                <span :class="(row.realized_pnl || 0) >= 0 ? 'profit' : 'loss'">
                  ¥{{ (row.realized_pnl || 0).toFixed(2) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="strategy_id" label="策略ID" min-width="120" />
          </el-table>

          <el-empty v-if="!positions.length" description="暂无持仓" />
        </el-card>

        <!-- 风控规则说明 -->
        <el-card shadow="hover" style="margin-top: 16px">
          <template #header>
            <span class="card-title">风控规则参考</span>
          </template>
          <el-table :data="riskRules" stripe size="small">
            <el-table-column prop="name" label="规则名称" width="180" />
            <el-table-column prop="description" label="说明" />
            <el-table-column label="参数" width="200">
              <template #default="{ row }">
                <el-tag v-for="(v, k) in row.params" :key="k" size="small" style="margin-right:4px">
                  {{ k }}: {{ v }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getPortfolio, getPositions, getRiskRules } from '../api'

const portfolio = ref({})
const positions = ref([])
const riskRules = ref([])
const loading = ref(false)

async function loadData() {
  loading.value = true
  try {
    const [pRes, posRes, rRes] = await Promise.all([
      getPortfolio(),
      getPositions(),
      getRiskRules(),
    ])
    portfolio.value = pRes.data
    positions.value = posRes.data
    riskRules.value = rRes.data
  } catch (e) {
    console.error('加载组合数据失败:', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.page-title {
  margin: 16px 0;
  font-size: 20px;
  font-weight: 600;
}
.card-title {
  font-weight: 600;
}
.profit {
  color: #e32525;
  font-weight: 600;
}
.loss {
  color: #1ca01c;
  font-weight: 600;
}
</style>
