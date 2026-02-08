export interface Conversation {
  id: string
  title: string | null
  created_at: string
  updated_at: string
  messages?: Message[]
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  tool_calls?: ToolCall[]
  created_at: string
}

export interface ToolCall {
  tool: string
  args: Record<string, unknown>
  result: string
}

export interface Collection {
  id: string
  name: string
  description: string | null
  document_count: number
  created_at: string
  updated_at: string
}

export interface Document {
  id: string
  collection_id: string
  filename: string
  mime_type: string
  file_size: number
  page_count: number | null
  status: 'pending' | 'processing' | 'completed' | 'failed'
  error_message: string | null
  summary: string | null
  created_at: string
  updated_at: string
}

export interface Database {
  id: string
  name: string
  file_path: string
  description: string | null
  is_active: boolean
  created_at: string
}

export interface TableInfo {
  name: string
  columns: ColumnInfo[]
  row_count: number
  sample_data?: Record<string, unknown>[]
}

export interface ColumnInfo {
  name: string
  type: string
  nullable: boolean
  primary_key: boolean
  foreign_key: string | null
}

export interface DatabaseSchema {
  database_id: string
  database_name: string
  tables: TableInfo[]
}

export interface SearchResult {
  chunk_id: string
  document_id: string
  collection_id: string
  filename: string
  content: string
  score: number
}

export interface ChatStreamChunk {
  type: 'metadata' | 'content' | 'tool_call' | 'error' | 'done'
  conversation_id?: string
  content?: string
  tool?: string
  args?: Record<string, unknown>
  result?: string
  error?: string
}

export interface Connector {
  id: string
  user_id: string
  name: string
  db_type: 'sqlite' | 'postgresql' | 'mysql'
  status: 'pending' | 'indexing' | 'ready' | 'failed'
  indexing_progress: {
    stage: string
    current: number
    total: number
    table?: string
    column?: string
  } | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface SchemaSearchResult {
  id: string
  definition_type: 'table' | 'column'
  table_name: string
  column_name: string | null
  data_type: string | null
  semantic_definition: string
  sample_values: unknown[] | null
  score: number | null
}
