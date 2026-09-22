import { computed, ref } from 'vue'
import { api } from '../api'
import type { DocumentItem } from '../types'

const ACTIVE_STATUSES = ['pending', 'parsing', 'chunking', 'embedding', 'indexing']

export function useDocuments(
  notebookId: string,
  options: { onGraphTransition?: (doc: DocumentItem, previous: string) => void } = {},
) {
  const documents = ref<DocumentItem[]>([])
  const selected = ref<string[]>([])
  const loading = ref(false)
  const graphSnapshot = new Map<string, string>()
  let timer: number | undefined

  const readyCount = computed(() => documents.value.filter((item) => item.status === 'ready').length)
  const hasActive = computed(() =>
    documents.value.some(
      (item) =>
        ACTIVE_STATUSES.includes(item.status) ||
        (item.status === 'ready' && ['pending', 'building'].includes(item.graph_status)),
    ),
  )

  async function load() {
    loading.value = true
    try {
      const { data } = await api.get(`/notebooks/${notebookId}/documents`)
      const items = (data.items || []) as DocumentItem[]
      documents.value = items
      for (const doc of items) {
        const previous = graphSnapshot.get(doc.id)
        graphSnapshot.set(doc.id, doc.graph_status)
        if (previous && previous !== doc.graph_status) options.onGraphTransition?.(doc, previous)
      }
      selected.value = selected.value.filter((id) =>
        items.some((item) => item.id === id && item.status === 'ready'),
      )
    } finally {
      loading.value = false
    }
  }

  function toggle(id: string) {
    const index = selected.value.indexOf(id)
    if (index >= 0) selected.value.splice(index, 1)
    else selected.value.push(id)
  }

  function clearSelection() {
    selected.value = []
  }

  function startPolling(interval = 4000) {
    stopPolling()
    timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load()
    }, interval)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = undefined
    }
  }

  return {
    documents,
    selected,
    loading,
    readyCount,
    hasActive,
    load,
    toggle,
    clearSelection,
    startPolling,
    stopPolling,
  }
}
