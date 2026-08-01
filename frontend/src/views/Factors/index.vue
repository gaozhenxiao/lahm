<template>
  <div class="factors-page">
    <div class="page-header">
      <h1 class="page-title">因子列表 Factors</h1>
      <p class="page-description"># 为生成顺序；点击表头可按指标或序号排序，点「说明」看完整介绍</p>
    </div>

    <el-card shadow="never">
      <el-table
        :data="items"
        v-loading="loading"
        stripe
        :default-sort="{ prop: 'bt_sharpe', order: 'descending' }"
      >
        <el-table-column
          prop="gen_seq"
          label="#"
          width="64"
          sortable
          :sort-method="sortNum('gen_seq')"
        >
          <template #default="{ row }">
            <span class="gen-seq">{{ row.gen_seq }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="140" sortable />
        <el-table-column prop="category" label="分类" width="110" sortable>
          <template #default="{ row }">
            {{ categoryLabel(row.category) }}
          </template>
        </el-table-column>
        <el-table-column prop="bt_total_return" label="累计收益" width="110" sortable :sort-method="sortNum('bt_total_return')">
          <template #default="{ row }">
            <span :class="retClass(row.bt_total_return)">{{ pct(row.bt_total_return) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="bt_cagr" label="CAGR" width="100" sortable :sort-method="sortNum('bt_cagr')">
          <template #default="{ row }">
            <span :class="retClass(row.bt_cagr)">{{ pct(row.bt_cagr) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="bt_sharpe" label="Sharpe" width="100" sortable :sort-method="sortNum('bt_sharpe')">
          <template #default="{ row }">
            <span :class="retClass(row.bt_sharpe)">{{ num(row.bt_sharpe) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="bt_mdd" label="最大回撤" width="110" sortable :sort-method="sortNum('bt_mdd')">
          <template #default="{ row }">
            <span class="mdd">{{ pct(row.bt_mdd) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="回测区间" min-width="160">
          <template #default="{ row }">
            <span v-if="row.bt_start && row.bt_end" class="range">{{ row.bt_start }} ~ {{ row.bt_end }}</span>
            <span v-else class="muted">暂无回测</span>
          </template>
        </el-table-column>
        <el-table-column label="产物" min-width="200">
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
        <el-table-column label="操作" width="160" fixed="right">
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
      width="860px"
      top="6vh"
      destroy-on-close
      class="guide-dialog"
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
      :width="preview.kind === 'trades' ? '1080px' : '860px'"
      destroy-on-close
      @closed="revokePreview"
    >
      <div v-loading="preview.loading" class="preview-body">
        <img v-if="preview.kind === 'image' && preview.url" :src="preview.url" class="preview-img" alt="" />
        <pre v-else-if="preview.kind === 'json' && preview.text" class="result">{{ preview.text }}</pre>
        <template v-else-if="preview.kind === 'trades'">
          <el-tabs v-model="preview.tradeTab" class="trades-tabs">
            <el-tab-pane label="操作流水" name="flow">
              <div class="trades-meta">
                按日期从新到旧 · 共 {{ preview.tradeTotal }} 条
                <span v-if="preview.tradeTotal > preview.trades.length">（展示最近 {{ preview.trades.length }} 条）</span>
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
            </el-tab-pane>
            <el-tab-pane label="净值贡献" name="contrib">
              <div class="trades-meta contrib-toolbar">
                <el-radio-group v-model="preview.contribMode" size="small">
                  <el-radio-button label="symbol">按标的</el-radio-button>
                  <el-radio-button label="leg">按笔明细</el-radio-button>
                </el-radio-group>
                <span>
                  已平仓 {{ preview.contribLegs.length }} 笔 ·
                  累计净值贡献 {{ fmtPct(preview.contribTotalNav) }}
                </span>
              </div>
              <el-table
                v-if="preview.contribMode === 'symbol'"
                :data="preview.contribSymbols"
                stripe
                height="460"
                size="small"
                :default-sort="{ prop: 'nav_pnl_num', order: 'descending' }"
              >
                <el-table-column prop="code" label="代码" min-width="100" />
                <el-table-column prop="name" label="名称" min-width="100" />
                <el-table-column prop="n_legs" label="笔数" width="70" align="right" />
                <el-table-column prop="first_buy" label="首次买入" width="110" />
                <el-table-column prop="last_sell" label="末次卖出" width="110" />
                <el-table-column prop="avg_hold_days" label="平均持有(天)" width="110" align="right" />
                <el-table-column prop="win_rate" label="胜率" width="80" align="right" />
                <el-table-column prop="nav_pnl" label="累计净值贡献" min-width="120" align="right">
                  <template #default="{ row }">
                    <span :class="retClass(row.nav_pnl_num)">{{ row.nav_pnl }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="share" label="贡献占比" width="90" align="right">
                  <template #default="{ row }">
                    <span :class="retClass(row.nav_pnl_num)">{{ row.share }}</span>
                  </template>
                </el-table-column>
              </el-table>
              <el-table
                v-else
                :data="preview.contribLegs"
                stripe
                height="460"
                size="small"
              >
                <el-table-column prop="code" label="代码" min-width="100" />
                <el-table-column prop="name" label="名称" min-width="100" />
                <el-table-column prop="buy_date" label="买入日" width="110" />
                <el-table-column prop="sell_date" label="卖出日" width="110" />
                <el-table-column prop="hold_days" label="持有(天)" width="90" align="right" />
                <el-table-column prop="buy_price" label="买入价" width="90" align="right" />
                <el-table-column prop="sell_price" label="卖出价" width="90" align="right" />
                <el-table-column prop="buy_position" label="仓位" width="80" align="right" />
                <el-table-column prop="stock_ret" label="标的收益" width="90" align="right">
                  <template #default="{ row }">
                    <span :class="retClass(parsePct(row.stock_ret))">{{ row.stock_ret || '-' }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="nav_pnl" label="净值贡献" width="100" align="right">
                  <template #default="{ row }">
                    <span :class="retClass(row.nav_pnl_num)">{{ row.nav_pnl }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="share" label="贡献占比" width="90" align="right">
                  <template #default="{ row }">
                    <span :class="retClass(row.nav_pnl_num)">{{ row.share }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
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
  type FactorBacktestLogic,
  type FactorItem,
} from '@/api/factors'

type FactorRow = FactorItem & {
  gen_seq: number
  bt_total_return: number | null
  bt_cagr: number | null
  bt_sharpe: number | null
  bt_mdd: number | null
  bt_start: string | null
  bt_end: string | null
  bt_logic: string | null
}

const loading = ref(false)
const items = ref<FactorRow[]>([])
const computing = ref('')
const lastResult = ref<any>(null)

const guide = reactive({
  visible: false,
  loading: false,
  title: '',
  html: '',
})

type ContribLeg = {
  code: string
  name: string
  buy_date: string
  sell_date: string
  hold_days: number
  buy_price: string
  sell_price: string
  buy_position: string
  stock_ret: string
  nav_pnl: string
  nav_pnl_num: number
  share: string
}

type ContribSymbol = {
  code: string
  name: string
  n_legs: number
  first_buy: string
  last_sell: string
  avg_hold_days: number
  win_rate: string
  nav_pnl: string
  nav_pnl_num: number
  share: string
}

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
  tradeTab: 'flow' as 'flow' | 'contrib',
  contribMode: 'symbol' as 'symbol' | 'leg',
  contribLegs: [] as ContribLeg[],
  contribSymbols: [] as ContribSymbol[],
  contribTotalNav: 0,
})

const TRADE_LABELS: Record<string, string> = {
  date: '日期',
  action: '动作',
  side: '方向',
  code: '代码',
  name: '名称',
  code_name: '名称',
  buy_position: '买入仓位',
  nav_pnl: '净值盈亏',
  entry_mode: '入场路径',
  surprise_tier: '超预期档',
  event_pub: '公告日',
  days_after_announce: '公告后天数',
  pre_run: '公告前涨幅',
  lt_run: '两年涨幅',
  pullback: '回撤',
  price: '价格',
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

const CATEGORY_LABELS: Record<string, string> = {
  fundamental: '基本面',
  technical: '技术面',
  alternative: '另类',
  sentiment: '情绪',
  macro: '宏观',
  event: '事件',
}

const pretty = (o: any) => JSON.stringify(o, null, 2)
const num = (v?: number | null) => (v == null || Number.isNaN(Number(v)) ? '-' : Number(v).toFixed(2))
const pct = (v?: number | null) => {
  if (v == null || Number.isNaN(Number(v))) return '-'
  return `${(Number(v) * 100).toFixed(1)}%`
}

function categoryLabel(c?: string) {
  if (!c) return '-'
  return CATEGORY_LABELS[c] || c
}

function retClass(v?: number | null) {
  if (v == null || Number.isNaN(Number(v))) return ''
  if (Number(v) > 0) return 'pos'
  if (Number(v) < 0) return 'neg'
  return ''
}

/** null 沉底；数值按字段比较 */
function sortNum(key: keyof FactorRow) {
  return (a: FactorRow, b: FactorRow) => {
    const av = a[key]
    const bv = b[key]
    const an = typeof av === 'number' && !Number.isNaN(av)
    const bn = typeof bv === 'number' && !Number.isNaN(bv)
    if (!an && !bn) return 0
    if (!an) return 1
    if (!bn) return -1
    return (av as number) - (bv as number)
  }
}

function primaryMetrics(row: FactorItem): FactorBacktestLogic | null {
  const bt = row.backtest
  if (!bt?.available || !bt.logics) return null
  const primary = bt.primary_logic
  if (primary && bt.logics[primary]) return bt.logics[primary]
  const vals = Object.values(bt.logics)
  return vals.length ? vals[0] : null
}

function enrichRow(row: FactorItem, gen_seq: number): FactorRow {
  const m = primaryMetrics(row)
  return {
    ...row,
    gen_seq,
    bt_total_return: m?.total_return ?? null,
    bt_cagr: m?.annual_return ?? null,
    bt_sharpe: m?.sharpe ?? null,
    bt_mdd: m?.max_drawdown ?? null,
    bt_start: m?.start ?? null,
    bt_end: m?.end ?? null,
    bt_logic: m?.position_logic || row.backtest?.primary_logic || null,
  }
}

function tradeColLabel(col: string) {
  return TRADE_LABELS[col] || col
}

function tradeColWidth(col: string) {
  if (col === 'note') return 320
  if (col === 'date' || col === 'event_pub') return 110
  if (col === 'action' || col === 'side') return 80
  if (col === 'buy_position' || col === 'nav_pnl') return 100
  if (col === 'entry_mode') return 110
  if (col === 'code') return 100
  if (col === 'name' || col === 'code_name') return 110
  if (col === 'equity' || col === 'day_ret' || col === 'price') return 90
  if (col === 'best_universe' || col === 'universe_exec' || col === 'era' || col === 'logic') return 90
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

function fmtPct(n: number) {
  return `${(n * 100).toFixed(2)}%`
}

const ENTRY_NOTE_RE = /[；;]?\s*买入\d{4}-\d{2}-\d{2}\s*成本价[\d.]+/g

function withEntryNote(note: string, entryDate: string, cost: number) {
  const base = String(note || '').replace(ENTRY_NOTE_RE, '').replace(/[；;]\s*$/, '').trim()
  const extra = `买入${entryDate} 成本价${cost.toFixed(4)}`
  return base ? `${base}；${extra}` : extra
}

/** 补齐买入仓位 / 卖出净值盈亏 / 卖出备注中的买入日与成本价 */
function enrichTrades(rows: Record<string, string>[]): Record<string, string>[] {
  if (!rows.length) return rows
  const chrono = [...rows].sort((a, b) => {
    const d = String(a.date || '').localeCompare(String(b.date || ''))
    if (d !== 0) return d
    const rank = (x: string) => (x.includes('开') || x.includes('加') ? 0 : 1)
    return rank(String(a.action || '')) - rank(String(b.action || ''))
  })
  const hasPos = chrono.some((r) => r.position_after != null && r.position_after !== '')
  const hasCode = chrono.some((r) => r.code)

  if (hasPos) {
    let entryEq: number | null = null
    let entryPos: number | null = null
    let entryDate: string | null = null
    let entryCost: number | null = null
    for (const r of chrono) {
      const action = String(r.action || '')
      const equity = Number(r.equity)
      const pAfter = Number(r.position_after)
      const pBefore = Number(r.position_before)
      const delta = Number(r.delta)
      const close = Number(r.close)
      const price = Number(r.price)
      const cost = !Number.isNaN(close) ? close : price
      const dt = String(r.date || '').slice(0, 10)
      if (action.includes('开') || action.includes('加')) {
        const pos = !Number.isNaN(pAfter) ? pAfter : !Number.isNaN(delta) ? delta : null
        if (pos != null) r.buy_position = String(Number(pos.toFixed(4)))
        if (action.includes('开') || entryEq == null) {
          if (!Number.isNaN(equity)) entryEq = equity
          entryPos = pos
          entryDate = dt
          entryCost = !Number.isNaN(cost) ? cost : null
        }
        if (!r.nav_pnl) r.nav_pnl = ''
      } else if (action.includes('清') || action.includes('减')) {
        const pos = entryPos != null ? entryPos : !Number.isNaN(pBefore) ? pBefore : null
        if (pos != null) r.buy_position = String(Number(pos.toFixed(4)))
        if (action.includes('清') && entryEq != null && entryEq > 0 && !Number.isNaN(equity)) {
          if (!r.nav_pnl) r.nav_pnl = fmtPct(equity / entryEq - 1)
        }
        if (action.includes('清') && entryDate && entryCost != null) {
          r.note = withEntryNote(r.note || '', entryDate, entryCost)
        }
        if (action.includes('清')) {
          entryEq = null
          entryPos = null
          entryDate = null
          entryCost = null
        }
      }
    }
  } else if (hasCode) {
    const stacks: Record<string, { price: number; w: number; date: string }[]> = {}
    const defaultW = 0.125
    for (const r of chrono) {
      const action = String(r.action || '')
      const code = String(r.code || '')
      const price = Number(r.price)
      const existingW = Number(r.buy_position)
      const w = !Number.isNaN(existingW) && existingW > 0 ? existingW : defaultW
      const dt = String(r.date || '').slice(0, 10)
      if (action.includes('开')) {
        r.buy_position = String(Number(w.toFixed(4)))
        if (!r.nav_pnl) r.nav_pnl = ''
        if (!stacks[code]) stacks[code] = []
        stacks[code].push({ price: Number.isNaN(price) ? 0 : price, w, date: dt })
      } else if (action.includes('清')) {
        const ent = (stacks[code] || []).shift()
        const ww = ent?.w ?? w
        r.buy_position = String(Number(ww.toFixed(4)))
        if (!r.nav_pnl) {
          let ret = parsePct(r.day_ret)
          if (ret == null && ent && ent.price > 0 && !Number.isNaN(price)) {
            ret = price / ent.price - 1
          }
          if (ret != null) r.nav_pnl = fmtPct(ret * ww)
        }
        if (ent?.date && ent.price > 0) {
          r.note = withEntryNote(r.note || '', ent.date, ent.price)
        }
      }
    }
  }

  return rows.map((r) => {
    if (r.buy_position == null) r.buy_position = ''
    if (r.nav_pnl == null) r.nav_pnl = ''
    return r
  })
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
    'close',
    'note',
  ]
  const present = new Set([
    ...headers,
    ...rows.flatMap((r) => Object.keys(r)),
  ])
  // name / code_name 统一成 name 列展示
  if (present.has('code_name') && !present.has('name')) {
    for (const r of rows) {
      if (!r.name && r.code_name) r.name = r.code_name
    }
    present.add('name')
    present.delete('code_name')
  }
  const ordered = preferred.filter((c) => present.has(c))
  // equity 固定最后一列（与 CSV 一致）
  const rest = [...present].filter(
    (c) => !ordered.includes(c) && c !== 'equity' && c !== 'code_name',
  )
  const cols = [...ordered, ...rest]
  if (present.has('equity')) cols.push('equity')
  return cols
}

function isTradeArtifact(a: FactorArtifact) {
  return a.kind === 'csv' && (a.id.includes('trade') || a.id === 'trades' || a.label.includes('操作历史'))
}

function calendarHoldDays(buy: string, sell: string): number {
  const a = Date.parse(buy)
  const b = Date.parse(sell)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0
  return Math.max(0, Math.round((b - a) / 86400000))
}

/** 从操作流水配对开平仓，生成净值贡献明细与按标的汇总 */
function buildNavContribution(rows: Record<string, string>[]): {
  legs: ContribLeg[]
  symbols: ContribSymbol[]
  totalNav: number
} {
  const chrono = [...rows].sort((a, b) => {
    const d = String(a.date || '').localeCompare(String(b.date || ''))
    if (d !== 0) return d
    const rank = (x: string) => (x.includes('开') || x.includes('加') ? 0 : 1)
    return rank(String(a.action || '')) - rank(String(b.action || ''))
  })
  const stacks: Record<string, { date: string; price: number; w: number; name: string }[]> = {}
  const rawLegs: Omit<ContribLeg, 'share'>[] = []

  for (const r of chrono) {
    const action = String(r.action || '')
    const code = String(r.code || '').trim()
    if (!code) continue
    const name = String(r.name || r.code_name || '').trim()
    const dt = String(r.date || '').slice(0, 10)
    const price = Number(r.price)
    const wRaw = Number(r.buy_position)
    const w = !Number.isNaN(wRaw) && wRaw > 0 ? wRaw : 0.125
    if (action.includes('开')) {
      if (!stacks[code]) stacks[code] = []
      stacks[code].push({
        date: dt,
        price: Number.isNaN(price) ? 0 : price,
        w,
        name,
      })
    } else if (action.includes('清') || action.includes('卖') || action.includes('平')) {
      const ent = (stacks[code] || []).shift()
      if (!ent) continue
      let stockRet = parsePct(r.day_ret)
      if (stockRet == null && ent.price > 0 && !Number.isNaN(price) && price > 0) {
        stockRet = price / ent.price - 1
      }
      let nav = parsePct(r.nav_pnl)
      if (nav == null && stockRet != null) nav = stockRet * ent.w
      if (nav == null) nav = 0
      rawLegs.push({
        code,
        name: name || ent.name || '',
        buy_date: ent.date,
        sell_date: dt,
        hold_days: calendarHoldDays(ent.date, dt),
        buy_price: ent.price > 0 ? ent.price.toFixed(4) : '',
        sell_price: !Number.isNaN(price) ? price.toFixed(4) : '',
        buy_position: ent.w.toFixed(4),
        stock_ret: stockRet != null ? fmtPct(stockRet) : '',
        nav_pnl: fmtPct(nav),
        nav_pnl_num: nav,
      })
    }
  }

  const absSum = rawLegs.reduce((s, x) => s + Math.abs(x.nav_pnl_num), 0)
  const totalNav = rawLegs.reduce((s, x) => s + x.nav_pnl_num, 0)
  const legs: ContribLeg[] = rawLegs
    .map((x) => ({
      ...x,
      share: absSum > 0 ? fmtPct(x.nav_pnl_num / absSum) : '0.00%',
    }))
    .sort((a, b) => b.nav_pnl_num - a.nav_pnl_num)

  const byCode = new Map<
    string,
    {
      code: string
      name: string
      n: number
      wins: number
      hold: number
      nav: number
      firstBuy: string
      lastSell: string
    }
  >()
  for (const leg of legs) {
    const cur = byCode.get(leg.code) || {
      code: leg.code,
      name: leg.name,
      n: 0,
      wins: 0,
      hold: 0,
      nav: 0,
      firstBuy: leg.buy_date,
      lastSell: leg.sell_date,
    }
    cur.n += 1
    cur.hold += leg.hold_days
    cur.nav += leg.nav_pnl_num
    if (leg.nav_pnl_num > 0) cur.wins += 1
    if (leg.name) cur.name = leg.name
    if (leg.buy_date && (!cur.firstBuy || leg.buy_date < cur.firstBuy)) cur.firstBuy = leg.buy_date
    if (leg.sell_date && (!cur.lastSell || leg.sell_date > cur.lastSell)) cur.lastSell = leg.sell_date
    byCode.set(leg.code, cur)
  }
  const symbols: ContribSymbol[] = [...byCode.values()]
    .map((x) => ({
      code: x.code,
      name: x.name,
      n_legs: x.n,
      first_buy: x.firstBuy,
      last_sell: x.lastSell,
      avg_hold_days: x.n ? Math.round((x.hold / x.n) * 10) / 10 : 0,
      win_rate: x.n ? fmtPct(x.wins / x.n) : '0.00%',
      nav_pnl: fmtPct(x.nav),
      nav_pnl_num: x.nav,
      share: absSum > 0 ? fmtPct(x.nav / absSum) : '0.00%',
    }))
    .sort((a, b) => b.nav_pnl_num - a.nav_pnl_num)

  return { legs, symbols, totalNav }
}

function downloadTextFile(filename: string, text: string) {
  const blob = new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function csvEscape(v: unknown) {
  const s = v == null ? '' : String(v)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

function downloadContributionCsv() {
  const fid = preview.factorId || 'factor'
  if (preview.contribMode === 'symbol') {
    const headers = [
      'code',
      'name',
      'n_legs',
      'first_buy',
      'last_sell',
      'avg_hold_days',
      'win_rate',
      'nav_pnl',
      'share',
    ]
    const lines = [
      headers.join(','),
      ...preview.contribSymbols.map((r) =>
        headers.map((h) => csvEscape((r as any)[h])).join(','),
      ),
    ]
    downloadTextFile(`${fid}_nav_contribution_by_symbol.csv`, lines.join('\n'))
  } else {
    const headers = [
      'code',
      'name',
      'buy_date',
      'sell_date',
      'hold_days',
      'buy_price',
      'sell_price',
      'buy_position',
      'stock_ret',
      'nav_pnl',
      'share',
    ]
    const lines = [
      headers.join(','),
      ...preview.contribLegs.map((r) => headers.map((h) => csvEscape((r as any)[h])).join(',')),
    ]
    downloadTextFile(`${fid}_nav_contribution_legs.csv`, lines.join('\n'))
  }
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

function availableArtifacts(row: FactorItem): FactorArtifact[] {
  return (row.backtest?.artifacts || []).filter((a) => {
    if (!a.available) return false
    if (a.kind === 'json') return false
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

async function load() {
  loading.value = true
  try {
    const data = await factorsApi.list()
    // 按创建时间（注册生成顺序）编号；与当前按 Sharpe 等排序无关
    const byGen = [...(data.items || [])].sort((a, b) => {
      const ta = a.created_at || ''
      const tb = b.created_at || ''
      if (ta !== tb) return ta < tb ? -1 : 1
      return String(a.factor_id).localeCompare(String(b.factor_id))
    })
    const seqMap = new Map(byGen.map((row, i) => [row.factor_id, i + 1]))
    const rows = (data.items || []).map((row) => enrichRow(row, seqMap.get(row.factor_id) || 0))
    rows.sort((a, b) => sortNum('bt_sharpe')(b, a))
    items.value = rows
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
  preview.tradeTab = 'flow'
  preview.contribMode = 'symbol'
  preview.contribLegs = []
  preview.contribSymbols = []
  preview.contribTotalNav = 0
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
        const enriched = enrichTrades(rows)
        const sorted = [...enriched].sort((x, y) => String(y.date || '').localeCompare(String(x.date || '')))
        const maxShow = 300
        preview.kind = 'trades'
        preview.tradeTab = 'flow'
        preview.tradeTotal = sorted.length
        preview.trades = sorted.slice(0, maxShow)
        preview.tradeColumns = tradeColumnsOf(headers, enriched)
        const contrib = buildNavContribution(enriched)
        preview.contribLegs = contrib.legs
        preview.contribSymbols = contrib.symbols
        preview.contribTotalNav = contrib.totalNav
        preview.contribMode = 'symbol'
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

async function downloadCurrent() {
  if (!preview.factorId) return
  try {
    if (preview.kind === 'trades' && preview.tradeTab === 'contrib') {
      downloadContributionCsv()
      ElMessage.success('已下载净值贡献表')
      return
    }
    if (!preview.artifactId) return
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
.range { font-size: 12px; color: var(--el-text-color-regular); }
.gen-seq { color: var(--el-text-color-secondary); font-variant-numeric: tabular-nums; }
.pos { color: var(--el-color-success); font-variant-numeric: tabular-nums; }
.neg { color: var(--el-color-danger); font-variant-numeric: tabular-nums; }
.mdd { color: var(--el-color-warning); font-variant-numeric: tabular-nums; }
.preview-body { min-height: 120px; }
.preview-img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
.trades-meta { margin-bottom: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.contrib-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.trades-tabs :deep(.el-tabs__header) { margin-bottom: 10px; }
.guide-body { min-height: 160px; max-height: 74vh; overflow: auto; padding-right: 6px; }
.markdown-body { font-size: 14px; line-height: 1.7; color: var(--el-text-color-primary); }
.markdown-body :deep(h1) { font-size: 20px; margin: 0 0 12px; }
.markdown-body :deep(h2) { font-size: 16px; margin: 18px 0 8px; border-bottom: 1px solid var(--el-border-color-lighter); padding-bottom: 4px; }
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
.markdown-body :deep(td:nth-child(n+3)) { font-variant-numeric: tabular-nums; }
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
.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--el-border-color-lighter);
  margin: 18px 0;
}
</style>
