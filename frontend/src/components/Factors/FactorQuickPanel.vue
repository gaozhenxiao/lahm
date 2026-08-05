<template>
  <!-- 因子速览：类似 Factors 列表一行 -->
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="720px"
    destroy-on-close
    class="factor-quick-panel"
    @closed="onClosed"
  >
    <div v-loading="loading" class="panel-body">
      <template v-if="factor">
        <div class="meta-row">
          <div class="meta-main">
            <div class="name">{{ factor.name }}</div>
            <div class="id-line">
              <code>{{ factor.factor_id }}</code>
              <el-tag v-if="factor.status" size="small" effect="plain">{{ factor.status }}</el-tag>
              <el-tag v-if="!factor.builtin" size="small" type="info" effect="plain">非内置</el-tag>
            </div>
          </div>
          <div class="meta-side">
            <div class="cat">{{ categoryLabel(factor.category) }}</div>
            <div v-if="factor.tags?.length" class="tags">
              <el-tag v-for="t in factor.tags" :key="t" size="small" type="info" effect="plain" round>
                {{ t }}
              </el-tag>
            </div>
          </div>
        </div>

        <el-descriptions :column="2" size="small" border class="metrics">
          <el-descriptions-item label="Sharpe">
            <span :class="retClass(metrics?.sharpe)">{{ num(metrics?.sharpe) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="累计收益">
            <span :class="retClass(metrics?.total_return)">{{ pct(metrics?.total_return) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="年化 (CAGR)">
            <span :class="retClass(metrics?.annual_return)">{{ pct(metrics?.annual_return) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="最大回撤">
            <span class="mdd">{{ pct(metrics?.max_drawdown) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="回测区间" :span="2">
            <span v-if="metrics?.start && metrics?.end" class="range">
              {{ metrics.start }} ~ {{ metrics.end }}
            </span>
            <span v-else-if="metrics?.error || factor?.last_backtest_error" class="muted">
              {{ metrics?.error || factor?.last_backtest_error }}
              <template v-if="metrics?.note"> · {{ metrics.note }}</template>
            </span>
            <span v-else class="muted">暂无回测摘要</span>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="factor.description" class="desc">{{ factor.description }}</div>

        <div class="actions">
          <span class="actions-label">产物</span>
          <template v-if="artifacts.length">
            <el-button
              v-for="a in artifacts"
              :key="a.id"
              link
              type="primary"
              :loading="preview.loading && preview.artifactId === a.id"
              @click="openArtifact(a)"
            >
              {{ shortLabel(a) }}
            </el-button>
          </template>
          <span v-else class="muted">暂无可用产物</span>
          <el-divider direction="vertical" />
          <el-button link type="primary" :loading="guide.loading" @click="openGuide">说明</el-button>
          <el-button link type="info" @click="goFactorsPage">在 Factors 页打开</el-button>
        </div>
      </template>
      <el-empty v-else-if="!loading" :description="loadError || '未能加载因子'" />
    </div>
    <template #footer>
      <el-button type="primary" @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>

  <!-- 产物预览（交易表 / 净值图） -->
  <el-dialog
    v-model="preview.visible"
    :title="preview.title"
    :width="preview.kind === 'trades' || preview.kind === 'equity' ? '1080px' : '860px'"
    destroy-on-close
    append-to-body
    @closed="revokePreview"
  >
    <div v-loading="preview.loading" class="preview-body">
      <template v-if="preview.kind === 'equity'">
        <v-chart
          v-if="preview.equitySeries.length"
          class="equity-chart"
          :option="equityChartOption"
          autoresize
        />
        <img
          v-else-if="preview.url"
          :src="preview.url"
          class="preview-img"
          alt="净值图"
        />
        <p v-else-if="!preview.loading" class="muted">暂无净值数据</p>
      </template>
      <img
        v-else-if="preview.kind === 'image' && preview.url"
        :src="preview.url"
        class="preview-img"
        alt=""
      />
      <template v-else-if="preview.kind === 'trades'">
        <div class="trades-meta">
          按日期从新到旧 · 共 {{ preview.tradeTotal }} 条
          <span v-if="preview.tradeTotal > preview.trades.length">
            （展示最近 {{ preview.trades.length }} 条）
          </span>
        </div>
        <el-table :data="preview.trades" stripe height="460" size="small">
          <el-table-column
            v-for="col in preview.tradeColumns"
            :key="col"
            :prop="col"
            :label="tradeColLabel(col)"
            :min-width="tradeColWidth(col)"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <span :class="col === 'nav_pnl' || col === 'day_ret' ? retClass(parsePct(row[col])) : ''">
                {{ formatTradeCell(col, row[col]) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <pre v-else-if="preview.text" class="result">{{ preview.text }}</pre>
      <p v-else-if="!preview.loading" class="muted">无法预览该文件</p>
    </div>
    <template #footer>
      <el-button @click="preview.visible = false">关闭</el-button>
      <el-button type="primary" :disabled="!preview.factorId || !preview.artifactId" @click="downloadCurrent">
        下载
      </el-button>
    </template>
  </el-dialog>

  <!-- 说明 -->
  <el-dialog
    v-model="guide.visible"
    :title="guide.title || '因子说明'"
    width="860px"
    top="6vh"
    destroy-on-close
    append-to-body
  >
    <div v-loading="guide.loading" class="guide-body">
      <div v-if="guide.html" class="markdown-body" v-html="guide.html" />
      <p v-else-if="!guide.loading" class="muted">暂无说明</p>
    </div>
    <template #footer>
      <el-button type="primary" @click="guide.visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import { use as echartsUse } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import {
  factorsApi,
  type FactorArtifact,
  type FactorBacktestLogic,
  type FactorItem,
} from '@/api/factors'

echartsUse([
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  CanvasRenderer,
])

const router = useRouter()

const visible = ref(false)
const loading = ref(false)
const loadError = ref('')
const factor = ref<FactorItem | null>(null)

const guide = reactive({
  visible: false,
  loading: false,
  title: '',
  html: '',
})

type EquityPoint = { date: string; equity: number; bench: number; position: number; n_pos: number }

const preview = reactive({
  visible: false,
  loading: false,
  title: '',
  kind: '' as string,
  url: '' as string,
  text: '' as string,
  factorId: '' as string,
  artifactId: '' as string,
  filename: '' as string,
  trades: [] as Record<string, string>[],
  tradeColumns: [] as string[],
  tradeTotal: 0,
  equitySeries: [] as EquityPoint[],
})

const CATEGORY_LABELS: Record<string, string> = {
  fundamental: '基本面',
  technical: '技术面',
  alternative: '另类',
  sentiment: '情绪',
  macro: '宏观',
  event: '事件',
}

const TRADE_LABELS: Record<string, string> = {
  date: '日期',
  action: '动作',
  side: '方向',
  code: '代码',
  name: '名称',
  code_name: '名称',
  buy_position: '买入仓位',
  nav_pnl: '净值盈亏',
  price: '价格',
  note: '备注',
  equity: '净值',
  day_ret: '当日收益',
  position_before: '仓位前',
  position_after: '仓位后',
  delta: '变动',
  entry_mode: '入场路径',
}

const dialogTitle = computed(() => {
  if (factor.value?.name) return `因子 · ${factor.value.name}`
  return '因子详情'
})

const metrics = computed<FactorBacktestLogic | null>(() => {
  const bt = factor.value?.backtest
  if (!bt?.available || !bt.logics) return null
  const primary = bt.primary_logic
  if (primary && bt.logics[primary]) return bt.logics[primary]
  const vals = Object.values(bt.logics)
  return vals.length ? vals[0] : null
})

const artifacts = computed(() => {
  const row = factor.value
  if (!row) return [] as FactorArtifact[]
  return (row.backtest?.artifacts || []).filter((a) => {
    if (!a.available) return false
    if (a.kind === 'json') return false
    if (a.kind === 'csv' && a.id.startsWith('daily')) return false
    return true
  })
})

/** dataZoom 过滤后，净值轴按可见数据范围留约 5% padding */
function equityYAxisPad(extent: { min: number; max: number }) {
  const lo = Number(extent.min)
  const hi = Number(extent.max)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { min: extent.min, max: extent.max }
  const span = hi - lo
  const pad = span > 0 ? span * 0.05 : Math.max(Math.abs(hi) * 0.05, 0.01)
  return { min: lo - pad, max: hi + pad }
}

const equityChartOption = computed<EChartsOption>(() => {
  const pts = preview.equitySeries
  const dates = pts.map((p) => p.date)
  const equity = pts.map((p) => p.equity)
  const bench = pts.map((p) => p.bench)
  const hasBench = pts.some((p) => Math.abs(p.bench - 1) > 1e-9)
  return {
    animation: false,
    grid: { left: 52, right: 24, top: 40, bottom: 72 },
    legend: { top: 4, data: hasBench ? ['策略净值', '基准'] : ['策略净值'] },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLabel: { hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      scale: true,
      min: (v: { min: number; max: number }) => equityYAxisPad(v).min,
      max: (v: { min: number; max: number }) => equityYAxisPad(v).max,
      axisLabel: { formatter: (v: number) => Number(v).toFixed(2) },
      splitLine: { lineStyle: { type: 'dashed', opacity: 0.45 } },
    },
    dataZoom: [
      { type: 'inside', filterMode: 'filter', zoomOnMouseWheel: true, moveOnMouseMove: true },
      { type: 'slider', height: 22, bottom: 8, filterMode: 'filter' },
    ],
    series: [
      {
        name: '策略净值',
        type: 'line' as const,
        data: equity,
        showSymbol: false,
        sampling: 'lttb' as const,
        lineStyle: { width: 2 },
      },
      ...(hasBench
        ? [
            {
              name: '基准',
              type: 'line' as const,
              data: bench,
              showSymbol: false,
              sampling: 'lttb' as const,
              lineStyle: { width: 1.5, type: 'dashed' as const },
            },
          ]
        : []),
    ],
  } as EChartsOption
})

function categoryLabel(c?: string) {
  if (!c) return '-'
  return CATEGORY_LABELS[c] || c
}

function num(v?: number | null) {
  if (v == null || Number.isNaN(Number(v))) return '-'
  return Number(v).toFixed(2)
}

function pct(v?: number | null) {
  if (v == null || Number.isNaN(Number(v))) return '-'
  return `${(Number(v) * 100).toFixed(1)}%`
}

function retClass(v?: number | null) {
  if (v == null || Number.isNaN(Number(v))) return ''
  if (Number(v) > 0) return 'pos'
  if (Number(v) < 0) return 'neg'
  return ''
}

function shortLabel(a: FactorArtifact): string {
  if (a.kind === 'image') {
    if (a.id.includes('share')) return '份额图'
    if (a.logic === 'continuous') return '净值·连续'
    if (a.logic === 'long_hold') return '净值·粘持'
    return '净值图'
  }
  if (a.id.includes('trades') || a.id === 'trades') {
    return a.logic === 'continuous' ? '交易·连续' : a.logic === 'long_hold' ? '交易·粘持' : '交易'
  }
  if (a.id.includes('daily')) return a.logic === 'continuous' ? '日度·连续' : '日度·粘持'
  return a.label
}

function isTradeArtifact(a: FactorArtifact) {
  return a.kind === 'csv' && (a.id.includes('trade') || a.id === 'trades' || a.label.includes('操作历史'))
}

function isEquityCurveArtifact(a: FactorArtifact): boolean {
  if (a.kind !== 'image') return false
  if (a.id.includes('share')) return false
  return a.id.includes('equity') || (a.label || '').includes('净值')
}

function tradeColLabel(col: string) {
  return TRADE_LABELS[col] || col
}

function tradeColWidth(col: string) {
  if (col === 'note') return 280
  if (col === 'date') return 110
  if (col === 'action' || col === 'side') return 80
  if (col === 'buy_position' || col === 'nav_pnl') return 100
  if (col === 'code') return 100
  if (col === 'name') return 110
  return 90
}

function formatTradeCell(col: string, raw: unknown) {
  if (raw == null || raw === '') return '-'
  if (col === 'buy_position') {
    const n = Number(raw)
    if (!Number.isNaN(n)) return n.toFixed(4)
    return String(raw)
  }
  if (col === 'day_ret' || col === 'nav_pnl') {
    const s = String(raw).trim()
    if (s.endsWith('%')) return s
    const n = Number(s)
    if (Number.isNaN(n)) return s
    return `${(n * 100).toFixed(2)}%`
  }
  return String(raw)
}

function parsePct(raw: unknown): number | null {
  if (raw == null || raw === '') return null
  const s = String(raw).trim()
  if (!s) return null
  if (s.endsWith('%')) {
    const n = Number(s.slice(0, -1))
    return Number.isNaN(n) ? null : n / 100
  }
  const n = Number(s)
  return Number.isNaN(n) ? null : n
}

function parseCsv(text: string): { headers: string[]; rows: Record<string, string>[] } {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter((l) => l.trim().length)
  if (!lines.length) return { headers: [], rows: [] }
  const split = (line: string) => {
    const out: string[] = []
    let cur = ''
    let inQ = false
    for (let i = 0; i < line.length; i++) {
      const ch = line[i]
      if (ch === '"') {
        if (inQ && line[i + 1] === '"') {
          cur += '"'
          i++
        } else {
          inQ = !inQ
        }
      } else if (ch === ',' && !inQ) {
        out.push(cur)
        cur = ''
      } else {
        cur += ch
      }
    }
    out.push(cur)
    return out
  }
  const headers = split(lines[0]).map((h) => h.trim())
  const rows = lines.slice(1).map((line) => {
    const cols = split(line)
    const row: Record<string, string> = {}
    headers.forEach((h, i) => {
      row[h] = (cols[i] ?? '').trim()
    })
    return row
  })
  return { headers, rows }
}

function tradeColumnsOf(headers: string[], rows: Record<string, string>[]): string[] {
  const preferred = [
    'date',
    'action',
    'code',
    'name',
    'buy_position',
    'nav_pnl',
    'side',
    'price',
    'position_before',
    'position_after',
    'delta',
    'day_ret',
    'note',
  ]
  const present = new Set([...headers, ...rows.flatMap((r) => Object.keys(r))])
  if (present.has('code_name') && !present.has('name')) {
    for (const r of rows) {
      if (!r.name && r.code_name) r.name = r.code_name
    }
    present.add('name')
    present.delete('code_name')
  }
  const ordered = preferred.filter((c) => present.has(c))
  const rest = [...present].filter((c) => !ordered.includes(c) && c !== 'equity' && c !== 'code_name')
  const cols = [...ordered, ...rest]
  if (present.has('equity')) cols.push('equity')
  return cols
}

function resolveDailyArtifactIdForEquity(row: FactorItem, equityArtifact: FactorArtifact): string | null {
  const arts = row.backtest?.artifacts || []
  const continuous =
    equityArtifact.logic === 'continuous' || equityArtifact.id.includes('continuous')
  if (continuous) {
    const c = arts.find(
      (a) =>
        a.available &&
        a.kind === 'csv' &&
        (a.id === 'daily_continuous' || (a.id.includes('daily') && a.id.includes('continuous'))),
    )
    if (c) return c.id
  }
  const longHold =
    equityArtifact.logic === 'long_hold' ||
    equityArtifact.id === 'equity_curve' ||
    equityArtifact.id.includes('long_hold')
  if (longHold) {
    const lh = arts.find((a) => a.available && a.id === 'daily_long_hold')
    if (lh) return lh.id
    const d = arts.find((a) => a.available && a.id === 'daily')
    if (d) return d.id
  }
  const anyDaily = arts.find(
    (a) =>
      a.available &&
      a.kind === 'csv' &&
      (a.id.startsWith('daily') || a.id.includes('backtest') || (a.label || '').includes('日度')),
  )
  return anyDaily?.id || null
}

function parseEquitySeries(text: string): EquityPoint[] {
  const { rows } = parseCsv(text)
  const dated = rows
    .map((r) => ({
      date: String(r.date || '').slice(0, 10),
      equity: Number(r.equity),
      bench_ret: Number(r.bench_ret),
      position: Number(r.position),
      n_pos: Number(r.n_pos),
    }))
    .filter((r) => r.date && Number.isFinite(r.equity))
    .sort((a, b) => a.date.localeCompare(b.date))
  let bench = 1.0
  return dated.map((r) => {
    const br = Number.isFinite(r.bench_ret) ? r.bench_ret : 0
    bench *= 1 + br
    return {
      date: r.date,
      equity: r.equity,
      bench,
      position: Number.isFinite(r.position) ? r.position : 0,
      n_pos: Number.isFinite(r.n_pos) ? r.n_pos : 0,
    }
  })
}

async function open(factorId: string) {
  const id = String(factorId || '').trim()
  if (!id) return
  visible.value = true
  loading.value = true
  loadError.value = ''
  factor.value = null
  try {
    let item = await factorsApi.get(id)
    // get 若未带完整 backtest，再拉摘要
    if (!item.backtest?.available) {
      try {
        const bt = await factorsApi.backtest(id)
        item = { ...item, backtest: bt }
      } catch {
        /* 已 RETIRED / 无产物时保持 get 结果 */
      }
    }
    factor.value = item
  } catch (e: any) {
    loadError.value = e?.message || '加载因子失败（可能已下线或不在 builtins）'
    ElMessage.warning(loadError.value)
  } finally {
    loading.value = false
  }
}

function onClosed() {
  factor.value = null
  loadError.value = ''
}

function goFactorsPage() {
  const id = factor.value?.factor_id
  if (!id) return
  router.push({ path: '/factors', query: { factor_id: id } })
}

function revokePreview() {
  if (preview.url) {
    URL.revokeObjectURL(preview.url)
    preview.url = ''
  }
  preview.text = ''
  preview.kind = ''
  preview.factorId = ''
  preview.artifactId = ''
  preview.trades = []
  preview.tradeColumns = []
  preview.tradeTotal = 0
  preview.equitySeries = []
}

async function openArtifact(a: FactorArtifact) {
  const row = factor.value
  if (!row) return
  revokePreview()
  preview.visible = true
  preview.loading = true
  preview.title = `${row.name} · ${a.label}`
  preview.kind = a.kind || ''
  preview.factorId = row.factor_id
  preview.artifactId = a.id
  preview.filename = a.id
  try {
    const blob = await factorsApi.artifactBlob(row.factor_id, a.id)
    if (a.kind === 'image' && isEquityCurveArtifact(a)) {
      preview.kind = 'equity'
      preview.url = URL.createObjectURL(blob)
      preview.equitySeries = []
      const dailyId = resolveDailyArtifactIdForEquity(row, a)
      if (dailyId) {
        try {
          const dailyBlob = await factorsApi.artifactBlob(row.factor_id, dailyId)
          preview.equitySeries = parseEquitySeries(await dailyBlob.text())
        } catch {
          preview.equitySeries = []
        }
      }
      if (!preview.equitySeries.length) {
        ElMessage.warning('未找到日度回测 CSV，已回退静态净值图')
      }
    } else if (a.kind === 'image') {
      preview.url = URL.createObjectURL(blob)
    } else {
      const text = await blob.text()
      if (isTradeArtifact(a)) {
        const { headers, rows } = parseCsv(text)
        const sorted = [...rows].sort((x, y) => String(y.date || '').localeCompare(String(x.date || '')))
        const maxShow = 300
        preview.kind = 'trades'
        preview.tradeTotal = sorted.length
        preview.trades = sorted.slice(0, maxShow)
        preview.tradeColumns = tradeColumnsOf(headers, sorted)
      } else if (a.kind === 'json') {
        try {
          preview.text = JSON.stringify(JSON.parse(text), null, 2)
        } catch {
          preview.text = text
        }
      } else {
        const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter((l) => l.length)
        if (lines.length <= 1) {
          preview.text = text
        } else {
          const head = lines[0]
          const body = lines.slice(1)
          const tail = body.slice(-120)
          preview.text =
            `${head}\n` +
            (body.length > tail.length ? `…(更早 ${body.length - tail.length} 行省略)\n` : '') +
            tail.join('\n')
        }
      }
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '打开产物失败')
    preview.visible = false
  } finally {
    preview.loading = false
  }
}

async function openGuide() {
  const row = factor.value
  if (!row) return
  guide.visible = true
  guide.loading = true
  guide.title = `${row.name} · 说明`
  guide.html = ''
  try {
    const data = await factorsApi.guide(row.factor_id)
    guide.title = data.title || guide.title
    try {
      guide.html = String(marked.parse(data.content || ''))
    } catch {
      guide.html = data.content || ''
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '加载说明失败')
    guide.visible = false
  } finally {
    guide.loading = false
  }
}

async function downloadCurrent() {
  if (!preview.factorId || !preview.artifactId) return
  try {
    await factorsApi.downloadArtifact(preview.factorId, preview.artifactId, preview.filename)
  } catch (e: any) {
    ElMessage.error(e?.message || '下载失败')
  }
}

defineExpose({ open })
</script>

<style scoped>
.panel-body { min-height: 160px; }
.meta-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.meta-main .name { font-size: 18px; font-weight: 600; line-height: 1.3; }
.id-line {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.id-line code {
  font-size: 12px;
  background: var(--el-fill-color-light);
  padding: 2px 6px;
  border-radius: 4px;
}
.meta-side { text-align: right; }
.meta-side .cat { font-size: 13px; color: var(--el-text-color-regular); margin-bottom: 6px; }
.tags { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
.metrics { margin-bottom: 12px; }
.desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-bottom: 12px;
  max-height: 72px;
  overflow: auto;
}
.actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  padding-top: 4px;
}
.actions-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-right: 4px;
}
.muted { color: var(--el-text-color-secondary); }
.range { font-size: 12px; }
.pos { color: var(--el-color-success); font-variant-numeric: tabular-nums; }
.neg { color: var(--el-color-danger); font-variant-numeric: tabular-nums; }
.mdd { color: var(--el-color-warning); font-variant-numeric: tabular-nums; }
.preview-body { min-height: 120px; }
.preview-img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
.equity-chart {
  width: 100%;
  height: min(52vh, 420px);
  min-height: 280px;
}
.trades-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}
.result {
  white-space: pre-wrap;
  font-size: 12px;
  max-height: 420px;
  overflow: auto;
  margin: 0;
}
.guide-body { min-height: 120px; max-height: 70vh; overflow: auto; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) { margin-top: 1em; }
.markdown-body :deep(p) { line-height: 1.6; }
.markdown-body :deep(pre) {
  background: var(--el-fill-color-light);
  padding: 10px;
  overflow: auto;
  border-radius: 4px;
}
</style>
