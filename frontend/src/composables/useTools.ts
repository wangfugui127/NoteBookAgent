import { ref } from 'vue'
import { api } from '../api'
import type { McpServer, SkillSummary } from '../types'

export function useTools() {
  const servers = ref<McpServer[]>([])
  const tools = ref<string[]>([])
  const skills = ref<SkillSummary[]>([])
  const errors = ref<Record<string, string>>({})
  const loading = ref(false)

  async function load() {
    loading.value = true
    try {
      const [mcp, skill] = await Promise.all([
        api.get('/runtime/mcp'),
        api.get('/runtime/skills'),
      ])
      servers.value = mcp.data.servers || []
      tools.value = mcp.data.tools || []
      errors.value = mcp.data.errors || {}
      skills.value = skill.data.items || []
    } finally {
      loading.value = false
    }
  }

  async function reloadMcp() {
    await api.post('/runtime/mcp/reload')
    await load()
  }

  async function reloadSkills() {
    await api.post('/runtime/skills/reload')
    await load()
  }

  return { servers, tools, skills, errors, loading, load, reloadMcp, reloadSkills }
}
