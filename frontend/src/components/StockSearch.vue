<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    :title="dialogTitle"
    width="460px"
    destroy-on-close
  >
    <div v-loading="loading">
      <template v-if="stock">
        <el-descriptions :column="1" border size="large">
          <el-descriptions-item label="代码">{{ stock.code }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ stock.name }}</el-descriptions-item>
          <el-descriptions-item label="最新价">
            {{ stock.price != null ? Number(stock.price).toFixed(2) : '--' }}
          </el-descriptions-item>
          <el-descriptions-item label="股息率">
            <el-tag
              :type="stock.dividend_yield >= 5 ? 'danger' : 'success'"
              size="small"
              effect="light"
            >
              {{ stock.dividend_yield != null ? Number(stock.dividend_yield).toFixed(2) + '%' : '--' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="每股分红">
            {{ stock.dividend_per_share != null ? Number(stock.dividend_per_share).toFixed(4) + ' 元/股' : '--' }}
          </el-descriptions-item>
          <el-descriptions-item label="分红财年">
            {{ stock.dividend_note || '--' }}
          </el-descriptions-item>
        </el-descriptions>
        <div class="stock-link">
          <el-link :href="eastmoneyUrl" target="_blank" type="primary">
            东方财富详情页 →
          </el-link>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="未找到该股票" :image-size="60" />
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { getStock } from '../api'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  symbol: { type: String, default: '' },
})

const emit = defineEmits(['update:visible'])

const stock = ref(null)
const loading = ref(false)

const dialogTitle = computed(() =>
  props.symbol ? `股票详情 · ${props.symbol}` : '股票详情'
)

const eastmoneyUrl = computed(() => {
  if (!stock.value?.code) return ''
  const code = stock.value.code
  let market = 'sh'
  if (code.startsWith('0') || code.startsWith('3')) market = 'sz'
  else if (code.startsWith('4') || code.startsWith('8')) market = 'bj'
  return `http://quote.eastmoney.com/${market}${code}.html`
})

watch(
  () => props.visible,
  async (v) => {
    if (!v || !props.symbol) return
    loading.value = true
    stock.value = null
    try {
      const code = typeof props.symbol === 'string' ? props.symbol : String(props.symbol?.code || '')
      if (!code) return
      const { data } = await getStock(code)
      stock.value = data
    } catch (e) {
      ElMessage.error(e.response?.data?.error || '查询失败')
    } finally {
      loading.value = false
    }
  }
)
</script>

<style scoped>
.stock-link {
  margin-top: 16px;
  text-align: right;
}
</style>
