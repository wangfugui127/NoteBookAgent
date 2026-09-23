import { ref } from 'vue'
import { api } from '../api'
import type {
  EvalCaseInput,
  EvalCaseResultItem,
  EvalDatasetDetail,
  EvalDatasetItem,
  EvalRunItem,
} from '../types'

const ACTIVE_STATUSES = ['pending', 'running']

export function useEvaluations() {
  const datasets = ref<EvalDatasetItem[]>([])
  const activeId = ref('')
  const detail = ref<EvalDatasetDetail | null>(null)
  const run = ref<EvalRunItem | null>(null)
  const results = ref<EvalCaseResultItem[]>([])
  const history = ref<EvalRunItem[]>([])
  const loading = ref(false)
  let timer: number | undefined

  async function loadDatasets() {
    loading.value = true
    try {
      datasets.value = (await api.get('/eval/datasets')).data.items
    } finally {
      loading.value = false
    }
  }

  async function loadDetail(id: string) {
    activeId.value = id
    detail.value = (await api.get(`/eval/datasets/${id}`)).data
  }

  async function createDataset(name: string, description = '') {
    const { data } = await api.post('/eval/datasets', { name, description })
    await loadDatasets()
    await loadDetail(data.id)
    return data.id as string
  }

  async function importDefaultDataset() {
    const { data } = await api.post('/eval/datasets/import-default')
    await loadDatasets()
    await loadDetail(data.id)
    return data.id as string
  }

  async function importCases(id: string, cases: EvalCaseInput[], replace: boolean) {
    await api.post(`/eval/datasets/${id}/import`, { cases, replace })
    await loadDetail(id)
  }

  async function addCase(id: string, payload: EvalCaseInput) {
    await api.post(`/eval/datasets/${id}/cases`, payload)
    await loadDetail(id)
  }

  async function updateCase(caseId: string, payload: Partial<EvalCaseInput>) {
    await api.patch(`/eval/cases/${caseId}`, payload)
    if (activeId.value) await loadDetail(activeId.value)
  }

  async function deleteCase(caseId: string) {
    await api.delete(`/eval/cases/${caseId}`)
    if (activeId.value) await loadDetail(activeId.value)
  }

  async function deleteDataset(id: string) {
    await api.delete(`/eval/datasets/${id}`)
    if (activeId.value === id) {
      activeId.value = ''
      detail.value = null
    }
    await loadDatasets()
  }

  async function startRun(id: string, notebookId: string, allowMissing: boolean) {
    const { data } = await api.post(`/eval/datasets/${id}/runs`, {
      notebook_id: notebookId,
      allow_missing: allowMissing,
    })
    run.value = data
    results.value = []
    startPolling(data.id)
    return data as EvalRunItem
  }

  async function loadRun(runId: string) {
    const data = (await api.get(`/eval/runs/${runId}`)).data as EvalRunItem
    run.value = data
    if (!ACTIVE_STATUSES.includes(data.status)) {
      const payload = (await api.get(`/eval/runs/${runId}/results`)).data
      results.value = payload.items
      stopPolling()
    }
    return data
  }

  function startPolling(runId: string, interval = 2500) {
    stopPolling()
    timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void loadRun(runId)
    }, interval)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = undefined
    }
  }

  async function loadHistory(notebookId?: string) {
    history.value = (
      await api.get('/eval/runs', { params: notebookId ? { notebook_id: notebookId } : {} })
    ).data.items
  }

  async function cancelRun(runId: string) {
    await api.post(`/eval/runs/${runId}/cancel`)
    await loadRun(runId)
  }

  function resetRun() {
    stopPolling()
    run.value = null
    results.value = []
  }

  return {
    datasets,
    activeId,
    detail,
    run,
    results,
    history,
    loading,
    loadDatasets,
    loadDetail,
    createDataset,
    importDefaultDataset,
    importCases,
    addCase,
    updateCase,
    deleteCase,
    deleteDataset,
    startRun,
    loadRun,
    loadHistory,
    startPolling,
    stopPolling,
    cancelRun,
    resetRun,
  }
}


