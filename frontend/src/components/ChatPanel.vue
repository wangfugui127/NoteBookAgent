<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MarkdownBody from './MarkdownBody.vue'
import { parseMarkdown, hasInlineCitation } from '../utils/markdown'
import { APPROVAL_MODES } from '../composables/useApprovalMode'
import type { ApprovalMode, Citation, ConversationSummary } from '../types'

const props = defineProps<{
  messages: { id?: string; role: string; content: string; citations?: Citation[] }[]
  liveText: string
  running: boolean
  status: string
  approvals: any[]
  activeCitationId?: string
  error?: string
  attachmentCount?: number
  sourcesShown?: boolean
  studioShown?: boolean
  conversations: ConversationSummary[]
  conversationId?: string
}>()

const emit = defineEmits<{
  send: [text: string]
  resolve: [id: string, decision: 'approved' | 'rejected']
  selectCitation: [evidenceId: string, citations?: Citation[]]
  toggleSources: []
  toggleStudio: []
  newConversation: []
  selectConversation: [id: string]
  deleteConversation: [id: string]
}>()

const draft = defineModel<string>('draft', { default: '' })
const approvalMode = defineModel<ApprovalMode>('approvalMode', { default: 'confirm' })
const textarea = ref<HTMLTextAreaElement>()

const COMPOSER_MAX_HEIGHT = 164
const menuOpen = ref(false)
const pendingDelete = ref('')
const convoRef = ref<HTMLElement>()

const currentTitle = computed(
  () =>
    props.conversations.find((item) => item.id === props.conversationId)?.title || '研究对话',
)

function relativeTime(value: string) {
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return ''
  const diff = Date.now() - time
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 2 * day) return '昨天'
  return new Date(value).toLocaleDateString()
}

function autoGrow() {
  const element = textarea.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, COMPOSER_MAX_HEIGHT)}px`
}

function locator(citation: Citation) {
  const parts: string[] = []
  if (citation.section_title) parts.push(citation.section_title)
  if (citation.page_start != null) parts.push(`页 ${citation.page_start}–${citation.page_end ?? citation.page_start}`)
  if (citation.char_start != null) parts.push(`字符 ${citation.char_start}–${citation.char_end ?? citation.char_start}`)
  return parts.join(' · ') || citation.source_kind
}

function statusLabel(status: string) {
  if (status === 'pending') return '思考中'
  if (status === 'tool_call') return '调用工具'
  if (status === 'tool_result') return '整理证据'
  if (status === 'text_delta') return '生成回答'
  if (status === 'approval_required') return '等待确认'
  if (status === 'context_manifest') return '读取上下文'
  return status.replaceAll('_', ' ')
}

function submit() {
  const value = draft.value.trim()
  if (!value || props.running) return
  emit('send', value)
  draft.value = ''
}

function focus() {
  textarea.value?.focus()
}

function toggleMenu() {
  if (props.running) return
  menuOpen.value = !menuOpen.value
  if (!menuOpen.value) pendingDelete.value = ''
}

function onCreate() {
  menuOpen.value = false
  pendingDelete.value = ''
  emit('newConversation')
}

function onSelect(id: string) {
  if (id === props.conversationId) {
    menuOpen.value = false
    return
  }
  menuOpen.value = false
  pendingDelete.value = ''
  emit('selectConversation', id)
}

function confirmDelete(id: string) {
  pendingDelete.value = ''
  menuOpen.value = false
  emit('deleteConversation', id)
}

function onDocumentClick(event: MouseEvent) {
  if (!menuOpen.value) return
  if (convoRef.value && !convoRef.value.contains(event.target as Node)) {
    menuOpen.value = false
    pendingDelete.value = ''
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && menuOpen.value) {
    menuOpen.value = false
    pendingDelete.value = ''
  }
}

watch(
  () => props.conversationId,
  () => {
    menuOpen.value = false
    pendingDelete.value = ''
  },
)

watch(draft, () => nextTick(autoGrow))
onMounted(() => {
  nextTick(autoGrow)
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})

defineExpose({ focus })
</script>

<template>
  <section class="panel panel--chat">
    <header class="chat__head">
      <div class="chat__head-main">
        <button
          class="icon-btn"
          type="button"
          :aria-pressed="sourcesShown"
          title="显示 / 收起来源面板"
          @click="emit('toggleSources')"
        >
          来源
        </button>
        <div class="chat__head-titles">
          <div ref="convoRef" class="convo">
            <button
              class="convo__trigger"
              type="button"
              :disabled="running"
              :aria-expanded="menuOpen"
              aria-haspopup="menu"
              title="管理研究对话"
              @click="toggleMenu"
            >
              <span class="convo__title">{{ currentTitle }}</span>
              <span class="convo__caret" aria-hidden="true">▾</span>
            </button>

            <div v-if="menuOpen" class="convo-menu" role="menu">
              <button class="convo-menu__new" type="button" role="menuitem" @click="onCreate">
                新建对话
              </button>
              <ul class="convo-menu__list">
                <li
                  v-for="item in conversations"
                  :key="item.id"
                  class="convo-menu__row"
                  :class="{ 'is-active': item.id === conversationId }"
                >
                  <template v-if="pendingDelete === item.id">
                    <span class="convo-menu__confirm">删除这个对话？</span>
                    <button class="convo-menu__danger" type="button" @click="confirmDelete(item.id)">
                      删除
                    </button>
                    <button class="convo-menu__cancel" type="button" @click="pendingDelete = ''">
                      取消
                    </button>
                  </template>
                  <template v-else>
                    <button
                      class="convo-menu__item"
                      type="button"
                      role="menuitem"
                      :disabled="running"
                      @click="onSelect(item.id)"
                    >
                      <span class="convo-menu__item-title">{{ item.title || '未命名对话' }}</span>
                      <time class="convo-menu__item-time">{{ relativeTime(item.updated_at) }}</time>
                    </button>
                    <button
                      class="convo-menu__delete"
                      type="button"
                      :disabled="running"
                      title="删除对话"
                      :aria-label="`删除对话：${item.title || '未命名对话'}`"
                      @click="pendingDelete = item.id"
                    >
                      ✕
                    </button>
                  </template>
                </li>
              </ul>
              <p v-if="!conversations.length" class="convo-menu__empty">还没有对话。</p>
            </div>
          </div>
          <p>每条结论都能回到页码、字符区间与 chunk</p>
        </div>
      </div>
      <div class="chat__head-side">
        <button
          class="icon-btn"
          type="button"
          :aria-pressed="studioShown"
          title="显示 / 收起证据面板"
          @click="emit('toggleStudio')"
        >
          证据
        </button>
        <span class="chat__status" :data-state="running ? 'active' : 'idle'">
          <span v-if="running" class="streaming-dot" aria-hidden="true" />
          {{ running ? statusLabel(status) : '就绪' }}
        </span>
      </div>
    </header>

    <div class="chat__stream scroll-area">
      <div v-if="!messages.length && !liveText" class="chat__empty">
        <h2>提出一个可以被论文验证的问题</h2>
        <p>比较方法、追踪数据集、核对指标，或让 Agent 先搜索相关研究。</p>
      </div>

      <article
        v-for="(message, index) in messages"
        :key="message.id || index"
        class="msg"
        :class="`msg--${message.role}`"
      >
        <header class="msg__meta">
          <span>{{ message.role === 'user' ? '你' : 'NotebookAgent' }}</span>
        </header>
        <div class="msg__body">
          <MarkdownBody
            :blocks="parseMarkdown(message.content)"
            :citations="message.citations"
            :active-citation-id="activeCitationId"
            @select-citation="(id, list) => emit('selectCitation', id, list)"
          />
        </div>
        <div
          v-if="message.citations?.length && !hasInlineCitation(message.content)"
          class="msg__citations"
        >
          <button
            v-for="(citation, citationIndex) in message.citations"
            :key="citation.evidence_id"
            class="cite-chip"
            :class="{ 'is-active': citation.evidence_id === activeCitationId }"
            :title="locator(citation)"
            @click="emit('selectCitation', citation.evidence_id, message.citations)"
          >
            {{ citationIndex + 1 }}
          </button>
        </div>
      </article>

      <article v-if="liveText" class="msg msg--assistant">
        <header class="msg__meta">
          <span class="streaming-dot" aria-hidden="true" />
          <span>NotebookAgent 正在分析</span>
        </header>
        <div class="msg__body">
          <MarkdownBody :blocks="parseMarkdown(liveText)" :active-citation-id="activeCitationId" />
        </div>
      </article>

      <article v-for="approval in approvals" :key="approval.id" class="approval">
        <strong>这个工具会产生外部操作</strong>
        <p>{{ approval.reason }}</p>
        <div class="approval__actions">
          <button class="btn btn--primary btn--sm" type="button" @click="emit('resolve', approval.id, 'approved')">
            允许执行
          </button>
          <button class="btn btn--danger btn--sm" type="button" @click="emit('resolve', approval.id, 'rejected')">
            拒绝
          </button>
        </div>
      </article>
    </div>

    <p v-if="error" class="chat__error" role="alert">{{ error }}</p>

    <form class="composer" @submit.prevent="submit">
      <textarea
        ref="textarea"
        v-model="draft"
        rows="1"
        :disabled="running"
        placeholder="比较这些论文的方法、数据集和结论，并给出可定位的引用……"
        @input="autoGrow"
        @keydown.ctrl.enter.prevent="submit"
        @keydown.meta.enter.prevent="submit"
      />
      <div class="composer__bar">
        <div class="composer__modes" role="group" aria-label="权限模式">
          <button
            v-for="mode in APPROVAL_MODES"
            :key="mode.value"
            class="mode-chip"
            :class="{ 'is-active': approvalMode === mode.value }"
            type="button"
            :title="mode.hint"
            :aria-pressed="approvalMode === mode.value"
            @click="approvalMode = mode.value"
          >
            {{ mode.label }}
          </button>
        </div>
        <div class="composer__send">
          <span>{{ attachmentCount || 0 }} 篇全文附件 · Ctrl + Enter 发送</span>
          <button class="btn btn--primary" :disabled="running || !draft.trim()">
            {{ running ? '运行中' : '开始研究' }}
          </button>
        </div>
      </div>
    </form>
  </section>
</template>
