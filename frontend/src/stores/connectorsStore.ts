import { create } from 'zustand'
import type { Connector, SchemaSearchResult } from '../types'
import { connectorsApi } from '../services/api'

interface ConnectorsState {
  connectors: Connector[]
  selectedConnector: Connector | null
  tables: { name: string; column_count: number }[]
  schemaSearchResults: SchemaSearchResult[]
  isLoading: boolean
  error: string | null

  // Actions
  loadConnectors: () => Promise<void>
  createConnector: (data: {
    name: string
    db_type: 'sqlite' | 'postgresql' | 'mysql'
    connection_string: string
    user_id: string
  }) => Promise<void>
  selectConnector: (id: string) => Promise<void>
  testConnection: (id: string) => Promise<{ success: boolean; message: string }>
  indexSchema: (id: string) => Promise<void>
  deleteConnector: (id: string) => Promise<void>
  searchSchema: (query: string, connectorId: string) => Promise<void>
  refreshConnector: (id: string) => Promise<void>
  clearError: () => void
}

export const useConnectorsStore = create<ConnectorsState>((set, get) => ({
  connectors: [],
  selectedConnector: null,
  tables: [],
  schemaSearchResults: [],
  isLoading: false,
  error: null,

  loadConnectors: async () => {
    set({ isLoading: true })
    try {
      const connectors = await connectorsApi.list()
      set({ connectors, isLoading: false })
    } catch (error) {
      set({ error: 'Failed to load connectors', isLoading: false })
    }
  },

  createConnector: async (data) => {
    set({ isLoading: true })
    try {
      const connector = await connectorsApi.create(data)
      set({
        connectors: [...get().connectors, connector],
        isLoading: false,
      })
    } catch (error) {
      set({ error: 'Failed to create connector', isLoading: false })
      throw error
    }
  },

  selectConnector: async (id: string) => {
    set({ isLoading: true })
    try {
      const connector = await connectorsApi.get(id)
      let tables: { name: string; column_count: number }[] = []

      if (connector.status === 'ready') {
        tables = await connectorsApi.listTables(id)
      }

      set({
        selectedConnector: connector,
        tables,
        schemaSearchResults: [],
        isLoading: false,
      })
    } catch (error) {
      set({ error: 'Failed to load connector', isLoading: false })
    }
  },

  testConnection: async (id: string) => {
    try {
      const result = await connectorsApi.test(id)
      return result
    } catch (error) {
      throw new Error('Failed to test connection')
    }
  },

  indexSchema: async (id: string) => {
    set({ isLoading: true })
    try {
      await connectorsApi.index(id)

      // Poll for completion
      const pollInterval = setInterval(async () => {
        try {
          const connector = await connectorsApi.get(id)
          const { connectors, selectedConnector } = get()

          // Update connector in list
          set({
            connectors: connectors.map((c) => (c.id === id ? connector : c)),
            selectedConnector: selectedConnector?.id === id ? connector : selectedConnector,
          })

          // Stop polling when done
          if (connector.status === 'ready' || connector.status === 'failed') {
            clearInterval(pollInterval)
            set({ isLoading: false })

            // Refresh tables if ready
            if (connector.status === 'ready' && selectedConnector?.id === id) {
              const tables = await connectorsApi.listTables(id)
              set({ tables })
            }
          }
        } catch (error) {
          clearInterval(pollInterval)
          set({ error: 'Failed to poll connector status', isLoading: false })
        }
      }, 2000) // Poll every 2 seconds

      // Stop polling after 5 minutes
      setTimeout(() => {
        clearInterval(pollInterval)
        set({ isLoading: false })
      }, 300000)
    } catch (error) {
      set({ error: 'Failed to index schema', isLoading: false })
      throw error
    }
  },

  deleteConnector: async (id: string) => {
    try {
      await connectorsApi.delete(id)
      const { connectors, selectedConnector } = get()
      set({
        connectors: connectors.filter((c) => c.id !== id),
        ...(selectedConnector?.id === id
          ? { selectedConnector: null, tables: [], schemaSearchResults: [] }
          : {}),
      })
    } catch (error) {
      set({ error: 'Failed to delete connector' })
    }
  },

  searchSchema: async (query: string, connectorId: string) => {
    set({ isLoading: true })
    try {
      const results = await connectorsApi.searchSchema({
        query,
        connector_id: connectorId,
        limit: 10,
      })
      set({ schemaSearchResults: results, isLoading: false })
    } catch (error) {
      set({ error: 'Failed to search schema', isLoading: false })
    }
  },

  refreshConnector: async (id: string) => {
    try {
      const connector = await connectorsApi.get(id)
      const { connectors, selectedConnector } = get()

      set({
        connectors: connectors.map((c) => (c.id === id ? connector : c)),
        selectedConnector: selectedConnector?.id === id ? connector : selectedConnector,
      })
    } catch (error) {
      set({ error: 'Failed to refresh connector' })
    }
  },

  clearError: () => set({ error: null }),
}))
