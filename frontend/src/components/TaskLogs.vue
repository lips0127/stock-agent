<template>
  <div>
    <div class="logs-toolbar">
      <span class="logs-count">最近 {{ recentLogs.length }} 条</span>
      <el-button text size="small" @click="expanded = !expanded">
        {{ expanded ? '收起' : '展开' }}
        <el-icon class="el-icon--right">
          <component :is="expanded ? 'ArrowUp' : 'ArrowDown'" />
        </el-icon>
      </el-button>
    </div>
    <div v-if="expanded" v-loading="loading" class="logs-body">
      <div v-if="recentLogs.length" class="logs-list">
        <div
          v-for="(log, i) in recentLogs"
          :key="i"
          class="log-row"
        >
          <span class="log-time">{{ log.time }}</span>
          <span class="log-dot" :class="`log-dot--${logLevel(log)}`" />
          <span class="log-msg">{{ log.message }}</span>
        </div>
      </div>
      <EmptyHint
        v-else
        icon="∅"
        title="暂无日志"
        description="系统暂无最近的任务执行记录"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import EmptyHint from './ui/EmptyHint.vue'

const props = defineProps({
  logs: { type: Array, default: () => [] },
  loading: Boolean,
})

const expanded = ref(true)
const recentLogs = computed(() => props.logs.slice(-20).reverse())

function logLevel(log) {
  const m = (log.message || '').toLowerCase()
  if (m.includes('失败') || m.includes('error') || m.includes('fail')) return 'error'
  if (m.includes('成功') || m.includes('success') || m.includes('完成')) return 'success'
  return 'info'
}
</script>

<style scoped>
.logs-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}
.logs-count {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}
.logs-body {
  max-height: 360px;
  overflow-y: auto;
}
.logs-list {
  display: flex;
  flex-direction: column;
}
.log-row {
  display: grid;
  grid-template-columns: 160px 12px 1fr;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-divider);
  font-size: var(--text-sm);
}
.log-row:last-child {
  border-bottom: none;
}
.log-time {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
}
.log-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-info);
  flex-shrink: 0;
}
.log-dot--success { background: var(--color-success); }
.log-dot--error { background: var(--color-danger); }
.log-dot--info { background: var(--color-info); }
.log-msg {
  color: var(--color-text-primary);
  line-height: var(--leading-normal);
  word-break: break-word;
}
</style>
