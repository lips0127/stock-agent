<template>
  <div class="app-layout">
    <header class="app-header">
      <div class="header-left">
        <h1 class="logo" @click="$router.push('/dashboard')">A股股息监测</h1>
        <el-menu
          mode="horizontal"
          :default-active="activeMenu"
          :ellipsis="false"
          router
          class="header-nav"
          background-color="transparent"
          text-color="rgba(255,255,255,0.7)"
          active-text-color="#fff"
        >
          <el-menu-item index="/dashboard">仪表盘</el-menu-item>
          <el-menu-item index="/stocks">全量扫描</el-menu-item>
          <el-menu-item index="/sentiment">舆情监控</el-menu-item>
        </el-menu>
      </div>
      <div class="header-right">
        <el-button
          type="primary"
          plain
          size="small"
          :icon="Refresh"
          :loading="refreshing"
          @click="handleRefresh"
        >
          刷新红利指数
        </el-button>
        <el-button
          type="warning"
          plain
          size="small"
          :icon="Search"
          :loading="fullRefreshing"
          @click="handleFullRefresh"
        >
          全市场扫描
        </el-button>
        <el-dropdown @command="handleCommand">
          <span class="user-dropdown">
            <el-icon><User /></el-icon>
            {{ auth.username }}
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

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
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useTaskStore } from '../stores/task'
import { indexScan, fullRefreshData } from '../api'
import { ElMessage } from 'element-plus'
import { Refresh, Search, User, ArrowDown } from '@element-plus/icons-vue'
import ScanProgressBar from '../components/ScanProgressBar.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const taskStore = useTaskStore()

const refreshing = ref(false)
const fullRefreshing = ref(false)

const activeMenu = computed(() => route.path)

async function handleRefresh() {
  if (taskStore.currentTask?.status === 'running') {
    ElMessage.warning('已有扫描任务在运行')
    return
  }
  refreshing.value = true
  try {
    const { data } = await indexScan()
    ElMessage.success('红利指数扫描已提交')
    taskStore.startPolling(data.task_id)
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.error || '已有扫描任务在运行')
    } else {
      ElMessage.error('刷新失败: ' + (e.response?.data?.error || e.message))
    }
  } finally {
    refreshing.value = false
  }
}

async function handleFullRefresh() {
  if (taskStore.currentTask?.status === 'running') {
    ElMessage.warning('已有扫描任务在运行')
    return
  }
  fullRefreshing.value = true
  try {
    const { data } = await fullRefreshData()
    ElMessage.success(data.message || '全市场扫描已启动')
    taskStore.startPolling(data.task_id)
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.error || '已有扫描任务在运行')
    } else {
      ElMessage.error('全市场扫描启动失败: ' + (e.response?.data?.error || e.message))
    }
  } finally {
    fullRefreshing.value = false
  }
}

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
  flex-direction: column;
}
.app-header {
  background: var(--color-header-bg);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 24px;
}
.logo {
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  cursor: pointer;
  white-space: nowrap;
  letter-spacing: 0.5px;
}
.header-nav {
  border-bottom: none !important;
}
.header-nav :deep(.el-menu-item) {
  height: 56px;
  line-height: 56px;
  border-bottom: 2px solid transparent !important;
  font-size: 14px;
}
.header-nav :deep(.el-menu-item.is-active) {
  border-bottom-color: var(--color-primary) !important;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.user-dropdown {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.8);
  font-size: 14px;
}
.app-main {
  flex: 1;
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}
</style>
