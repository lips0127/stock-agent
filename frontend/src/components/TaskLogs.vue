<template>
  <el-card shadow="never" class="section-card">
    <template #header>
      <div class="logs-header">
        <span class="section-title">扫描任务日志</span>
        <el-button text size="small" @click="expanded = !expanded">
          {{ expanded ? '收起' : '展开' }}
          <el-icon><component :is="expanded ? 'ArrowUp' : 'ArrowDown'" /></el-icon>
        </el-button>
      </div>
    </template>
    <div v-if="expanded" v-loading="loading">
      <el-timeline v-if="logs.length">
        <el-timeline-item
          v-for="(log, i) in recentLogs"
          :key="i"
          :timestamp="log.time"
          placement="top"
          type="primary"
        >
          {{ log.message }}
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无日志" :image-size="50" />
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ArrowUp, ArrowDown } from '@element-plus/icons-vue'

const props = defineProps({
  logs: { type: Array, default: () => [] },
  loading: Boolean,
})

const expanded = ref(false)
const recentLogs = computed(() => props.logs.slice(-20).reverse())
</script>

<style scoped>
.logs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
