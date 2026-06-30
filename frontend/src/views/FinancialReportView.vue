<template>
  <div class="finreport-page">
    <div class="finreport-page__ambient" aria-hidden="true">
      <GradientBlob position="tr" size="lg" />
    </div>

    <PageHeader
      title="财报解析"
      subtitle="粘贴财经报告/新闻/会议纪要，自动识别A股公司并查看财务数据"
      size="lg"
    >
      <template #icon>
        <el-icon :size="20"><Document /></el-icon>
      </template>
    </PageHeader>

    <!-- 输入区 -->
    <ModernCard title="输入报告文本" description="支持财经新闻、研究报告、业绩说明会纪要等自由文本">
      <div class="input-section">
        <el-input
          v-model="reportText"
          type="textarea"
          :rows="8"
          placeholder="在此粘贴财经新闻、研究报告、业绩说明会纪要等文本...&#10;&#10;例如：&#10;贵州茅台(600519)今日发布2025年财报，全年营收同比增长15%，超出市场预期。宁德时代(300750)则因电池业务毛利率下滑，净利润同比下降8%。"
          resize="vertical"
        />
        <div class="input-actions">
          <span class="input-hint">{{ reportText.length }} 字</span>
          <el-button
            type="primary"
            :loading="analyzing"
            :disabled="!reportText.trim() || reportText.trim().length < 50"
            @click="handleAnalyze"
          >
            <el-icon><Search /></el-icon>
            解析报告
          </el-button>
        </div>
      </div>
    </ModernCard>

    <!-- 错误提示 -->
    <transition name="fade">
      <div v-if="errorMsg" class="error-bar">
        <el-icon><WarningFilled /></el-icon>
        {{ errorMsg }}
      </div>
    </transition>

    <!-- 空状态 -->
    <EmptyHint
      v-if="!result && !analyzing"
      title="尚未解析"
      description="在上方粘贴财经报告文本，点击「解析报告」开始分析"
      carded
    />

    <!-- 结果区 -->
    <template v-if="result">
      <ModernCard v-if="result.summary" title="报告摘要" variant="glass">
        <p class="summary-text">{{ result.summary }}</p>
      </ModernCard>

      <ModernCard
        v-if="result.companies && result.companies.length"
        :title="`识别到 ${result.companies.length} 家公司`"
        variant="bordered"
      >
        <div class="company-list">
          <div
            v-for="(company, idx) in result.companies"
            :key="idx"
            class="company-card"
          >
            <StockDashboard
              :code="company.code"
              :name="company.name"
              :price="company.price"
              :sentiment="company.sentiment"
              :context="company.context"
              :total-market-cap="company.total_market_cap"
              :float-market-cap="company.float_market_cap"
              :ttm-pe="company.ttm_pe"
              :pe-percentile="company.ttm_pe_percentile"
              :pe-percentile-basis="company.ttm_pe_percentile_basis"
              :ttm-revenue="company.ttm_revenue"
              :ttm-net-profit="company.ttm_net_profit"
              :ttm-gross-profit="company.ttm_gross_profit"
              :quarters="company.quarters"
              :price-history="company.price_history"
              :pe-history="company.pe_history"
            />
          </div>
        </div>
      </ModernCard>
    </template>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Document, WarningFilled } from '@element-plus/icons-vue'
import { analyzeFinancialReport } from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'
import GradientBlob from '../components/ui/GradientBlob.vue'
import StockDashboard from '../components/stock/StockDashboard.vue'

const reportText = ref('')
const analyzing = ref(false)
const result = ref(null)
const errorMsg = ref('')

async function handleAnalyze() {
  const text = reportText.value.trim()
  if (!text) {
    ElMessage.warning('请输入报告文本')
    return
  }
  if (text.length < 50) {
    ElMessage.warning('报告文本过短，至少需要50字')
    return
  }

  analyzing.value = true
  errorMsg.value = ''
  result.value = null

  try {
    const { data } = await analyzeFinancialReport(text)
    if (data.error) {
      errorMsg.value = data.error
      return
    }
    result.value = data
    const count = data.companies?.length || 0
    if (count > 0) {
      ElMessage.success(`识别到 ${count} 家公司`)
    } else {
      ElMessage.info('未识别到A股公司，请检查文本内容')
    }
  } catch (e) {
    const msg = e.response?.data?.error || '解析失败，请稍后重试'
    errorMsg.value = msg
    ElMessage.error(msg)
  } finally {
    analyzing.value = false
  }
}
</script>

<style scoped>
.finreport-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  position: relative;
}

.finreport-page__ambient {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

/* 输入区 */
.input-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.input-hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

/* 错误条 */
.error-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-soft, #fef2f2);
  color: var(--color-danger, #dc2626);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
}

/* 摘要 */
.summary-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: 1.7;
  margin: 0;
}

/* 公司列表 */
.company-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.company-card {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-elevated);
  transition: box-shadow var(--duration-base) var(--ease);
}

.company-card:hover {
  box-shadow: var(--shadow-md);
}
</style>
