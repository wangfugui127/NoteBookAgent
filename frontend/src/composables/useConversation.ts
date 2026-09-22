import { ref } from 'vue'
import { api } from '../api'
import type { ChatMessage } from '../types'

export function useConversation(notebookId: string) {
  const conversationId = ref('')
  const messages = ref<ChatMessage[]>([])

  async function load() {
    const existing = (await api.get('/conversations', { params: { notebook_id: notebookId } })).data
      .items
    conversationId.value =
      existing[0]?.id ||
      (await api.post('/conversations', { notebook_id: notebookId, title: '研究对话' })).data.id
    messages.value = (
      await api.get(`/conversations/${conversationId.value}/messages`)
    ).data.items
  }

  function append(message: ChatMessage) {
    messages.value.push(message)
  }

  return { conversationId, messages, load, append }
}
