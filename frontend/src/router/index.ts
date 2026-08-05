import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { nextTick } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { ElMessage } from 'element-plus'
import NProgress from 'nprogress'
import 'nprogress/nprogress.css'

// 配置NProgress
NProgress.configure({
  showSpinner: false,
  minimum: 0.2,
  easing: 'ease',
  speed: 500
})

// 路由配置
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard'
  },
  // 已下线功能入口：兼容旧链接，统一跳转仪表板
  { path: '/learning/:pathMatch(.*)*', redirect: '/dashboard' },
  { path: '/learning', redirect: '/dashboard' },
  { path: '/analysis/history', redirect: '/dashboard' },
  { path: '/analysis/:pathMatch(.*)*', redirect: '/dashboard' },
  { path: '/analysis', redirect: '/dashboard' },
  { path: '/screening/:pathMatch(.*)*', redirect: '/dashboard' },
  { path: '/screening', redirect: '/dashboard' },
  { path: '/paper/:name.md', redirect: '/dashboard' },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '仪表板',
      icon: 'Dashboard',
      requiresAuth: true,
      transition: 'fade'
    },
    children: [
      {
        path: '',
        name: 'DashboardHome',
        component: () => import('@/views/Dashboard/index.vue'),
        meta: {
          title: '仪表板',
          requiresAuth: true
        }
      }
    ]
  },

  {
    path: '/leads',
    name: 'Leads',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: { title: '机会列表', requiresAuth: true, transition: 'slide-up' },
    children: [
      {
        path: '',
        name: 'LeadsHome',
        component: () => import('@/views/Leads/index.vue'),
        meta: { title: '机会列表', requiresAuth: true }
      }
    ]
  },
  {
    path: '/factors',
    name: 'Factors',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: { title: '多因子', requiresAuth: true, transition: 'slide-up' },
    children: [
      {
        path: '',
        name: 'FactorsHome',
        component: () => import('@/views/Factors/index.vue'),
        meta: { title: '多因子', requiresAuth: true }
      }
    ]
  },
  // 旧入口兼容
  { path: '/cb', redirect: '/multi-asset/cb' },
  { path: '/strategies', redirect: '/multi-asset/strategies' },
  { path: '/derivatives', redirect: '/multi-asset/cb' },
  { path: '/derivatives/cb', redirect: '/multi-asset/cb' },
  { path: '/derivatives/strategies', redirect: '/multi-asset/strategies' },
  {
    path: '/multi-asset',
    name: 'MultiAsset',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: { title: '多资产', requiresAuth: true, transition: 'slide-up' },
    redirect: '/multi-asset/cb',
    children: [
      {
        path: 'cb',
        name: 'MultiAssetCb',
        component: () => import('@/views/ConvertibleBonds/index.vue'),
        meta: { title: '可转债', requiresAuth: true, parent: '多资产' }
      },
      { path: 'strategies', redirect: '/multi-asset/dual_low' },
      {
        path: 'dual_low',
        name: 'MultiAssetDualLow',
        component: () => import('@/views/Strategies/index.vue'),
        meta: { title: '转债双低', requiresAuth: true, parent: '多资产', strategyId: 'dual_low' }
      },
      {
        path: 'etf_grid',
        name: 'MultiAssetEtfGrid',
        component: () => import('@/views/Strategies/index.vue'),
        meta: { title: 'ETF网格', requiresAuth: true, parent: '多资产', strategyId: 'etf_grid' }
      },
      {
        path: 'lof_arb',
        name: 'MultiAssetLofArb',
        component: () => import('@/views/Strategies/index.vue'),
        meta: { title: 'LOF套利', requiresAuth: true, parent: '多资产', strategyId: 'lof_arb' }
      },
      {
        path: 'bond_etf_arb',
        name: 'MultiAssetBondEtfArb',
        component: () => import('@/views/Strategies/index.vue'),
        meta: { title: '债券ETF折溢价', requiresAuth: true, parent: '多资产', strategyId: 'bond_etf_arb' }
      },
      {
        path: 'futures_basis',
        name: 'MultiAssetFuturesBasis',
        component: () => import('@/views/Strategies/index.vue'),
        meta: { title: '股指基差', requiresAuth: true, parent: '多资产', strategyId: 'futures_basis' }
      },
      {
        path: 'treasury_basis',
        name: 'MultiAssetTreasuryBasis',
        component: () => import('@/views/Strategies/index.vue'),
        meta: { title: '国债期货基差', requiresAuth: true, parent: '多资产', strategyId: 'treasury_basis' }
      },
      {
        path: 'covered_call',
        name: 'MultiAssetCoveredCall',
        component: () => import('@/views/Strategies/index.vue'),
        meta: { title: '高股息备兑', requiresAuth: true, parent: '多资产', strategyId: 'covered_call' }
      },
      {
        path: 'pairs',
        name: 'MultiAssetPairs',
        component: () => import('@/views/Strategies/index.vue'),
        meta: { title: '配对交易', requiresAuth: true, parent: '多资产', strategyId: 'pairs' }
      }
    ]
  },
  {
    path: '/investments',
    name: 'Investments',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: { title: '投资列表', requiresAuth: true, transition: 'slide-up' },
    children: [
      {
        path: '',
        name: 'InvestmentsHome',
        component: () => import('@/views/Investments/index.vue'),
        meta: { title: '投资列表', requiresAuth: true }
      }
    ]
  },

  {
    path: '/favorites',
    name: 'Favorites',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '我的自选股',
      icon: 'Star',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: '',
        name: 'FavoritesHome',
        component: () => import('@/views/Favorites/index.vue'),
        meta: {
          title: '我的自选股',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/stocks',
    name: 'Stocks',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '股票详情',
      icon: 'TrendCharts',
      requiresAuth: true,
      hideInMenu: true,
      transition: 'fade'
    },
    children: [
      {
        path: ':code',
        name: 'StockDetail',
        component: () => import('@/views/Stocks/Detail.vue'),
        meta: {
          title: '股票详情',
          requiresAuth: true,
          hideInMenu: true,
          transition: 'fade'
        }
      }
    ]
  },


  { path: '/tasks', redirect: '/dashboard' },
  { path: '/tasks/:pathMatch(.*)*', redirect: '/dashboard' },
  { path: '/queue', redirect: '/dashboard' },
  {
    path: '/reports',
    name: 'Reports',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '分析报告',
      icon: 'Document',
      requiresAuth: true,
      transition: 'fade'
    },
    children: [
      {
        path: '',
        name: 'ReportsHome',
        component: () => import('@/views/Reports/index.vue'),
        meta: {
          title: '分析报告',
          requiresAuth: true
        }
      },
      {
        path: 'view/:id',
        name: 'ReportDetail',
        component: () => import('@/views/Reports/ReportDetail.vue'),
        meta: {
          title: '报告详情',
          requiresAuth: true
        }
      },
      {
        path: 'token',
        name: 'TokenStatistics',
        component: () => import('@/views/Reports/TokenStatistics.vue'),
        meta: {
          title: 'Token统计',
          requiresAuth: true
        }
      }
    ]
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '设置',
      icon: 'Setting',
      requiresAuth: true,
      transition: 'slide-left'
    },
    children: [
      {
        path: '',
        name: 'SettingsHome',
        component: () => import('@/views/Settings/index.vue'),
        meta: {
          title: '设置',
          requiresAuth: true
        }
      },
      {
        path: 'config',
        name: 'ConfigManagement',
        component: () => import('@/views/Settings/ConfigManagement.vue'),
        meta: {
          title: '配置管理',
          requiresAuth: true
        }
      },
      {
        path: 'database',
        name: 'DatabaseManagement',
        component: () => import('@/views/System/DatabaseManagement.vue'),
        meta: {
          title: '数据库管理',
          requiresAuth: true
        }
      },
      {
        path: 'logs',
        name: 'OperationLogs',
        component: () => import('@/views/System/OperationLogs.vue'),
        meta: {
          title: '操作日志',
          requiresAuth: true
        }
      },
      {
        path: 'system-logs',
        name: 'LogManagement',
        component: () => import('@/views/System/LogManagement.vue'),
        meta: {
          title: '系统日志',
          requiresAuth: true
        }
      },
      {
        path: 'sync',
        name: 'MultiSourceSync',
        component: () => import('@/views/System/MultiSourceSync.vue'),
        meta: {
          title: '多数据源同步',
          requiresAuth: true
        }
      },
      {
        path: 'cache',
        name: 'CacheManagement',
        component: () => import('@/views/Settings/CacheManagement.vue'),
        meta: {
          title: '缓存管理',
          requiresAuth: true
        }
      },
      {
        path: 'usage',
        name: 'UsageStatistics',
        component: () => import('@/views/Settings/UsageStatistics.vue'),
        meta: {
          title: '使用统计',
          requiresAuth: true
        }
      },
      {
        path: 'scheduler',
        name: 'SchedulerManagement',
        component: () => import('@/views/System/SchedulerManagement.vue'),
        meta: {
          title: '定时任务',
          requiresAuth: true
        }
      }
    ]
  },

  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Auth/Login.vue'),
    meta: {
      title: '登录',
      hideInMenu: true,
      transition: 'fade'
    }
  },

  {
    path: '/about',
    name: 'About',
    component: () => import('@/views/About/index.vue'),
    meta: {
      title: '关于',
      icon: 'InfoFilled',
      requiresAuth: false, // 关于页面不需要认证
      transition: 'fade'
    }
  },
  {
    path: '/paper',
    name: 'PaperTrading',
    component: () => import('@/layouts/BasicLayout.vue'),
    meta: {
      title: '模拟交易',
      icon: 'CreditCard',
      requiresAuth: true,
      transition: 'slide-up'
    },
    children: [
      {
        path: '',
        name: 'PaperTradingHome',
        component: () => import('@/views/PaperTrading/index.vue'),
        meta: {
          title: '模拟交易',
          requiresAuth: true
        }
      }
    ]
  },

  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/Error/404.vue'),
    meta: {
      title: '页面不存在',
      hideInMenu: true,
      requiresAuth: true
    }
  }
]

// 创建路由实例
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    } else {
      return { top: 0 }
    }
  }
})

// 全局前置守卫
router.beforeEach(async (to, _from, next) => {
  // 开始进度条
  NProgress.start()

  const authStore = useAuthStore()
  const appStore = useAppStore()

  // 设置页面标题
  const title = to.meta.title as string
  if (title) {
    document.title = `${title} - 柳暗花明`
  }

  console.log('🚦 路由守卫检查:', {
    path: to.fullPath,
    name: to.name,
    requiresAuth: to.meta.requiresAuth,
    isAuthenticated: authStore.isAuthenticated,
    hasToken: !!authStore.token
  })

  // 检查是否需要认证
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    console.log('🔒 需要认证但用户未登录:', {
      path: to.fullPath,
      requiresAuth: to.meta.requiresAuth,
      isAuthenticated: authStore.isAuthenticated,
      token: authStore.token ? '存在' : '不存在'
    })
    // 保存原始路径，登录后跳转
    authStore.setRedirectPath(to.fullPath)
    next('/login')
    return
  }



  // 如果已登录且访问登录页，重定向到仪表板
  if (authStore.isAuthenticated && to.name === 'Login') {
    next('/dashboard')
    return
  }

  // 更新当前路由信息
  appStore.setCurrentRoute(to)

  next()
})

// 全局后置守卫
router.afterEach((_to, _from) => {
  // 结束进度条
  NProgress.done()

  // 页面切换后的处理
  nextTick(() => {
    // 可以在这里添加页面分析、埋点等逻辑
  })
})

// 路由错误处理
router.onError((error) => {
  console.error('路由错误:', error)
  NProgress.done()
  ElMessage.error('页面加载失败，请重试')
})

export default router

// 导出路由配置供其他地方使用
export { routes }
