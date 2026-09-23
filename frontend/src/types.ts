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

export interface ConversationSummary {
  id: string
  title: string
  updated_at: string
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

export type ApprovalMode = 'read_only' | 'confirm' | 'auto'

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

export interface EvalCaseItem {
  id: string
  case_key: string
  question: string
  expected_tools: string[]
  expected_source_titles: string[]
  required_keywords: string[]
  ordinal: number
}

export interface EvalCaseInput {
  case_key?: string
  question: string
  expected_tools: string[]
  expected_source_titles: string[]
  required_keywords: string[]
}

export interface EvalRunSummary {
  id: string
  status: string
  pass_rate: number | null
  created_at: string
}

export interface EvalDatasetItem {
  id: string
  name: string
  description: string
  created_at: string
  case_count: number
  latest_run: EvalRunSummary | null
}

export interface EvalDatasetDetail {
  id: string
  name: string
  description: string
  created_at: string
  cases: EvalCaseItem[]
}

export interface EvalMetrics {
  total_cases?: number
  completed_cases?: number
  passed_cases?: number
  pass_rate?: number | null
  route_accuracy?: number | null
  retrieval_accuracy?: number | null
  citation_accuracy?: number | null
  keyword_coverage?: number | null
  avg_total_score?: number | null
  avg_latency_ms?: number | null
}

export interface EvalRunItem {
  id: string
  notebook_id?: string
  dataset_id?: string | null
  dataset_name: string
  status: string
  total_cases: number
  completed_cases: number
  passed_cases: number
  current_case_key?: string | null
  metrics: EvalMetrics
  error_message?: string | null
  created_at: string
}

export interface EvalCaseResultItem {
  id: string
  case_key: string
  ordinal: number
  question: string
  status: string
  expected_tools: string[]
  actual_tools: string[]
  expected_source_titles: string[]
  matched_sources: string[]
  missing_sources: string[]
  required_keywords: string[]
  matched_keywords: string[]
  answer: string | null
  route_score: number | null
  retrieval_score: number | null
  citation_score: number | null
  keyword_score: number | null
  total_score: number | null
  passed: boolean
  latency_ms: number | null
  agent_run_id: string | null
  error_message: string | null
  detail: Record<string, unknown>
}
