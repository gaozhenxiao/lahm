<template>
  <div class="investments-page">
    <div class="page-header">
      <h1 class="page-title">投资列表 Investments</h1>
      <p class="page-description">研究仓/决策台账；可从 Leads 一键转入，后续可对接模拟交易</p>
    </div>

    <el-card shadow="never" class="toolbar">
      <el-row :gutter="12">
        <el-col :span="4">
          <el-select v-model="status" clearable placeholder="状态" @change="load">
            <el-option label="计划中" value="planned" />
            <el-option label="持有中" value="open" />
            <el-option label="已关闭" value="closed" />
          </el-select>
        </el-col>
        <el-col :span="20" class="actions">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" @click="showCreate = true">新建</el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="code" label="代码" width="110" />
        <el-table-column prop="name" label="名称" width="120" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column prop="side" label="方向" width="80" />
        <el-table-column prop="thesis" label="逻辑" min-width="200" show-overflow-tooltip />
        <el-table-column prop="lead_id" label="来源Lead" width="120" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新" width="170" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="success" @click="setStatus(row, 'open')">持有</el-button>
            <el-button link type="warning" @click="setStatus(row, 'closed')">关闭</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="新建投资" width="480px">
      <el-form label-width="80px">
        <el-form-item label="代码"><el-input v-model="form.code" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="逻辑"><el-input v-model="form.thesis" type="textarea" /></el-form-item>
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
import { investmentsApi, type InvestmentItem } from '@/api/investments'

const loading = ref(false)
const items = ref<InvestmentItem[]>([])
const status = ref<string | undefined>()
const showCreate = ref(false)
const form = reactive({ code: '', name: '', thesis: '' })

async function load() {
  loading.value = true
  try {
    const data = await investmentsApi.list({ status: status.value })
    items.value = data.items || []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!form.code) {
    ElMessage.warning('请填写代码')
    return
  }
  await investmentsApi.create({ ...form, market: 'CN', status: 'planned', side: 'long' })
  showCreate.value = false
  ElMessage.success('已创建')
  load()
}

async function setStatus(row: InvestmentItem, s: string) {
  await investmentsApi.update(row.id, { status: s })
  load()
}

async function remove(row: InvestmentItem) {
  await ElMessageBox.confirm(`删除 ${row.code}?`, '确认')
  await investmentsApi.remove(row.id)
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
