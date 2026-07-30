import { ApiClient } from './request'

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
  created_at?: string
  updated_at?: string
}

export const leadsApi = {
  list: async (params?: { status?: string; keyword?: string }) => {
    const res = await ApiClient.get<{ total: number; items: LeadItem[] }>('/api/leads/', params)
    return ((res as any)?.data || res) as { total: number; items: LeadItem[] }
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
