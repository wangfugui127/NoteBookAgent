import { ref } from 'vue'
import { api } from '../api'
import type { ApprovalMode } from '../types'

export const APPROVAL_MODES: { value: ApprovalMode; label: string; hint: string }[] = [
  { value: 'read_only', label: '只读', hint: '只允许检索与读取，写入操作一律拒绝' },
  { value: 'confirm', label: '询问', hint: '写入或删除前先请求你确认' },
  { value: 'auto', label: '全权', hint: 'Agent 可自行执行所有操作，包括删除' },
]

export function useApprovalMode() {
  const approvalMode = ref<ApprovalMode>('confirm')

  async function load() {
    try {
      approvalMode.value = (await api.get('/users/me/settings')).data.approval_mode
    } catch {
      approvalMode.value = 'confirm'
    }
  }

  async function save(mode: ApprovalMode) {
    approvalMode.value = mode
    try {
      await api.put('/users/me/settings', { approval_mode: mode })
    } catch {
      /* keep the local choice even if the write fails */
    }
  }

  return { approvalMode, load, save }
}
