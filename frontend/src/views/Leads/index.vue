<template>
  <div class="leads-page">
    <div class="page-header">
      <!-- 页内标题已隐藏（导航已有）
      <h1 class="page-title">机会列表 Leads</h1>
      -->
      <!-- 说明文字已隐藏
      <p class="page-description">
        汇总因子回测末日持仓（与 Factors「持仓分布」同口径：buy ≤ asOf ≤ sell，含当日买入）。
        <strong>机会</strong>来自优质因子（Sharpe≥{{ thresholds.good_sharpe }}）；
        <strong>警醒</strong>标出弱势因子（Sharpe&lt;{{ thresholds.weak_sharpe }}）也持有的标的——不是主推买入。
        多因子同持一只时全部标注；既有优质又有弱势时主标签为「混合」。
      </p>
      -->
    </div>

    <el-card shadow="never" class="toolbar">
      <el-row :gutter="12" align="middle">
        <el-col :span="5">
          <el-input v-model="keyword" clearable placeholder="代码/名称/因子" @keyup.enter="() => loadBook(false)" />
        </el-col>
        <el-col :span="5">
          <el-select v-model="filterMode" placeholder="筛选" @change="() => loadBook(false)">
            <el-option label="全部持仓书" value="all" />
            <el-option label="仅看优质机会" value="good" />
            <el-option label="含警醒" value="alert" />
            <el-option label="仅纯警醒" value="alert_only" />
            <el-option label="仅中性观察" value="watch" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-radio-group v-model="tab" size="default" @change="onTab">
            <el-radio-button label="book">因子持仓书</el-radio-button>
            <el-radio-button label="manual">手工/筛选</el-radio-button>
          </el-radio-group>
        </el-col>
        <el-col :span="10" class="actions">
          <span v-if="metaLine" class="meta">{{ metaLine }}</span>
          <el-button :loading="loading" @click="loadBook(false)">刷新</el-button>
          <el-button :loading="loading" type="warning" plain @click="loadBook(true)">重算缓存</el-button>
          <el-button v-if="tab === 'manual'" type="primary" @click="showCreate = true">新建机会</el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card v-show="tab === 'book'" shadow="never">
      <el-table :data="bookItems" v-loading="loading" stripe row-key="id">
        <el-table-column prop="name" label="名称" width="100" sortable />
        <el-table-column label="优质因子（机会）" min-width="220">
          <template #default="{ row }">
            <div v-if="row.factors_good?.length" class="badge-wrap">
              <el-tooltip
                v-for="f in visibleGood(row)"
                :key="'g-' + f.factor_id"
                :content="factorTip(f)"
                placement="top"
              >
                <el-tag
                  class="factor-badge good clickable"
                  size="small"
                  effect="light"
                  round
                  title="查看因子详情"
                  @click.stop="openFactorPanel(f)"
                >
                  {{ f.name }}{{ f.is_champion ? '★' : '' }}
                  <span v-if="f.sharpe != null" class="sh">{{ num(f.sharpe) }}</span>
                </el-tag>
              </el-tooltip>
              <el-button
                v-if="(row.factors_good?.length || 0) > BADGE_LIMIT"
                link
                type="primary"
                size="small"
                class="badge-expand"
                @click.stop="toggleBadgeExpand(row.id, 'good')"
              >
                {{ isBadgeExpanded(row.id, 'good')
                  ? '收起'
                  : `展开(+${(row.factors_good?.length || 0) - BADGE_LIMIT})` }}
              </el-button>
            </div>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="警醒 / 中性" min-width="220">
          <template #default="{ row }">
            <div v-if="alertFactorEntries(row).length" class="badge-wrap">
              <template v-for="item in visibleAlert(row)" :key="item.key">
                <el-tooltip
                  :content="item.kind === 'warn'
                    ? '警醒：弱势因子也持有。' + factorTip(item.f)
                    : '中性观察：' + factorTip(item.f)"
                  placement="top"
                >
                  <el-tag
                    :class="['factor-badge', 'clickable', item.kind === 'warn' ? 'warn' : 'neutral']"
                    size="small"
                    :effect="item.kind === 'warn' ? 'dark' : 'plain'"
                    round
                    title="查看因子详情"
                    @click.stop="openFactorPanel(item.f)"
                  >
                    {{ item.f.name }}
                    <span v-if="item.f.sharpe != null" class="sh">{{ num(item.f.sharpe) }}</span>
                  </el-tag>
                </el-tooltip>
              </template>
              <el-button
                v-if="alertFactorEntries(row).length > BADGE_LIMIT"
                link
                type="primary"
                size="small"
                class="badge-expand"
                @click.stop="toggleBadgeExpand(row.id, 'alert')"
              >
                {{ isBadgeExpanded(row.id, 'alert')
                  ? '收起'
                  : `展开(+${alertFactorEntries(row).length - BADGE_LIMIT})` }}
              </el-button>
            </div>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="评分" width="72" sortable />
        <el-table-column prop="as_of" label="asOf" width="110" />
        <el-table-column prop="reason" label="说明" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="success"
              :disabled="row.kind === 'alert'"
              @click="toInvestFromBook(row)"
            >
              {{ row.kind === 'alert' ? '仅警醒' : '转入投资' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-show="tab === 'manual'" shadow="never">
      <el-table :data="manualItems" v-loading="manualLoading" stripe>
        <el-table-column prop="code" label="代码" width="110" sortable />
        <el-table-column prop="name" label="名称" width="120" sortable />
        <el-table-column prop="source" label="来源" width="100" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="评分" width="80" sortable />
        <el-table-column prop="reason" label="理由" min-width="180" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新" width="170" />
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="setStatus(row, 'watching')">观察</el-button>
            <el-button link type="warning" @click="setStatus(row, 'analyzing')">分析中</el-button>
            <el-button link type="success" @click="toInvest(row)">转入投资</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="新建机会" width="480px">
      <el-form label-width="80px">
        <el-form-item label="代码"><el-input v-model="form.code" placeholder="600519 或 600519.SH" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="评分"><el-input-number v-model="form.score" :min="0" :max="100" /></el-form-item>
        <el-form-item label="理由"><el-input v-model="form.reason" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="create">保存</el-button>
      </template>
    </el-dialog>

    <FactorQuickPanel ref="factorPanel" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { leadsApi, type FactorRef, type LeadItem } from '@/api/leads'
import FactorQuickPanel from '@/components/Factors/FactorQuickPanel.vue'

const BADGE_LIMIT = 5

type BadgeCol = 'good' | 'alert'
type AlertEntry = { key: string; kind: 'warn' | 'neutral'; f: FactorRef }

const factorPanel = ref<InstanceType<typeof FactorQuickPanel> | null>(null)
const loading = ref(false)
const manualLoading = ref(false)
const bookItems = ref<LeadItem[]>([])
const manualItems = ref<LeadItem[]>([])
const keyword = ref('')
const filterMode = ref('good')
const tab = ref<'book' | 'manual'>('book')
const showCreate = ref(false)
const form = reactive({ code: '', name: '', score: 60 as number | undefined, reason: '' })
const thresholds = reactive({ good_sharpe: 0.15, weak_sharpe: 0.05 })
const stats = ref<Record<string, number>>({})
const asOf = ref('')
const updatedAt = ref('')
const buildMs = ref<number | undefined>()
/** 按行折叠：`${rowId}:good` / `${rowId}:alert` */
const badgeExpanded = reactive<Record<string, boolean>>({})

const metaLine = computed(() => {
  if (tab.value !== 'book') return ''
  const s = stats.value || {}
  const parts = [
    asOf.value ? `asOf ${asOf.value}` : '',
    s.total_names != null ? `标的 ${bookItems.value.length}/${s.total_names}` : `共 ${bookItems.value.length}`,
    s.names_opportunity != null
      ? `机会${s.names_opportunity}·混合${s.names_mixed}·警醒${s.names_alert}·观察${s.names_watch}`
      : '',
    buildMs.value != null ? `构建 ${buildMs.value}ms` : '',
  ]
  return parts.filter(Boolean).join(' · ')
})

const statusLabel = (s: string) =>
  ({ new: '新建', watching: '观察中', analyzing: '分析中', invested: '已投资', closed: '已关闭' } as any)[s] || s

function num(v?: number | null) {
  if (v == null || Number.isNaN(Number(v))) return ''
  return Number(v).toFixed(2)
}

function factorTip(f: FactorRef) {
  const bits = [
    f.factor_id,
    f.sharpe != null ? `Sharpe ${num(f.sharpe)}` : '',
    f.weight != null ? `权重 ${(Number(f.weight) * 100).toFixed(1)}%` : '',
    f.buy_date ? `持仓自 ${f.buy_date}` : '',
    f.n_legs != null && Number(f.n_legs) > 1 ? `${Number(f.n_legs)} 笔合并` : '',
    f.is_champion ? '隔夜冠军' : '',
    '点击查看因子详情',
  ]
  return bits.filter(Boolean).join(' · ')
}

function openFactorPanel(f: FactorRef) {
  if (!f?.factor_id) return
  factorPanel.value?.open(f.factor_id)
}

function badgeKey(rowId: string, col: BadgeCol) {
  return `${rowId}:${col}`
}

function isBadgeExpanded(rowId: string, col: BadgeCol) {
  return !!badgeExpanded[badgeKey(rowId, col)]
}

function toggleBadgeExpand(rowId: string, col: BadgeCol) {
  const k = badgeKey(rowId, col)
  badgeExpanded[k] = !badgeExpanded[k]
}

function visibleGood(row: LeadItem): FactorRef[] {
  const list = row.factors_good || []
  if (list.length <= BADGE_LIMIT || isBadgeExpanded(row.id, 'good')) return list
  return list.slice(0, BADGE_LIMIT)
}

function alertFactorEntries(row: LeadItem): AlertEntry[] {
  const warn = (row.factors_warn || []).map((f) => ({
    key: `w-${f.factor_id}`,
    kind: 'warn' as const,
    f,
  }))
  const neutral = (row.factors_neutral || []).map((f) => ({
    key: `n-${f.factor_id}`,
    kind: 'neutral' as const,
    f,
  }))
  return [...warn, ...neutral]
}

function visibleAlert(row: LeadItem): AlertEntry[] {
  const list = alertFactorEntries(row)
  if (list.length <= BADGE_LIMIT || isBadgeExpanded(row.id, 'alert')) return list
  return list.slice(0, BADGE_LIMIT)
}

async function loadBook(refresh: boolean = false) {
  loading.value = true
  try {
    const data = await leadsApi.factorBook({
      refresh: refresh === true,
      filter_mode: filterMode.value,
      keyword: keyword.value || undefined,
    })
    bookItems.value = data.items || []
    // 刷新后清理已不存在行的展开状态，避免键堆积
    const ids = new Set(bookItems.value.map((r) => r.id))
    for (const k of Object.keys(badgeExpanded)) {
      const rowId = k.split(':')[0]
      if (!ids.has(rowId)) delete badgeExpanded[k]
    }
    if (data.thresholds) {
      thresholds.good_sharpe = data.thresholds.good_sharpe
      thresholds.weak_sharpe = data.thresholds.weak_sharpe
    }
    stats.value = data.stats || {}
    asOf.value = data.as_of || ''
    updatedAt.value = data.updated_at || ''
    buildMs.value = data.build_ms
  } catch (e: any) {
    ElMessage.error(e?.message || '加载因子持仓书失败')
  } finally {
    loading.value = false
  }
}

async function loadManual() {
  manualLoading.value = true
  try {
    const data = await leadsApi.list({ keyword: keyword.value || undefined })
    manualItems.value = data.items || []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    manualLoading.value = false
  }
}

function onTab() {
  if (tab.value === 'book') loadBook()
  else loadManual()
}

async function create() {
  if (!form.code) {
    ElMessage.warning('请填写代码')
    return
  }
  await leadsApi.create({ ...form, source: 'manual', status: 'new', market: 'CN' })
  showCreate.value = false
  form.code = ''
  form.name = ''
  form.reason = ''
  ElMessage.success('已创建')
  loadManual()
}

async function setStatus(row: LeadItem, s: string) {
  await leadsApi.update(row.id, { status: s })
  loadManual()
}

async function toInvest(row: LeadItem) {
  await leadsApi.toInvestment(row.id)
  ElMessage.success('已转入投资列表')
  loadManual()
}

async function toInvestFromBook(row: LeadItem) {
  if (row.kind === 'alert') {
    ElMessage.warning('纯警醒条目不建议转入；若仍要跟踪请到手工机会新建')
    return
  }
  await leadsApi.factorBookToInvestment(row)
  ElMessage.success('已转入投资列表（附带来源因子）')
}

async function remove(row: LeadItem) {
  await ElMessageBox.confirm(`删除机会 ${row.code}?`, '确认')
  await leadsApi.remove(row.id)
  loadManual()
}

onMounted(() => loadBook())
</script>

<style scoped>
.page-header { margin-bottom: 16px; }
.page-title { margin: 0 0 6px; font-size: 22px; }
.page-description { margin: 0; color: var(--el-text-color-secondary); line-height: 1.55; font-size: 13px; max-width: 960px; }
.toolbar { margin-bottom: 12px; }
.actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; flex-wrap: wrap; }
.meta { font-size: 12px; color: var(--el-text-color-secondary); margin-right: 4px; }
.muted { color: var(--el-text-color-placeholder); }
.badge-wrap { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.badge-expand { padding: 0 4px; height: auto; font-size: 12px; }
.factor-badge { max-width: 100%; }
.factor-badge.clickable { cursor: pointer; }
.factor-badge.good { --el-tag-bg-color: #e8f5e9; --el-tag-border-color: #a5d6a7; --el-tag-text-color: #2e7d32; }
.factor-badge.warn { background: #e65100 !important; border-color: #e65100 !important; color: #fff !important; }
.factor-badge.neutral { color: #8d6e63; border-color: #bcaaa4; }
.factor-badge .sh { margin-left: 4px; opacity: 0.85; font-variant-numeric: tabular-nums; }
</style>
