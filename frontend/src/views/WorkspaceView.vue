<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AddSourceDialog from '../components/AddSourceDialog.vue'
import ChatPanel from '../components/ChatPanel.vue'
import SourcesPanel from '../components/SourcesPanel.vue'
import StudioPanel from '../components/StudioPanel.vue'
import ToastStack from '../components/ToastStack.vue'
import { useConversation } from '../composables/useConversation'
import { useDocuments } from '../composables/useDocuments'
import { useHotkeys } from '../composables/useHotkeys'
import { useRunStream } from '../composables/useRunStream'
import { useToasts } from '../composables/useToasts'
import type { Citation, DocumentItem } from '../types'

const route = useRoute()
const notebookId = String(route.params.id)

const { toasts, push, dismiss } = useToasts()

const { documents, selected, readyCount, load, toggle, startPolling, stopPolling } = useDocuments(
  notebookId,
  { onGraphTransition },
)

const { conversationId, messages, load: loadConversation, append } = useConversation(notebookId)
const {
  liveText,
  status,
  running,
  trace,
  approvals,
  error,
  start,
  stop,
  resolveApproval,
} = useRunStream()

const draft = ref('')
const activeCitationId = ref('')
const activeSourceId = ref('')
const dialogOpen = ref(false)
const studioOpen = ref(false)
const sourcesOpen = ref(false)
const chatRef = ref<InstanceType<typeof ChatPanel>>()

const activeCitations = ref<Citation[]>([])

function onGraphTransition(doc: DocumentItem, previous: string) {
  if (doc.graph_status === 'ready' && previous !== 'ready') {
    push(`《${doc.title}》图谱索引已就绪，可用 GraphRAG 检索`)
  } else if (doc.graph_status === 'failed') {
    push(`《${doc.title}》图谱索引失败，可稍后重试`, 'error')
  }
}

function selectCitation(evidenceId: string, citations?: Citation[]) {
  if (citations?.length) activeCitations.value = citations
  activeCitationId.value = evidenceId
  studioOpen.value = true
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
    onComplete: (answer, citations) => {
      append({ role: 'assistant', content: answer, citations })
      activeCitations.value = citations
      if (citations.length === 1) selectCitation(citations[0].evidence_id)
    },
  })
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
  await Promise.all([load(), loadConversation()])
  const latestCited = [...messages.value]
    .reverse()
    .find((message) => message.role === 'assistant' && message.citations?.length)
  if (latestCited?.citations) activeCitations.value = latestCited.citations
  const paperPrompt = sessionStorage.getItem('paper_prompt:' + notebookId)
  if (paperPrompt) {
    draft.value = paperPrompt
    sessionStorage.removeItem('paper_prompt:' + notebookId)
  }
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
  stop()
})
</script>

<template>
  <section class="workspace">
    <SourcesPanel
      :documents="documents"
      :selected="selected"
      :active-source-id="activeSourceId"
      :open="sourcesOpen"
      @toggle="toggle"
      @select="activeSourceId = $event"
      @add="openAddSource"
      @close="sourcesOpen = false"
    />

    <ChatPanel
      ref="chatRef"
      v-model:draft="draft"
      :messages="messages"
      :live-text="liveText"
      :running="running"
      :status="status"
      :approvals="approvals"
      :active-citation-id="activeCitationId"
      :error="error"
      :attachment-count="selected.length"
      @send="send"
      @resolve="(id, decision) => resolveApproval(id, decision)"
      @select-citation="selectCitation"
    />

    <StudioPanel
      :citations="activeCitations"
      :active-citation-id="activeCitationId"
      :trace="trace"
      :notebook-id="notebookId"
      :open="studioOpen"
      @select-citation="selectCitation"
      @close="studioOpen = false"
    />

    <div class="only-compact" style="position: fixed; z-index: 20; left: 16px; bottom: 16px; gap: 8px">
      <button class="btn btn--outline btn--sm" type="button" @click="sourcesOpen = true">
        来源 · {{ readyCount }}
      </button>
      <button class="btn btn--outline btn--sm" type="button" @click="studioOpen = true">
        证据 · {{ activeCitations.length }}
      </button>
    </div>

    <AddSourceDialog
      v-model:open="dialogOpen"
      :notebook-id="notebookId"
      @uploaded="onUploaded"
      @ask-paper="onAskPaper"
    />

    <ToastStack :toasts="toasts" @dismiss="dismiss" />
  </section>
</template>
