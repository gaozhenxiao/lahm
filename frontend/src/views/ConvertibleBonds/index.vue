<template>
  <div class="cb-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">可转债 Convertible Bonds</h1>
        <p class="page-description">
          多资产 · 可转债。当前支持转债-正股套利扫描；日内套利后续接入。双低见侧栏「转债双低」。
        </p>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="load(false)">刷新缓存</el-button>
        <el-button type="primary" :loading="loading" @click="load(true)">强制重扫</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="cb-tabs">
      <el-tab-pane label="转债-正股套利" name="stock_arb">
        <div v-loading="loading" class="tab-body">
          <el-alert
            v-if="error"
            type="error"
            :title="error"
            show-icon
            :closable="false"
            class="mb-12"
          />

          <el-row v-if="result" :gutter="12" class="stats-row">
            <el-col :xs="12" :sm="6">
              <el-card shadow="never" class="stat-card">
                <div class="stat-label">真实成交样本</div>
                <div class="stat-value">{{ result.summary.n_traded }}</div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6">
              <el-card shadow="never" class="stat-card warn">
                <div class="stat-label">折价候选</div>
                <div class="stat-value">{{ result.summary.n_discount }}</div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6">
              <el-card shadow="never" class="stat-card">
                <div class="stat-label">平价附近</div>
                <div class="stat-value">{{ result.summary.n_near_parity }}</div>
              </el-card>
            </el-col>
            <el-col :xs="12" :sm="6">
              <el-card shadow="never" class="stat-card">
                <div class="stat-label">双低池</div>
                <div class="stat-value">{{ result.summary.n_dual_low }}</div>
              </el-card>
            </el-col>
          </el-row>

          <div v-if="result" class="meta-line muted">
            更新 {{ result.asof }}
            <template v-if="result.cached"> · 缓存 {{ result.cache_age_sec ?? 0 }}s</template>
            <template v-else> · 刚扫描</template>
            · {{ result.source }}
          </div>

          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="section-header">
                <span>折价套利（溢价率 ≤ {{ discountMax }}%）</span>
                <el-tag size="small" type="warning" effect="plain">T+1 隔夜风险</el-tag>
              </div>
            </template>
            <el-empty v-if="!result?.discount?.length" description="当前无折价候选" />
            <el-table v-else :data="result.discount" stripe size="small">
              <el-table-column prop="bond_code" label="转债" width="90" />
              <el-table-column prop="bond_name" label="简称" width="100" />
              <el-table-column label="正股" min-width="120">
                <template #default="{ row }">
                  {{ row.stock_code }} {{ row.stock_name }}
                </template>
              </el-table-column>
              <el-table-column prop="bond_price" label="债价" width="88" align="right">
                <template #default="{ row }">{{ fmt(row.bond_price) }}</template>
              </el-table-column>
              <el-table-column prop="conversion_value" label="转股价值" width="96" align="right">
                <template #default="{ row }">{{ fmt(row.conversion_value) }}</template>
              </el-table-column>
              <el-table-column prop="premium_pct" label="溢价%" width="88" align="right" sortable>
                <template #default="{ row }">
                  <span class="neg">{{ fmt(row.premium_pct) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="net_edge_pct" label="净边%~" width="88" align="right">
                <template #default="{ row }">{{ fmt(row.net_edge_pct) }}</template>
              </el-table-column>
              <el-table-column prop="change_pct" label="涨跌%" width="80" align="right">
                <template #default="{ row }">{{ fmt(row.change_pct) }}</template>
              </el-table-column>
              <el-table-column label="成交额" width="100" align="right">
                <template #default="{ row }">{{ fmtAmount(row.amount) }}</template>
              </el-table-column>
              <el-table-column label="转股期" width="80" align="center">
                <template #default="{ row }">
                  <el-tag
                    v-if="row.approx_in_convert_period === true"
                    size="small"
                    type="success"
                    effect="plain"
                  >约可转</el-tag>
                  <el-tag
                    v-else-if="row.approx_in_convert_period === false"
                    size="small"
                    type="info"
                    effect="plain"
                  >未到</el-tag>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="标记" min-width="160">
                <template #default="{ row }">
                  <el-tag
                    v-for="f in row.flags || []"
                    :key="f"
                    size="small"
                    class="flag-tag"
                    :type="f.includes('强赎') ? 'danger' : 'warning'"
                    effect="plain"
                  >{{ f }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="section-header">
                <span>平价附近（0 ~ {{ nearParityMax }}%）</span>
                <span class="muted small">股性替代 / 联动，非无风险套利</span>
              </div>
            </template>
            <el-table :data="result?.near_parity || []" stripe size="small" max-height="360">
              <el-table-column prop="bond_code" label="转债" width="90" />
              <el-table-column prop="bond_name" label="简称" width="100" />
              <el-table-column label="正股" min-width="120">
                <template #default="{ row }">
                  {{ row.stock_code }} {{ row.stock_name }}
                </template>
              </el-table-column>
              <el-table-column prop="bond_price" label="债价" width="88" align="right">
                <template #default="{ row }">{{ fmt(row.bond_price) }}</template>
              </el-table-column>
              <el-table-column prop="conversion_value" label="转股价值" width="96" align="right">
                <template #default="{ row }">{{ fmt(row.conversion_value) }}</template>
              </el-table-column>
              <el-table-column prop="premium_pct" label="溢价%" width="88" align="right" sortable>
                <template #default="{ row }">{{ fmt(row.premium_pct) }}</template>
              </el-table-column>
              <el-table-column prop="dual_low" label="双低" width="80" align="right">
                <template #default="{ row }">{{ fmt(row.dual_low) }}</template>
              </el-table-column>
              <el-table-column label="成交额" width="100" align="right">
                <template #default="{ row }">{{ fmtAmount(row.amount) }}</template>
              </el-table-column>
              <el-table-column prop="rating" label="评级" width="72" />
            </el-table>
          </el-card>

          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="section-header">
                <span>双低排序（债价 + 溢价率）</span>
                <span class="muted small">相对价值轮动</span>
              </div>
            </template>
            <el-table :data="result?.dual_low || []" stripe size="small" max-height="360">
              <el-table-column type="index" label="#" width="48" />
              <el-table-column prop="bond_code" label="转债" width="90" />
              <el-table-column prop="bond_name" label="简称" width="100" />
              <el-table-column label="正股" min-width="120">
                <template #default="{ row }">
                  {{ row.stock_code }} {{ row.stock_name }}
                </template>
              </el-table-column>
              <el-table-column prop="bond_price" label="债价" width="88" align="right">
                <template #default="{ row }">{{ fmt(row.bond_price) }}</template>
              </el-table-column>
              <el-table-column prop="premium_pct" label="溢价%" width="88" align="right">
                <template #default="{ row }">{{ fmt(row.premium_pct) }}</template>
              </el-table-column>
              <el-table-column prop="dual_low" label="双低分" width="88" align="right" sortable>
                <template #default="{ row }">{{ fmt(row.dual_low) }}</template>
              </el-table-column>
              <el-table-column label="成交额" width="100" align="right">
                <template #default="{ row }">{{ fmtAmount(row.amount) }}</template>
              </el-table-column>
              <el-table-column prop="rating" label="评级" width="72" />
            </el-table>
          </el-card>

          <el-card v-if="result?.notes?.length" shadow="never" class="section-card">
            <template #header>说明</template>
            <ul class="notes">
              <li v-for="(n, i) in result.notes" :key="i">{{ n }}</li>
            </ul>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane name="intraday_arb" disabled>
        <template #label>
          <span>日内套利</span>
          <el-tag size="small" type="info" effect="plain" class="soon-tag">即将推出</el-tag>
        </template>
        <el-empty description="日内盘口/分钟级套利规划中" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { cbApi, type CbStockArbResult } from '@/api/cb'

const activeTab = ref('stock_arb')
const loading = ref(false)
const error = ref('')
const result = ref<CbStockArbResult | null>(null)
const discountMax = ref(-0.3)
const nearParityMax = ref(3)

function fmt(v: number | null | undefined, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return Number(v).toFixed(digits)
}

function fmtAmount(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`
  return String(Math.round(v))
}

async function load(force: boolean) {
  loading.value = true
  error.value = ''
  try {
    const data = force
      ? await cbApi.refreshStockArb()
      : await cbApi.stockArb({
          refresh: false,
          discount_max: discountMax.value,
          near_parity_max: nearParityMax.value,
        })
    result.value = data
    if (data.params?.discount_max !== undefined) discountMax.value = data.params.discount_max
    if (data.params?.near_parity_max !== undefined) nearParityMax.value = data.params.near_parity_max
    if (force) ElMessage.success('已重新扫描')
  } catch (e: any) {
    error.value = e?.message || '加载失败'
    ElMessage.error(error.value)
  } finally {
    loading.value = false
  }
}

onMounted(() => load(false))
</script>

<style scoped>
.cb-page {
  padding-bottom: 24px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 12px;
}
.page-title {
  margin: 0 0 6px;
  font-size: 22px;
}
.page-description {
  margin: 0;
  color: var(--el-text-color-secondary);
  max-width: 640px;
}
.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.cb-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.stats-row {
  margin-bottom: 12px;
}
.stat-card {
  margin-bottom: 8px;
}
.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.stat-value {
  margin-top: 4px;
  font-size: 24px;
  font-weight: 600;
}
.stat-card.warn .stat-value {
  color: var(--el-color-warning);
}
.meta-line {
  margin-bottom: 12px;
  font-size: 13px;
}
.section-card {
  margin-bottom: 12px;
}
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.muted {
  color: var(--el-text-color-secondary);
}
.small {
  font-size: 12px;
}
.neg {
  color: var(--el-color-danger);
  font-weight: 600;
}
.flag-tag {
  margin-right: 4px;
  margin-bottom: 2px;
}
.notes {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
  line-height: 1.7;
}
.soon-tag {
  margin-left: 6px;
}
.mb-12 {
  margin-bottom: 12px;
}
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
  }
}
</style>
