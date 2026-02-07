import { useEffect, useState, useRef } from 'react'
import { Plus, FolderOpen, Trash2, Upload, FileText, Loader2, CheckCircle, XCircle, Clock } from 'lucide-react'
import { useCollectionsStore } from '../stores/collectionsStore'
import clsx from 'clsx'

export default function CollectionsPage() {
  const {
    collections,
    selectedCollection,
    documents,
    isLoading,
    error,
    loadCollections,
    createCollection,
    selectCollection,
    deleteCollection,
    uploadDocuments,
    deleteDocument,
    clearError,
  } = useCollectionsStore()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    loadCollections()
  }, [loadCollections])

  const handleCreate = async () => {
    if (!newName.trim()) return
    await createCollection(newName.trim(), newDescription.trim() || undefined)
    setShowCreateModal(false)
    setNewName('')
    setNewDescription('')
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    await uploadDocuments(Array.from(files))
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle size={16} className="text-green-500" />
      case 'failed':
        return <XCircle size={16} className="text-red-500" />
      case 'processing':
        return <Loader2 size={16} className="text-blue-500 animate-spin" />
      default:
        return <Clock size={16} className="text-gray-400" />
    }
  }

  return (
    <div className="flex h-full">
      {/* Collections list */}
      <div className="w-80 border-r bg-white">
        <div className="p-4 border-b">
          <h2 className="font-semibold text-lg mb-4">Collections</h2>
          <button
            onClick={() => setShowCreateModal(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus size={18} />
            New Collection
          </button>
        </div>

        <div className="overflow-y-auto">
          {collections.length === 0 ? (
            <div className="p-4 text-center text-gray-500 text-sm">
              No collections yet
            </div>
          ) : (
            <div className="p-2">
              {collections.map((collection) => (
                <div
                  key={collection.id}
                  onClick={() => selectCollection(collection.id)}
                  className={clsx(
                    'group flex items-center gap-3 px-3 py-3 rounded-lg cursor-pointer mb-1',
                    selectedCollection?.id === collection.id
                      ? 'bg-blue-50 border border-blue-200'
                      : 'hover:bg-gray-50'
                  )}
                >
                  <FolderOpen size={20} className="text-blue-500" />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{collection.name}</div>
                    <div className="text-xs text-gray-500">
                      {collection.document_count} documents
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteCollection(collection.id)
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-100 rounded"
                  >
                    <Trash2 size={16} className="text-red-500" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Collection details */}
      <div className="flex-1 p-6">
        {selectedCollection ? (
          <div>
            <div className="mb-6">
              <h2 className="text-2xl font-bold">{selectedCollection.name}</h2>
              {selectedCollection.description && (
                <p className="text-gray-600 mt-1">{selectedCollection.description}</p>
              )}
            </div>

            {/* Upload area */}
            <div className="mb-6">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileUpload}
                className="hidden"
                accept=".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt,.md"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2 border-2 border-dashed rounded-lg',
                  'hover:border-blue-400 hover:bg-blue-50 transition-colors',
                  isLoading && 'opacity-50 cursor-not-allowed'
                )}
              >
                {isLoading ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : (
                  <Upload size={18} />
                )}
                Upload Documents
              </button>
            </div>

            {/* Documents list */}
            <div className="bg-white rounded-lg border">
              <div className="px-4 py-3 border-b bg-gray-50 font-medium">
                Documents ({documents.length})
              </div>
              {documents.length === 0 ? (
                <div className="p-8 text-center text-gray-500">
                  No documents yet. Upload some files to get started.
                </div>
              ) : (
                <div className="divide-y">
                  {documents.map((doc) => (
                    <div
                      key={doc.id}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50"
                    >
                      <FileText size={20} className="text-gray-400" />
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{doc.filename}</div>
                        <div className="text-xs text-gray-500">
                          {(doc.file_size / 1024).toFixed(1)} KB
                          {doc.page_count && ` • ${doc.page_count} pages`}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {getStatusIcon(doc.status)}
                        <span className="text-xs text-gray-500 capitalize">
                          {doc.status}
                        </span>
                      </div>
                      <button
                        onClick={() => deleteDocument(doc.id)}
                        className="p-1 hover:bg-red-100 rounded"
                      >
                        <Trash2 size={16} className="text-red-500" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <FolderOpen size={48} className="mb-4 text-gray-300" />
            <p>Select a collection to view documents</p>
          </div>
        )}
      </div>

      {/* Create modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h3 className="text-lg font-semibold mb-4">Create Collection</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2"
                  placeholder="Collection name"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Description</label>
                <textarea
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2"
                  placeholder="Optional description"
                  rows={3}
                />
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!newName.trim()}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  Create
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
