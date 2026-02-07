import { create } from 'zustand'
import type { Database, DatabaseSchema } from '../types'
import { databasesApi } from '../services/api'

interface DatabasesState {
  databases: Database[]
  selectedDatabase: Database | null
  schema: DatabaseSchema | null
  queryResult: {
    columns: string[]
    rows: unknown[][]
    row_count: number
    error?: string
  } | null
  isLoading: boolean
  error: string | null

  // Actions
  loadDatabases: () => Promise<void>
  createSampleDatabase: (name: string) => Promise<void>
  uploadDatabase: (file: File, name?: string) => Promise<void>
  selectDatabase: (id: string) => Promise<void>
  deleteDatabase: (id: string) => Promise<void>
  executeQuery: (sql: string) => Promise<void>
  clearQueryResult: () => void
  clearError: () => void
}

export const useDatabasesStore = create<DatabasesState>((set, get) => ({
  databases: [],
  selectedDatabase: null,
  schema: null,
  queryResult: null,
  isLoading: false,
  error: null,

  loadDatabases: async () => {
    set({ isLoading: true })
    try {
      const databases = await databasesApi.list()
      set({ databases, isLoading: false })
    } catch (error) {
      set({ error: 'Failed to load databases', isLoading: false })
    }
  },

  createSampleDatabase: async (name: string) => {
    set({ isLoading: true })
    try {
      const database = await databasesApi.create(name, 'Sample sales database', true)
      set({
        databases: [...get().databases, database],
        isLoading: false,
      })
    } catch (error) {
      set({ error: 'Failed to create database', isLoading: false })
    }
  },

  uploadDatabase: async (file: File, name?: string) => {
    set({ isLoading: true })
    try {
      const database = await databasesApi.upload(file, name)
      set({
        databases: [...get().databases, database],
        isLoading: false,
      })
    } catch (error) {
      set({ error: 'Failed to upload database', isLoading: false })
    }
  },

  selectDatabase: async (id: string) => {
    set({ isLoading: true })
    try {
      const database = await databasesApi.get(id)
      const schema = await databasesApi.getSchema(id)
      set({
        selectedDatabase: database,
        schema,
        queryResult: null,
        isLoading: false,
      })
    } catch (error) {
      set({ error: 'Failed to load database', isLoading: false })
    }
  },

  deleteDatabase: async (id: string) => {
    try {
      await databasesApi.delete(id)
      const { databases, selectedDatabase } = get()
      set({
        databases: databases.filter((d) => d.id !== id),
        ...(selectedDatabase?.id === id
          ? { selectedDatabase: null, schema: null, queryResult: null }
          : {}),
      })
    } catch (error) {
      set({ error: 'Failed to delete database' })
    }
  },

  executeQuery: async (sql: string) => {
    const { selectedDatabase } = get()
    if (!selectedDatabase) return

    set({ isLoading: true })
    try {
      const result = await databasesApi.query(selectedDatabase.id, sql)
      set({ queryResult: result, isLoading: false })
    } catch (error) {
      set({ error: 'Failed to execute query', isLoading: false })
    }
  },

  clearQueryResult: () => set({ queryResult: null }),
  clearError: () => set({ error: null }),
}))
