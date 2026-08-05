<template>
  <div class="reports-workbench">
    <div class="page-header">
      <div>
        <h1>分析报告</h1>
        <p class="subtitle">需求 · 竞争 · 产供销 · 量价利 · 股东 · 中远期重大影响</p>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="workbench-tabs">
      <!-- ① 个股 DeepSeek 分析 -->
      <el-tab-pane label="个股分析" name="stock">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-head">
              <span>生成经营要点报告（约 2 页 A4）</span>
              <el-tag type="success" size="small" effect="plain">DeepSeek</el-tag>
            </div>
          </template>

          <el-form :inline="true" class="stock-form" @submit.prevent>
            <el-form-item label="股票代码">
              <el-input
                v-model="stockCode"
                placeholder="如 000001 / 600519"
                clearable
                style="width: 180px"
                @keyup.enter="startStockAnalysis"
              />
            </el-form-item>
            <el-form-item label="市场">
              <el-select v-model="marketType" style="width: 120px">
                <el-option label="A股" value="A股" />
                <el-option label="港股" value="港股" />
                <el-option label="美股" value="美股" />
              </el-select>
            </el-form-item>
            <el-form-item label="研究深度">
              <el-select v-model="researchDepth" style="width: 110px">
                <el-option label="快速" :value="1" />
                <el-option label="标准" :value="2" />
                <el-option label="深度" :value="3" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="analyzing" @click="startStockAnalysis">
                开始分析
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          >
            <template #title>
              只写这几项：
              <strong>行业需求</strong>、<strong>竞争格局</strong>、<strong>产供销</strong>、<strong>量价利</strong>、<strong>股东（如有）</strong>，
              并单独看有没有<strong>中远期重大影响因素</strong>。
              不做技术/情绪分析；无结论章、无买卖口号。
            </template>
          </el-alert>

          <div v-if="analyzing || analysisTaskId" class="task-box">
            <div class="task-row">
              <span>任务：{{ analysisTaskId || '提交中…' }}</span>
              <el-tag :type="taskStatusType" size="small">{{ taskStatusText }}</el-tag>
            </div>
            <el-progress :percentage="taskProgress" :status="taskProgressStatus" />
            <p class="task-msg">{{ taskMessage }}</p>
            <el-button
              v-if="analysisResultId"
              type="success"
              size="small"
              @click="openAnalysisResult"
            >
              查看报告
            </el-button>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ② 新闻雷达 -->
      <el-tab-pane label="新闻雷达" name="news">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-head">
              <span>扫描财联社快讯 → 判断重要性 → 映射标的 → 给出推荐</span>
              <div class="head-actions">
                <el-switch v-model="forceNewsScan" active-text="强制刷新" />
                <el-button type="primary" :loading="newsLoading" @click="runNewsScan">
                  扫描重大新闻
                </el-button>
              </div>
            </div>
          </template>

          <el-alert
            v-if="newsMeta.llm_error"
            type="warning"
            :closable="false"
            show-icon
            :title="`LLM 调用异常，已用启发式兜底：${newsMeta.llm_error}`"
            style="margin-bottom: 12px"
          />

          <div v-if="newsMeta.asof" class="news-meta">
            来源 {{ newsMeta.source || 'cls.cn' }} · 扫描
            {{ formatTime(newsMeta.asof) }}
            <template v-if="newsMeta.cached"> · 缓存 {{ newsMeta.cache_age_sec }}s</template>
            · 拉取 {{ newsMeta.n_raw }} 条 · 重要 {{ newsMeta.n_important }} 条 · 推荐
            {{ newsMeta.n_recommend }} 只
          </div>

          <h3 class="section-title">推荐标的</h3>
          <el-empty v-if="!newsLoading && recommendations.length === 0" description="点击上方按钮开始扫描" />
          <el-table v-else :data="recommendations" v-loading="newsLoading" stripe>
            <el-table-column prop="code" label="代码" width="100" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="score" label="分数" width="80" sortable />
            <el-table-column prop="impacts" label="影响" width="120">
              <template #default="{ row }">
                {{ (row.impacts || []).join(' / ') }}
              </template>
            </el-table-column>
            <el-table-column prop="news" label="相关新闻" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">
                {{ (row.news || []).join('；') }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" link @click="analyzeRecommended(row)">DeepSeek 分析</el-button>
              </template>
            </el-table-column>
          </el-table>

          <h3 class="section-title" style="margin-top: 24px">重要新闻</h3>
          <el-table :data="importantNews" v-loading="newsLoading" stripe>
            <el-table-column prop="importance" label="重要度" width="80" sortable />
            <el-table-column prop="impact" label="方向" width="100">
              <template #default="{ row }">
                <el-tag :type="impactTag(row.impact)" size="small">{{ row.impact }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="260" show-overflow-tooltip />
            <el-table-column prop="summary" label="摘要" min-width="220" show-overflow-tooltip />
            <el-table-column label="相关标的" min-width="180">
              <template #default="{ row }">
                <el-tag
                  v-for="(t, i) in (row.stocks || []).slice(0, 4)"
                  :key="i"
                  size="small"
                  class="ticker-tag"
                  @click="analyzeRecommended(t)"
                >
                  {{ t.code }} {{ t.name }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="time" label="时间" width="170">
              <template #default="{ row }">{{ formatTime(row.time) }}</template>
            </el-table-column>
            <el-table-column label="原文" width="70">
              <template #default="{ row }">
                <el-link v-if="row.url" :href="row.url" target="_blank" type="primary">打开</el-link>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ③ 历史报告 -->
      <el-tab-pane label="历史报告" name="history">
        <el-card shadow="never">
          <div class="toolbar">
            <div class="toolbar-left">
              <el-input
                v-model="searchKeyword"
                placeholder="搜索股票代码或名称"
                style="width: 240px"
                clearable
                @keyup.enter="handleSearch"
              >
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
              <el-select
                v-model="marketFilter"
                placeholder="市场"
                style="width: 110px; margin-left: 8px"
                clearable
                @change="handleMarketChange"
              >
                <el-option label="全部" value="" />
                <el-option label="A股" value="A股" />
                <el-option label="港股" value="港股" />
                <el-option label="美股" value="美股" />
              </el-select>
              <el-date-picker
                v-model="dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始"
                end-placeholder="结束"
                style="margin-left: 8px"
                @change="handleDateChange"
              />
            </div>
            <div class="toolbar-right">
              <el-button @click="refreshReports" :loading="loading">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
              <el-button
                type="danger"
                :disabled="selectedReports.length === 0"
                @click="batchDelete"
              >
                批量删除
              </el-button>
            </div>
          </div>

          <el-table
            :data="filteredReports"
            v-loading="loading"
            @selection-change="handleSelectionChange"
            stripe
          >
            <el-table-column type="selection" width="50" />
            <el-table-column prop="title" label="报告标题" min-width="260">
              <template #default="{ row }">
                <el-link type="primary" :underline="false" @click.prevent="viewReport(row)">
                  {{ displayTitle(row) }}
                </el-link>
                <div class="report-subtitle" v-if="row.stock_code">
                  {{ row.stock_code }}<template v-if="row.stock_name && row.stock_name !== row.stock_code"> · {{ row.stock_name }}</template>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="type" label="类型" width="110">
              <template #default="{ row }">
                <el-tag :type="getTypeColor(row.type)" size="small">{{ getTypeText(row.type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="model_info" label="模型" width="140">
              <template #default="{ row }">
                <span>{{ row.model_info && row.model_info !== 'Unknown' ? row.model_info : '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="170">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" link @click="viewReport(row)">查看</el-button>
                <el-dropdown
                  v-if="row.status === 'completed'"
                  trigger="click"
                  @command="(fmt: string) => downloadReport(row, fmt)"
                >
                  <el-button type="primary" link>下载</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="markdown">Markdown</el-dropdown-item>
                      <el-dropdown-item command="docx">Word</el-dropdown-item>
                      <el-dropdown-item command="pdf">PDF</el-dropdown-item>
                      <el-dropdown-item command="json" divided>JSON</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button type="danger" link @click="deleteReport(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="currentPage"
              v-model:page-size="pageSize"
              :page-sizes="[20, 50, 100]"
              :total="totalReports"
              layout="total, sizes, prev, pager, next"
              @size-change="handleSizeChange"
              @current-change="handleCurrentChange"
            />
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  reportsWorkbenchApi,
  type RadarRecommendation,
  type RadarNewsItem,
} from '@/api/reportsWorkbench'
import { analysisApi } from '@/api/analysis'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

type ReportListItem = {
  id: string
  mongo_id?: string
  analysis_id?: string
  task_id?: string
  title: string
  stock_code: string
  stock_name: string
  type: string
  format: string
  status: string
  model_info?: string
  analysis_date?: string
  created_at: string
}

const router = useRouter()
const authStore = useAuthStore()

const activeTab = ref('stock')

// —— 个股分析 ——
const stockCode = ref('')
const marketType = ref('A股')
const researchDepth = ref(2)
const analyzing = ref(false)
const analysisTaskId = ref('')
const analysisResultId = ref('')
const taskStatus = ref('')
const taskProgress = ref(0)
const taskMessage = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const taskStatusText = computed(() => {
  const map: Record<string, string> = {
    pending: '准备中',
    processing: '分析中',
    running: '分析中',
    completed: '已完成',
    failed: '失败',
  }
  return map[taskStatus.value] || taskStatus.value || '—'
})
const taskStatusType = computed<TagType>(() => {
  if (taskStatus.value === 'completed') return 'success'
  if (taskStatus.value === 'failed') return 'danger'
  if (taskStatus.value === 'processing' || taskStatus.value === 'running') return 'warning'
  return 'info'
})
const taskProgressStatus = computed(() => {
  if (taskStatus.value === 'completed') return 'success'
  if (taskStatus.value === 'failed') return 'exception'
  return undefined
})

const stopPoll = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const pollTask = async () => {
  if (!analysisTaskId.value) return
  try {
    const st = await analysisApi.getTaskStatus(analysisTaskId.value)
    const data = (st as any)?.data || st
    taskStatus.value = data?.status || ''
    taskProgress.value = Number(data?.progress || 0)
    taskMessage.value = data?.message || data?.current_step || ''
    if (data?.status === 'completed') {
      stopPoll()
      analyzing.value = false
      try {
        const res = await analysisApi.getTaskResult(analysisTaskId.value)
        const rd = (res as any)?.data || res
        analysisResultId.value = rd?.analysis_id || rd?.id || analysisTaskId.value
      } catch {
        analysisResultId.value = analysisTaskId.value
      }
      ElMessage.success('分析完成')
      activeTab.value = 'history'
      refreshReports()
    } else if (data?.status === 'failed') {
      stopPoll()
      analyzing.value = false
      ElMessage.error(data?.error_message || '分析失败')
    }
  } catch (e: any) {
    console.warn('poll task failed', e)
  }
}

const startStockAnalysis = async () => {
  const code = stockCode.value.trim().toUpperCase()
  if (!code) {
    ElMessage.warning('请输入股票代码')
    return
  }
  analyzing.value = true
  analysisResultId.value = ''
  taskProgress.value = 0
  taskStatus.value = 'pending'
  taskMessage.value = '提交任务…'
  stopPoll()
  try {
    const res = await reportsWorkbenchApi.startDeepseekAnalysis({
      symbol: code,
      market_type: marketType.value,
      research_depth: researchDepth.value,
    })
    const data = (res as any)?.data || res
    analysisTaskId.value = data?.task_id || data?.analysis_id || ''
    if (!analysisTaskId.value) throw new Error('未返回任务 ID')
    ElMessage.success('已提交 DeepSeek 分析')
    pollTimer = setInterval(pollTask, 2500)
    pollTask()
  } catch (e: any) {
    analyzing.value = false
    ElMessage.error(e?.message || '提交失败')
  }
}

const openAnalysisResult = () => {
  // 优先 task_id（稳定），避免脏 analysis_id（如 None_…）
  const id = analysisTaskId.value || analysisResultId.value
  if (id) {
    router.push(`/reports/view/${encodeURIComponent(id)}`)
  }
}

const displayTitle = (row: ReportListItem) => {
  if (row?.title && !/none/i.test(row.title) && row.title !== '() 分析报告') {
    return row.title
  }
  const code = row?.stock_code || ''
  const name = row?.stock_name || ''
  if (name && code && name !== code) return `${name}（${code}）`
  return name || code || '分析报告'
}

const resolveViewId = (report: ReportListItem) => {
  const candidates = [report.id, report.task_id, report.mongo_id, report.analysis_id]
  for (const c of candidates) {
    const s = String(c || '').trim()
    if (!s) continue
    if (/^none(_|$)/i.test(s) || s.toLowerCase() === 'none') continue
    return s
  }
  return report.id
}


const analyzeRecommended = (row: { code?: string; name?: string }) => {
  if (!row?.code) return
  stockCode.value = String(row.code)
  marketType.value = 'A股'
  activeTab.value = 'stock'
  startStockAnalysis()
}

// —— 新闻雷达 ——
const newsLoading = ref(false)
const forceNewsScan = ref(false)
const recommendations = ref<RadarRecommendation[]>([])
const importantNews = ref<RadarNewsItem[]>([])
const newsMeta = ref<{
  asof?: string
  source?: string
  cached?: boolean
  cache_age_sec?: number
  n_raw?: number
  n_important?: number
  n_recommend?: number
  llm_error?: string | null
}>({})

const runNewsScan = async () => {
  newsLoading.value = true
  try {
    const data = await reportsWorkbenchApi.scanNews({
      limit: 40,
      refresh: forceNewsScan.value,
      use_llm: true,
    })
    recommendations.value = data?.recommendations || []
    importantNews.value = data?.important || []
    newsMeta.value = {
      asof: data?.asof,
      source: data?.source,
      cached: data?.cached,
      cache_age_sec: data?.cache_age_sec,
      n_raw: data?.summary?.n_raw,
      n_important: data?.summary?.n_important,
      n_recommend: data?.summary?.n_recommend_stocks,
      llm_error: data?.llm_error,
    }
    ElMessage.success(
      `扫描完成：重要 ${data?.summary?.n_important || 0} 条，推荐 ${data?.summary?.n_recommend_stocks || 0} 只`,
    )
  } catch (e: any) {
    ElMessage.error(e?.message || '扫描失败')
  } finally {
    newsLoading.value = false
  }
}

const impactTag = (a?: string): TagType => {
  if (!a) return 'info'
  if (a.includes('多')) return 'success'
  if (a.includes('空')) return 'danger'
  return 'info'
}

// —— 历史报告 ——
const loading = ref(false)
const searchKeyword = ref('')
const marketFilter = ref('')
const dateRange = ref<[string, string] | null>(null)
const selectedReports = ref<ReportListItem[]>([])
const currentPage = ref(1)
const pageSize = ref(20)
const totalReports = ref(0)
const reports = ref<ReportListItem[]>([])
const filteredReports = computed(() => reports.value)

const fetchReports = async () => {
  loading.value = true
  try {
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      page_size: pageSize.value.toString(),
    })
    if (searchKeyword.value) params.append('search_keyword', searchKeyword.value)
    if (marketFilter.value) params.append('market_filter', marketFilter.value)
    if (dateRange.value) {
      params.append('start_date', dateRange.value[0])
      params.append('end_date', dateRange.value[1])
    }
    const response = await fetch(`/api/reports/list?${params}`, {
      headers: {
        Authorization: `Bearer ${authStore.token}`,
        'Content-Type': 'application/json',
      },
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const result = await response.json()
    if (result.success) {
      reports.value = result.data.reports
      totalReports.value = result.data.total
    } else {
      throw new Error(result.message || '获取报告列表失败')
    }
  } catch (error) {
    console.error(error)
    ElMessage.error('获取报告列表失败')
  } finally {
    loading.value = false
  }
}

const refreshReports = () => fetchReports()
const handleSearch = () => {
  currentPage.value = 1
  fetchReports()
}
const handleDateChange = () => {
  currentPage.value = 1
  fetchReports()
}
const handleMarketChange = () => {
  currentPage.value = 1
  fetchReports()
}
const handleSelectionChange = (selection: ReportListItem[]) => {
  selectedReports.value = selection
}
const handleSizeChange = () => fetchReports()
const handleCurrentChange = () => fetchReports()

const viewReport = (report: ReportListItem) => {
  const id = resolveViewId(report)
  if (!id) {
    ElMessage.error('无法打开：缺少报告 ID')
    return
  }
  router.push(`/reports/view/${encodeURIComponent(id)}`)
}

const getFormatName = (format: string) => {
  const map: Record<string, string> = {
    markdown: 'Markdown',
    docx: 'Word',
    pdf: 'PDF',
    json: 'JSON',
  }
  return map[format] || format
}

const downloadReport = async (report: ReportListItem, format: string = 'markdown') => {
  try {
    const loadingMsg = ElMessage({
      message: `正在生成${getFormatName(format)}…`,
      type: 'info',
      duration: 0,
    })
    const response = await fetch(`/api/reports/${report.id}/download?format=${format}`, {
      headers: { Authorization: `Bearer ${authStore.token}` },
    })
    loadingMsg.close()
    if (!response.ok) throw new Error(await response.text())
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${report.stock_code}_${report.stock_name}_${report.id}.${format === 'markdown' ? 'md' : format}`
    a.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('下载成功')
  } catch (e: any) {
    ElMessage.error(e?.message || '下载失败')
  }
}

const deleteReport = async (report: ReportListItem) => {
  try {
    await ElMessageBox.confirm(`确定删除「${report.title}」？`, '确认', { type: 'warning' })
    const response = await fetch(`/api/reports/${report.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${authStore.token}` },
    })
    const result = await response.json()
    if (result.success) {
      ElMessage.success('已删除')
      fetchReports()
    } else {
      throw new Error(result.message)
    }
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '删除失败')
  }
}

const batchDelete = async () => {
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selectedReports.value.length} 份报告？`, '确认', {
      type: 'warning',
    })
    for (const r of selectedReports.value) {
      await fetch(`/api/reports/${r.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${authStore.token}` },
      })
    }
    ElMessage.success('批量删除完成')
    fetchReports()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('批量删除失败')
  }
}

const getTypeColor = (type: string): TagType => {
  const map: Record<string, TagType> = {
    analysis: 'primary',
    summary: 'success',
    detail: 'warning',
  }
  return map[type] || 'info'
}
const getTypeText = (type: string) => {
  const map: Record<string, string> = {
    analysis: '分析报告',
    summary: '摘要',
    detail: '详细',
  }
  return map[type] || type
}
const getStatusType = (status: string): TagType => {
  const map: Record<string, TagType> = {
    completed: 'success',
    processing: 'warning',
    failed: 'danger',
    pending: 'info',
  }
  return map[status] || 'info'
}
const getStatusText = (status: string) => {
  const map: Record<string, string> = {
    completed: '已完成',
    processing: '生成中',
    failed: '失败',
    pending: '等待中',
  }
  return map[status] || status
}

const formatTime = (time?: string) => {
  if (!time) return '-'
  try {
    return new Date(time).toLocaleString('zh-CN')
  } catch {
    return time
  }
}

onMounted(() => {
  fetchReports()
})
onUnmounted(() => stopPoll())
</script>

<style scoped>
.reports-workbench {
  padding: 20px;
}
.page-header {
  margin-bottom: 12px;
}
.page-header h1 {
  margin: 0;
  font-size: 22px;
}
.subtitle {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.stock-form {
  margin-bottom: 8px;
}
.task-box {
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 14px 16px;
}
.task-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
}
.task-msg {
  margin: 8px 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.news-meta {
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.section-title {
  margin: 8px 0 12px;
  font-size: 15px;
}
.ticker-tag {
  margin: 2px 4px 2px 0;
  cursor: pointer;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 8px;
}
.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.report-subtitle {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
