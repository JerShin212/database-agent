import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsState {
  selectedDatabaseId: string | null
  selectedCollectionIds: string[]

  // Actions
  setDatabase: (id: string | null) => void
  toggleCollection: (id: string) => void
  clearCollections: () => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      selectedDatabaseId: null,
      selectedCollectionIds: [],

      setDatabase: (id: string | null) => {
        set({ selectedDatabaseId: id })
      },

      toggleCollection: (id: string) => {
        const { selectedCollectionIds } = get()
        if (selectedCollectionIds.includes(id)) {
          set({
            selectedCollectionIds: selectedCollectionIds.filter((cid) => cid !== id),
          })
        } else {
          set({
            selectedCollectionIds: [...selectedCollectionIds, id],
          })
        }
      },

      clearCollections: () => {
        set({ selectedCollectionIds: [] })
      },
    }),
    {
      name: 'database-agent-settings',
    }
  )
)
