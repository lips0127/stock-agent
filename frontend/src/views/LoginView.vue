<template>
  <div class="login-page">
    <div class="login-bg" aria-hidden="true">
      <div class="login-bg__orb login-bg__orb--1" />
      <div class="login-bg__orb login-bg__orb--2" />
      <div class="login-bg__grid" />
    </div>

    <div class="login-shell">
      <div class="login-card">
        <div class="login-card__head">
          <div class="login-card__mark">Q</div>
          <h1 class="login-card__title">QuantLab</h1>
          <p class="login-card__subtitle">A股量化监控工作台</p>
        </div>

        <el-form :model="form" @submit.prevent="handleLogin" class="login-form">
          <el-form-item>
            <el-input
              v-model="form.username"
              placeholder="用户名"
              size="large"
              autocomplete="username"
            >
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              size="large"
              show-password
              autocomplete="current-password"
              @keyup.enter="handleLogin"
            >
              <template #prefix>
                <el-icon><Lock /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          >
            登 录
          </el-button>
        </el-form>

        <p class="login-foot">提示：默认账号 <code>admin</code> / <code>admin123</code></p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { login } from '../api'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuthStore()

const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function handleLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const { data } = await login(form.username, form.password)
    if (data.success) {
      auth.setToken(data.token, form.username)
      ElMessage.success('登录成功')
      router.push('/dashboard')
    } else {
      ElMessage.error(data.message || '登录失败')
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '登录失败，请检查网络')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-page);
  overflow: hidden;
}

/* ── 背景：柔光球 + 极淡网格 ── */
.login-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}
.login-bg__orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.4;
}
.login-bg__orb--1 {
  width: 480px;
  height: 480px;
  top: -120px;
  left: -120px;
  background: radial-gradient(circle, #93c5fd 0%, transparent 70%);
}
.login-bg__orb--2 {
  width: 380px;
  height: 380px;
  bottom: -100px;
  right: -100px;
  background: radial-gradient(circle, #c4b5fd 0%, transparent 70%);
}
.login-bg__grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0, 0, 0, 0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 0, 0, 0.025) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: radial-gradient(ellipse at center, #000 30%, transparent 80%);
}

.login-shell {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 420px;
  padding: 0 var(--space-4);
}

.login-card {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-2xl);
  padding: var(--space-10) var(--space-8);
  box-shadow: var(--shadow-lg);
  text-align: center;
}
.login-card__head {
  margin-bottom: var(--space-8);
}
.login-card__mark {
  width: 48px;
  height: 48px;
  margin: 0 auto var(--space-4);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.02em;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}
.login-card__title {
  font-size: var(--text-3xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
  letter-spacing: -0.02em;
}
.login-card__subtitle {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.login-form { text-align: left; }
.login-btn {
  width: 100%;
  height: 44px;
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  margin-top: var(--space-2);
}

.login-foot {
  margin-top: var(--space-6);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.login-foot code {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 1px 6px;
  background: var(--color-bg-muted);
  border-radius: 4px;
  color: var(--color-text-secondary);
}
</style>
