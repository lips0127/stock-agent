<template>
  <ModernCard class="task-card" :class="{ 'task-card--disabled': !form.enabled }">
    <template #title>
      <div class="task-card__title-row">
        <span class="task-card__name">{{ task.display_name }}</span>
        <el-tag
          v-if="task.trigger_type === 'cron'"
          type="primary"
          size="small"
          effect="plain"
        >cron</el-tag>
        <el-tag
          v-else
          type="success"
          size="small"
          effect="plain"
        >interval</el-tag>
      </div>
    </template>
    <template #extra>
      <el-switch
        v-model="form.enabled"
        :loading="toggling"
        @change="onToggle"
        inline-prompt
        active-text="启用"
        inactive-text="暂停"
      />
    </template>

    <p class="task-card__desc">{{ task.description }}</p>
    <code class="task-card__func">{{ task.function_name }}</code>

    <!-- cron 编辑控件 -->
    <div v-if="task.trigger_type === 'cron'" class="task-card__form">
      <div class="form-row">
        <label>小时</label>
        <el-input-number
          v-model="form.hour" :min="0" :max="23" size="small" :step="1"
          controls-position="right"
        />
      </div>
      <div class="form-row">
        <label>分钟</label>
        <el-input-number
          v-model="form.minute" :min="0" :max="59" size="small" :step="1"
          controls-position="right"
        />
      </div>
      <div class="form-row form-row--wide">
        <label>星期</label>
        <el-select v-model="dowMode" size="small" style="width: 100%">
          <el-option label="每日" value="*" />
          <el-option label="工作日 (周一-周五)" value="mon-fri" />
          <el-option label="周末 (周六-周日)" value="sat,sun" />
          <el-option label="周一" value="mon" />
          <el-option label="周二" value="tue" />
          <el-option label="周三" value="wed" />
          <el-option label="周四" value="thu" />
          <el-option label="周五" value="fri" />
          <el-option label="周六" value="sat" />
          <el-option label="周日" value="sun" />
          <el-option label="自定义…" value="__custom__" />
        </el-select>
        <el-input
          v-if="dowMode === '__custom__'"
          v-model="form.day_of_week" size="small" style="margin-top: 6px"
          placeholder="例如: mon,wed,fri"
        />
      </div>
    </div>

    <!-- interval 编辑控件 -->
    <div v-else class="task-card__form">
      <div class="form-row form-row--wide">
        <label>间隔（小时）</label>
        <el-input-number
          v-model="form.interval_hours" :min="1" :max="168" size="small" :step="1"
          controls-position="right"
        />
      </div>
    </div>

    <div class="task-card__footer">
      <span class="task-card__hint">
        切换开关<strong>立即生效</strong>；时间改动需点保存
      </span>
      <el-button
        type="primary" size="small"
        :disabled="!dirty || saving"
        :loading="saving"
        @click="onSave"
      >保存</el-button>
    </div>

    <div class="task-card__next">
      <span v-if="form.enabled" class="next-run">
        <el-icon><Clock /></el-icon>
        下次执行：<strong>{{ formatNext(task.next_run_time) }}</strong>
      </span>
      <span v-else class="next-run next-run--paused">
        <el-icon><VideoPause /></el-icon>
        已暂停
      </span>
    </div>

    <!-- 运行历史手风琴 -->
    <div class="task-card__history" @click="toggleHistory">
      <el-icon class="history-icon"><component :is="historyOpen ? ArrowDown : ArrowRight" /></el-icon>
      <span class="history-label">运行历史</span>
      <span v-if="latestSummary" class="history-summary" :class="`history-summary--${latestSummary.status}`">
        最近：{{ latestSummary.text }}
      </span>
      <span v-else class="history-summary history-summary--empty">无记录</span>
    </div>

    <transition name="collapse">
      <div v-show="historyOpen" class="task-card__history-panel">
        <div v-if="loadingRuns" class="history-loading">加载中…</div>
        <div v-else-if="!runs.length" class="history-empty">暂无运行记录</div>
        <ul v-else class="history-list">
          <li v-for="r in runs" :key="r.id" class="history-item" :class="`history-item--${r.status}`">
            <div class="history-item__head">
              <el-tag
                :type="statusTagType(r.status)" size="small" effect="plain"
              >{{ statusLabel(r.status) }}</el-tag>
              <span class="history-item__time">{{ formatStarted(r.started_at) }}</span>
              <span v-if="r.duration_ms != null" class="history-item__dur">
                {{ formatDuration(r.duration_ms) }}
              </span>
            </div>
            <div v-if="r.message" class="history-item__msg" :title="r.message">
              {{ truncate(r.message, 120) }}
            </div>
          </li>
        </ul>
      </div>
    </transition>
  </ModernCard>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Clock, VideoPause, ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import ModernCard from './ui/ModernCard.vue'
import {
  updateSchedulerConfig, pauseSchedulerJob, resumeSchedulerJob,
  getSchedulerJobRuns,
} from '../api/scheduler'

const PRESET_DOW = new Set(['*', 'mon-fri', 'sat,sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])

const props = defineProps({
  task: { type: Object, required: true },
})
const emit = defineEmits(['saved', 'toggle'])

// 本地副本（包含 enabled 切换，dirty 比较时排除 enabled）
const form = ref(cloneForm(props.task))
watch(() => props.task, (t) => { form.value = cloneForm(t) }, { deep: true })

function cloneForm(t) {
  return {
    hour: t.hour,
    minute: t.minute,
    day_of_week: t.day_of_week,
    interval_hours: t.interval_hours,
    enabled: !!t.enabled,
  }
}

// dirty：timing 字段变了（不算 enabled，enabled 走 toggle）
const dirty = computed(() => {
  if (form.value.hour !== props.task.hour) return true
  if (form.value.minute !== props.task.minute) return true
  if ((form.value.day_of_week || '') !== (props.task.day_of_week || '')) return true
  if (form.value.interval_hours !== props.task.interval_hours) return true
  return false
})

// dowMode 让 day_of_week 有"友好下拉"+"自定义"两种模式
const dowMode = ref(props.task.day_of_week && !PRESET_DOW.has(props.task.day_of_week) ? '__custom__' : (props.task.day_of_week || '*'))
watch(() => form.value.day_of_week, (v) => {
  if (v && !PRESET_DOW.has(v) && dowMode.value !== '__custom__') dowMode.value = '__custom__'
  else if (v && PRESET_DOW.has(v)) dowMode.value = v
})
watch(dowMode, (m) => {
  if (m !== '__custom__') form.value.day_of_week = m
})

const saving = ref(false)
async function onSave() {
  saving.value = true
  try {
    const payload = {}
    if (props.task.trigger_type === 'cron') {
      payload.hour = Number(form.value.hour)
      payload.minute = Number(form.value.minute)
      payload.day_of_week = form.value.day_of_week || '*'
    } else {
      payload.interval_hours = Number(form.value.interval_hours)
    }
    const { data } = await updateSchedulerConfig(props.task.job_id, payload)
    ElMessage.success(`已保存：下次执行 ${formatNext(data.next_run_time) || '—'}`)
    emit('saved', { ...props.task, ...payload, next_run_time: data.next_run_time })
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '保存失败')
  } finally { saving.value = false }
}

const toggling = ref(false)
async function onToggle(val) {
  toggling.value = true
  try {
    if (val) {
      const { data } = await resumeSchedulerJob(props.task.job_id)
      ElMessage.success(`${props.task.display_name} 已恢复`)
      emit('toggle', { job_id: props.task.job_id, enabled: true, next_run_time: data.next_run_time })
    } else {
      await pauseSchedulerJob(props.task.job_id)
      ElMessage.success(`${props.task.display_name} 已暂停`)
      emit('toggle', { job_id: props.task.job_id, enabled: false, next_run_time: null })
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '切换失败')
    form.value.enabled = !val  // 还原
  } finally { toggling.value = false }
}

function formatNext(s) {
  if (!s) return '—'
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch { return s }
}

// ── 运行历史（v5, 2026-06-07）──
const historyOpen = ref(false)
const runs = ref([])
const loadingRuns = ref(false)

async function toggleHistory() {
  historyOpen.value = !historyOpen.value
  if (historyOpen.value && !runs.value.length) await loadRuns()
}

async function loadRuns() {
  loadingRuns.value = true
  try {
    const { data } = await getSchedulerJobRuns(props.task.job_id, 10)
    runs.value = Array.isArray(data) ? data : []
  } catch (e) {
    ElMessage.error('加载运行历史失败')
    runs.value = []
  } finally { loadingRuns.value = false }
}

const latestSummary = computed(() => {
  if (!runs.value.length) return null
  const r = runs.value[0]
  return {
    status: r.status,
    text: `${statusLabel(r.status)} · ${formatStarted(r.started_at)}`,
  }
})

function statusLabel(s) {
  return { success: '成功', failed: '失败', running: '运行中', skipped: '跳过' }[s] || s
}

function statusTagType(s) {
  return { success: 'success', failed: 'danger', running: 'warning', skipped: 'info' }[s] || ''
}

function formatStarted(s) {
  if (!s) return '—'
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatDuration(ms) {
  if (ms == null) return ''
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60000), s = Math.floor((ms % 60000) / 1000)
  return `${m}m${s}s`
}

function truncate(s, n) {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}

// 当父组件刷新任务列表时（enabled 变化等），自动重新加载历史
watch(() => props.task.enabled, () => {
  if (historyOpen.value) loadRuns()
})
</script>

<style scoped>
.task-card {
  position: relative;
  transition: opacity 0.2s;
}
.task-card--disabled {
  opacity: 0.65;
}
.task-card__title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-card__name {
  font-weight: 600;
  font-size: 14px;
}
.task-card__desc {
  font-size: 12px;
  color: var(--text-tertiary, #6b7280);
  margin: 6px 0;
  line-height: 1.5;
}
.task-card__func {
  display: inline-block;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 11px;
  color: var(--text-secondary, #4b5563);
  background: var(--bg-elevated, #f3f4f6);
  padding: 2px 8px;
  border-radius: 4px;
  margin-bottom: 14px;
}
.task-card__form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
  margin-top: 8px;
}
.form-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.form-row--wide {
  grid-column: 1 / -1;
}
.form-row label {
  font-size: 12px;
  color: var(--text-secondary, #4b5563);
  min-width: 38px;
}
.task-card__footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border-soft, #e5e7eb);
}
.task-card__hint {
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
}
.task-card__hint strong {
  color: var(--color-bull, #16a34a);
}
.task-card__next {
  margin-top: 10px;
  font-size: 12px;
}
.next-run {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-secondary, #4b5563);
}
.next-run--paused {
  color: var(--text-tertiary, #9ca3af);
}

/* ── 运行历史手风琴 ── */
.task-card__history {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-soft, #e5e7eb);
  cursor: pointer;
  font-size: 12px;
  user-select: none;
  transition: color 0.15s;
}
.task-card__history:hover { color: var(--color-accent, #4f46e5); }
.history-icon { font-size: 12px; opacity: 0.7; }
.history-label {
  font-weight: 500;
  color: var(--text-secondary, #4b5563);
}
.history-summary {
  margin-left: auto;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  background: var(--bg-elevated, #f3f4f6);
  color: var(--text-tertiary, #9ca3af);
}
.history-summary--success { color: #16a34a; }
.history-summary--failed { color: #dc2626; }
.history-summary--running { color: #d97706; }
.history-summary--skipped { color: #6b7280; }
.history-summary--empty { font-style: italic; }

.task-card__history-panel {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--bg-muted, #fafafa);
  border-radius: 6px;
  max-height: 240px;
  overflow-y: auto;
}
.history-loading,
.history-empty {
  font-size: 12px;
  color: var(--text-tertiary, #9ca3af);
  padding: 8px 0;
  text-align: center;
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.history-item {
  padding: 6px 8px;
  border-radius: 4px;
  background: #fff;
  border-left: 3px solid var(--border-soft, #e5e7eb);
  font-size: 12px;
}
.history-item--success { border-left-color: #16a34a; }
.history-item--failed { border-left-color: #dc2626; }
.history-item--running { border-left-color: #d97706; }
.history-item--skipped { border-left-color: #9ca3af; }
.history-item__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.history-item__time {
  color: var(--text-secondary, #4b5563);
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 11px;
}
.history-item__dur {
  color: var(--text-tertiary, #9ca3af);
  font-size: 11px;
  margin-left: auto;
}
.history-item__msg {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
  line-height: 1.4;
  word-break: break-all;
}

.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.18s ease;
  overflow: hidden;
}
.collapse-enter-from,
.collapse-leave-to {
  opacity: 0;
  max-height: 0;
}
.collapse-enter-to,
.collapse-leave-from {
  opacity: 1;
  max-height: 240px;
}
</style>
