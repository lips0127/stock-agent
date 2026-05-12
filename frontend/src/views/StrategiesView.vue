<template>
  <div class="strategies-page">
    <el-page-header @back="$router.push('/dashboard')" title="返回" />
    <h2 class="page-title">策略管理</h2>

    <el-row :gutter="20">
      <el-col :span="12" v-for="s in strategies" :key="s.name" style="margin-bottom: 16px">
        <el-card shadow="hover" :body-style="{ padding: '20px' }">
          <template #header>
            <div class="card-header">
              <span class="strategy-name">{{ s.name }}</span>
              <el-tag type="info" size="small">{{ s.class_name }}</el-tag>
            </div>
          </template>

          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="关注标的">
              <el-tag v-for="sym in s.symbols" :key="sym" size="small" style="margin-right:4px">
                {{ sym }}
              </el-tag>
              <span v-if="!s.symbols.length" class="text-muted">未指定</span>
            </el-descriptions-item>
            <el-descriptions-item label="K线周期">
              {{ s.timeframes.join(', ') }}
            </el-descriptions-item>
            <el-descriptions-item label="参数" :span="2">
              <template v-if="Object.keys(s.params).length">
                <el-tag v-for="(v, k) in s.params" :key="k" size="small" type="warning" style="margin-right:6px">
                  {{ k }}: {{ v }}
                </el-tag>
              </template>
              <span v-else class="text-muted">无额外参数</span>
            </el-descriptions-item>
            <el-descriptions-item label="说明" :span="2" v-if="s.doc">
              <span class="doc-text">{{ s.doc }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <div style="margin-top: 12px">
            <el-button type="primary" size="small" @click="goBacktest(s)">
              去回测
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!strategies.length" description="暂无已注册的策略" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getStrategies } from '../api'

const router = useRouter()
const strategies = ref([])

function goBacktest(s) {
  router.push({ name: 'Backtest', query: { strategy: s.name } })
}

onMounted(async () => {
  try {
    const { data } = await getStrategies()
    strategies.value = data
  } catch (e) {
    console.error('获取策略列表失败:', e)
  }
})
</script>

<style scoped>
.page-title {
  margin: 16px 0;
  font-size: 20px;
  font-weight: 600;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.strategy-name {
  font-weight: 700;
  font-size: 15px;
  font-family: monospace;
}
.doc-text {
  color: #666;
  font-size: 13px;
  white-space: pre-wrap;
}
.text-muted {
  color: #999;
  font-size: 13px;
}
</style>
