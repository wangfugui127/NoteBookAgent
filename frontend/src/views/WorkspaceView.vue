<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AddSourceDialog from '../components/AddSourceDialog.vue'
import ChatPanel from '../components/ChatPanel.vue'
import SourcesPanel from '../components/SourcesPanel.vue'
import StudioPanel from '../components/StudioPanel.vue'
import ToastStack from '../components/ToastStack.vue'
import { useApprovalMode } from '../composables/useApprovalMode'
import { useConversation } from '../composables/useConversation'
import { useDocuments } from '../composables/useDocuments'
import { useHotkeys } from '../composables/useHotkeys'
import { useRunStream } from '../composables/useRunStream'
import { useToasts } from '../composables/useToasts'
import type { ApprovalMode, Citation, DocumentItem } from '../types'

const route = useRoute()
const notebookId = String(route.params.id)

const { toasts, push, dismiss } = useToasts()
const {
  approvalMode,
  load: loadApprovalMode,
  save: saveApprovalMode,
} = useApprovalMode()

function onApprovalModeChange(mode: ApprovalMode) {
  void saveApprovalMode(mode)
}

const { documents, selected, load, toggle, startPolling, stopPolling } = useDocuments(notebookId, {
  onGraphTransition,
})

const {
  conversations,
  conversationId,
  messages,
  load: loadConversation,
  createConversation,
  selectConversation,
  removeConversation,
  refreshConversations,
  append,
} = useConversation(notebookId)
const {
  liveText,
  status,
  running,
  trace,
  approvals,
  error,
  start,
  stop,
  reset,
  resolveApproval,
} = useRunStream()

const draft = ref('')
const activeCitationId = ref('')
const activeSourceId = ref('')
const activeCitations = ref<Citation[]>([])
const dialogOpen = ref(false)
const sourcesOpen = ref(false)
const studioOpen = ref(false)
const chatRef = ref<InstanceType<typeof ChatPanel>>()

const SOURCES_KEY = `notebookagent:panel:sources:${notebookId}`
const STUDIO_KEY = `notebookagent:panel:studio:${notebookId}`
const sourcesHidden = ref(localStorage.getItem(SOURCES_KEY) === 'hidden')
const studioHidden = ref(localStorage.getItem(STUDIO_KEY) === 'hidden')
const viewportWidth = ref(window.innerWidth)

const narrowStudio = computed(() => viewportWidth.value <= 1280)
const narrowSources = computed(() => viewportWidth.value <= 1024)
const sourcesCollapsed = computed(() => !narrowSources.value && sourcesHidden.value)
const studioCollapsed = computed(() => !narrowStudio.value && studioHidden.value)
const sourcesShown = computed(() => (narrowSources.value ? sourcesOpen.value : !sourcesHidden.value))
const studioShown = computed(() => (narrowStudio.value ? studioOpen.value : !studioHidden.value))

const gridStyle = computed(() => {
  if (narrowSources.value) return { gridTemplateColumns: 'minmax(0, 1fr)' }
  if (narrowStudio.value) {
    return {
      gridTemplateColumns: sourcesCollapsed.value
        ? 'minmax(0, 1fr)'
        : 'var(--panel-left) minmax(0, 1fr)',
    }
  }
  const columns: string[] = []
  if (!sourcesCollapsed.value) columns.push('var(--panel-left)')
  columns.push('minmax(0, 1fr)')
  if (!studioCollapsed.value) columns.push('var(--panel-right)')
  return { gridTemplateColumns: columns.join(' ') }
})

function onResize() {
  viewportWidth.value = window.innerWidth
}

function toggleSources() {
  if (narrowSources.value) {
    sourcesOpen.value = !sourcesOpen.value
    return
  }
  sourcesHidden.value = !sourcesHidden.value
  localStorage.setItem(SOURCES_KEY, sourcesHidden.value ? 'hidden' : 'shown')
}

function toggleStudio() {
  if (narrowStudio.value) {
    studioOpen.value = !studioOpen.value
    return
  }
  studioHidden.value = !studioHidden.value
  localStorage.setItem(STUDIO_KEY, studioHidden.value ? 'hidden' : 'shown')
}

function onGraphTransition(doc: DocumentItem, previous: string) {
  if (doc.graph_status === 'ready' && previous !== 'ready') {
    push(`《${doc.title}》图谱索引已就绪，可用 GraphRAG 检索`)
  } else if (doc.graph_status === 'failed') {
    push(`《${doc.title}》图谱索引失败，可稍后重试`, 'error')
  }
}

function revealStudio() {
  if (narrowStudio.value) {
    studioOpen.value = true
  } else if (studioHidden.value) {
    studioHidden.value = false
    localStorage.setItem(STUDIO_KEY, 'shown')
  }
}

function selectCitation(evidenceId: string, citations?: Citation[]) {
  if (citations?.length) activeCitations.value = citations
  activeCitationId.value = evidenceId
  revealStudio()
  const source = activeCitations.value.find((item) => item.evidence_id === evidenceId)
  if (source?.source_id) activeSourceId.value = source.source_id
}

function send(text: string) {
  if (running.value || !conversationId.value) return
  append({ role: 'user', content: text })
  activeCitations.value = []
  activeCitationId.value = ''
  void start({
    conversationId: conversationId.value,
    query: text,
    attachmentIds: selected.value,
    approvalMode: approvalMode.value,
    onApproval: (payload) => {
      push(`需要你确认：${payload.tool}。${payload.reason || ''}`, 'error')
      revealStudio()
    },
    onComplete: (answer, citations) => {
      append({ role: 'assistant', content: answer, citations })
      activeCitations.value = citations
      if (citations.length === 1) selectCitation(citations[0].evidence_id)
      void refreshConversations()
    },
  })
}

function resetViewState() {
  stop()
  reset()
  activeCitations.value = []
  activeCitationId.value = ''
  activeSourceId.value = ''
}

async function onNewConversation() {
  if (running.value) return
  resetViewState()
  try {
    await createConversation()
  } catch {
    push('新建对话失败，请稍后重试', 'error')
  }
}

async function onSelectConversation(id: string) {
  if (running.value || id === conversationId.value) return
  resetViewState()
  try {
    await selectConversation(id)
  } catch {
    push('切换对话失败，请稍后重试', 'error')
  }
}

async function onDeleteConversation(id: string) {
  if (running.value) return
  resetViewState()
  try {
    await removeConversation(id)
    push('对话已删除')
  } catch (value: any) {
    const detail = value?.response?.data?.detail
    push(detail === '对话正在运行，请先停止' ? detail : '删除对话失败，请稍后重试', 'error')
  }
}

function openAddSource() {
  dialogOpen.value = true
}

async function onUploaded() {
  await load()
  push('已提交解析，完成后会自动出现在来源列表')
}

function onAskPaper(prompt: string) {
  draft.value = prompt
  chatRef.value?.focus()
}

useHotkeys([
  {
    combo: 'mod+k',
    handler: (event) => {
      event.preventDefault()
      chatRef.value?.focus()
    },
  },
  {
    combo: 'escape',
    handler: () => {
      if (dialogOpen.value) return
      studioOpen.value = false
      sourcesOpen.value = false
    },
  },
])

onMounted(async () => {
  await Promise.all([load(), loadConversation(), loadApprovalMode()])
  const latestCited = [...messages.value]
    .reverse()
    .find((message) => message.role === 'assistant' && message.citations?.length)
  if (latestCited?.citations) activeCitations.value = latestCited.citations
  window.addEventListener('resize', onResize)
  startPolling()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  stopPolling()
  stop()
})
</script>

<template>
  <section class="workspace" :style="gridStyle">
    <SourcesPanel
      v-show="!sourcesCollapsed"
      :documents="documents"
      :selected="selected"
      :active-source-id="activeSourceId"
      :open="sourcesOpen"
      @toggle="toggle"
      @select="activeSourceId = $event"
      @add="openAddSource"
      @collapse="toggleSources"
    />

    <ChatPanel
      ref="chatRef"
      v-model:draft="draft"
      v-model:approval-mode="approvalMode"
      :messages="messages"
      :live-text="liveText"
      :running="running"
      :status="status"
      :approvals="approvals"
      :active-citation-id="activeCitationId"
      :error="error"
      :attachment-count="selected.length"
      :sources-shown="sourcesShown"
      :studio-shown="studioShown"
      :conversations="conversations"
      :conversation-id="conversationId"
      @send="send"
      @update:approval-mode="onApprovalModeChange"
      @resolve="(id, decision) => resolveApproval(id, decision)"
      @select-citation="selectCitation"
      @toggle-sources="toggleSources"
      @toggle-studio="toggleStudio"
      @new-conversation="onNewConversation"
      @select-conversation="onSelectConversation"
      @delete-conversation="onDeleteConversation"
    />

    <StudioPanel
      v-show="!studioCollapsed"
      :citations="activeCitations"
      :active-citation-id="activeCitationId"
      :trace="trace"
      :notebook-id="notebookId"
      :open="studioOpen"
      @select-citation="selectCitation"
      @collapse="toggleStudio"
    />

    <AddSourceDialog
      v-model:open="dialogOpen"
      :notebook-id="notebookId"
      @uploaded="onUploaded"
      @ask-paper="onAskPaper"
    />

    <ToastStack :toasts="toasts" @dismiss="dismiss" />
  </section>
</template>
