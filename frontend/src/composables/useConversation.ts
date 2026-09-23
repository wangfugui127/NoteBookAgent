import { ref } from 'vue'
import { api } from '../api'
import type { ChatMessage, ConversationSummary } from '../types'

export function useConversation(notebookId: string) {
  const conversations = ref<ConversationSummary[]>([])
  const conversationId = ref('')
  const messages = ref<ChatMessage[]>([])

  async function refreshConversations() {
    conversations.value = (
      await api.get('/conversations', { params: { notebook_id: notebookId } })
    ).data.items
  }

  async function loadMessages(id: string) {
    messages.value = (await api.get(`/conversations/${id}/messages`)).data.items
  }

  async function selectConversation(id: string) {
    conversationId.value = id
    await loadMessages(id)
  }

  async function createConversation() {
    const { data } = await api.post('/conversations', {
      notebook_id: notebookId,
      title: '研究对话',
    })
    await refreshConversations()
    await selectConversation(data.id)
    return data.id as string
  }

  async function removeConversation(id: string) {
    await api.delete(`/conversations/${id}`)
    await refreshConversations()
    if (id !== conversationId.value) return conversationId.value
    const next = conversations.value[0]?.id
    if (next) {
      await selectConversation(next)
      return next
    }
    return createConversation()
  }

  async function load() {
    await refreshConversations()
    if (conversations.value.length) {
      await selectConversation(conversations.value[0].id)
    } else {
      await createConversation()
    }
  }

  function append(message: ChatMessage) {
    messages.value.push(message)
  }

  return {
    conversations,
    conversationId,
    messages,
    load,
    createConversation,
    selectConversation,
    removeConversation,
    refreshConversations,
    append,
  }
}
