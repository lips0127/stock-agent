<template>
  <div class="zhihu-page">
    <PageHeader
      title="知乎大V监控"
      subtitle="监控关注用户最新动态 · LLM 情绪分析 · 邮件订阅"
    >
      <template #actions>
        <el-button @click="$router.push('/zhihu/timeline')">📊 大V时间线</el-button>
        <el-button :icon="Setting" @click="openSettings">邮箱设置</el-button>
        <el-button type="primary" :icon="Refresh" :loading="refreshingAll" @click="handleRefreshAll">
          刷新全部大V
        </el-button>
      </template>
    </PageHeader>

    <div class="content-grid">
      <!-- 左侧：用户列表 + 订阅 -->
      <div class="left-panel">
        <ModernCard title="添加大V" description="粘贴知乎主页 URL 或 url_token">
          <div class="add-form">
            <el-input
              v-model="newUrl"
              placeholder="如 https://www.zhihu.com/people/hongliqi"
              clearable
              @keyup.enter="handleAddUser"
            />
            <el-button type="primary" :loading="adding" @click="handleAddUser">添加</el-button>
          </div>
          <div class="add-hint">
            <el-icon><InfoFilled /></el-icon>
            <span>输入知乎 <code>/people/</code> 后面的 url_token 也可</span>
          </div>
        </ModernCard>

        <ModernCard :title="`监控列表 (${users.length})`">
          <template #extra>
            <el-button text size="small" @click="fetchUsers">刷新</el-button>
          </template>
          <div v-loading="usersLoading" class="user-list">
            <EmptyHint
              v-if="!users.length && !usersLoading"
              icon="∅"
              title="尚未添加任何大V"
              description="上方输入 URL 添加"
            />
            <div
              v-for="u in users"
              :key="u.id"
              class="user-row"
              :class="{ 'user-row--active': selectedUserId === u.id }"
              @click="selectUser(u)"
            >
              <el-avatar :src="u.avatar_url" :size="40" class="avatar">
                {{ (u.display_name || u.url_token).slice(0, 1) }}
              </el-avatar>
              <div class="user-info">
                <div class="user-name">
                  <span class="user-name__text">{{ u.display_name || u.url_token }}</span>
                  <el-badge
                    v-if="u.unanalyzed_count"
                    :value="u.unanalyzed_count"
                    class="user-name__badge"
                  />
                </div>
                <div class="user-meta">
                  <span class="url-token">@{{ u.url_token }}</span>
                  <span class="dot">·</span>
                  <span>{{ formatFollower(u.follower_count) }} 粉丝</span>
                </div>
                <div class="user-status">
                  <span class="status-pill" :class="u.enabled ? 'status-pill--on' : 'status-pill--off'">
                    {{ u.enabled ? '启用' : '停用' }}
                  </span>
                  <span v-if="u.email_notify" class="status-pill status-pill--mail">邮件</span>
                  <span class="status-pill" :class="statusKindClass(u)">
                    {{ statusKindLabel(u) }}
                  </span>
                </div>
                <div v-if="u.last_error" class="user-error" :title="u.last_error">
                  <el-icon><Warning /></el-icon>
                  <span>{{ truncate(u.last_error, 60) }}</span>
                </div>
                <div class="user-foot">
                  <span class="last-check">{{ formatTime(u.last_checked_at) || '未抓取' }}</span>
                  <span class="post-count">{{ u.post_count || 0 }} 条动态</span>
                </div>
              </div>
              <el-dropdown trigger="click" @command="(c) => onUserCommand(c, u)" @click.stop>
                <el-button text size="small" :icon="MoreFilled" @click.stop />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="refresh">
                      <el-icon><Refresh /></el-icon> 立即刷新
                    </el-dropdown-item>
                    <el-dropdown-item :command="u.enabled ? 'disable' : 'enable'">
                      {{ u.enabled ? '禁用' : '启用' }}
                    </el-dropdown-item>
                    <el-dropdown-item :command="u.email_notify ? 'mute' : 'unmute'">
                      {{ u.email_notify ? '关闭邮件' : '开启邮件' }}
                    </el-dropdown-item>
                    <el-dropdown-item command="delete" divided>
                      <span style="color: var(--color-danger)">删除</span>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </ModernCard>

        <ModernCard :title="`邮件订阅 (${subs.length})`">
          <template #extra>
            <el-button text size="small" @click="fetchSubs">刷新</el-button>
          </template>
          <div class="sub-add-row">
            <el-input v-model="newSubEmail" size="default" placeholder="邮箱地址" clearable
                      @keyup.enter="handleAddSub" />
            <el-button type="primary" :loading="addingSub" @click="handleAddSub">添加</el-button>
          </div>
          <div class="sub-list">
            <EmptyHint
              v-if="!subs.length"
              icon="∅"
              title="无订阅"
            />
            <div v-for="s in subs" :key="s.id" class="sub-row">
              <div class="sub-info">
                <span class="sub-email">{{ s.email }}</span>
                <div class="sub-meta">
                  <span class="status-pill" :class="s.enabled ? 'status-pill--on' : 'status-pill--off'">
                    {{ s.enabled ? '启用' : '停用' }}
                  </span>
                  <span v-if="s.url_tokens && s.url_tokens !== '[]'" class="sub-scope">
                    限定 {{ countTokens(s.url_tokens) }} 个
                  </span>
                  <span v-else class="sub-scope">全部大V</span>
                </div>
              </div>
              <div class="sub-actions">
                <el-button text size="small" @click.stop="handleTestEmail(s.email)">测试</el-button>
                <el-button text size="small" @click.stop="toggleSub(s)">
                  {{ s.enabled ? '停用' : '启用' }}
                </el-button>
                <el-button text size="small" type="danger" @click.stop="deleteSub(s)">删除</el-button>
              </div>
            </div>
          </div>
        </ModernCard>

        <ModernCard title="发送日志">
          <template #extra>
            <el-button text size="small" @click="fetchLogs">刷新</el-button>
          </template>
          <div class="log-list">
            <EmptyHint v-if="!emailLogs.length" icon="∅" title="无日志" />
            <div v-for="l in emailLogs" :key="l.id" class="log-row">
              <span class="status-pill" :class="l.status === 'success' ? 'status-pill--on' : 'status-pill--danger'">
                {{ l.status === 'success' ? '成功' : '失败' }}
              </span>
              <span class="log-email">{{ l.email }}</span>
              <span class="log-subject">{{ l.subject }}</span>
              <span class="log-time">{{ formatTime(l.sent_at) }}</span>
            </div>
          </div>
        </ModernCard>
      </div>

      <!-- 右侧：动态时间线 -->
      <div class="right-panel">
        <EmptyHint
          v-if="!selectedUserId"
          icon="◉"
          title="从左侧选择大V"
          description="选择后查看其最新动态与 LLM 分析"
        />

        <template v-else>
          <ModernCard>
            <template #title>
              <div class="detail-title">
                <el-avatar :src="selectedUser.avatar_url" :size="32" class="avatar">
                  {{ (selectedUser.display_name || selectedUser.url_token).slice(0, 1) }}
                </el-avatar>
                <div>
                  <div class="detail-title__name">
                    {{ selectedUser.display_name || selectedUser.url_token }}
                  </div>
                  <div class="detail-title__meta">
                    <span class="url-token">@{{ selectedUser.url_token }}</span>
                    <span v-if="selectedUser.follower_count" class="text-muted">
                      · {{ formatFollower(selectedUser.follower_count) }} 粉丝
                    </span>
                  </div>
                </div>
              </div>
            </template>
            <template #extra>
              <!-- 任务进度指示器 -->
              <div v-if="activeTask" class="task-progress-inline">
                <span class="task-progress-inline__spinner" />
                <span class="task-progress-inline__label">{{ activeTask.kind === 'analyze' ? '分析中' : '抓取中' }}</span>
                <span v-if="activeTask.progress_pct > 0" class="task-progress-inline__pct">
                  {{ activeTask.progress_pct }}%
                </span>
                <span v-if="activeTask.current_step" class="task-progress-inline__step">
                  {{ activeTask.current_step }}
                </span>
              </div>
              <div v-if="activeTask && activeTask.status === 'failed'" class="task-error-inline">
                ⚠ {{ activeTask.error_message || '任务失败' }}
              </div>
              <el-button
                :icon="Download"
                :loading="activeTask?.kind === 'refresh'"
                size="small"
                @click="handleRefreshUser(false)"
              >仅抓取</el-button>
              <el-button
                :icon="MagicStick"
                :loading="activeTask?.kind === 'refresh'"
                size="small"
                type="primary"
                @click="handleRefreshUser(true)"
              >抓取并分析</el-button>
              <el-button
                :icon="Refresh"
                :loading="activeTask?.kind === 'analyze'"
                size="small"
                @click="handleAnalyzeRecent"
              >重新分析</el-button>
            </template>
            <div v-if="selectedUser.headline" class="user-headline">{{ selectedUser.headline }}</div>
          </ModernCard>

          <div v-loading="postsLoading" class="posts-area">
            <EmptyHint
              v-if="!posts.length && !postsLoading"
              icon="∅"
              title="暂无动态"
              description="点击「抓取最新」获取"
            />
            <div v-for="p in posts" :key="p.id" class="post-card">
              <div class="post-meta">
                <span
                  class="type-pill"
                  :class="typePillClass(p.post_type)"
                >{{ typePillLabel(p.post_type) }}</span>
                <span class="post-time">{{ formatTime(p.created_at_original) }}</span>
                <span class="post-stats">
                  <el-icon><CaretTop /></el-icon>
                  <span class="num">{{ p.voteup_count || 0 }}</span>
                  <el-icon class="ml"><ChatDotRound /></el-icon>
                  <span class="num">{{ p.comment_count || 0 }}</span>
                </span>
              </div>
              <a :href="p.url" target="_blank" class="post-title">{{ p.title }}</a>
              <div v-if="p.excerpt" class="post-excerpt">{{ truncate(p.excerpt, 200) }}</div>

              <div v-if="p.stance" class="analysis-card">
                <div class="analysis-header">
                  <span class="stance-badge" :style="{ background: stanceColor(p.stance) }">
                    {{ stanceLabel(p.stance) }} · 置信度 {{ p.confidence || 0 }}
                  </span>
                  <el-button
                    text
                    size="small"
                    :loading="reanalyzing === p.post_id"
                    @click="handleReanalyze(p)"
                  >重新分析</el-button>
                </div>
                <div v-if="p.stance_assets && p.stance_assets.length" class="assets-row">
                  <span
                    v-for="(a, i) in p.stance_assets"
                    :key="i"
                    class="asset-chip"
                    :style="{ background: stanceColor(a.stance) }"
                    :title="a.reason"
                  >
                    <span v-if="a.code" class="asset-chip__code">{{ a.code }}</span>
                    <span class="asset-chip__name">{{ a.asset }}</span>
                    <span class="asset-chip__stance">{{ stanceLabel(a.stance) }}</span>
                  </span>
                </div>
                <div v-if="p.summary" class="analysis-summary">{{ p.summary }}</div>
                <div v-if="p.action_suggestion" class="analysis-action">
                  <b>建议：</b>{{ p.action_suggestion }}
                </div>
                <ul v-if="p.key_points && p.key_points.length" class="key-points">
                  <li v-for="(kp, i) in p.key_points" :key="i">{{ kp }}</li>
                </ul>
                <a :href="p.url" target="_blank" class="post-link">打开知乎原文 →</a>
              </div>
              <div v-else class="no-analysis">
                <span>尚未分析</span>
                <el-button
                  text
                  size="small"
                  type="primary"
                  :loading="reanalyzing === p.post_id"
                  @click="handleReanalyze(p)"
                >立即分析</el-button>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <el-dialog v-model="showSettings" title="邮箱设置（SMTP）" width="520px">
      <el-form :model="settingsForm" label-position="top">
        <el-form-item label="SMTP 服务器">
          <el-input v-model="settingsForm.host" placeholder="如 smtp.qq.com / smtp.gmail.com" />
        </el-form-item>
        <el-form-item label="端口">
          <div class="form-row">
            <el-input-number v-model="settingsForm.port" :min="1" :max="65535" />
            <span class="form-hint">SSL 通常用 465，STARTTLS 用 587</span>
          </div>
        </el-form-item>
        <el-form-item label="账号">
          <el-input v-model="settingsForm.user" placeholder="登录用户名（通常为邮箱）" />
        </el-form-item>
        <el-form-item label="密码 / 授权码">
          <el-input v-model="settingsForm.password" type="password" placeholder="留空表示不修改" show-password />
          <div v-if="settingsForm.password && settingsForm.password.includes('*')" class="form-hint">
            当前密码：{{ settingsForm.password }}（如需修改请直接覆盖）
          </div>
        </el-form-item>
        <el-form-item label="发件人">
          <el-input v-model="settingsForm.from_addr" placeholder="留空则使用账号" />
        </el-form-item>
        <el-form-item label="SSL">
          <el-switch v-model="settingsForm.use_ssl" />
        </el-form-item>
      </el-form>
      <div class="dialog-tip">
        <el-icon><InfoFilled /></el-icon>
        <span>
          配置来源：<b>{{ settingsForm.source || 'env' }}</b>。
          QQ 邮箱授权码在「设置 → 账户 → POP3/IMAP」生成；Gmail 需「应用专用密码」。
        </span>
      </div>
      <template #footer>
        <el-button @click="showSettings = false">取消</el-button>
        <el-button type="primary" :loading="savingSettings" @click="handleSaveSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Refresh, Setting, MoreFilled, InfoFilled, CaretTop, ChatDotRound, Warning, MagicStick, Download,
} from '@element-plus/icons-vue'
import {
  getZhihuUsers, addZhihuUser, deleteZhihuUser, patchZhihuUser, refreshZhihuUser,
  analyzeRecentZhihuUser,
  getZhihuUserPosts, reanalyzeZhihuPost,
  getZhihuSubscriptions, addZhihuSubscription, deleteZhihuSubscription, patchZhihuSubscription,
  getZhihuEmailSettings, saveZhihuEmailSettings, testZhihuEmail,
  getZhihuEmailLogs, getTask,
} from '../api'
import PageHeader from '../components/ui/PageHeader.vue'
import ModernCard from '../components/ui/ModernCard.vue'
import EmptyHint from '../components/ui/EmptyHint.vue'

const users = ref([])
const usersLoading = ref(false)
const selectedUserId = ref(null)
const selectedUser = ref({})
const posts = ref([])
const postsLoading = ref(false)
const newUrl = ref('')
const adding = ref(false)
const refreshing = ref(false)
const refreshingAll = ref(false)
// 统一任务状态：{ task_id, kind:'refresh'|'analyze', status, progress_pct, current_step, error_message }
const activeTask = ref(null)
let pollTimer = null
let taskPollTimer = null

const subs = ref([])
const newSubEmail = ref('')
const addingSub = ref(false)
const emailLogs = ref([])

const reanalyzing = ref('')

const showSettings = ref(false)
const savingSettings = ref(false)
const settingsForm = reactive({
  host: '', port: 465, user: '', password: '',
  from_addr: '', use_ssl: true, source: 'env',
})

const stanceLabel = (s) => ({
  bullish: '看多', bearish: '看空', neutral: '中性', mixed: '混合',
}[s] || '中性')

const stanceColor = (s) => ({
  bullish: '#34c759', bearish: '#ff3b30', neutral: '#aeaeb2', mixed: '#ff9f0a',
}[s] || '#aeaeb2')

const typePillLabel = (t) => ({
  article: '文章', answer: '回答', pin: '想法',
}[t] || t || '其他')

const typePillClass = (t) => ({
  article: 'type-pill--article',
  answer: 'type-pill--answer',
  pin: 'type-pill--pin',
}[t] || 'type-pill--answer')

const formatTime = (t) => {
  if (!t) return '--'
  try {
    const d = new Date(t)
    if (isNaN(d.getTime())) return t
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch { return t }
}

const formatFollower = (n) => {
  n = n || 0
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

const truncate = (s, n) => (s && s.length > n ? s.slice(0, n) + '…' : s || '')

const countTokens = (j) => {
  try { return JSON.parse(j).length } catch { return 0 }
}

const statusKindLabel = (u) => ({
  never_scanned: '未抓取',
  error: '抓取失败',
  no_posts: '无动态',
  ok: '正常',
}[u.status_kind] || '未知')

const statusKindClass = (u) => ({
  never_scanned: 'status-pill--pending',
  error: 'status-pill--danger',
  no_posts: 'status-pill--pending',
  ok: 'status-pill--ok',
}[u.status_kind] || 'status-pill--pending')

async function fetchUsers() {
  usersLoading.value = true
  try {
    const { data } = await getZhihuUsers()
    users.value = data || []
  } catch (e) { console.error(e) }
  finally { usersLoading.value = false }
}

async function fetchSubs() {
  try { const { data } = await getZhihuSubscriptions(); subs.value = data || [] }
  catch (e) { /* noop */ }
}

async function fetchLogs() {
  try { const { data } = await getZhihuEmailLogs(20); emailLogs.value = data || [] }
  catch (e) { /* noop */ }
}

async function handleAddUser() {
  const v = newUrl.value.trim()
  if (!v) { ElMessage.warning('请输入知乎 URL 或 url_token'); return }
  adding.value = true
  try {
    const { data } = await addZhihuUser(v)
    ElMessage.success(`已添加 ${data.display_name || data.url_token}`)
    newUrl.value = ''
    fetchUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '添加失败')
  } finally { adding.value = false }
}

async function selectUser(u) {
  selectedUserId.value = u.id
  selectedUser.value = u
  await fetchPosts()
}

async function fetchPosts() {
  if (!selectedUserId.value) return
  postsLoading.value = true
  try {
    const { data } = await getZhihuUserPosts(selectedUserId.value, 30)
    posts.value = data || []
  } catch (e) { console.error(e) }
  finally { postsLoading.value = false }
}

async function pollTask(taskId, onDone) {
  // 使用统一任务 API 轮询进度（含 done/total/current_step/error_message）
  stopTaskPolling()
  const maxAttempts = 240  // 最多等 120s
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 500))
    try {
      const { data } = await getTask(taskId)
      if (!data) continue
      activeTask.value = {
        task_id: taskId,
        kind: data.kind?.includes('analyze') ? 'analyze' : 'refresh',
        status: data.status,
        progress_pct: data.progress_pct || 0,
        current_step: data.current_step || data.latest_milestone || '',
        error_message: data.error_message || '',
        result: data.result_json ? (typeof data.result_json === 'string' ? JSON.parse(data.result_json) : data.result_json) : null,
      }
      if (data.status === 'success' || data.status === 'failed' || data.status === 'cancelled') {
        // 完成/失败后保持 3s 再清除
        const result = activeTask.value
        setTimeout(() => { activeTask.value = null }, 3000)
        if (onDone) onDone(result)
        return result
      }
    } catch (e) { /* 静默重试 */ }
  }
  // 超时
  activeTask.value = { task_id: taskId, kind: 'refresh', status: 'timeout', error_message: '任务超时（>120s），后台可能仍在运行' }
  setTimeout(() => { activeTask.value = null }, 5000)
  return null
}

function stopTaskPolling() {
  if (taskPollTimer) { clearInterval(taskPollTimer); taskPollTimer = null }
}

async function handleRefreshUser(analyze = true) {
  if (!selectedUserId.value) return
  activeTask.value = { kind: 'refresh', status: 'running', progress_pct: 0, current_step: '正在启动...' }
  try {
    const { data } = await refreshZhihuUser(selectedUserId.value, analyze ? {} : { analyze: '0' })
    // refreshZhihuUser 使用 query param ?analyze=0 跳过分析
    // 默认 analyze=true 时走标准 refresh（自动分析新帖）
    const result = await pollTask(data.task_id, async (final) => {
      await fetchUsers()
      if (selectedUserId.value) {
        const u = users.value.find(x => x.id === selectedUserId.value)
        if (u) selectedUser.value = u
        await fetchPosts()
      }
      const r = final?.result || {}
      if (final?.status === 'failed') {
        ElMessage.error(`抓取失败: ${final.error_message || '未知错误'}`)
      } else if (r.new_posts > 0) {
        ElMessage.success(`抓取到 ${r.new_posts} 条新动态${r.analyzed ? `，已分析 ${r.analyzed} 条` : ''}`)
      } else if (!r.errors?.length) {
        ElMessage.info(`无新动态（共扫描 ${r.fetched || 0} 条）`)
      }
    })
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '启动失败')
    activeTask.value = null
  }
}

async function handleAnalyzeRecent() {
  if (!selectedUserId.value) return
  activeTask.value = { kind: 'analyze', status: 'running', progress_pct: 0, current_step: '正在启动 LLM...' }
  try {
    const { data } = await analyzeRecentZhihuUser(selectedUserId.value, 10)
    const result = await pollTask(data.task_id, async (final) => {
      await fetchUsers()
      if (selectedUserId.value) {
        const u = users.value.find(x => x.id === selectedUserId.value)
        if (u) selectedUser.value = u
        await fetchPosts()
      }
      const r = final?.result || {}
      if (final?.status === 'failed') {
        ElMessage.error(`分析失败: ${final.error_message || '未知错误'}`)
      } else if (r.analyzed > 0) {
        ElMessage.success(`已分析 ${r.analyzed} 条${r.skipped ? `（${r.skipped} 条已有分析）` : ''}`)
      } else if (r.skipped > 0) {
        ElMessage.info('最近动态都已分析过')
      } else {
        ElMessage.warning('无可分析动态，请先抓取最新内容')
      }
    })
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '分析启动失败')
    activeTask.value = null
  }
}

async function handleRefreshAll() {
  refreshingAll.value = true
  let ok = 0, fail = 0
  try {
    const tasks = []
    for (const u of users.value) {
      if (!u.enabled) continue
      try {
        const { data } = await refreshZhihuUser(u.id)
        tasks.push({ id: u.id, token: u.url_token, taskId: data.task_id })
      } catch (e) { fail++ }
    }
    // 并发轮询所有任务
    const results = await Promise.all(
      tasks.map(t => pollTask(t.taskId).catch(() => null))
    )
    ok = results.filter(r => r?.status === 'success').length
    fail += results.filter(r => !r || r.status === 'failed').length
    await fetchUsers()
    if (selectedUserId.value) await fetchPosts()
    ElMessage.success(`刷新完成: 成功 ${ok}，失败 ${fail}`)
  } catch (e) {
    ElMessage.error('批量刷新异常')
  } finally {
    refreshingAll.value = false
    activeTask.value = null
  }
}

async function handleReanalyze(p) {
  reanalyzing.value = p.post_id
  try {
    await reanalyzeZhihuPost(p.post_id)
    ElMessage.success('重分析已启动')
    setTimeout(fetchPosts, 4000)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '失败')
  } finally { reanalyzing.value = '' }
}

async function onUserCommand(cmd, u) {
  if (cmd === 'refresh') {
    try {
      const { data } = await refreshZhihuUser(u.id)
      ElMessage.info(`已发起 @${u.url_token} 抓取…`)
      await pollTask(data.task_id)
      await fetchUsers()
      if (selectedUserId.value === u.id) await fetchPosts()
      ElMessage.success(`@${u.url_token} 刷新完成`)
    } catch (e) { ElMessage.error('刷新失败') }
  } else if (cmd === 'enable' || cmd === 'disable') {
    try {
      await patchZhihuUser(u.id, { enabled: cmd === 'enable' })
      ElMessage.success('已更新')
      fetchUsers()
    } catch (e) { ElMessage.error('失败') }
  } else if (cmd === 'mute' || cmd === 'unmute') {
    try {
      await patchZhihuUser(u.id, { email_notify: cmd === 'unmute' })
      ElMessage.success('已更新')
      fetchUsers()
    } catch (e) { ElMessage.error('失败') }
  } else if (cmd === 'delete') {
    try {
      await ElMessageBox.confirm(`确认删除 @${u.url_token}？关联动态也会保留。`, '确认', { type: 'warning' })
    } catch { return }
    try {
      await deleteZhihuUser(u.id)
      ElMessage.success('已删除')
      if (selectedUserId.value === u.id) {
        selectedUserId.value = null
        selectedUser.value = {}
        posts.value = []
      }
      fetchUsers()
    } catch (e) { ElMessage.error('失败') }
  }
}

async function handleAddSub() {
  const v = newSubEmail.value.trim()
  if (!v || !v.includes('@')) { ElMessage.warning('请输入合法邮箱'); return }
  addingSub.value = true
  try {
    await addZhihuSubscription({ email: v, url_tokens: [] })
    ElMessage.success('已添加订阅')
    newSubEmail.value = ''
    fetchSubs()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '失败')
  } finally { addingSub.value = false }
}

async function toggleSub(s) {
  try {
    await patchZhihuSubscription(s.id, { enabled: !s.enabled })
    fetchSubs()
  } catch { ElMessage.error('失败') }
}

async function deleteSub(s) {
  try { await ElMessageBox.confirm(`确认删除订阅 ${s.email}？`, '确认', { type: 'warning' }) }
  catch { return }
  try {
    await deleteZhihuSubscription(s.id)
    ElMessage.success('已删除')
    fetchSubs()
  } catch (e) { ElMessage.error('失败') }
}

async function handleTestEmail(email) {
  try {
    await testZhihuEmail(email)
    ElMessage.success('测试邮件已发送')
    setTimeout(fetchLogs, 1000)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '发送失败')
  }
}

async function openSettings() {
  try {
    const { data } = await getZhihuEmailSettings()
    Object.assign(settingsForm, {
      host: data.host || '',
      port: data.port || 465,
      user: data.user || '',
      password: data.password || '',
      from_addr: data.from_addr || '',
      use_ssl: data.use_ssl !== false,
      source: data.source || 'env',
    })
  } catch (e) { /* noop */ }
  showSettings.value = true
}

async function handleSaveSettings() {
  savingSettings.value = true
  try {
    await saveZhihuEmailSettings({
      host: settingsForm.host, port: settingsForm.port,
      user: settingsForm.user, password: settingsForm.password,
      from_addr: settingsForm.from_addr, use_ssl: settingsForm.use_ssl,
    })
    ElMessage.success('已保存')
    showSettings.value = false
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '保存失败')
  } finally { savingSettings.value = false }
}

onMounted(() => {
  fetchUsers()
  fetchSubs()
  fetchLogs()
  pollTimer = setInterval(fetchLogs, 30000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  stopTaskPolling()
  activeTask.value = null
})
</script>

<style scoped>
.zhihu-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.content-grid {
  display: grid;
  grid-template-columns: 400px 1fr;
  gap: var(--space-4);
  align-items: start;
}
.left-panel,
.right-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.add-form {
  display: flex;
  gap: var(--space-2);
}
.add-hint {
  margin-top: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.add-hint code {
  background: var(--color-bg-muted);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 11px;
}

/* ── 用户列表 ── */
.user-list {
  display: flex;
  flex-direction: column;
}
.user-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease);
}
.user-row:hover {
  background: var(--color-bg-subtle);
}
.user-row--active {
  background: var(--color-accent-soft);
  border-color: rgba(37, 99, 235, 0.2);
}
.avatar {
  flex-shrink: 0;
}
.user-info {
  flex: 1;
  min-width: 0;
}
.user-name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: var(--weight-semibold);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}
.user-name__text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 160px;
}
.user-meta {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.url-token {
  font-family: var(--font-mono);
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}
.user-status {
  margin-top: var(--space-2);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.user-error {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: var(--space-1);
  padding: 4px 8px;
  background: var(--color-danger-soft);
  color: var(--color-danger);
  border-radius: var(--radius-sm);
  font-size: 11px;
  line-height: 1.4;
  word-break: break-all;
}
.user-foot {
  margin-top: 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--color-text-tertiary);
}
.post-count {
  font-variant-numeric: tabular-nums;
}
.last-check {
  font-size: 11px;
  color: var(--color-text-tertiary);
}

/* ── 状态小标签 ── */
.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 11px;
  font-weight: var(--weight-medium);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}
.status-pill--on {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.status-pill--off {
  background: var(--color-bg-muted);
  color: var(--color-text-tertiary);
}
.status-pill--ok {
  background: var(--color-accent-soft);
  color: var(--color-accent-text);
}
.status-pill--pending {
  background: var(--color-bg-muted);
  color: var(--color-text-tertiary);
}
.status-pill--mail {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}
.status-pill--danger {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

/* ── 订阅 ── */
.sub-add-row {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.sub-list {
  display: flex;
  flex-direction: column;
}
.sub-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-divider);
}
.sub-row:last-child { border-bottom: none; }
.sub-info { flex: 1; min-width: 0; }
.sub-email {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  font-weight: var(--weight-medium);
}
.sub-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 4px;
  font-size: 11px;
  color: var(--color-text-tertiary);
}
.sub-scope { color: var(--color-text-tertiary); }
.sub-actions {
  display: flex;
  gap: 0;
  flex-shrink: 0;
}

/* ── 日志 ── */
.log-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.log-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-divider);
  font-size: var(--text-xs);
  flex-wrap: wrap;
}
.log-row:last-child { border-bottom: none; }
.log-email {
  font-family: var(--font-mono);
  color: var(--color-text-primary);
}
.log-subject {
  color: var(--color-text-secondary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.log-time {
  color: var(--color-text-tertiary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

/* ── 统一任务进度指示器 ── */
.task-progress-inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  margin-right: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-accent-text);
  background: var(--color-accent-soft);
  border-radius: var(--radius-full);
  white-space: nowrap;
  border: 1px solid rgba(37, 99, 235, 0.15);
}
.task-progress-inline__spinner {
  width: 10px;
  height: 10px;
  border: 2px solid var(--color-accent-text);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.task-progress-inline__label {
  font-weight: var(--weight-medium);
}
.task-progress-inline__pct {
  font-weight: var(--weight-bold);
  font-variant-numeric: tabular-nums;
}
.task-progress-inline__step {
  color: var(--color-text-tertiary);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-error-inline {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  margin-right: var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--color-danger, #ef4444);
  background: var(--color-danger-soft, rgba(239,68,68,0.1));
  border-radius: var(--radius-full);
  border: 1px solid rgba(239, 68, 68, 0.2);
  white-space: nowrap;
  cursor: help;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.detail-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.detail-title__name {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
}
.detail-title__meta {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  margin-top: 2px;
}
.user-headline {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

/* ── 动态卡片 ── */
.posts-area {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.post-card {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-5);
  transition: all var(--duration-fast) var(--ease);
}
.post-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-sm);
}
.post-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-2);
}
.post-time { color: var(--color-text-tertiary); }
.post-stats {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-tertiary);
  font-size: var(--text-xs);
}
.post-stats .ml { margin-left: 8px; }
.post-stats .num { font-variant-numeric: tabular-nums; }

.type-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: var(--weight-medium);
}
.type-pill--article {
  background: var(--color-accent-soft);
  color: var(--color-accent-text);
}
.type-pill--answer {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.type-pill--pin {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.post-title {
  display: block;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  text-decoration: none;
  margin-bottom: var(--space-2);
  line-height: var(--leading-normal);
  letter-spacing: -0.01em;
  transition: color var(--duration-fast) var(--ease);
}
.post-title:hover { color: var(--color-accent); }
.post-excerpt {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-3);
}

/* ── 分析卡片 ── */
.analysis-card {
  background: var(--color-bg-subtle);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin-top: var(--space-2);
}
.analysis-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}
.stance-badge {
  display: inline-block;
  padding: 3px 12px;
  border-radius: var(--radius-full);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
}
.assets-row {
  margin: var(--space-2) 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}
.asset-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  color: #fff;
  line-height: 1.5;
  font-size: 11px;
  cursor: help;
}

.asset-chip__code {
  font-weight: 600;
  letter-spacing: 0.02em;
  font-variant-numeric: tabular-nums;
  padding-right: 4px;
  border-right: 1px solid rgba(255, 255, 255, 0.35);
}

.asset-chip__name {
  opacity: 0.95;
}

.asset-chip__stance {
  opacity: 0.75;
  font-size: 10px;
  padding-left: 4px;
  border-left: 1px solid rgba(255, 255, 255, 0.35);
}
.analysis-summary {
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  margin: var(--space-2) 0;
  line-height: var(--leading-relaxed);
}
.analysis-action {
  font-size: var(--text-sm);
  color: var(--color-up);
  background: var(--color-up-soft);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  margin: var(--space-2) 0;
  line-height: var(--leading-relaxed);
}
.analysis-action b { font-weight: var(--weight-semibold); }
.key-points {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin: var(--space-2) 0 var(--space-2) var(--space-4);
  line-height: var(--leading-relaxed);
}
.key-points li { margin: 2px 0; }
.post-link {
  font-size: var(--text-xs);
  color: var(--color-accent);
  text-decoration: none;
  display: inline-block;
  margin-top: var(--space-1);
}
.post-link:hover { text-decoration: underline; }

.no-analysis {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

/* ── SMTP 设置弹窗 ── */
.form-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}
.form-hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.dialog-tip {
  background: var(--color-accent-soft);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-accent-text);
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-3);
  line-height: var(--leading-relaxed);
}
</style>
