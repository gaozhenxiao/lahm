<template>
  <div class="strats-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">{{ pageTitle }}</h1>
        <p class="page-description">
          多资产 · {{ pageTitle }}。期现不做。执行对接 QMT。
        </p>
      </div>
      <div class="header-actions">
        <el-button :loading="qmtLoading" @click="loadQmt">QMT状态</el-button>
        <el-button type="primary" :loading="loading" @click="loadScan(true)">强制重扫</el-button>
      </div>
    </div>

    <el-alert
      v-if="qmt"
      class="mb-12"
      :type="qmt.ready_for_orders ? 'success' : qmt.xtquant?.importable ? 'warning' : 'info'"
      show-icon
      :closable="false"
      :title="qmtTitle"
    >
      <template #default>
        <div class="qmt-body">
          <div>配置：{{ qmt.config_path }}</div>
          <div v-if="qmt.connect_error" class="err">连接：{{ qmt.connect_error }}</div>
          <ul class="checklist">
            <li v-for="(c, i) in qmt.checklist" :key="i">{{ c }}</li>
          </ul>
        </div>
      </template>
    </el-alert>

    <div v-if="currentMeta" class="meta-bar muted">
      <el-tag size="small" effect="plain">{{ currentMeta.best_regime || '—' }}</el-tag>
      <el-tag size="small" effect="plain">难度 {{ currentMeta.difficulty || '—' }}</el-tag>
      <el-tag size="small" effect="plain">资金 {{ currentMeta.capital || '—' }}</el-tag>
      <span>{{ currentMeta.description }}</span>
      <el-button
        v-if="activeId === 'cb_stock_arb' || currentMeta.redirect"
        link
        type="primary"
        @click="$router.push('/multi-asset/cb')"
      >打开可转债</el-button>
    </div>

    <div v-loading="loading" class="scan-body">
      <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="mb-12" />

      <template v-if="scan">
        <div class="meta-line muted">
          更新 {{ scan.asof }}
          <template v-if="scan.cached"> · 缓存 {{ scan.cache_age_sec ?? 0 }}s</template>
          · {{ scan.source }}
        </div>

        <el-row :gutter="12" class="stats-row">
          <el-col v-for="(v, k) in summaryEntries" :key="k" :xs="12" :sm="6">
            <el-card shadow="never" class="stat-card">
              <div class="stat-label">{{ k }}</div>
              <div class="stat-value">{{ v }}</div>
            </el-card>
          </el-col>
        </el-row>

        <!-- dual_low -->
        <el-table v-if="activeId === 'dual_low'" :data="scan.items || []" stripe size="small">
          <el-table-column type="index" width="48" />
          <el-table-column prop="bond_code" label="转债" width="90" />
          <el-table-column prop="bond_name" label="简称" width="100" />
          <el-table-column label="正股" min-width="120">
            <template #default="{ row }">{{ row.stock_code }} {{ row.stock_name }}</template>
          </el-table-column>
          <el-table-column prop="bond_price" label="债价" width="80" align="right" />
          <el-table-column prop="premium_pct" label="溢价%" width="80" align="right" />
          <el-table-column prop="dual_low" label="双低" width="80" align="right" sortable />
          <el-table-column prop="rating" label="评级" width="72" />
        </el-table>

        <!-- 倾斜网格：红利ETF / 移动+四大行 -->
        <template v-else-if="activeId === 'etf_grid' || activeId === 'cm_big4_grid'">
          <el-alert
            type="success"
            :closable="false"
            show-icon
            class="mb-12"
            :title="slopeGridTitle"
          />
          <el-table :data="scan.items || []" stripe size="small">
            <el-table-column prop="code" label="代码" width="84" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="price" label="现价" width="72" align="right" />
            <el-table-column prop="center" label="中枢" width="72" align="right" />
            <el-table-column prop="zone" label="区域" width="88" />
            <el-table-column prop="step_pct" label="步长%" width="72" align="right" />
            <el-table-column label="买档" min-width="160">
              <template #default="{ row }">{{ (row.buy_levels || []).slice(0, 4).join(' / ') }}</template>
            </el-table-column>
            <el-table-column label="卖档" min-width="160">
              <template #default="{ row }">{{ (row.sell_levels || []).slice(0, 4).join(' / ') }}</template>
            </el-table-column>
            <el-table-column label="回测CAGR" width="88" align="right">
              <template #default="{ row }">{{ fmtPct(row.bt_cagr) }}</template>
            </el-table-column>
            <el-table-column label="超额" width="72" align="right">
              <template #default="{ row }">{{ fmtPct(row.bt_excess) }}</template>
            </el-table-column>
            <el-table-column label="Sharpe" width="72" align="right">
              <template #default="{ row }">{{ row.bt_sharpe != null ? Number(row.bt_sharpe).toFixed(2) : '—' }}</template>
            </el-table-column>
            <el-table-column label="回撤" width="80" align="right">
              <template #default="{ row }">{{ fmtPct(row.bt_max_dd) }}</template>
            </el-table-column>
            <el-table-column prop="hint" label="提示" min-width="180" show-overflow-tooltip />
          </el-table>
          <el-table
            v-if="scan.backtest?.summary_table?.length"
            :data="scan.backtest.summary_table"
            stripe
            size="small"
            class="mt-12"
            style="margin-top: 12px"
          >
            <el-table-column prop="code" label="代码" width="84" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column label="网格CAGR" width="96" align="right">
              <template #default="{ row }">{{ fmtPct(row.grid_cagr) }}</template>
            </el-table-column>
            <el-table-column label="持有CAGR" width="96" align="right">
              <template #default="{ row }">{{ fmtPct(row.bh_cagr) }}</template>
            </el-table-column>
            <el-table-column label="超额" width="80" align="right">
              <template #default="{ row }">{{ fmtPct(row.excess_cagr) }}</template>
            </el-table-column>
            <el-table-column label="Sharpe" width="80" align="right">
              <template #default="{ row }">{{ row.grid_sharpe != null ? Number(row.grid_sharpe).toFixed(2) : '—' }}</template>
            </el-table-column>
            <el-table-column label="最大回撤" width="88" align="right">
              <template #default="{ row }">{{ fmtPct(row.grid_max_dd) }}</template>
            </el-table-column>
            <el-table-column label="持有回撤" width="88" align="right">
              <template #default="{ row }">{{ fmtPct(row.bh_max_dd) }}</template>
            </el-table-column>
          </el-table>
        </template>

        <!-- lof_arb -->
        <el-table v-else-if="activeId === 'lof_arb'" :data="scan.items || []" stripe size="small" max-height="520">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column prop="kind" label="类型" width="64" />
          <el-table-column prop="price" label="市价" width="80" align="right" />
          <el-table-column prop="iopv" label="IOPV" width="80" align="right" />
          <el-table-column prop="premium_pct" label="溢价%" width="88" align="right" sortable />
          <el-table-column prop="side" label="方向" min-width="140" />
          <el-table-column label="成交额" width="100" align="right">
            <template #default="{ row }">{{ fmtAmount(row.amount) }}</template>
          </el-table-column>
        </el-table>

        <!-- bond_etf_arb -->
        <el-table v-else-if="activeId === 'bond_etf_arb'" :data="scan.items || []" stripe size="small" max-height="520">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column prop="price" label="市价" width="80" align="right" />
          <el-table-column prop="iopv" label="IOPV" width="80" align="right" />
          <el-table-column prop="premium_pct" label="溢价%" width="88" align="right" sortable />
          <el-table-column prop="side" label="方向" min-width="140" />
          <el-table-column label="成交额" width="100" align="right">
            <template #default="{ row }">{{ fmtAmount(row.amount) }}</template>
          </el-table-column>
        </el-table>

        <!-- futures_basis -->
        <el-table v-else-if="activeId === 'futures_basis'" :data="scan.items || []" stripe size="small">
          <el-table-column prop="prefix" label="品种" width="64" />
          <el-table-column prop="futures_name" label="期货" min-width="120" />
          <el-table-column prop="futures_price" label="期价" width="88" align="right" />
          <el-table-column prop="index_name" label="现货" width="100" />
          <el-table-column prop="index_price" label="现价" width="88" align="right" />
          <el-table-column prop="basis_pct" label="基差%" width="88" align="right" sortable />
          <el-table-column prop="regime" label="状态" width="80" />
          <el-table-column prop="signal" label="信号" min-width="180" show-overflow-tooltip />
        </el-table>

        <!-- treasury_basis -->
        <template v-else-if="activeId === 'treasury_basis'">
          <el-table :data="scan.items || []" stripe size="small">
            <el-table-column prop="prefix" label="品种" width="64" />
            <el-table-column prop="futures_name" label="期货" min-width="100" />
            <el-table-column prop="futures_price" label="期价" width="88" align="right" />
            <el-table-column label="代理ETF" min-width="140">
              <template #default="{ row }">{{ row.proxy_code }} {{ row.proxy_name }}</template>
            </el-table-column>
            <el-table-column prop="proxy_price" label="代理ETF价" width="100" align="right" />
            <el-table-column prop="trade_date" label="期货日" width="100" />
            <el-table-column prop="regime" label="状态" width="100" />
            <el-table-column prop="signal" label="说明" min-width="180" show-overflow-tooltip />
          </el-table>
          <el-table
            v-if="scan.spreads?.length"
            :data="scan.spreads"
            stripe
            size="small"
            class="mt-12"
            style="margin-top: 12px"
          >
            <el-table-column prop="pair" label="跨期" width="100" />
            <el-table-column prop="spread" label="价差" width="100" align="right" />
            <el-table-column prop="note" label="说明" min-width="200" />
          </el-table>
        </template>

        <!-- covered_call -->
        <el-table v-else-if="activeId === 'covered_call'" :data="scan.items || []" stripe size="small">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="140" />
          <el-table-column prop="style" label="风格" width="72" />
          <el-table-column prop="price" label="现价" width="80" align="right" />
          <el-table-column prop="qvix" label="QVIX" width="80" align="right" />
          <el-table-column prop="environment" label="环境" width="120" />
          <el-table-column prop="advice" label="建议" min-width="180" show-overflow-tooltip />
          <el-table-column prop="option_hint" label="期权说明" min-width="200" show-overflow-tooltip />
        </el-table>

        <!-- pairs -->
        <el-table v-else-if="activeId === 'pairs'" :data="scan.items || []" stripe size="small">
          <el-table-column prop="pair" label="配对" min-width="160" />
          <el-table-column prop="zscore" label="Z" width="80" align="right" sortable />
          <el-table-column prop="beta" label="β" width="72" align="right" />
          <el-table-column prop="a_price" label="A价" width="80" align="right" />
          <el-table-column prop="b_price" label="B价" width="80" align="right" />
          <el-table-column prop="signal" label="信号" min-width="140" />
          <el-table-column prop="reason" label="备注" min-width="140" show-overflow-tooltip />
        </el-table>

        <!-- cb_stock_arb compact -->
        <template v-else-if="activeId === 'cb_stock_arb'">
          <el-table :data="scan.discount || []" stripe size="small">
            <el-table-column prop="bond_code" label="转债" width="90" />
            <el-table-column prop="bond_name" label="简称" width="100" />
            <el-table-column prop="premium_pct" label="溢价%" width="88" align="right" />
            <el-table-column prop="net_edge_pct" label="净边%~" width="88" align="right" />
            <el-table-column label="标记" min-width="160">
              <template #default="{ row }">
                <el-tag v-for="f in row.flags || []" :key="f" size="small" class="flag">{{ f }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <p class="muted">完整折价/平价表请到侧栏「可转债」；薄折价建议盘中实时扫。</p>
        </template>

        <el-card v-if="scan.notes?.length" shadow="never" class="notes-card">
          <template #header>说明</template>
          <ul class="notes">
            <li v-for="(n, i) in scan.notes" :key="i">{{ n }}</li>
          </ul>
        </el-card>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { strategiesApi, type QmtStatus, type StrategyMeta } from '@/api/strategies'

const route = useRoute()
const strategies = ref<StrategyMeta[]>([])
const loading = ref(false)
const qmtLoading = ref(false)
const error = ref('')
const scan = ref<any>(null)
const qmt = ref<QmtStatus | null>(null)

const activeId = computed(
  () => (route.meta.strategyId as string) || String(route.path.split('/').pop() || 'dual_low')
)

const currentMeta = computed(() => strategies.value.find((s) => s.id === activeId.value))
const pageTitle = computed(
  () => currentMeta.value?.name || (route.meta.title as string) || '策略'
)

const summaryEntries = computed(() => {
  const s = scan.value?.summary || {}
  return s as Record<string, any>
})

const qmtTitle = computed(() => {
  if (!qmt.value) return ''
  if (qmt.value.ready_for_orders) return 'QMT 已就绪，可接下单'
  if (qmt.value.connected) return 'QMT 已连接，请确认资金账号'
  if (qmt.value.xtquant?.importable) return 'xtquant 可导入，尚未连接 MiniQMT'
  return 'QMT 未就绪（今天开好后填写 userdata 即可）'
})

const slopeGridTitle = computed(() => {
  const p = scan.value?.params
  const label = activeId.value === 'cm_big4_grid' ? '移动+工农中建 等权' : '红利 ETF'
  if (!p) return `向上倾斜网格 · ${label}`
  return `向上倾斜网格 · ${label} · 步长 ${(Number(p.step_pct) * 100).toFixed(1)}% · ${p.n_grids}档 · 底仓≥${p.min_layers} · MA${p.ma_center}`
})

function fmtAmount(v: number | null | undefined) {
  if (v == null || Number.isNaN(v)) return '—'
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`
  return String(Math.round(v))
}

function fmtPct(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(1)}%`
}

async function loadHome() {
  const data = await strategiesApi.home()
  strategies.value = data.strategies || []
}

async function loadScan(force = false) {
  if (!activeId.value) return
  loading.value = true
  error.value = ''
  try {
    scan.value = force
      ? await strategiesApi.refresh(activeId.value)
      : await strategiesApi.scan(activeId.value)
  } catch (e: any) {
    error.value = e?.message || '扫描失败'
    ElMessage.error(error.value)
  } finally {
    loading.value = false
  }
}

async function loadQmt() {
  qmtLoading.value = true
  try {
    qmt.value = await strategiesApi.qmtStatus()
  } catch (e: any) {
    ElMessage.error(e?.message || 'QMT状态失败')
  } finally {
    qmtLoading.value = false
  }
}

watch(activeId, () => {
  loadScan(false)
})

onMounted(async () => {
  try {
    await loadHome()
    await Promise.all([loadScan(false), loadQmt()])
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  }
})
</script>

<style scoped>
.strats-page { padding-bottom: 24px; }
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.page-title { margin: 0 0 6px; font-size: 22px; }
.page-description { margin: 0; color: var(--el-text-color-secondary); max-width: 720px; }
.header-actions { display: flex; gap: 8px; flex-shrink: 0; }
.meta-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
  font-size: 13px;
}
.meta-line { margin-bottom: 12px; font-size: 13px; }
.stats-row { margin-bottom: 12px; }
.stat-card { margin-bottom: 8px; }
.stat-label { font-size: 13px; color: var(--el-text-color-secondary); }
.stat-value { margin-top: 4px; font-size: 22px; font-weight: 600; }
.muted { color: var(--el-text-color-secondary); }
.mb-12 { margin-bottom: 12px; }
.notes { margin: 0; padding-left: 18px; line-height: 1.7; }
.notes-card { margin-top: 12px; }
.flag { margin-right: 4px; }
.checklist { margin: 6px 0 0; padding-left: 18px; }
.err { color: var(--el-color-danger); margin-top: 4px; }
.qmt-body { font-size: 13px; }
@media (max-width: 768px) {
  .page-header { flex-direction: column; }
}
</style>
