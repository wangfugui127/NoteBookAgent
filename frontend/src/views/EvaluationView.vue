<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { useEvaluations } from '../composables/useEvaluations'
import type { EvalCaseInput, EvalCaseItem } from '../types'

interface Notebook {
  id: string
  title: string
}

const evalApi = useEvaluations()

const notebooks = ref<Notebook[]>([])
const selectedNotebook = ref('')
const error = ref('')

const newDatasetName = ref('')
const showJsonDialog = ref(false)
const jsonText = ref('')
const jsonReplace = ref(false)

const missingSources = ref<{ case_key: string; question: string; missing: string[] }[]>([])

const editingId = ref('')
const formQuestion = ref('')
const formTools = ref('')
const formSources = ref('')
const formKeywords = ref('')

const filterFailed = ref(false)
const sortByScore = ref(true)
const expandedId = ref('')

const ROUTE_HINTS = ['search_notebook', 'get_notebook_items', 'list_notebook_sources', 'search_papers']

function parseList(value: string): string[] {
  return value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function formatList(values: string[] | undefined): string {
  return (values || []).join('，')
}

function pct(value: number | null | undefined) {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

function scoreText(value: number | null) {
  return value == null ? '—' : String(Math.round(value * 100))
}

function latency(value: number | null | undefined) {
  if (value == null) return '—'
  return `${(value / 1000).toFixed(1)}s`
}

const currentDataset = computed(() => evalApi.detail.value)

const filteredResults = computed(() => {
  let items = [...evalApi.results.value]
  if (filterFailed.value) items = items.filter((item) => !item.passed)
  if (sortByScore.value) {
    items.sort((a, b) => (b.total_score ?? -1) - (a.total_score ?? -1))
  }
  return items
})

const progress = computed(() => {
  const run = evalApi.run.value
  if (!run || !run.total_cases) return 0
  return Math.round((run.completed_cases / run.total_cases) * 100)
})

const runActive = computed(
  () => !!evalApi.run.value && ['pending', 'running'].includes(evalApi.run.value.status),
)

async function loadNotebooks() {
  try {
    notebooks.value = (await api.get('/notebooks')).data
    if (!selectedNotebook.value && notebooks.value.length) {
      selectedNotebook.value = notebooks.value[0].id
    }
  } catch {
    error.value = 'Notebook 列表加载失败。'
  }
}

async function selectDataset(id: string) {
  evalApi.resetRun()
  error.value = ''
  await evalApi.loadDetail(id)
}

async function createDataset() {
  const name = newDatasetName.value.trim()
  if (!name) return
  try {
    await evalApi.createDataset(name)
    newDatasetName.value = ''
  } catch {
    error.value = '创建评测集失败。'
  }
}

async function importDefault() {
  try {
    await evalApi.importDefaultDataset()
  } catch {
    error.value = '导入示例评测集失败。'
  }
}

async function submitImport() {
  if (!evalApi.activeId.value) {
    error.value = '先选择一个评测集。'
    return
  }
  try {
    const cases = JSON.parse(jsonText.value)
    const list = (Array.isArray(cases) ? cases : cases.cases) as EvalCaseInput[]
    await evalApi.importCases(evalApi.activeId.value, list, jsonReplace.value)
    showJsonDialog.value = false
    jsonText.value = ''
  } catch {
    error.value = 'JSON 解析或导入失败，请检查格式。'
  }
}

function resetForm() {
  editingId.value = ''
  formQuestion.value = ''
  formTools.value = ''
  formSources.value = ''
  formKeywords.value = ''
}

function editCase(item: EvalCaseItem) {
  editingId.value = item.id
  formQuestion.value = item.question
  formTools.value = formatList(item.expected_tools)
  formSources.value = formatList(item.expected_source_titles)
  formKeywords.value = formatList(item.required_keywords)
}

async function submitCase() {
  const question = formQuestion.value.trim()
  if (!question || !evalApi.activeId.value) return
  const payload: EvalCaseInput = {
    question,
    expected_tools: parseList(formTools.value),
    expected_source_titles: parseList(formSources.value),
    required_keywords: parseList(formKeywords.value),
  }
  try {
    if (editingId.value) await evalApi.updateCase(editingId.value, payload)
    else await evalApi.addCase(evalApi.activeId.value, payload)
    resetForm()
  } catch {
    error.value = '保存题目失败。'
  }
}

async function removeCase(id: string) {
  try {
    if (editingId.value === id) resetForm()
    await evalApi.deleteCase(id)
  } catch {
    error.value = '删除题目失败。'
  }
}

async function removeDataset() {
  const dataset = currentDataset.value
  if (!dataset) return
  if (!window.confirm(`删除评测集「${dataset.name}」？历史评测结果会保留。`)) return
  try {
    await evalApi.deleteDataset(dataset.id)
  } catch {
    error.value = '删除评测集失败。'
  }
}

async function runEvaluation(allowMissing = false) {
  const dataset = currentDataset.value
  if (!dataset) return
  if (!selectedNotebook.value) {
    error.value = '请先选择要评测的 Notebook。'
    return
  }
  error.value = ''
  try {
    await evalApi.startRun(dataset.id, selectedNotebook.value, allowMissing)
    missingSources.value = []
    await evalApi.loadHistory(selectedNotebook.value)
  } catch (value: any) {
    const detail = value?.response?.data?.detail
    if (value?.response?.status === 409 && detail?.missing_sources) {
      missingSources.value = detail.missing_sources
    } else {
      error.value = typeof detail === 'string' ? detail : '启动评测失败。'
    }
  }
}

async function confirmForceRun() {
  missingSources.value = []
  await runEvaluation(true)
}

function cancelRun() {
  const run = evalApi.run.value
  if (!run) return
  void evalApi.cancelRun(run.id)
}

async function openHistory() {
  await evalApi.loadHistory(selectedNotebook.value || undefined)
}

onMounted(async () => {
  await Promise.all([loadNotebooks(), evalApi.loadDatasets()])
  if (evalApi.datasets.value.length) {
    await selectDataset(evalApi.datasets.value[0].id)
  }
  await openHistory()
})

onBeforeUnmount(() => evalApi.stopPolling())
</script>

<template>
  <section class="eval">
    <header class="eval__head">
      <div>
        <p class="kicker">固定评测集 · Golden Sample</p>
        <h1 class="eval__title">评测中心</h1>
        <p class="eval__lead">用固定题目重跑真实 Agent，对比工具路由、检索命中与引用质量。</p>
      </div>
      <div class="eval__head-actions">
        <form class="eval__create" @submit.prevent="createDataset">
          <input v-model="newDatasetName" class="input" placeholder="新评测集名称" />
          <button class="btn btn--outline" type="submit">新建</button>
        </form>
        <button class="btn btn--quiet" type="button" @click="importDefault">导入示例评测集</button>
      </div>
    </header>

    <p v-if="error" class="form-error" role="alert">{{ error }}</p>

    <div class="eval__grid">
      <aside class="eval__list">
        <h2 class="eval__section-title">评测集</h2>
        <button
          v-for="item in evalApi.datasets.value"
          :key="item.id"
          type="button"
          class="dataset-card"
          :class="{ 'is-active': item.id === evalApi.activeId.value }"
          @click="selectDataset(item.id)"
        >
          <span class="dataset-card__name">{{ item.name }}</span>
          <span class="dataset-card__meta">
            {{ item.case_count }} 题
            <template v-if="item.latest_run">
              · 最近 {{ pct(item.latest_run.pass_rate) }}
            </template>
          </span>
        </button>
        <p v-if="!evalApi.datasets.value.length" class="empty-note">
          还没有评测集。新建一个，或导入示例评测集。
        </p>
      </aside>

      <main class="eval__main">
        <template v-if="currentDataset">
          <div class="eval__main-head">
            <div>
              <h2 class="eval__dataset-name">{{ currentDataset.name }}</h2>
              <p class="eval__dataset-desc">{{ currentDataset.description || '未填写说明' }}</p>
            </div>
            <div class="eval__main-actions">
              <button class="btn btn--quiet btn--sm" type="button" @click="showJsonDialog = true">
                导入 JSON
              </button>
              <button class="btn btn--danger btn--sm" type="button" @click="removeDataset">
                删除评测集
              </button>
            </div>
          </div>

          <div class="eval-cases">
            <h3 class="eval__section-title">固定题目</h3>
            <div v-for="item in currentDataset.cases" :key="item.id" class="eval-case">
              <div class="eval-case__body">
                <p class="eval-case__q">{{ item.question }}</p>
                <p class="eval-case__meta">
                  工具：{{ formatList(item.expected_tools) || '—' }} ·
                  来源：{{ formatList(item.expected_source_titles) || '—' }} ·
                  关键点：{{ formatList(item.required_keywords) || '—' }}
                </p>
              </div>
              <div class="eval-case__actions">
                <button class="btn btn--quiet btn--sm" type="button" @click="editCase(item)">编辑</button>
                <button class="btn btn--quiet btn--sm" type="button" @click="removeCase(item.id)">删除</button>
              </div>
            </div>
            <p v-if="!currentDataset.cases.length" class="empty-note">还没有题目，请在下方添加。</p>
          </div>

          <form class="eval-case-form" @submit.prevent="submitCase">
            <h3 class="eval__section-title">{{ editingId ? '编辑题目' : '添加题目' }}</h3>
            <textarea
              v-model="formQuestion"
              class="textarea"
              rows="2"
              placeholder="固定问题，例如：比较论文 A 和论文 B 使用的研究方法"
            />
            <div class="eval-case-form__grid">
              <label class="field">
                <span>期望工具（逗号分隔）</span>
                <input v-model="formTools" class="input" :placeholder="ROUTE_HINTS.join('，')" />
              </label>
              <label class="field">
                <span>期望来源文档标题（逗号分隔）</span>
                <input v-model="formSources" class="input" placeholder="例如：水稻遥感，小麦产量" />
              </label>
              <label class="field">
                <span>关键点（逗号分隔）</span>
                <input v-model="formKeywords" class="input" placeholder="例如：数据集，实验，结论" />
              </label>
            </div>
            <div class="eval-case-form__actions">
              <button v-if="editingId" class="btn btn--quiet btn--sm" type="button" @click="resetForm">
                取消
              </button>
              <button class="btn btn--primary btn--sm" type="submit">
                {{ editingId ? '保存' : '添加' }}
              </button>
            </div>
          </form>

          <div class="eval-run">
            <h3 class="eval__section-title">运行评测</h3>
            <div class="eval-run__bar">
              <label class="field">
                <span>目标 Notebook</span>
                <select v-model="selectedNotebook" class="input">
                  <option v-for="nb in notebooks" :key="nb.id" :value="nb.id">{{ nb.title }}</option>
                </select>
              </label>
              <button
                class="btn btn--primary"
                type="button"
                :disabled="runActive"
                @click="runEvaluation(false)"
              >
                开始评测
              </button>
            </div>
          </div>
        </template>
        <p v-else class="empty-note">从左侧选择一个评测集，或新建一个开始。</p>
      </main>
    </div>

    <section v-if="evalApi.run.value" class="eval-report">
      <div class="eval-report__head">
        <div>
          <h2 class="eval__section-title">评测进度 · {{ evalApi.run.value.dataset_name }}</h2>
          <p class="eval-report__sub">
            {{ evalApi.run.value.completed_cases }} / {{ evalApi.run.value.total_cases }} 题
            <template v-if="evalApi.run.value.current_case_key">
              · 当前：{{ evalApi.run.value.current_case_key }}
            </template>
          </p>
        </div>
        <button v-if="runActive" class="btn btn--danger btn--sm" type="button" @click="cancelRun">
          取消
        </button>
      </div>

      <div class="eval-progress"><span :style="{ width: `${progress}%` }" /></div>

      <div v-if="!runActive" class="eval-metrics">
        <div class="metric">
          <span class="metric__value">{{ pct(evalApi.run.value.metrics.pass_rate) }}</span>
          <span class="metric__label">通过率</span>
        </div>
        <div class="metric">
          <span class="metric__value">{{ pct(evalApi.run.value.metrics.route_accuracy) }}</span>
          <span class="metric__label">工具路由</span>
        </div>
        <div class="metric">
          <span class="metric__value">{{ pct(evalApi.run.value.metrics.retrieval_accuracy) }}</span>
          <span class="metric__label">检索命中</span>
        </div>
        <div class="metric">
          <span class="metric__value">{{ pct(evalApi.run.value.metrics.citation_accuracy) }}</span>
          <span class="metric__label">引用正确率</span>
        </div>
        <div class="metric">
          <span class="metric__value">{{ pct(evalApi.run.value.metrics.keyword_coverage) }}</span>
          <span class="metric__label">关键点覆盖</span>
        </div>
        <div class="metric">
          <span class="metric__value">{{ latency(evalApi.run.value.metrics.avg_latency_ms) }}</span>
          <span class="metric__label">平均耗时</span>
        </div>
      </div>

      <p v-if="evalApi.run.value.error_message" class="form-error">
        {{ evalApi.run.value.error_message }}
      </p>

      <div v-if="evalApi.results.value.length" class="eval-results">
        <div class="eval-results__toolbar">
          <label class="check">
            <input v-model="filterFailed" type="checkbox" /> 只看失败
          </label>
          <label class="check">
            <input v-model="sortByScore" type="checkbox" /> 按总分排序
          </label>
        </div>
        <table class="eval-table">
          <thead>
            <tr>
              <th>问题</th>
              <th>路由</th>
              <th>检索</th>
              <th>引用</th>
              <th>总分</th>
              <th>状态</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="item in filteredResults" :key="item.id">
              <tr
                class="eval-table__row"
                :class="`is-${item.status}`"
                @click="expandedId = expandedId === item.id ? '' : item.id"
              >
                <td class="eval-table__q">{{ item.question }}</td>
                <td>{{ scoreText(item.route_score) }}</td>
                <td>{{ scoreText(item.retrieval_score) }}</td>
                <td>{{ scoreText(item.citation_score) }}</td>
                <td class="eval-table__total">{{ item.total_score ?? '—' }}</td>
                <td><span class="status-chip" :class="`status-chip--${item.status}`">{{ item.status }}</span></td>
                <td>{{ latency(item.latency_ms) }}</td>
              </tr>
              <tr v-if="expandedId === item.id" class="eval-table__detail">
                <td colspan="7">
                  <div class="eval-detail">
                    <p><strong>实际工具：</strong>{{ item.actual_tools.join('，') || '未调用' }}</p>
                    <p><strong>命中来源：</strong>{{ item.matched_sources.join('，') || '—' }}</p>
                    <p v-if="item.missing_sources.length" class="eval-detail__warn">
                      <strong>缺失文档：</strong>{{ item.missing_sources.join('，') }}（检索与引用已记 0）
                    </p>
                    <p><strong>命中关键点：</strong>{{ item.matched_keywords.join('，') || '—' }}</p>
                    <p v-if="item.error_message" class="eval-detail__warn">
                      <strong>错误：</strong>{{ item.error_message }}
                    </p>
                    <details>
                      <summary>查看 Agent 回答</summary>
                      <pre class="eval-detail__answer">{{ item.answer || '（无回答）' }}</pre>
                    </details>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="evalApi.history.value.length" class="eval-history">
      <h2 class="eval__section-title">历史评测</h2>
      <button
        v-for="item in evalApi.history.value"
        :key="item.id"
        type="button"
        class="history-row"
        @click="evalApi.loadRun(item.id)"
      >
        <span>{{ item.dataset_name }}</span>
        <span class="history-row__meta">
          {{ new Date(item.created_at).toLocaleString() }} · {{ item.status }} ·
          {{ item.passed_cases }}/{{ item.total_cases }}
        </span>
      </button>
    </section>

    <div v-if="showJsonDialog" class="modal">
      <div class="modal__box">
        <h3>导入题目 JSON</h3>
        <p class="empty-note">支持数组，或 {"cases": [...]}。字段：question、expected_tools、expected_source_titles、required_keywords。</p>
        <textarea v-model="jsonText" class="textarea" rows="8" placeholder="[{'question':'...','required_keywords':['数据集']}]" />
        <label class="check"><input v-model="jsonReplace" type="checkbox" /> 覆盖现有题目</label>
        <div class="modal__actions">
          <button class="btn btn--quiet" type="button" @click="showJsonDialog = false">取消</button>
          <button class="btn btn--primary" type="button" @click="submitImport">导入</button>
        </div>
      </div>
    </div>

    <div v-if="missingSources.length" class="modal">
      <div class="modal__box">
        <h3>目标 Notebook 缺少预期文档</h3>
        <p class="empty-note">以下题目的期望来源在所选 Notebook 中找不到匹配文档。可补充文档，或仍然开始（对应检索/引用记 0）。</p>
        <ul class="missing-list">
          <li v-for="entry in missingSources" :key="entry.case_key">
            <strong>{{ entry.question }}</strong>
            <span>{{ entry.missing.join('，') }}</span>
          </li>
        </ul>
        <div class="modal__actions">
          <button class="btn btn--quiet" type="button" @click="missingSources = []">取消</button>
          <button class="btn btn--danger" type="button" @click="confirmForceRun">仍然开始</button>
        </div>
      </div>
    </div>
  </section>
</template>
