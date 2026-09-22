import { onBeforeUnmount, onMounted } from 'vue'

export interface Hotkey {
  combo: string
  handler: (event: KeyboardEvent) => void
}

function matches(combo: string, event: KeyboardEvent) {
  const parts = combo.toLowerCase().split('+')
  const key = parts[parts.length - 1]
  const wantsMod = parts.includes('mod') || parts.includes('ctrl') || parts.includes('meta')
  const wantsShift = parts.includes('shift')
  if (wantsMod !== (event.ctrlKey || event.metaKey)) return false
  if (wantsShift !== event.shiftKey) return false
  return event.key.toLowerCase() === key
}

export function useHotkeys(hotkeys: Hotkey[]) {
  function onKeydown(event: KeyboardEvent) {
    for (const hotkey of hotkeys) {
      if (matches(hotkey.combo, event)) {
        hotkey.handler(event)
        return
      }
    }
  }

  onMounted(() => window.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
}
