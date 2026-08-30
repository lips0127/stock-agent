<template>
  <transition name="scan-bar-slide">
    <div v-if="task" class="scan-bar">
      <div class="scan-bar__inner">
        <div class="scan-bar__info">
          <span class="scan-bar__pulse" :class="`scan-bar__pulse--${task.status}`" />
          <span class="scan-bar__label">
            {{ scanLabel }}
          </span>
          <span class="scan-bar__status" :class="`scan-bar__status--${task.status}`">
            {{ statusLabel }}
          </span>
        </div>

        <div v-if="task.status === 'running' && task.total > 0" class="scan-bar__progress">
          <div class="scan-bar__track">
            <div
              class="scan-bar__fill"
              :style="{ width: Math.round((task.done / task.total) * 100) + '%' }"
            />
          </div>
          <span class="scan-bar__count">{{ task.done }} / {{ task.total }}</span>
          <el-link type="primary" :underline="false" @click="goProgress">详情 →</el-link>
        </div>

        <div
          v-else-if="task.status === 'running'"
          class="scan-bar__progress scan-bar__progress--preparing"
        >
          <span class="scan-bar__dots">
            <span /><span /><span />
          </span>
          <span class="scan-bar__count">正在准备股票列表</span>
        </div>

        <div v-else-if="task.status === 'success'" class="scan-bar__result">
          <span>扫描完成 · 共 <strong>{{ task.result_count ?? 0 }}</strong> 只股票</span>
          <el-link type="primary" :underline="false" @click="goProgress">查看详情 →</el-link>
        </div>

        <div v-else-if="task.status === 'failed'" class="scan-bar__error">
          {{ task.error_message || '扫描失败' }}
        </div>
      </div>

      <button class="scan-bar__close" @click="taskStore.dismissTask()" aria-label="关闭">
        <el-icon><Close /></el-icon>
      </button>
    </div>
  </transition>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Close } from '@element-plus/icons-vue'
import { useTaskStore } from '../stores/task'

const router = useRouter()
const taskStore = useTaskStore()

const task = computed(() => taskStore.currentTask)

// 轮询后 /api/tasks/<id> 返回的是 kind（scan_full/scan_index），初始态是 type，两者都兜住
const scanLabel = computed(() => {
  const t = task.value
  if (!t) return ''
  const isFull = t.type === 'full' || t.kind === 'scan_full'
  return isFull ? '全市场扫描' : '红利指数扫描'
})

const statusLabel = computed(() => {
  const map = {
    running: '扫描中',
    success: '已完成',
    failed: '失败',
    pending: '等待中',
  }
  return map[task.value?.status] || task.value?.status
})

function goProgress() {
  if (taskStore.taskId) {
    router.push({ name: 'ScanProgress', params: { taskId: taskStore.taskId } })
  }
}
</script>

<style scoped>
/* ── 全局底部条：固定跨整个主区（侧边栏外），与右侧内容不冲突 ── */
.scan-bar {
  position: fixed;
  left: var(--layout-sidebar-width);
  right: 0;
  bottom: 0;
  z-index: var(--z-sticky);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: saturate(180%) blur(16px);
  -webkit-backdrop-filter: saturate(180%) blur(16px);
  border-top: 1px solid var(--color-border);
  padding: var(--space-3) var(--space-6);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  box-shadow: 0 -4px 24px -8px rgba(15, 15, 15, 0.06);
  font-size: var(--text-sm);
}

.scan-bar__inner {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-5);
  min-width: 0;
  max-width: var(--layout-max-width);
  margin: 0 auto;
  width: 100%;
}

.scan-bar__info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.scan-bar__pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-info);
  flex-shrink: 0;
  position: relative;
}
.scan-bar__pulse--running {
  background: var(--color-warning);
  animation: scan-pulse 1.4s var(--ease) infinite;
}
.scan-bar__pulse--success { background: var(--color-success); }
.scan-bar__pulse--failed  { background: var(--color-danger); }
.scan-bar__pulse--pending { background: var(--color-text-tertiary); }
@keyframes scan-pulse {
  0%, 100% { opacity: 1;   transform: scale(1);   }
  50%      { opacity: 0.5; transform: scale(1.4); }
}

.scan-bar__label {
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  white-space: nowrap;
  letter-spacing: -0.01em;
}
.scan-bar__status {
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-weight: var(--weight-medium);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}
.scan-bar__status--running { background: var(--color-warning-soft); color: var(--color-warning); }
.scan-bar__status--success { background: var(--color-success-soft); color: var(--color-success); }
.scan-bar__status--failed  { background: var(--color-danger-soft);  color: var(--color-danger);  }

.scan-bar__progress {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.scan-bar__progress--preparing {
  color: var(--color-text-tertiary);
  font-style: normal;
}
.scan-bar__track {
  flex: 1;
  height: 6px;
  background: var(--color-bg-muted);
  border-radius: var(--radius-full);
  overflow: hidden;
  max-width: 360px;
}
.scan-bar__fill {
  height: 100%;
  background: var(--color-accent);
  border-radius: var(--radius-full);
  transition: width var(--duration-page) var(--ease);
}
.scan-bar__count {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum';
  font-weight: var(--weight-medium);
}

/* 三点呼吸动画：替代"…"文本，更克制 */
.scan-bar__dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.scan-bar__dots > span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--color-warning);
  animation: scan-dot 1.2s var(--ease) infinite;
}
.scan-bar__dots > span:nth-child(2) { animation-delay: 0.15s; }
.scan-bar__dots > span:nth-child(3) { animation-delay: 0.3s; }
@keyframes scan-dot {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.85); }
  40%           { opacity: 1;   transform: scale(1.1);  }
}

.scan-bar__result {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  min-width: 0;
}
.scan-bar__result strong {
  color: var(--color-accent);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
}

.scan-bar__error {
  color: var(--color-danger);
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.scan-bar__close {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  border-radius: var(--radius-md);
  color: var(--color-text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all var(--duration-page) var(--ease);
}
.scan-bar__close:hover {
  background: var(--color-bg-muted);
  color: var(--color-text-primary);
}

/* ── 进场动画：上滑 + 淡入 ── */
.scan-bar-slide-enter-active,
.scan-bar-slide-leave-active {
  transition: transform var(--duration-slow) var(--ease),
              opacity var(--duration-slow) var(--ease);
}
.scan-bar-slide-enter-from,
.scan-bar-slide-leave-to {
  transform: translateY(20px);
  opacity: 0;
}
</style>
