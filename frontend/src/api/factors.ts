import { ApiClient, request } from './request'

export interface FactorArtifact {
  id: string
  label: string
  kind?: string
  logic?: string
  available: boolean
  url: string
}

export interface FactorBacktestLogic {
  total_return?: number
  annual_return?: number
  sharpe?: number
  max_drawdown?: number
  roundtrips?: number
  start?: string
  end?: string
  bars?: number
  buy_hold_return?: number
  avg_position?: number
  position_logic?: string
  mode?: string
  error?: string
  note?: string
  n_legs_raw?: number
  n_legs_accepted?: number
}

export interface FactorBacktest {
  available: boolean
  primary_logic?: string
  logics?: Record<string, FactorBacktestLogic>
  artifacts?: FactorArtifact[]
  updated_at?: string | null
  note?: string
}

export interface FactorItem {
  factor_id: string
  name: string
  category: string
  description: string
  status: string
  params?: Record<string, any>
  tags?: string[]
  builtin?: boolean
  latest_signal?: string | null
  latest_value?: number | null
  latest_asof?: string | null
  created_at?: string | null
  /** 稳定 UI 序号（含已删占位空洞，不因隐藏 pad 前移） */
  gen_seq?: number
  backtest?: FactorBacktest | null
  has_guide?: boolean
  last_backtest_error?: string | null
}

export interface FactorGuide {
  factor_id: string
  title: string
  format: string
  content: string
  path?: string
  fallback?: boolean
}

export type FactorMatchStatus = 'hit' | 'miss' | 'unsupported' | 'insufficient_data'

export interface FactorStockMatchItem {
  factor_id: string
  name: string
  match: boolean
  status: FactorMatchStatus | string
  signal?: string
  reason?: string
  entry_date?: string | null
  note?: string
  /** 符合标准的详细解释（阈值/面板值） */
  detail?: string
  explanation?: string
}

export interface FactorStockMatchResult {
  code: string
  code_norm: string
  /** 股票中文名（可能为空） */
  name?: string | null
  stock_name?: string | null
  /** 交易日收盘价（前复权） */
  price?: number | null
  close?: number | null
  price_date?: string | null
  price_adjust?: string | null
  price_adjust_label?: string | null
  asof?: string | null
  trade_date?: string | null
  data_status?: Record<string, any>
  error?: string
  matches: FactorStockMatchItem[]
  summary?: {
    hit: number
    miss: number
    unsupported: number
    insufficient_data: number
    total: number
  }
  evaluated_at?: string
}

export const factorsApi = {
  list: async () => {
    const res = await ApiClient.get<{ total: number; items: FactorItem[] }>('/api/factors/')
    return ((res as any)?.data || res) as { total: number; items: FactorItem[] }
  },
  get: async (id: string) => {
    const res = await ApiClient.get<FactorItem>(`/api/factors/${id}`)
    return ((res as any)?.data || res) as FactorItem
  },
  matchStock: async (code: string, asof?: string) => {
    const params: Record<string, string> = { code }
    if (asof) params.asof = asof
    const res = await ApiClient.get<FactorStockMatchResult>('/api/factors/match-stock', params)
    return ((res as any)?.data || res) as FactorStockMatchResult
  },
  compute: async (id: string, asof?: string) => {
    const res = await ApiClient.post(`/api/factors/${id}/compute`, {}, { params: { asof } })
    return (res as any)?.data || res
  },
  /** 统一更新：K线增量 + 财报增量 + 信号重算（默认后台） */
  update: async (opts?: {
    include_kline?: boolean
    include_financial?: boolean
    include_signals?: boolean
    background?: boolean
  }) => {
    const params: Record<string, boolean> = {
      include_kline: opts?.include_kline ?? true,
      include_financial: opts?.include_financial ?? true,
      include_signals: opts?.include_signals ?? true,
      background: opts?.background ?? true,
    }
    const res = await ApiClient.post('/api/factors/update', {}, { params })
    return (res as any)?.data || res
  },
    updateSettings: async () => {
    const res = await ApiClient.get<{
      kline: {
        enabled: boolean
        cron: string
        universe: string
        data_source?: string
        times_hint: string
      }
      financial: {
        enabled: boolean
        cron: string
        universe: string
        data_source?: string
        times_hint: string
      }
      signals: { enabled: boolean; cron: string }
      timezone: string
    }>('/api/factors/update/settings')
    return ((res as any)?.data || res) as {
      kline: {
        enabled: boolean
        cron: string
        universe: string
        data_source?: string
        times_hint: string
      }
      financial: {
        enabled: boolean
        cron: string
        universe: string
        data_source?: string
        times_hint: string
      }
      signals: { enabled: boolean; cron: string }
      timezone: string
    }
  },
  signals: async (id: string) => {
    const res = await ApiClient.get(`/api/factors/${id}/signals`)
    return (res as any)?.data || res
  },
  backtest: async (id: string) => {
    const res = await ApiClient.get<FactorBacktest>(`/api/factors/${id}/backtest`)
    return ((res as any)?.data || res) as FactorBacktest
  },
  guide: async (id: string) => {
    const res = await ApiClient.get<FactorGuide>(`/api/factors/${id}/guide`)
    return ((res as any)?.data || res) as FactorGuide
  },
  /** Fetch artifact as Blob (auth header included). */
  artifactBlob: async (factorId: string, artifactId: string) => {
    const data = await request.get(`/api/factors/${factorId}/artifacts/${artifactId}`, {
      responseType: 'blob',
    })
    return data instanceof Blob ? data : new Blob([data as unknown as BlobPart])
  },
  downloadArtifact: async (factorId: string, artifactId: string, filename?: string) => {
    await ApiClient.download(
      `/api/factors/${factorId}/artifacts/${artifactId}`,
      filename || artifactId,
    )
  },
}
