import { useEffect } from 'react'
import ConversationList from '../components/chat/ConversationList'
import ChatInterface from '../components/chat/ChatInterface'
import { useChatStore } from '../stores/chatStore'
import { useSettingsStore } from '../stores/settingsStore'
import { useCollectionsStore } from '../stores/collectionsStore'
import { useDatabasesStore } from '../stores/databasesStore'
import { Database, FolderOpen, X } from 'lucide-react'
import clsx from 'clsx'

export default function ChatPage() {
  const { error, clearError } = useChatStore()
  const { selectedDatabaseId, selectedCollectionIds, setDatabase, toggleCollection } = useSettingsStore()
  const { collections, loadCollections } = useCollectionsStore()
  const { databases, loadDatabases } = useDatabasesStore()

  useEffect(() => {
    loadCollections()
    loadDatabases()
  }, [loadCollections, loadDatabases])

  return (
    <div className="flex h-full">
      {/* Conversation sidebar */}
      <div className="w-64 border-r bg-white">
        <ConversationList />
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col">
        {/* Header with selectors */}
        <div className="bg-white border-b px-4 py-3 flex items-center gap-4">
          <h1 className="font-semibold text-lg">Database Agent</h1>

          {/* Database selector */}
          <div className="flex items-center gap-2">
            <Database size={16} className="text-gray-500" />
            <select
              value={selectedDatabaseId || ''}
              onChange={(e) => setDatabase(e.target.value || null)}
              className="text-sm border rounded px-2 py-1"
            >
              <option value="">All databases</option>
              {databases.map((db) => (
                <option key={db.id} value={db.id}>
                  {db.name}
                </option>
              ))}
            </select>
          </div>

          {/* Collection selector */}
          <div className="flex items-center gap-2">
            <FolderOpen size={16} className="text-gray-500" />
            <div className="flex gap-1 flex-wrap">
              {selectedCollectionIds.length === 0 ? (
                <span className="text-sm text-gray-500">All collections</span>
              ) : (
                selectedCollectionIds.map((id) => {
                  const coll = collections.find((c) => c.id === id)
                  return (
                    <span
                      key={id}
                      className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-xs px-2 py-1 rounded"
                    >
                      {coll?.name || id}
                      <button onClick={() => toggleCollection(id)}>
                        <X size={12} />
                      </button>
                    </span>
                  )
                })
              )}
              <select
                value=""
                onChange={(e) => e.target.value && toggleCollection(e.target.value)}
                className="text-sm border rounded px-2 py-1"
              >
                <option value="">+ Add collection</option>
                {collections
                  .filter((c) => !selectedCollectionIds.includes(c.id))
                  .map((coll) => (
                    <option key={coll.id} value={coll.id}>
                      {coll.name}
                    </option>
                  ))}
              </select>
            </div>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="bg-red-50 border-b border-red-200 px-4 py-2 flex items-center justify-between">
            <span className="text-red-700 text-sm">{error}</span>
            <button onClick={clearError} className="text-red-500 hover:text-red-700">
              <X size={16} />
            </button>
          </div>
        )}

        {/* Chat interface */}
        <div className="flex-1 overflow-hidden">
          <ChatInterface />
        </div>
      </div>
    </div>
  )
}
