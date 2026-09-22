import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1' })
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = axios
      .post('/api/v1/auth/refresh', { refresh_token: localStorage.getItem('refresh_token') || '' })
      .then(({ data }) => {
        localStorage.setItem('access_token', data.access_token)
        localStorage.setItem('refresh_token', data.refresh_token)
        return data.access_token as string
      })
      .finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

api.interceptors.response.use(undefined, async (error) => {
  const request = error.config
  if (error.response?.status === 401 && !request?._retried && localStorage.getItem('refresh_token')) {
    request._retried = true
    request.headers.Authorization = `Bearer ${await refreshAccessToken()}`
    return api.request(request)
  }
  return Promise.reject(error)
})

export async function streamRun(
  runId: string,
  onEvent: (event: string, data: any, eventId: number) => void,
  startAfter = 0,
  signal?: AbortSignal,
): Promise<number> {
  let cursor = startAfter
  let retries = 0
  while (!signal?.aborted) {
    let token = localStorage.getItem('access_token') || ''
    let response = await fetch(`/api/v1/agent/runs/${runId}/events?after=${cursor}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    })
    if (response.status === 401 && localStorage.getItem('refresh_token')) {
      token = await refreshAccessToken()
      response = await fetch(`/api/v1/agent/runs/${runId}/events?after=${cursor}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal,
      })
    }
    if (!response.ok || !response.body) throw new Error(`SSE failed: ${response.status}`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''
        for (const block of blocks) {
          let event = 'message'
          let data = '{}'
          let id = cursor
          for (const line of block.split('\n')) {
            if (line.startsWith('id:')) id = Number(line.slice(3).trim()) || cursor
            if (line.startsWith('event:')) event = line.slice(6).trim()
            if (line.startsWith('data:')) data = line.slice(5).trim()
          }
          if (id <= cursor) continue
          cursor = id
          onEvent(event, JSON.parse(data), id)
          if (['run_completed', 'run_failed', 'run_cancelled'].includes(event)) return cursor
        }
      }
      retries += 1
      if (retries > 5) throw new Error('SSE connection ended before the run completed')
      await new Promise((resolve) => setTimeout(resolve, Math.min(1000 * retries, 5000)))
    } catch (error) {
      if (signal?.aborted) return cursor
      retries += 1
      if (retries > 5) throw error
      await new Promise((resolve) => setTimeout(resolve, Math.min(1000 * retries, 5000)))
    }
  }
  return cursor
}
