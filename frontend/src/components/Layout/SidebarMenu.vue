<template>
  <el-menu
    :default-active="activeMenu"
    :collapse="appStore.sidebarCollapsed"
    :unique-opened="true"
    router
    class="sidebar-menu"
  >
    <el-menu-item index="/dashboard">
      <el-icon><Odometer /></el-icon>
      <template #title>仪表板</template>
    </el-menu-item>

    <el-sub-menu index="/equities">
      <template #title>
        <el-icon><DataLine /></el-icon>
        <span>股票</span>
      </template>
      <el-menu-item index="/factors">多因子</el-menu-item>
      <el-menu-item index="/leads">机会列表</el-menu-item>
      <el-menu-item index="/investments">投资列表</el-menu-item>
      <el-menu-item index="/favorites">我的自选股</el-menu-item>
    </el-sub-menu>

    <el-sub-menu index="/multi-asset">
      <template #title>
        <el-icon><Connection /></el-icon>
        <span>多资产</span>
      </template>
      <el-menu-item index="/multi-asset/cb">可转债</el-menu-item>
      <el-menu-item index="/multi-asset/dual_low">转债双低</el-menu-item>
      <el-menu-item index="/multi-asset/etf_grid">红利倾斜网格</el-menu-item>
      <el-menu-item index="/multi-asset/cm_big4_grid">移动四大行网格</el-menu-item>
      <el-menu-item index="/multi-asset/lof_arb">LOF套利</el-menu-item>
      <el-menu-item index="/multi-asset/bond_etf_arb">债券ETF折溢价</el-menu-item>
      <el-menu-item index="/multi-asset/futures_basis">股指基差</el-menu-item>
      <el-menu-item index="/multi-asset/treasury_basis">国债期货基差</el-menu-item>
      <el-menu-item index="/multi-asset/covered_call">高股息备兑</el-menu-item>
      <el-menu-item index="/multi-asset/pairs">配对交易</el-menu-item>
    </el-sub-menu>

    <el-menu-item index="/paper">
      <el-icon><CreditCard /></el-icon>
      <template #title>模拟交易</template>
    </el-menu-item>

    <el-menu-item index="/reports">
      <el-icon><Document /></el-icon>
      <template #title>分析报告</template>
    </el-menu-item>

    <el-sub-menu index="/settings">
      <template #title>
        <el-icon><Setting /></el-icon>
        <span>设置</span>
      </template>
      <el-menu-item index="/settings">通用设置</el-menu-item>
      <el-menu-item index="/settings?tab=appearance">外观</el-menu-item>
      <el-menu-item index="/settings?tab=analysis">分析偏好</el-menu-item>
      <el-menu-item index="/settings?tab=notifications">通知</el-menu-item>
      <el-menu-item index="/settings?tab=security">安全</el-menu-item>
      <el-menu-item index="/settings/config">配置管理</el-menu-item>
      <el-menu-item index="/settings/cache">缓存</el-menu-item>
      <el-menu-item index="/settings/database">数据库</el-menu-item>
      <el-menu-item index="/settings/logs">操作日志</el-menu-item>
      <el-menu-item index="/settings/system-logs">系统日志</el-menu-item>
      <el-menu-item index="/settings/sync">多源同步</el-menu-item>
      <el-menu-item index="/settings/scheduler">定时任务</el-menu-item>
      <el-menu-item index="/settings/usage">使用统计</el-menu-item>
    </el-sub-menu>

    <el-menu-item index="/about">
      <el-icon><InfoFilled /></el-icon>
      <template #title>关于</template>
    </el-menu-item>
  </el-menu>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import {
  Odometer,
  Setting,
  InfoFilled,
  CreditCard,
  DataLine,
  Connection,
  Document
} from '@element-plus/icons-vue'

const route = useRoute()
const appStore = useAppStore()

const activeMenu = computed(() => {
  if (route.path === '/settings' && route.query.tab) {
    return `/settings?tab=${route.query.tab}`
  }
  return route.path
})
</script>

<style lang="scss" scoped>
.sidebar-menu {
  border: none;
  height: 100%;

  :deep(.el-menu-item),
  :deep(.el-sub-menu__title) {
    height: 48px;
    line-height: 48px;
  }

  :deep(.el-menu-item.is-active) {
    background-color: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
  }
}
</style>
