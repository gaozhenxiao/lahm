import { ApiClient } from './request'
import { analysisApi, type SingleAnalysisRequest } from './analysis'

export interface RadarStock {
  code: string
  name?: string
  reason?: string
}

export interface RadarNewsItem {
  id: string
  title?: string
  content?: string
  time?: string
  url?: string
  source?: string
  importance?: number
  important?: boolean
  impact?: string
  stocks?: RadarStock[]
  summary?: string
  action?: string
  reason?: string
  method?: string
}

export interface RadarRecommendation {
  code: string
  name?: string
  score: number
  news: string[]
  impacts: string[]
}

export interface NewsRadarResult {
  asof: string
  source: string
  cached?: boolean
  cache_age_sec?: number
  llm_error?: string | null
  summary: {
    n_raw: number
    n_analyzed: number
    n_important: number
    n_recommend_stocks: number
  }
  important: RadarNewsItem[]
  recommendations: RadarRecommendation[]
  feed: RadarNewsItem[]
}

function unwrap<T>(res: any): T {
  return (res?.data ?? res) as T
}

const DEPTH_LABEL: Record<number, string> = {
  1: '快速',
  2: '标准',
  3: '深度',
}

export const reportsWorkbenchApi = {
  scanNews: async (params?: { refresh?: boolean; limit?: number; use_llm?: boolean }) =>
    unwrap<NewsRadarResult>(await ApiClient.get('/api/news-radar/scan', params)),

  /** DeepSeek 个股分析：走既有 tradingagents 管道 */
  startDeepseekAnalysis: async (opts: {
    symbol: string
    market_type?: string
    research_depth?: number | string
  }) => {
    const depth =
      typeof opts.research_depth === 'number'
        ? DEPTH_LABEL[opts.research_depth] || '标准'
        : opts.research_depth || '标准'
    const payload: SingleAnalysisRequest = {
      symbol: opts.symbol.trim(),
      parameters: {
        market_type: opts.market_type || 'A股',
        research_depth: depth,
        selected_analysts: ['fundamentals', 'news'],
        language: 'zh-CN',
        quick_analysis_model: 'deepseek-chat',
        deep_analysis_model: 'deepseek-chat',
      },
    }
    return analysisApi.startSingleAnalysis(payload)
  },

  getTaskStatus: (taskId: string) => analysisApi.getTaskStatus(taskId),
  getTaskResult: (taskId: string) => analysisApi.getTaskResult(taskId),
}
