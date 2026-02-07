import axios from 'axios'
import type {
  Conversation,
  Collection,
  Document,
  Database,
  DatabaseSchema,
  SearchResult,
  ChatStreamChunk,
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
  async streamChat(
    message: string,
    conversationId: string | null,
    collectionIds: string[] | null,
    databaseId: string | null,
    onChunk: (chunk: ChatStreamChunk) => void
  ): Promise<void> {
    const response = await fetch(`${API_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        collection_ids: collectionIds,
        database_id: databaseId,
      }),
    })

    if (!response.ok) {
      throw new Error('Failed to send message')
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const chunk = JSON.parse(line.slice(6))
            onChunk(chunk)
          } catch {
            // Ignore parse errors
          }
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
