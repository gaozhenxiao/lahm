import { ApiClient } from './request'

export interface FactorRef {
  factor_id: string
  name: string
  sharpe?: number | null
  quality?: string
  weight?: number | null
  buy_date?: string | null
  buy_price?: number | null
  as_of?: string | null
  is_champion?: boolean
  note?: string
  /** 合并前重叠开仓腿数；展示为一条持仓 */
  n_legs?: number | null
}

export interface LeadItem {
  id: string
  code: string
  name: string
  market: string
  source: string
  status: string
  score?: number | null
  reason?: string
  tags?: string[]
  analysis_id?: string | null
  factor_id?: string | null
  kind?: string | null
  factors_good?: FactorRef[]
  factors_warn?: FactorRef[]
  factors_neutral?: FactorRef[]
  weights?: { factor_id: string; weight?: number; quality?: string }[]
  as_of?: string | null
  created_at?: string
  updated_at?: string
}

export interface FactorBookResponse {
  as_of?: string
  updated_at?: string
  thresholds?: { good_sharpe: number; weak_sharpe: number; note?: string }
  champion_id?: string | null
  stats?: Record<string, number>
  filter_mode?: string
  total: number
  items: LeadItem[]
  build_ms?: number
}

export const leadsApi = {
  list: async (params?: { status?: string; keyword?: string }) => {
    const res = await ApiClient.get<{ total: number; items: LeadItem[] }>('/api/leads/', params)
    return ((res as any)?.data || res) as { total: number; items: LeadItem[] }
  },
  factorBook: async (params?: {
    refresh?: boolean
    filter_mode?: string
    keyword?: string
    good_sharpe?: number
    weak_sharpe?: number
  }) => {
    const res = await ApiClient.get<FactorBookResponse>('/api/leads/factor-book', params)
    return ((res as any)?.data || res) as FactorBookResponse
  },
  factorBookToInvestment: async (payload: Partial<LeadItem> & { code: string }) => {
    const res = await ApiClient.post('/api/leads/factor-book/to-investment', payload)
    return (res as any)?.data || res
  },
  create: async (payload: Partial<LeadItem> & { code: string }) => {
    const res = await ApiClient.post<LeadItem>('/api/leads/', payload)
    return ((res as any)?.data || res) as LeadItem
  },
  update: async (id: string, payload: Partial<LeadItem>) => {
    const res = await ApiClient.patch<LeadItem>(`/api/leads/${id}`, payload)
    return ((res as any)?.data || res) as LeadItem
  },
  remove: (id: string) => ApiClient.delete(`/api/leads/${id}`),
  fromScreening: async (payload: { items: any[]; reason?: string; tags?: string[]; score?: number }) => {
    const res = await ApiClient.post('/api/leads/from-screening', payload)
    return (res as any)?.data || res
  },
  toInvestment: async (id: string) => {
    const res = await ApiClient.post(`/api/leads/${id}/to-investment`, {})
    return (res as any)?.data || res
  },
}
