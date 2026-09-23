<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useNotes } from '../composables/useNotes'
import { useTools } from '../composables/useTools'
import type { Citation, TraceItem } from '../types'

const props = defineProps<{
  citations: Citation[]
  activeCitationId?: string
  trace: TraceItem[]
  notebookId: string
  open?: boolean
}>()

const emit = defineEmits<{
  selectCitation: [evidenceId: string]
  collapse: []
}>()

const { notes } = useNotes(props.notebookId)
const tools = useTools()

type TabId = 'evidence' | 'trace' | 'notes' | 'tools'
const activeTab = ref<TabId>('evidence')

const tabs = computed(() => [
  { id: 'evidence' as const, label: '证据', count: props.citations.length },
  { id: 'trace' as const, label: '轨迹', count: props.trace.length },
  { id: 'notes' as const, label: '备注', count: 0 },
  { id: 'tools' as const, label: '工具', count: tools.servers.value.length + tools.skills.value.length },
])

watch(
  () => props.activeCitationId,
  (value) => {
    if (value) activeTab.value = 'evidence'
  },
)

watch(activeTab, (value) => {
  if (value === 'tools' && !tools.servers.value.length && !tools.skills.value.length) {
    void tools.load()
  }
})

function locator(citation: Citation) {
  const parts: string[] = []
  if (citation.page_start != null) {
    parts.push(`页 ${citation.page_start}–${citation.page_end ?? citation.page_start}`)
  }
  if (citation.char_start != null) {
    parts.push(`字符 ${citation.char_start}–${citation.char_end ?? citation.char_start}`)
  }
  if (citation.section_title) parts.push(citation.section_title)
  return parts.length ? parts.join(' · ') : citation.source_kind
}
</script>

<template>
  <aside class="panel panel--studio" :class="{ 'is-open': open }">
    <div class="studio__tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="studio__tab"
        :class="{ 'is-active': activeTab === tab.id }"
        role="tab"
        :aria-selected="activeTab === tab.id"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}<template v-if="tab.count"> · {{ tab.count }}</template>
      </button>
      <button
        class="icon-btn icon-btn--ghost studio__collapse"
        type="button"
        aria-label="收起面板"
        title="收起"
        @click="emit('collapse')"
      >
        »
      </button>
    </div>

    <div class="studio__body">
      <section v-if="activeTab === 'evidence'" class="studio__section">
        <h2>引用证据</h2>
        <div v-if="citations.length">
          <button
            v-for="(citation, index) in citations"
            :key="citation.evidence_id"
            class="evidence-card"
            :class="{ 'is-active': citation.evidence_id === activeCitationId }"
            type="button"
            @click="emit('selectCitation', citation.evidence_id)"
          >
            <span class="evidence-card__num">{{ index + 1 }}</span>
            <span>
              <span class="evidence-card__title">{{ citation.section_title || '证据定位' }}</span>
              <span class="evidence-card__loc">
                {{ locator(citation) }}<br />
                <span class="mono">{{ citation.chunk_id ? 'chunk ' + citation.chunk_id.slice(0, 8) : citation.source_kind }}</span>
              </span>
            </span>
          </button>
        </div>
        <p v-else class="empty-note">完成一次回答后，这里显示可核查的页码、字符区间与 chunk。</p>
      </section>

      <section v-else-if="activeTab === 'trace'" class="studio__section">
        <h2>运行轨迹</h2>
        <ol v-if="trace.length" class="trace-list">
          <li v-for="item in trace" :key="item.id" class="trace-item" :data-event="item.event">
            {{ item.label }}
          </li>
        </ol>
        <p v-else class="empty-note">工具调用、上下文窗口和审批状态会按顺序记录。</p>
      </section>

      <section v-else-if="activeTab === 'notes'" class="studio__section notes">
        <h2>备注</h2>
        <textarea v-model="notes" class="textarea" placeholder="记录阅读线索、待验证假设、下一步问题……" />
        <p class="notes__hint">仅保存在当前浏览器（localStorage），不会同步到账号。</p>
      </section>

      <section v-else class="studio__section">
        <h2>工具与技能</h2>
        <div v-if="tools.loading.value" class="empty-note">正在读取运行配置……</div>
        <template v-else>
          <div class="tool-row">
            <span>MCP 工具 · {{ tools.tools.value.length }}</span>
            <button class="btn btn--quiet btn--sm" type="button" @click="tools.reloadMcp">刷新</button>
          </div>
          <p v-if="tools.tools.value.length" class="empty-note mono" style="margin-top: 8px">
            {{ tools.tools.value.slice(0, 12).join(', ') }}
          </p>
          <p v-else class="empty-note" style="margin-top: 8px">没有已连接的 MCP 工具。</p>

          <div class="tool-row" style="margin-top: 12px">
            <span>技能 · {{ tools.skills.value.length }}</span>
            <button class="btn btn--quiet btn--sm" type="button" @click="tools.reloadSkills">刷新</button>
          </div>
          <div v-for="skill in tools.skills.value" :key="skill.name" class="tool-row">
            <span>{{ skill.name }}</span>
            <span class="empty-note">{{ skill.description }}</span>
          </div>
          <p v-if="!tools.skills.value.length" class="empty-note" style="margin-top: 8px">没有已启用的技能。</p>
        </template>
      </section>
    </div>
  </aside>
</template>
