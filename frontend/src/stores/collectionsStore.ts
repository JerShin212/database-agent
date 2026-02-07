import { create } from 'zustand'
import type { Collection, Document } from '../types'
import { collectionsApi } from '../services/api'

interface CollectionsState {
  collections: Collection[]
  selectedCollection: Collection | null
  documents: Document[]
  isLoading: boolean
  error: string | null

  // Actions
  loadCollections: () => Promise<void>
  createCollection: (name: string, description?: string) => Promise<void>
  selectCollection: (id: string) => Promise<void>
  deleteCollection: (id: string) => Promise<void>
  uploadDocuments: (files: File[]) => Promise<void>
  deleteDocument: (id: string) => Promise<void>
  clearError: () => void
}

export const useCollectionsStore = create<CollectionsState>((set, get) => ({
  collections: [],
  selectedCollection: null,
  documents: [],
  isLoading: false,
  error: null,

  loadCollections: async () => {
    set({ isLoading: true })
    try {
      const collections = await collectionsApi.list()
      set({ collections, isLoading: false })
    } catch (error) {
      set({ error: 'Failed to load collections', isLoading: false })
    }
  },

  createCollection: async (name: string, description?: string) => {
    try {
      const collection = await collectionsApi.create(name, description)
      set({ collections: [...get().collections, collection] })
    } catch (error) {
      set({ error: 'Failed to create collection' })
    }
  },

  selectCollection: async (id: string) => {
    set({ isLoading: true })
    try {
      const collection = await collectionsApi.get(id)
      const documents = await collectionsApi.getDocuments(id)
      set({
        selectedCollection: collection,
        documents,
        isLoading: false,
      })
    } catch (error) {
      set({ error: 'Failed to load collection', isLoading: false })
    }
  },

  deleteCollection: async (id: string) => {
    try {
      await collectionsApi.delete(id)
      const { collections, selectedCollection } = get()
      set({
        collections: collections.filter((c) => c.id !== id),
        ...(selectedCollection?.id === id
          ? { selectedCollection: null, documents: [] }
          : {}),
      })
    } catch (error) {
      set({ error: 'Failed to delete collection' })
    }
  },

  uploadDocuments: async (files: File[]) => {
    const { selectedCollection } = get()
    if (!selectedCollection) return

    set({ isLoading: true })
    try {
      const newDocs = await collectionsApi.uploadDocuments(selectedCollection.id, files)
      set({
        documents: [...get().documents, ...newDocs],
        isLoading: false,
      })
      // Reload collection to get updated count
      await get().selectCollection(selectedCollection.id)
    } catch (error) {
      set({ error: 'Failed to upload documents', isLoading: false })
    }
  },

  deleteDocument: async (id: string) => {
    try {
      await collectionsApi.deleteDocument(id)
      set({ documents: get().documents.filter((d) => d.id !== id) })
    } catch (error) {
      set({ error: 'Failed to delete document' })
    }
  },

  clearError: () => set({ error: null }),
}))
