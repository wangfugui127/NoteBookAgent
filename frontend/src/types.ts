export interface Citation {
  evidence_id: string
  chunk_id?: string | null
  source_kind: string
  source_id?: string | null
  section_title?: string | null
  page_start?: number | null
  page_end?: number | null
  char_start?: number | null
  char_end?: number | null
}

export interface ChatMessage {
  id?: string
  role: string
  content: string
  citations?: Citation[]
}

export interface DocumentItem {
  id: string
  title: string
  media_type?: string
  status: string
  graph_status: string
  version_id?: string | null
  error_message?: string | null
}

export interface TraceItem {
  id: number
  event: string
  label: string
}

export interface Toast {
  id: number
  text: string
  kind: 'ok' | 'error'
}

export interface Paper {
  paper_id: string
  title: string
  authors: string[]
  year?: number
  abstract?: string
  doi?: string
  url?: string
  citation_count: number
  source: string
}

export interface McpServer {
  id: string
  enabled: boolean
  transport: string
}

export interface SkillSummary {
  name: string
  description?: string
  enabled?: boolean
  [key: string]: unknown
}
