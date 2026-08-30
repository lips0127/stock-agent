<template>
  <div class="app-layout">
    <!-- 移动端顶栏：仅窄屏显示 -->
    <header class="mobile-topbar">
      <button class="mobile-topbar__menu" aria-label="打开导航" @click="sidebarOpen = true">
        <el-icon :size="20"><Menu /></el-icon>
      </button>
      <div class="mobile-topbar__logo" @click="$router.push('/dashboard')">
        <span class="logo__mark">Q</span>
        <span class="logo__text">QuantLab</span>
      </div>
    </header>

    <!-- 遮罩：窄屏侧栏打开时显示 -->
    <transition name="fade">
      <div v-if="sidebarOpen" class="app-backdrop" @click="sidebarOpen = false" />
    </transition>

    <aside class="app-sidebar" :class="{ 'app-sidebar--open': sidebarOpen }">
      <div class="sidebar-header">
        <div class="logo" @click="$router.push('/dashboard')">
          <span class="logo__mark">Q</span>
          <span class="logo__text">QuantLab</span>
        </div>
      </div>

      <nav class="sidebar-nav">
        <div v-for="group in navGroups" :key="group.label" class="nav-group">
          <div class="nav-group__label">{{ group.label }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ 'is-active': isActive(item) }"
            @click="sidebarOpen = false"
          >
            <el-icon class="nav-item__icon" :size="16"><component :is="item.icon" /></el-icon>
            <span class="nav-item__label">{{ item.label }}</span>
          </router-link>
        </div>
      </nav>

      <div class="sidebar-footer">
        <el-dropdown trigger="click" @command="handleCommand" placement="right-end">
          <div class="user-chip">
            <span class="user-chip__avatar">{{ avatarChar }}</span>
            <span class="user-chip__name">{{ auth.username }}</span>
            <el-icon class="user-chip__caret"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">
                <el-icon><SwitchButton /></el-icon>
                退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>

    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

    <ScanProgressBar />
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useTaskStore } from '../stores/task'
import {
  ArrowDown,
  SwitchButton,
  Menu,
  DataBoard,
  Search,
  Star,
  ChatDotRound,
  TrendCharts,
  Timer,
  Document,
  Coin,
} from '@element-plus/icons-vue'
import ScanProgressBar from '../components/ScanProgressBar.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const taskStore = useTaskStore()

const sidebarOpen = ref(false)
// 路由变化时收起移动端抽屉
watch(() => route.path, () => { sidebarOpen.value = false })

const navGroups = [
  {
    label: '市场研究',
    items: [
      { path: '/dashboard', label: '仪表盘', icon: DataBoard },
      { path: '/watchlist', label: '自选股', icon: Star },
      { path: '/stocks', label: '全量扫描', icon: Search },
      { path: '/dividend-index', label: '红利指数', icon: Coin },
    ],
  },
  {
    label: '辅助功能',
    items: [
      { path: '/sentiment', label: '舆情监控', icon: ChatDotRound },
      { path: '/vix', label: '恐慌贪婪指数', icon: TrendCharts },
      { path: '/financial-report', label: '财报解析', icon: Document },
    ],
  },
  {
    label: '系统',
    items: [
      { path: '/tasks', label: '任务调度', icon: Timer },
    ],
  },
]

const isActive = (item) => {
  if (item.path === '/dashboard') return route.path === '/dashboard'
  return route.path.startsWith(item.path)
}

const avatarChar = computed(() => {
  const u = (auth.username || 'U').trim()
  return u.charAt(0).toUpperCase()
})

function handleCommand(cmd) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}

onMounted(() => {
  taskStore.init()
})
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
  display: flex;
  background: var(--color-bg-page);
}

/* ── 侧边栏：实色面板 + 右沿 1px 分层（数据工具不用玻璃拟态） ── */
.app-sidebar {
  width: var(--layout-sidebar-width);
  height: 100vh;
  position: fixed;
  top: 0;
  left: 0;
  z-index: var(--z-sticky);
  display: flex;
  flex-direction: column;
  background: var(--color-bg-elevated);
  border-right: 1px solid var(--color-border);
  box-shadow: var(--shadow-sidebar);
  user-select: none;
}

.sidebar-header {
  padding: var(--space-5) var(--space-5) var(--space-4);
  border-bottom: 1px solid var(--color-divider);
}

/* ── Logo：实色主色方块，无渐变无光晕 ── */
.logo {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity var(--duration-base) var(--ease);
}
.logo:hover { opacity: 0.85; }
.logo__mark {
  width: 30px;
  height: 30px;
  border-radius: var(--radius-md);
  background: var(--color-accent);
  color: var(--color-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: var(--weight-bold);
  letter-spacing: -0.02em;
}
.logo__text {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: -0.015em;
}

/* ── 导航分组 ── */
.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4) var(--space-3);
}

.nav-group {
  margin-bottom: var(--space-5);
}
.nav-group__label {
  padding: var(--space-1) var(--space-3) var(--space-2);
  font-size: 11px;
  font-weight: var(--weight-semibold);
  color: var(--color-text-tertiary);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

/* ── 导航项：左侧 2px 激活条 ── */
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  text-decoration: none;
  transition: all var(--duration-page) var(--ease);
  margin-bottom: 2px;
}
.nav-item::before {
  content: '';
  position: absolute;
  left: -3px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: 0 2px 2px 0;
  background: transparent;
  transition: background var(--duration-page) var(--ease);
}
.nav-item:hover {
  color: var(--color-text-primary);
  background: var(--color-bg-muted);
}
.nav-item.is-active {
  color: var(--color-accent-deep);
  background: var(--color-accent-soft);
  font-weight: var(--weight-semibold);
}
.nav-item.is-active::before {
  background: var(--color-accent);
}
.nav-item__icon {
  flex-shrink: 0;
  opacity: 0.85;
  transition: opacity var(--duration-base) var(--ease);
}
.nav-item:hover .nav-item__icon,
.nav-item.is-active .nav-item__icon {
  opacity: 1;
}
.nav-item__label {
  white-space: nowrap;
  letter-spacing: -0.005em;
}

/* ── 底栏 ── */
.sidebar-footer {
  padding: var(--space-3) var(--space-4) var(--space-4);
  border-top: 1px solid var(--color-divider);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-2);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-page) var(--ease);
}
.user-chip:hover {
  background: var(--color-bg-muted);
}
.user-chip__avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--color-text-primary);
  color: var(--color-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
  letter-spacing: -0.01em;
}
.user-chip__name {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-chip__caret {
  font-size: 12px;
  color: var(--color-text-tertiary);
  flex-shrink: 0;
  margin-right: var(--space-1);
}

/* ── 主区 ── */
.app-main {
  flex: 1;
  margin-left: var(--layout-sidebar-width);
  min-height: 100vh;
  min-width: 0;   /* flex 子项默认 min-width:auto，宽表格会把整页撑出横向滚动 */
  padding: var(--space-6) var(--space-8);
}

/* ── 移动端：≤1024px 侧栏收进抽屉 ── */
.mobile-topbar {
  display: none;
}
.app-backdrop {
  display: none;
}

@media (max-width: 1024px) {
  .app-main {
    margin-left: 0;
    padding: 68px var(--space-4) var(--space-8); /* 顶部让位给固定顶栏 */
  }

  .mobile-topbar {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 52px;
    padding: 0 var(--space-4);
    z-index: calc(var(--z-sticky) + 2);
    background: var(--color-bg-elevated);
    border-bottom: 1px solid var(--color-divider);
  }
  .mobile-topbar__menu {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--color-text-primary);
    cursor: pointer;
  }
  .mobile-topbar__menu:hover { background: var(--color-bg-muted); }
  .mobile-topbar__logo {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    cursor: pointer;
  }

  .app-sidebar {
    transform: translateX(-100%);
    transition: transform var(--duration-slow) var(--ease);
    z-index: calc(var(--z-modal) - 1);
  }
  .app-sidebar--open {
    transform: translateX(0);
  }

  .app-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: calc(var(--z-modal) - 2);
    background: rgba(15, 15, 15, 0.32);
  }
}
</style>
