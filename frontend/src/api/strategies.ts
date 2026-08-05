import { ApiClient } from './request'

export interface StrategyMeta {
  id: string
  name: string
  status: string
  difficulty?: string
  capital?: string
  best_regime?: string
  description: string
  exec?: string
  redirect?: string
}

export interface StrategiesHome {
  module: string
  name: string
  description: string
  strategies: StrategyMeta[]
  excluded?: string[]
}

export interface QmtStatus {
  asof: string
  config_path: string
  config: {
    userdata_path?: string
    account_id?: string
    account_type?: string
    enabled?: boolean
    note?: string
  }
  xtquant: { importable: boolean; module_path?: string | null; error?: string | null }
  discovered_paths: string[]
  connected: boolean
  connect_error?: string | null
  ready_for_orders: boolean
  checklist: string[]
}

function unwrap<T>(res: any): T {
  return (res?.data ?? res) as T
}

export const strategiesApi = {
  home: async () => unwrap<StrategiesHome>(await ApiClient.get('/api/strategies/')),
  scan: async (id: string, params?: { refresh?: boolean; ttl_sec?: number }) =>
    unwrap<any>(await ApiClient.get(`/api/strategies/${id}/scan`, params)),
  refresh: async (id: string) => unwrap<any>(await ApiClient.post(`/api/strategies/${id}/refresh`)),
  qmtStatus: async () => unwrap<QmtStatus>(await ApiClient.get('/api/strategies/qmt/status')),
  qmtConfig: async (body: Record<string, any>) =>
    unwrap<any>(await ApiClient.post('/api/strategies/qmt/config', body)),
}
