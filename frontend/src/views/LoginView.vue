<template>
  <div class="login-page">
    <!-- 品牌面板：满贴左缘，纯排版叙事，不虚构数据 -->
    <div class="login-brand">
      <div class="login-brand__logo">
        <span class="login-brand__mark">Q</span>
        <span class="login-brand__name">QuantLab</span>
      </div>

      <div class="login-brand__body">
        <h1 class="login-brand__title">数据证据、风险状态与研究候选池，集中在一块看板。</h1>
        <p class="login-brand__desc">来源、时点与覆盖可见；失败和降级不会被伪装成正常数据。</p>
      </div>

      <p class="login-brand__foot">个人研究看板，数据仅供参考，不构成投资建议。</p>
    </div>

    <!-- 表单面板：固定阅读宽度 -->
    <div class="login-panel">
      <div class="login-panel__inner">
        <div class="login-panel__head">
          <h2 class="login-panel__title">登录</h2>
          <p class="login-panel__sub">个人 A 股研究与风险辅助看板</p>
        </div>

        <el-form :model="form" @submit.prevent="handleLogin" class="login-form">
          <div class="login-field">
            <label class="login-field__label" for="login-username">用户名</label>
            <el-input
              id="login-username"
              v-model="form.username"
              placeholder="输入用户名"
              size="large"
              autocomplete="username"
            >
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </div>

          <div class="login-field">
            <label class="login-field__label" for="login-password">密码</label>
            <el-input
              id="login-password"
              v-model="form.password"
              type="password"
              placeholder="输入密码"
              size="large"
              show-password
              autocomplete="current-password"
              @keyup.enter="handleLogin"
            >
              <template #prefix>
                <el-icon><Lock /></el-icon>
              </template>
            </el-input>
          </div>

          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          >
            登录
          </el-button>
        </el-form>

        <p class="login-foot">仅限本人使用。数据来自外部公开源，可能延迟或缺失。</p>
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
/* 满幅分屏：品牌面板贴左缘弹性拉伸，表单面板固定阅读宽度 */
.login-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1fr minmax(400px, 520px);
  background: var(--color-bg-page);
}

/* ── 品牌面板：墨色（zinc-900，非纯黑），纯排版 ── */
.login-brand {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--space-10);
  padding: var(--space-10) min(var(--space-16), 8vw);
  background: #18181b;
  color: #fafafa;
}
.login-brand__logo {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.login-brand__mark {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--color-accent);
  color: var(--color-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: var(--weight-bold);
}
.login-brand__name {
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  letter-spacing: -0.015em;
}
.login-brand__body {
  max-width: 44ch;
}
.login-brand__title {
  font-size: var(--text-3xl);
  font-weight: var(--weight-semibold);
  line-height: var(--leading-tight);
  letter-spacing: -0.02em;
  color: #fafafa;
}
.login-brand__desc {
  margin-top: var(--space-4);
  font-size: var(--text-md);
  line-height: var(--leading-relaxed);
  color: #a1a1aa;
}
.login-brand__foot {
  font-size: var(--text-xs);
  color: #71717a;
}

/* ── 表单面板 ── */
.login-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: var(--space-12) var(--space-10);
  background: var(--color-bg-elevated);
  border-left: 1px solid var(--color-border);
}
.login-panel__inner {
  width: 100%;
  max-width: 360px;
  margin: 0 auto;
}
.login-panel__head {
  margin-bottom: var(--space-8);
}
.login-panel__title {
  font-size: var(--text-2xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: -0.02em;
}
.login-panel__sub {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.login-form { display: flex; flex-direction: column; }
.login-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-5);
}
.login-field__label {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text-primary);
}
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

/* ── 窄屏：品牌面板退场，表单单列居中 ── */
@media (max-width: 880px) {
  .login-page {
    grid-template-columns: 1fr;
    align-content: center;
    padding: var(--space-6) var(--space-4);
  }
  .login-brand { display: none; }
  .login-panel {
    border-left: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-md);
    padding: var(--space-8) var(--space-6);
  }
}
</style>
