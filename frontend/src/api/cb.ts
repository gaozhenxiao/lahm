import { ApiClient } from './request'

export interface CbStrategy {
  id: string
  name: string
  status: string
  description: string
  endpoint?: string | null
}

export interface CbArbItem {
  bond_code: string
  bond_name: string
  stock_code: string
  stock_name: string
  bond_price: number | null
  stock_price: number | null
  conversion_price: number | null
  conversion_value: number | null
  premium_pct: number | null
  net_edge_pct: number | null
  dual_low: number | null
  rating?: string | null
  list_date?: string | null
  approx_in_convert_period?: boolean | null
  change_pct?: number | null
  amount?: number | null
  volume?: number | null
  ticktime?: string | null
  flags?: string[]
}

export interface CbStockArbResult {
  asof: string
  source: string
  cached?: boolean
  cache_age_sec?: number
  params?: Record<string, number>
  summary: {
    n_alive: number
    n_traded: number
    n_discount: number
    n_near_parity: number
    n_dual_low: number
  }
  discount: CbArbItem[]
  near_parity: CbArbItem[]
  dual_low: CbArbItem[]
  notes?: string[]
}

export interface CbModuleMeta {
  module: string
  name: string
  description: string
  strategies: CbStrategy[]
}

function unwrap<T>(res: any): T {
  return (res?.data ?? res) as T
}

export const cbApi = {
  meta: async () => unwrap<CbModuleMeta>(await ApiClient.get('/api/cb/')),
  strategies: async () =>
    unwrap<{ total: number; items: CbStrategy[] }>(await ApiClient.get('/api/cb/strategies')),
  stockArb: async (params?: {
    refresh?: boolean
    ttl_sec?: number
    discount_max?: number
    near_parity_max?: number
  }) => unwrap<CbStockArbResult>(await ApiClient.get('/api/cb/arb/stock', params)),
  refreshStockArb: async () =>
    unwrap<CbStockArbResult>(await ApiClient.post('/api/cb/arb/stock/refresh')),
}
