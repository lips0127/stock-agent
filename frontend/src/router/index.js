import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { guest: true },
  },
  {
    path: '/',
    component: () => import('../views/LayoutView.vue'),
    meta: { auth: true },
    children: [
      {
        path: '',
        redirect: '/dashboard',
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('../views/DashboardView.vue'),
      },
      {
        path: 'stocks',
        name: 'Stocks',
        component: () => import('../views/StocksView.vue'),
      },
      {
        path: 'scan/:taskId',
        name: 'ScanProgress',
        component: () => import('../views/ScanProgressView.vue'),
      },
      {
        path: 'sentiment',
        name: 'Sentiment',
        component: () => import('../views/SentimentView.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.auth && !auth.isLoggedIn) return { name: 'Login' }
  if (to.meta.guest && auth.isLoggedIn) return { name: 'Dashboard' }
})

export default router
