<template>
  <div class="factors-page">
    <div class="page-header">
      <h1 class="page-title">因子列表 Factors</h1>
      <p class="page-description">内置/自定义因子目录；可计算最新信号，并查看回测指标与净值图</p>
    </div>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="factor_id" label="ID" width="140" />
        <el-table-column prop="name" label="名称" width="120" />
        <el-table-column prop="latest_signal" label="最新信号" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.latest_signal" :type="signalType(row.latest_signal)" size="small">
              {{ row.latest_signal }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="latest_value" label="值" width="80">
          <template #default="{ row }">
            {{ row.latest_value != null ? Number(row.latest_value).toFixed(2) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="回测摘要" min-width="280">
          <template #default="{ row }">
            <div v-if="row.backtest?.available" class="bt-summary">
              <div
                v-for="(m, logic) in row.backtest.logics"
                :key="String(logic)"
                class="bt-line"
              >
                <el-tag size="small" effect="plain" class="bt-logic">{{ logic }}</el-tag>
                <span>累计 {{ pct(m.total_return) }}</span>
                <span>夏普 {{ num(m.sharpe) }}</span>
                <span>回撤 {{ pct(m.max_drawdown) }}</span>
              </div>
              <div v-if="row.backtest.updated_at" class="bt-meta">
                截至 {{ formatRange(row.backtest) }} · 更新 {{ shortTime(row.backtest.updated_at) }}
              </div>
            </div>
            <span v-else class="muted">暂无回测</span>
          </template>
        </el-table-column>
        <el-table-column label="产物" min-width="220">
          <template #default="{ row }">
            <template v-if="availableArtifacts(row).length">
              <el-button
                v-for="a in availableArtifacts(row)"
                :key="a.id"
                link
                type="primary"
                @click="openArtifact(row, a)"
              >
                {{ shortLabel(a) }}
              </el-button>
            </template>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openGuide(row)">说明</el-button>
            <el-button link type="primary" :loading="computing === row.factor_id" @click="compute(row)">
              计算信号
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="lastResult" shadow="never" style="margin-top: 12px">
      <template #header>最近计算结果</template>
      <pre class="result">{{ pretty(lastResult) }}</pre>
    </el-card>

    <el-dialog
      v-model="guide.visible"
      :title="guide.title || '因子说明'"
      width="720px"
      destroy-on-close
    >
      <div v-loading="guide.loading" class="guide-body">
        <div v-if="guide.html" class="markdown-body" v-html="guide.html" />
        <p v-else-if="!guide.loading" class="muted">暂无说明</p>
      </div>
      <template #footer>
        <el-button type="primary" @click="guide.visible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="preview.visible"
      :title="preview.title"
      :width="preview.kind === 'trades' ? '960px' : '860px'"
      destroy-on-close
      @closed="revokePreview"
    >
      <div v-loading="preview.loading" class="preview-body">
        <img v-if="preview.kind === 'image' && preview.url" :src="preview.url" class="preview-img" alt="" />
        <pre v-else-if="preview.kind === 'json' && preview.text" class="result">{{ preview.text }}</pre>
        <template v-else-if="preview.kind === 'trades'">
          <div class="trades-meta">
            按日期从新到旧 · 共 {{ preview.tradeTotal }} 条
            <span v-if="preview.tradeTotal > preview.trades.length">（展示最近 {{ preview.trades.length }} 条）</span>
          </div>
          <el-table :data="preview.trades" stripe height="480" size="small">
            <el-table-column
              v-for="col in preview.tradeColumns"
              :key="col"
              :prop="col"
              :label="tradeColLabel(col)"
              :min-width="tradeColWidth(col)"
              show-overflow-tooltip
            >
              <template #default="{ row }">
                {{ formatTradeCell(col, row[col]) }}
              </template>
            </el-table-column>
          </el-table>
        </template>
        <pre v-else-if="preview.kind === 'csv' && preview.text" class="result">{{ preview.text }}</pre>
        <p v-else-if="!preview.loading" class="muted">无法预览该文件</p>
      </div>
      <template #footer>
        <el-button @click="preview.visible = false">关闭</el-button>
        <el-button type="primary" :disabled="!preview.factorId" @click="downloadCurrent">下载</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import {
  factorsApi,
  type FactorArtifact,
  type FactorBacktest,
  type FactorItem,
} from '@/api/factors'

const loading = ref(false)
const items = ref<FactorItem[]>([])
const computing = ref('')
const lastResult = ref<any>(null)

const guide = reactive({
  visible: false,
  loading: false,
  title: '',
  html: '',
})

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
})

const TRADE_LABELS: Record<string, string> = {
  date: '日期',
  action: '动作',
  side: '方向',
  logic: '逻辑',
  position_before: '仓位前',
  position_after: '仓位后',
  position_from: '仓位前',
  position_to: '仓位后',
  delta: '变动',
  equity: '净值',
  day_ret: '当日收益',
  close: '收盘',
  factor: '因子值',
  best_universe: '宇宙',
  universe_exec: '交易宇宙',
  pos_nt: '国家队仓',
  pos_dip: '抄底仓',
  confirm_nt: '确认度',
  note: '备注',
  state: '状态',
  share_z: 'share_z',
  era: '时代',
}

const signalType = (s: string) => (s === 'buy' ? 'success' : s === 'sell' ? 'danger' : 'info')
const pretty = (o: any) => JSON.stringify(o, null, 2)
const num = (v?: number) => (v == null || Number.isNaN(v) ? '-' : Number(v).toFixed(2))
const pct = (v?: number) => {
  if (v == null || Number.isNaN(v)) return '-'
  return `${(Number(v) * 100).toFixed(1)}%`
}

function tradeColLabel(col: string) {
  return TRADE_LABELS[col] || col
}

function tradeColWidth(col: string) {
  if (col === 'note') return 220
  if (col === 'date') return 110
  if (col === 'action' || col === 'side') return 80
  if (col === 'equity' || col === 'day_ret') return 90
  if (col === 'best_universe' || col === 'universe_exec' || col === 'era' || col === 'logic') return 90
  return 90
}

/** 操作历史单元格：当日收益显示为百分之几（兼容小数或已带 % 的字符串） */
function formatTradeCell(col: string, raw: unknown) {
  if (raw == null || raw === '') return '-'
  if (col !== 'day_ret') return String(raw)
  const s = String(raw).trim()
  if (s.endsWith('%')) return s
  const n = Number(s)
  if (Number.isNaN(n)) return s
  return `${(n * 100).toFixed(2)}%`
}

function isTradeArtifact(a: FactorArtifact) {
  return a.kind === 'csv' && (a.id.includes('trade') || a.id === 'trades' || a.label.includes('操作历史'))
}

/** Simple CSV parse (handles quoted fields). */
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

function availableArtifacts(row: FactorItem): FactorArtifact[] {
  return (row.backtest?.artifacts || []).filter((a) => {
    if (!a.available) return false
    // 列表入口：图 / 摘要 / 交易；日度大 CSV 仍可通过 API 下载
    if (a.kind === 'csv' && a.id.startsWith('daily')) return false
    return true
  })
}

function shortLabel(a: FactorArtifact): string {
  if (a.kind === 'image') {
    if (a.id.includes('share')) return '份额图'
    if (a.logic === 'continuous') return '净值·连续'
    if (a.logic === 'long_hold') return '净值·粘持'
    return '净值图'
  }
  if (a.kind === 'json') return '摘要'
  if (a.id.includes('trades') || a.id === 'trades') {
    return a.logic === 'continuous' ? '交易·连续' : a.logic === 'long_hold' ? '交易·粘持' : '交易'
  }
  if (a.id.includes('daily')) return a.logic === 'continuous' ? '日度·连续' : '日度·粘持'
  return a.label
}

function formatRange(bt: FactorBacktest): string {
  const primary = bt.primary_logic || 'long_hold'
  const m = bt.logics?.[primary] || Object.values(bt.logics || {})[0]
  if (!m?.start || !m?.end) return '-'
  return `${m.start} ~ ${m.end}`
}

function shortTime(iso?: string | null): string {
  if (!iso) return '-'
  return iso.replace('T', ' ').slice(0, 16)
}

async function load() {
  loading.value = true
  try {
    const data = await factorsApi.list()
    items.value = data.items || []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function compute(row: FactorItem) {
  computing.value = row.factor_id
  try {
    lastResult.value = await factorsApi.compute(row.factor_id)
    ElMessage.success(`${row.name}: ${lastResult.value?.signal}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message || '计算失败')
  } finally {
    computing.value = ''
  }
}

function renderMarkdown(content: string) {
  try {
    return String(marked.parse(content || ''))
  } catch (e) {
    console.error('Markdown渲染失败:', e)
    return content
  }
}

async function openGuide(row: FactorItem) {
  guide.visible = true
  guide.loading = true
  guide.title = `${row.name} · 说明`
  guide.html = ''
  try {
    const data = await factorsApi.guide(row.factor_id)
    guide.title = data.title || guide.title
    guide.html = renderMarkdown(data.content || '')
  } catch (e: any) {
    ElMessage.error(e?.message || '加载说明失败')
    guide.visible = false
  } finally {
    guide.loading = false
  }
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
}

async function openArtifact(row: FactorItem, a: FactorArtifact) {
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
    if (a.kind === 'image') {
      preview.url = URL.createObjectURL(blob)
    } else {
      const text = await blob.text()
      if (a.kind === 'json') {
        try {
          preview.text = JSON.stringify(JSON.parse(text), null, 2)
        } catch {
          preview.text = text
        }
      } else if (isTradeArtifact(a)) {
        const { headers, rows } = parseCsv(text)
        // 最新在上
        const sorted = [...rows].sort((x, y) => String(y.date || '').localeCompare(String(x.date || '')))
        const maxShow = 300
        preview.kind = 'trades'
        preview.tradeTotal = sorted.length
        preview.trades = sorted.slice(0, maxShow)
        preview.tradeColumns = headers.length
          ? headers
          : Object.keys(sorted[0] || {})
      } else {
        // 其它 CSV：优先展示末尾（更新近）
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

async function downloadCurrent() {
  if (!preview.factorId || !preview.artifactId) return
  try {
    await factorsApi.downloadArtifact(preview.factorId, preview.artifactId, preview.filename)
  } catch (e: any) {
    ElMessage.error(e?.message || '下载失败')
  }
}

onMounted(load)
</script>

<style scoped>
.page-header { margin-bottom: 16px; }
.page-title { margin: 0 0 6px; font-size: 22px; }
.page-description { margin: 0; color: var(--el-text-color-secondary); }
.result { white-space: pre-wrap; font-size: 12px; max-height: 420px; overflow: auto; margin: 0; }
.muted { color: var(--el-text-color-secondary); }
.bt-summary { display: flex; flex-direction: column; gap: 4px; }
.bt-line { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12px; }
.bt-logic { margin-right: 2px; }
.bt-meta { font-size: 11px; color: var(--el-text-color-secondary); }
.preview-body { min-height: 120px; }
.preview-img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
.trades-meta { margin-bottom: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.guide-body { min-height: 120px; max-height: 70vh; overflow: auto; padding-right: 4px; }
.markdown-body { font-size: 14px; line-height: 1.7; color: var(--el-text-color-primary); }
.markdown-body :deep(h1) { font-size: 20px; margin: 0 0 12px; }
.markdown-body :deep(h2) { font-size: 16px; margin: 18px 0 8px; }
.markdown-body :deep(h3) { font-size: 14px; margin: 14px 0 6px; }
.markdown-body :deep(p) { margin: 0 0 10px; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 1.4em; margin: 0 0 10px; }
.markdown-body :deep(li) { margin: 4px 0; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 10px 0 14px; font-size: 13px; }
.markdown-body :deep(th), .markdown-body :deep(td) {
  border: 1px solid var(--el-border-color);
  padding: 6px 8px;
  text-align: left;
}
.markdown-body :deep(th) { background: var(--el-fill-color-light); }
.markdown-body :deep(blockquote) {
  margin: 8px 0;
  padding: 6px 12px;
  border-left: 3px solid var(--el-color-primary);
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
}
.markdown-body :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--el-fill-color);
}
</style>
