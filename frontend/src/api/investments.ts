import { ApiClient } from './request'

export interface InvestmentItem {
  id: string
  code: string
  name: string
  market: string
  status: string
  side: string
  thesis?: string
  lead_id?: string | null
  analysis_id?: string | null
  factor_ids?: string[]
  tags?: string[]
  entry_price?: number | null
  quantity?: number | null
  created_at?: string
  updated_at?: string
}

export const investmentsApi = {
  list: async (params?: { status?: string }) => {
    const res = await ApiClient.get<{ total: number; items: InvestmentItem[] }>('/api/investments/', params)
    return ((res as any)?.data || res) as { total: number; items: InvestmentItem[] }
  },
  create: async (payload: Partial<InvestmentItem> & { code: string }) => {
    const res = await ApiClient.post<InvestmentItem>('/api/investments/', payload)
    return ((res as any)?.data || res) as InvestmentItem
  },
  update: async (id: string, payload: Partial<InvestmentItem>) => {
    const res = await ApiClient.patch<InvestmentItem>(`/api/investments/${id}`, payload)
    return ((res as any)?.data || res) as InvestmentItem
  },
  remove: (id: string) => ApiClient.delete(`/api/investments/${id}`),
}
