<script setup lang="ts">
import { computed } from 'vue'
import type { DocumentItem } from '../types'

const props = defineProps<{ doc: DocumentItem }>()

const label = computed(() => {
  if (props.doc.status !== 'ready') {
    return props.doc.status === 'failed' ? '处理失败' : '处理中'
  }
  if (props.doc.graph_status === 'building') return '图谱构建中'
  if (props.doc.graph_status === 'failed') return '图谱失败'
  return '可检索'
})

const tone = computed(() => {
  if (props.doc.status !== 'ready') {
    return props.doc.status === 'failed' ? 'badge--failed' : 'badge--processing'
  }
  if (props.doc.graph_status === 'building') return 'badge--building'
  if (props.doc.graph_status === 'failed') return 'badge--failed'
  return 'badge--ready'
})
</script>

<template>
  <span class="badge" :class="tone">{{ label }}</span>
</template>
