import { ref } from 'vue'
import { api, streamRun } from '../api'
import type { ApprovalMode, Citation, TraceItem } from '../types'

export function useRunStream() {
  const liveText = ref('')
  const status = ref('idle')
  const running = ref(false)
  const trace = ref<TraceItem[]>([])
  const approvals = ref<any[]>([])
  const error = ref('')
  let streamController: AbortController | undefined

  function traceLabel(event: string, data: any) {
    if (event === 'tool_call') return '调用 ' + data.name
    if (event === 'tool_result') return data.tool + (data.ok ? ' 完成' : ' 失败')
    if (event === 'context_manifest') return '上下文：' + data.windows + ' 个窗口'
    if (event === 'approval_required') return '等待确认：' + data.tool
    if (event === 'attachment_window_completed') return '全文窗口 ' + data.index + '/' + data.total
    if (event === 'context_compacted') return '上下文已压缩'
    return event.replaceAll('_', ' ')
  }

  async function refreshApprovals(runId: string) {
    approvals.value = (await api.get(`/agent/runs/${runId}/approvals`)).data.items.filter(
      (item: any) => item.status === 'pending',
    )
  }

  async function resolveApproval(id: string, decision: 'approved' | 'rejected') {
    await api.post(`/agent/approvals/${id}/resolve`, { decision })
    approvals.value = approvals.value.filter((item) => item.id !== id)
  }

  async function start(params: {
    conversationId: string
    query: string
    attachmentIds: string[]
    approvalMode?: ApprovalMode
    onComplete: (answer: string, citations: Citation[]) => void
    onApproval?: (payload: any) => void
  }) {
    running.value = true
    status.value = 'pending'
    liveText.value = ''
    trace.value = []
    approvals.value = []
    error.value = ''
    try {
      const { data } = await api.post('/agent/runs', {
        conversation_id: params.conversationId,
        query: params.query,
        attachment_ids: params.attachmentIds,
        attachment_instructions: Object.fromEntries(
          params.attachmentIds.map((id) => [id, '结合当前问题处理全文']),
        ),
        approval_mode: params.approvalMode,
      })
      const runId = data.id as string
      streamController?.abort()
      streamController = new AbortController()
      await streamRun(
        runId,
        (event, payload, eventId) => {
          status.value = event
          if (event !== 'text_delta') {
            trace.value.push({ id: eventId, event, label: traceLabel(event, payload) })
          }
          if (event === 'text_delta') liveText.value += payload.delta
          if (event === 'approval_required') {
            void refreshApprovals(runId)
            params.onApproval?.(payload)
          }
          if (event === 'run_completed') {
            params.onComplete(payload.answer, payload.citations || [])
            liveText.value = ''
            running.value = false
            status.value = 'idle'
          }
          if (event === 'run_failed' || event === 'run_cancelled') {
            error.value =
              event === 'run_failed' ? '运行失败：' + payload.message : '运行已取消。'
            running.value = false
            status.value = 'idle'
          }
        },
        0,
        streamController.signal,
      )
    } catch (value: any) {
      running.value = false
      status.value = 'idle'
      error.value = value.response?.data?.detail || value.message || '无法启动 Agent。'
    }
  }

  function stop() {
    streamController?.abort()
  }

  function reset() {
    streamController?.abort()
    streamController = undefined
    running.value = false
    status.value = 'idle'
    liveText.value = ''
    trace.value = []
    approvals.value = []
    error.value = ''
  }

  return {
    liveText,
    status,
    running,
    trace,
    approvals,
    error,
    start,
    stop,
    reset,
    resolveApproval,
  }
}
