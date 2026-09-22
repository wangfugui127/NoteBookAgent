import { ref, watch } from 'vue'

export function useNotes(notebookId: string) {
  const key = `notebookagent:notes:${notebookId}`
  const notes = ref(localStorage.getItem(key) || '')

  watch(notes, (value) => {
    if (value.trim()) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  })

  return { notes }
}
