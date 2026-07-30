<template>
  <div class="leads-page">
    <div class="page-header">
      <h1 class="page-title">机会列表 Leads</h1>
      <p class="page-description">筛选/分析产生的投资机会管道：新建 → 观察 → 分析 → 转入投资</p>
    </div>

    <el-card shadow="never" class="toolbar">
      <el-row :gutter="12">
        <el-col :span="6">
          <el-input v-model="keyword" clearable placeholder="代码/名称/备注" @keyup.enter="load" />
        </el-col>
        <el-col :span="4">
          <el-select v-model="status" clearable placeholder="状态" @change="load">
            <el-option label="新建" value="new" />
            <el-option label="观察中" value="watching" />
            <el-option label="分析中" value="analyzing" />
            <el-option label="已投资" value="invested" />
            <el-option label="已关闭" value="closed" />
          </el-select>
        </el-col>
        <el-col :span="14" class="actions">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="showCreate = true">新建机会</el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="code" label="代码" width="110" />
        <el-table-column prop="name" label="名称" width="120" />
        <el-table-column prop="source" label="来源" width="100" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="评分" width="80" />
        <el-table-column prop="reason" label="理由" min-width="180" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新" width="170" />
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="setStatus(row, 'watching')">观察</el-button>
            <el-button link type="warning" @click="setStatus(row, 'analyzing')">分析中</el-button>
            <el-button link type="success" @click="toInvest(row)">转入投资</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="新建机会" width="480px">
      <el-form label-width="80px">
        <el-form-item label="代码"><el-input v-model="form.code" placeholder="600519 或 600519.SH" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="评分"><el-input-number v-model="form.score" :min="0" :max="100" /></el-form-item>
        <el-form-item label="理由"><el-input v-model="form.reason" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="create">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { leadsApi, type LeadItem } from '@/api/leads'

const loading = ref(false)
const items = ref<LeadItem[]>([])
const keyword = ref('')
const status = ref<string | undefined>()
const showCreate = ref(false)
const form = reactive({ code: '', name: '', score: 60 as number | undefined, reason: '' })

const statusLabel = (s: string) =>
  ({ new: '新建', watching: '观察中', analyzing: '分析中', invested: '已投资', closed: '已关闭' } as any)[s] || s

async function load() {
  loading.value = true
  try {
    const data = await leadsApi.list({ status: status.value, keyword: keyword.value || undefined })
    items.value = data.items || []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!form.code) return ElMessage.warning('请填写代码')
  await leadsApi.create({ ...form, source: 'manual', status: 'new', market: 'CN' })
  showCreate.value = false
  form.code = ''
  form.name = ''
  form.reason = ''
  ElMessage.success('已创建')
  load()
}

async function setStatus(row: LeadItem, s: string) {
  await leadsApi.update(row.id, { status: s })
  load()
}

async function toInvest(row: LeadItem) {
  await leadsApi.toInvestment(row.id)
  ElMessage.success('已转入投资列表')
  load()
}

async function remove(row: LeadItem) {
  await ElMessageBox.confirm(`删除机会 ${row.code}?`, '确认')
  await leadsApi.remove(row.id)
  load()
}

onMounted(load)
</script>

<style scoped>
.page-header { margin-bottom: 16px; }
.page-title { margin: 0 0 6px; font-size: 22px; }
.page-description { margin: 0; color: var(--el-text-color-secondary); }
.toolbar { margin-bottom: 12px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
