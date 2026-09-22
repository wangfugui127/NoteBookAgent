import { ref } from 'vue'
import type { Toast } from '../types'

export function useToasts() {
  const toasts = ref<Toast[]>([])
  let sequence = 0

  function push(text: string, kind: Toast['kind'] = 'ok') {
    const id = ++sequence
    toasts.value.push({ id, text, kind })
    window.setTimeout(() => dismiss(id), 6000)
  }

  function dismiss(id: number) {
    toasts.value = toasts.value.filter((item) => item.id !== id)
  }

  return { toasts, push, dismiss }
}
