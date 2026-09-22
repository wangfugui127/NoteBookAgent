<script setup lang="ts">
import { ref } from 'vue'
import MarkdownBody from './MarkdownBody.vue'
import { parseMarkdown, hasInlineCitation } from '../utils/markdown'
import type { Citation } from '../types'

const props = defineProps<{
  messages: { id?: string; role: string; content: string; citations?: Citation[] }[]
  liveText: string
  running: boolean
  status: string
  approvals: any[]
  activeCitationId?: string
  error?: string
  attachmentCount?: number
}>()

const emit = defineEmits<{
  send: [text: string]
  resolve: [id: string, decision: 'approved' | 'rejected']
  selectCitation: [evidenceId: string, citations?: Citation[]]
}>()

const draft = defineModel<string>('draft', { default: '' })
const textarea = ref<HTMLTextAreaElement>()

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

defineExpose({ focus })
</script>

<template>
  <section class="panel panel--chat">
    <header class="chat__head">
      <div>
        <h1>研究对话</h1>
        <p>每条结论都能回到页码、字符区间与 chunk</p>
      </div>
      <span class="chat__status" :data-state="running ? 'active' : 'idle'">
        <span v-if="running" class="streaming-dot" aria-hidden="true" />
        {{ running ? statusLabel(status) : '就绪' }}
      </span>
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
        :disabled="running"
        placeholder="比较这些论文的方法、数据集和结论，并给出可定位的引用……"
        @keydown.ctrl.enter.prevent="submit"
        @keydown.meta.enter.prevent="submit"
      />
      <div class="composer__bar">
        <span>{{ attachmentCount || 0 }} 篇全文附件 · Ctrl + Enter 发送</span>
        <button class="btn btn--primary" :disabled="running || !draft.trim()">
          {{ running ? '运行中' : '开始研究' }}
        </button>
      </div>
    </form>
  </section>
</template>
