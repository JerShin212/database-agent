import axios from 'axios'
import type {
  Conversation,
  Collection,
  Document,
  Database,
  DatabaseSchema,
  SearchResult,
  ChatResponse,
  Connector,
  SchemaSearchResult,
  ImageAttachment,
  ChatStreamEvent,
} from '../types'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Chat API
export const chatApi = {
  async sendMessage(
    message: string,
    conversationId: string | null,
    collectionIds: string[] | null,
    databaseId: string | null,
    image?: ImageAttachment | null,
  ): Promise<ChatResponse> {
    const response = await api.post('/api/chat', {
      message,
      conversation_id: conversationId,
      collection_ids: collectionIds,
      database_id: databaseId,
      image: image || null,
    })
    return response.data
  },

  /**
   * Stream a chat message over SSE (fetch + ReadableStream — EventSource
   * cannot POST a JSON body). Calls onEvent for each parsed event.
   */
  async sendMessageStream(
    message: string,
    conversationId: string | null,
    collectionIds: string[] | null,
    databaseId: string | null,
    image: ImageAttachment | null,
    onEvent: (event: ChatStreamEvent) => void,
  ): Promise<void> {
    const response = await fetch(`${API_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        collection_ids: collectionIds,
        database_id: databaseId,
        image: image || null,
      }),
    })

    if (!response.ok || !response.body) {
      throw new Error(`Stream request failed: ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      // sse-starlette emits \r\n line endings — normalize before splitting
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

      // SSE frames are separated by a blank line
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''

      for (const frame of frames) {
        const dataLines = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
        if (dataLines.length === 0) continue
        try {
          onEvent(JSON.parse(dataLines.join('')))
        } catch {
          // Skip malformed frames (e.g. SSE comments/pings)
        }
      }
    }
  },

  async getConversations(): Promise<Conversation[]> {
    const response = await api.get('/api/chat/conversations')
    return response.data
  },

  async getConversation(id: string): Promise<Conversation> {
    const response = await api.get(`/api/chat/conversations/${id}`)
    return response.data
  },

  async deleteConversation(id: string): Promise<void> {
    await api.delete(`/api/chat/conversations/${id}`)
  },
}

// Collections API
export const collectionsApi = {
  async list(): Promise<Collection[]> {
    const response = await api.get('/api/collections')
    return response.data
  },

  async create(name: string, description?: string): Promise<Collection> {
    const response = await api.post('/api/collections', { name, description })
    return response.data
  },

  async get(id: string): Promise<Collection> {
    const response = await api.get(`/api/collections/${id}`)
    return response.data
  },

  async delete(id: string): Promise<void> {
    await api.delete(`/api/collections/${id}`)
  },

  async getStatus(id: string): Promise<{
    total: number
    pending: number
    processing: number
    completed: number
    failed: number
  }> {
    const response = await api.get(`/api/collections/${id}/status`)
    return response.data
  },

  async uploadDocuments(collectionId: string, files: File[]): Promise<Document[]> {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))

    const response = await api.post(`/api/collections/${collectionId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  async getDocuments(collectionId: string): Promise<Document[]> {
    const response = await api.get(`/api/collections/${collectionId}/documents`)
    return response.data
  },

  async deleteDocument(id: string): Promise<void> {
    await api.delete(`/api/collections/documents/${id}`)
  },

  async search(query: string, collectionIds?: string[], limit?: number): Promise<SearchResult[]> {
    const response = await api.post('/api/collections/search', {
      query,
      collection_ids: collectionIds,
      limit,
    })
    return response.data
  },
}

// Databases API
export const databasesApi = {
  async list(): Promise<Database[]> {
    const response = await api.get('/api/databases')
    return response.data
  },

  async create(name: string, description?: string, createSample?: boolean): Promise<Database> {
    const response = await api.post('/api/databases', {
      name,
      description,
      create_sample: createSample,
    })
    return response.data
  },

  async upload(file: File, name?: string): Promise<Database> {
    const formData = new FormData()
    formData.append('file', file)
    if (name) {
      formData.append('name', name)
    }

    const response = await api.post('/api/databases/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  async get(id: string): Promise<Database> {
    const response = await api.get(`/api/databases/${id}`)
    return response.data
  },

  async getSchema(id: string): Promise<DatabaseSchema> {
    const response = await api.get(`/api/databases/${id}/schema`)
    return response.data
  },

  async query(id: string, sql: string): Promise<{
    columns: string[]
    rows: unknown[][]
    row_count: number
    error?: string
  }> {
    const response = await api.post(`/api/databases/${id}/query`, { sql })
    return response.data
  },

  async delete(id: string): Promise<void> {
    await api.delete(`/api/databases/${id}`)
  },
}

// Connectors API
export const connectorsApi = {
  async list(userId?: string, status?: string): Promise<Connector[]> {
    const params = new URLSearchParams()
    if (userId) params.append('user_id', userId)
    if (status) params.append('status', status)

    const response = await api.get(`/api/connectors?${params}`)
    return response.data
  },

  async create(data: {
    name: string
    db_type: 'sqlite' | 'postgresql' | 'mysql'
    connection_string: string
    user_id: string
  }): Promise<Connector> {
    const response = await api.post('/api/connectors', data)
    return response.data
  },

  async get(id: string): Promise<Connector> {
    const response = await api.get(`/api/connectors/${id}`)
    return response.data
  },

  async test(id: string): Promise<{ success: boolean; message: string }> {
    const response = await api.post(`/api/connectors/${id}/test`)
    return response.data
  },

  async index(id: string): Promise<{ message: string; connector_id: string }> {
    const response = await api.post(`/api/connectors/${id}/index`)
    return response.data
  },

  async delete(id: string): Promise<void> {
    await api.delete(`/api/connectors/${id}`)
  },

  async searchSchema(data: {
    query: string
    connector_id: string
    limit?: number
  }): Promise<SchemaSearchResult[]> {
    const response = await api.post('/api/schema/search', data)
    return response.data
  },

  async listTables(connectorId: string): Promise<{ name: string; column_count: number }[]> {
    const response = await api.get(`/api/schema/tables/${connectorId}`)
    return response.data
  },

  async getTableSchema(
    connectorId: string,
    tableName: string
  ): Promise<{
    table_name: string
    table_definition: string | null
    columns: Array<{
      name: string
      data_type: string
      semantic_definition: string
      sample_values: unknown[] | null
    }>
  }> {
    const response = await api.get(`/api/schema/tables/${connectorId}/${tableName}`)
    return response.data
  },
}
