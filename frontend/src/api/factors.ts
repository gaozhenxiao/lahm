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
  backtest?: FactorBacktest | null
  has_guide?: boolean
}

export interface FactorGuide {
  factor_id: string
  title: string
  format: string
  content: string
  path?: string
  fallback?: boolean
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
  compute: async (id: string, asof?: string) => {
    const res = await ApiClient.post(`/api/factors/${id}/compute`, {}, { params: { asof } })
    return (res as any)?.data || res
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
