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
        path: 'dividend-index',
        name: 'DividendIndex',
        component: () => import('../views/DividendIndexView.vue'),
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
      {
        path: 'vix',
        name: 'Vix',
        component: () => import('../views/VixView.vue'),
      },
      // 量化交易
      {
        path: 'strategies',
        name: 'Strategies',
        component: () => import('../views/StrategiesView.vue'),
      },
      {
        path: 'backtest',
        name: 'Backtest',
        component: () => import('../views/BacktestView.vue'),
      },
      {
        path: 'portfolio',
        name: 'Portfolio',
        component: () => import('../views/PortfolioView.vue'),
      },
      // 净值管理
      {
        path: 'nav',
        name: 'NAVManage',
        component: () => import('../views/NAVManageView.vue'),
      },
      {
        path: 'nav/transfers',
        name: 'TransferRecords',
        component: () => import('../views/TransferRecordView.vue'),
      },
      {
        path: 'nav/positions',
        name: 'PositionSnapshot',
        component: () => import('../views/PositionSnapshotView.vue'),
      },
      // 知乎大V监控
      {
        path: 'zhihu',
        name: 'ZhihuMonitor',
        component: () => import('../views/ZhihuMonitorView.vue'),
      },
      {
        path: 'zhihu/timeline',
        name: 'ZhihuTimeline',
        component: () => import('../views/ZhihuTimelineView.vue'),
      },
      // 系统
      {
        path: 'tasks',
        name: 'Tasks',
        component: () => import('../views/TaskSchedulerView.vue'),
      },
      // 财报解析
      {
        path: 'financial-report',
        name: 'FinancialReport',
        component: () => import('../views/FinancialReportView.vue'),
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
