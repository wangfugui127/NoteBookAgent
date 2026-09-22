<script setup lang="ts">
import type { Citation } from '../types'
import type { Inline } from '../utils/markdown'

const props = defineProps<{
  parts: Inline[]
  citations?: Citation[]
  activeCitationId?: string
}>()

const emit = defineEmits<{ selectCitation: [evidenceId: string, citations?: Citation[]] }>()

function indexOf(evidenceId: string) {
  return props.citations?.findIndex((item) => item.evidence_id === evidenceId) ?? -1
}

function locator(evidenceId: string) {
  const citation = props.citations?.find((item) => item.evidence_id === evidenceId)
  if (!citation) return '未匹配到证据'
  const parts: string[] = []
  if (citation.section_title) parts.push(citation.section_title)
  if (citation.page_start != null) parts.push(`页 ${citation.page_start}–${citation.page_end ?? citation.page_start}`)
  if (citation.char_start != null) parts.push(`字符 ${citation.char_start}–${citation.char_end ?? citation.char_start}`)
  return parts.join(' · ') || citation.source_kind
}
</script>

<template>
  <template v-for="(part, index) in parts" :key="index">
    <strong v-if="part.kind === 'bold'">{{ part.value }}</strong>
    <code v-else-if="part.kind === 'code'" class="md__code">{{ part.value }}</code>
    <button
      v-else-if="part.kind === 'cite'"
      class="cite-chip"
      :class="{ 'is-active': part.id === activeCitationId, 'cite-chip--unknown': indexOf(part.id) < 0 }"
      :title="locator(part.id)"
      @click="indexOf(part.id) >= 0 && emit('selectCitation', part.id, citations)"
    >
      {{ indexOf(part.id) >= 0 ? indexOf(part.id) + 1 : '?' }}
    </button>
    <template v-else>{{ part.value }}</template>
  </template>
</template>
