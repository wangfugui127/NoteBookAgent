<script setup lang="ts">
import InlineParts from './InlineParts.vue'
import type { Citation } from '../types'
import type { Block } from '../utils/markdown'

defineProps<{
  blocks: Block[]
  citations?: Citation[]
  activeCitationId?: string
}>()

const emit = defineEmits<{ selectCitation: [evidenceId: string, citations?: Citation[]] }>()
</script>

<template>
  <div class="md">
    <template v-for="(block, blockIndex) in blocks" :key="blockIndex">
      <p v-if="block.kind === 'paragraph'" class="md__p">
        <InlineParts :parts="block.parts" :citations="citations" :active-citation-id="activeCitationId" @select-citation="(id, list) => emit('selectCitation', id, list)" />
      </p>

      <h3 v-else-if="block.kind === 'heading'" class="md__h" :data-level="block.level">
        <InlineParts :parts="block.parts" :citations="citations" :active-citation-id="activeCitationId" @select-citation="(id, list) => emit('selectCitation', id, list)" />
      </h3>

      <ul v-else-if="block.kind === 'list' && !block.ordered" class="md__list">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
          <InlineParts :parts="item" :citations="citations" :active-citation-id="activeCitationId" @select-citation="(id, list) => emit('selectCitation', id, list)" />
        </li>
      </ul>

      <ol v-else-if="block.kind === 'list'" class="md__list">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
          <InlineParts :parts="item" :citations="citations" :active-citation-id="activeCitationId" @select-citation="(id, list) => emit('selectCitation', id, list)" />
        </li>
      </ol>

      <table v-else-if="block.kind === 'table'" class="md__table">
        <thead>
          <tr>
            <th v-for="(cell, cellIndex) in block.header" :key="cellIndex">
              <InlineParts :parts="cell" :citations="citations" :active-citation-id="activeCitationId" @select-citation="(id, list) => emit('selectCitation', id, list)" />
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
            <td v-for="(cell, cellIndex) in row" :key="cellIndex">
              <InlineParts :parts="cell" :citations="citations" :active-citation-id="activeCitationId" @select-citation="(id, list) => emit('selectCitation', id, list)" />
            </td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
