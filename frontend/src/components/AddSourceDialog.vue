<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { Paper } from '../types'

const props = defineProps<{ notebookId: string }>()
const emit = defineEmits<{ uploaded: []; askPaper: [prompt: string] }>()
const open = defineModel<boolean>('open', { default: false })

type TabId = 'local' | 'web' | 'agent'
const activeTab = ref<TabId>('local')

interface UploadFile {
  id: number
  file: File
  state: 'queued' | 'uploading' | 'done' | 'failed'
  progress: number
  error?: string
}

const files = ref<UploadFile[]>([])
const uploading = ref(false)
const isOver = ref(false)
let fileSeq = 0

const query = ref('')
const yearFrom = ref<number | undefined>()
const yearTo = ref<number | undefined>()
const results = ref<Paper[]>([])
const searching = ref(false)
const searchError = ref('')

function reset() {
  files.value = []
  results.value = []
  query.value = ''
  yearFrom.value = undefined
  yearTo.value = undefined
  searchError.value = ''
  activeTab.value = 'local'
}

function close() {
  if (uploading.value) return
  open.value = false
}

function addFiles(list: FileList | null) {
  if (!list) return
  for (const file of Array.from(list)) {
    files.value.push({ id: ++fileSeq, file, state: 'queued', progress: 0 })
  }
}

function onFileInput(event: Event) {
  const target = event.target as HTMLInputElement
  addFiles(target.files)
  target.value = ''
}

function onDrop(event: DragEvent) {
  isOver.value = false
  addFiles(event.dataTransfer?.files ?? null)
}

async function uploadAll() {
  if (!files.value.length || uploading.value) return
  uploading.value = true
  for (const item of files.value) {
    if (item.state === 'done') continue
    const body = new FormData()
    body.append('file', item.file)
    item.state = 'uploading'
    item.progress = 0
    try {
      await api.post(`/notebooks/${props.notebookId}/documents`, body, {
        onUploadProgress: (event) => {
          if (event.total) item.progress = Math.round((event.loaded / event.total) * 100)
        },
      })
      item.state = 'done'
      item.progress = 100
    } catch (value: any) {
      item.state = 'failed'
      item.error = value.response?.data?.detail || '上传失败'
    }
  }
  uploading.value = false
  emit('uploaded')
}

async function searchPapers() {
  if (query.value.trim().length < 2 || searching.value) return
  searching.value = true
  searchError.value = ''
  try {
    const { data } = await api.get(`/notebooks/${props.notebookId}/papers/search`, {
      params: { q: query.value, year_from: yearFrom.value, year_to: yearTo.value, limit: 25 },
    })
    results.value = data.items
  } catch (value: any) {
    searchError.value = value.response?.data?.detail || '外部论文检索失败。'
  } finally {
    searching.value = false
  }
}

function askPaper(paper: Paper) {
  const prompt = [
    '请核对这篇外部论文线索，并与 Notebook 中的全文证据比较：',
    '标题：' + paper.title,
    '作者：' + paper.authors.join(', '),
    '年份：' + (paper.year || '未知'),
    'OpenAlex ID：' + paper.paper_id,
    '注意：当前只有外部元数据和摘要线索，不要把它当成已读取的论文全文。',
  ].join('\n')
  emit('askPaper', prompt)
  open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) close()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

watch(open, (value) => {
  if (value) {
    reset()
    nextTick(() => document.getElementById('add-source-dialog')?.focus())
  }
})
</script>

<template>
  <template v-if="open">
    <button class="scrim" type="button" aria-label="关闭" @click="close" />
    <div
      id="add-source-dialog"
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-label="添加来源"
      tabindex="-1"
    >
      <header class="dialog__head">
        <h2>添加来源</h2>
        <button class="btn btn--quiet btn--sm" type="button" aria-label="关闭" @click="close">✕</button>
      </header>

      <div class="dialog__tabs" role="tablist">
        <button class="dialog__tab" :class="{ 'is-active': activeTab === 'local' }" role="tab" @click="activeTab = 'local'">
          本地文件
        </button>
        <button class="dialog__tab" :class="{ 'is-active': activeTab === 'web' }" role="tab" @click="activeTab = 'web'">
          网页搜索
        </button>
        <button class="dialog__tab" :class="{ 'is-active': activeTab === 'agent' }" role="tab" @click="activeTab = 'agent'">
          Agent 对话
        </button>
      </div>

      <div class="dialog__body">
        <template v-if="activeTab === 'local'">
          <label
            class="dropzone"
            :class="{ 'is-over': isOver }"
            @dragover.prevent="isOver = true"
            @dragleave.prevent="isOver = false"
            @drop.prevent="onDrop"
          >
            <input
              type="file"
              accept=".pdf,.txt,.md"
              multiple
              hidden
              @change="onFileInput"
            />
            <strong>把 PDF 拖到这里，或点击选择</strong>
            <span>支持 PDF、TXT、Markdown，单个不超过 100 MB</span>
          </label>

          <div v-if="files.length" class="file-list">
            <div v-for="item in files" :key="item.id" class="file-row">
              <div>
                <div class="file-row__name">{{ item.file.name }}</div>
                <div class="progress" v-if="item.state === 'uploading'"><i :style="{ width: item.progress + '%' }" /></div>
                <div v-else-if="item.error" class="file-row__state" data-state="failed">{{ item.error }}</div>
              </div>
              <span class="file-row__state" :data-state="item.state">
                {{ item.state === 'queued' ? '待上传' : item.state === 'uploading' ? item.progress + '%' : item.state === 'done' ? '已提交' : '失败' }}
              </span>
            </div>
          </div>

          <div style="display: flex; justify-content: flex-end; margin-top: 16px">
            <button class="btn btn--primary" type="button" :disabled="!files.length || uploading" @click="uploadAll">
              {{ uploading ? '上传中…' : '上传并解析' }}
            </button>
          </div>
        </template>

        <template v-else-if="activeTab === 'web'">
          <form class="source-search-form" @submit.prevent="searchPapers">
            <label class="field">
              <span>研究主题</span>
              <input v-model="query" class="input" placeholder="例如：remote sensing wildfire change detection" />
            </label>
            <div class="source-search-form__row">
              <label class="field">
                <span>起始年份</span>
                <input v-model="yearFrom" class="input" type="number" min="1800" max="2200" placeholder="2020" />
              </label>
              <label class="field">
                <span>截止年份</span>
                <input v-model="yearTo" class="input" type="number" min="1800" max="2200" placeholder="2026" />
              </label>
              <button class="btn btn--primary" :disabled="searching">{{ searching ? '检索中' : '搜索' }}</button>
            </div>
          </form>

          <p v-if="searchError" class="form-error" style="margin-top: 12px">{{ searchError }}</p>

          <div v-if="results.length" class="result-list">
            <div v-for="paper in results" :key="paper.paper_id" class="result-item">
              <div>
                <h3>{{ paper.title }}</h3>
                <p>{{ paper.year || '—' }} · {{ paper.authors.slice(0, 3).join(', ') }}{{ paper.authors.length > 3 ? ' 等' : '' }} · 被引 {{ paper.citation_count }}</p>
              </div>
              <button class="btn btn--outline btn--sm" type="button" @click="askPaper(paper)">带入对话</button>
            </div>
          </div>
          <p v-else class="empty-note" style="margin-top: 16px">
            输入主题后检索 OpenAlex。结果只是元数据线索，带入对话后由 Agent 决定如何使用。
          </p>
        </template>

        <template v-else>
          <p class="empty-note">
            让 Agent 通过检索工具来扩充来源：先用自然语言描述你想要的资料，Agent 会在对话中调用搜索工具，
            把结果加入 Notebook。该能力依赖已连接的工具，当前可在右栏「工具」查看可用性。
          </p>
        </template>
      </div>
    </div>
  </template>
</template>
