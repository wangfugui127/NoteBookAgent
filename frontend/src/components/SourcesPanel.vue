<script setup lang="ts">
import { computed, ref } from 'vue'
import GraphStatusBadge from './GraphStatusBadge.vue'
import type { DocumentItem } from '../types'

const props = defineProps<{
  documents: DocumentItem[]
  selected: string[]
  activeSourceId?: string
  open?: boolean
}>()

defineEmits<{
  toggle: [id: string]
  select: [id: string]
  add: []
  close: []
}>()

const filter = ref('')

const filtered = computed(() => {
  const value = filter.value.trim().toLowerCase()
  if (!value) return props.documents
  return props.documents.filter((doc) => doc.title.toLowerCase().includes(value))
})

const readyCount = computed(() => props.documents.filter((doc) => doc.status === 'ready').length)
</script>

<template>
  <aside class="panel panel--sources" :class="{ 'is-open': open }">
    <header class="panel__head">
      <h2 class="panel__title">来源</h2>
      <span class="panel__count">{{ readyCount }} / {{ documents.length }} 可用</span>
    </header>

    <div class="sources__toolbar">
      <div class="sources__search">
        <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.5" />
          <path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        </svg>
        <input
          v-model="filter"
          class="input"
          type="search"
          placeholder="筛选来源"
          aria-label="筛选来源"
        />
      </div>
      <button class="btn btn--outline" type="button" @click="$emit('add')">
        <span aria-hidden="true">+</span> 添加来源
      </button>
    </div>

    <div class="source-list">
      <div
        v-for="doc in filtered"
        :key="doc.id"
        class="source-item"
        :class="{ 'is-pending': doc.status !== 'ready', 'is-active': doc.id === activeSourceId }"
        @click="$emit('select', doc.id)"
      >
        <input
          type="checkbox"
          :checked="selected.includes(doc.id)"
          :disabled="doc.status !== 'ready'"
          :aria-label="'作为全文附件：' + doc.title"
          @click.stop
          @change="$emit('toggle', doc.id)"
        />
        <span>
          <span class="source-item__title" :title="doc.title">{{ doc.title }}</span>
          <span class="source-item__meta">
            <GraphStatusBadge :doc="doc" />
          </span>
        </span>
      </div>
      <p v-if="!documents.length" class="empty-note" style="padding: 12px">
        还没有来源。点“添加来源”上传本地 PDF，或搜索外部论文。
      </p>
      <p v-else-if="!filtered.length" class="empty-note" style="padding: 12px">
        没有匹配“{{ filter }}”的来源。
      </p>
    </div>

    <p class="sources__note">
      勾选后，正文会完整进入当前问题；超出安全窗口时按范围连续处理。
    </p>
  </aside>
</template>
