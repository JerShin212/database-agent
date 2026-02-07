import { useEffect, useState } from 'react'
import { Plus, Database, Trash2, Play, Table, Key, ArrowRight } from 'lucide-react'
import { useDatabasesStore } from '../stores/databasesStore'
import clsx from 'clsx'

export default function DatabasesPage() {
  const {
    databases,
    selectedDatabase,
    schema,
    queryResult,
    isLoading,
    loadDatabases,
    createSampleDatabase,
    selectDatabase,
    deleteDatabase,
    executeQuery,
    clearQueryResult,
  } = useDatabasesStore()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('Sales Database')
  const [sqlQuery, setSqlQuery] = useState('')

  useEffect(() => {
    loadDatabases()
  }, [loadDatabases])

  const handleCreate = async () => {
    if (!newName.trim()) return
    await createSampleDatabase(newName.trim())
    setShowCreateModal(false)
    setNewName('Sales Database')
  }

  const handleExecuteQuery = async () => {
    if (!sqlQuery.trim()) return
    await executeQuery(sqlQuery.trim())
  }

  return (
    <div className="flex h-full">
      {/* Databases list */}
      <div className="w-80 border-r bg-white">
        <div className="p-4 border-b">
          <h2 className="font-semibold text-lg mb-4">Databases</h2>
          <button
            onClick={() => setShowCreateModal(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus size={18} />
            Create Sample DB
          </button>
        </div>

        <div className="overflow-y-auto">
          {databases.length === 0 ? (
            <div className="p-4 text-center text-gray-500 text-sm">
              No databases yet
            </div>
          ) : (
            <div className="p-2">
              {databases.map((db) => (
                <div
                  key={db.id}
                  onClick={() => selectDatabase(db.id)}
                  className={clsx(
                    'group flex items-center gap-3 px-3 py-3 rounded-lg cursor-pointer mb-1',
                    selectedDatabase?.id === db.id
                      ? 'bg-blue-50 border border-blue-200'
                      : 'hover:bg-gray-50'
                  )}
                >
                  <Database size={20} className="text-green-500" />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{db.name}</div>
                    <div className="text-xs text-gray-500 truncate">
                      {db.file_path}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteDatabase(db.id)
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

      {/* Database details */}
      <div className="flex-1 overflow-y-auto p-6">
        {selectedDatabase && schema ? (
          <div>
            <div className="mb-6">
              <h2 className="text-2xl font-bold">{selectedDatabase.name}</h2>
              {selectedDatabase.description && (
                <p className="text-gray-600 mt-1">{selectedDatabase.description}</p>
              )}
            </div>

            {/* Schema viewer */}
            <div className="mb-6">
              <h3 className="font-semibold text-lg mb-3">Schema</h3>
              <div className="grid gap-4">
                {schema.tables.map((table) => (
                  <div key={table.name} className="bg-white rounded-lg border">
                    <div className="flex items-center gap-2 px-4 py-3 bg-gray-50 border-b">
                      <Table size={18} className="text-blue-500" />
                      <span className="font-medium">{table.name}</span>
                      <span className="text-xs text-gray-500">
                        ({table.row_count} rows)
                      </span>
                    </div>
                    <div className="p-4">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-gray-500">
                            <th className="pb-2">Column</th>
                            <th className="pb-2">Type</th>
                            <th className="pb-2">Constraints</th>
                          </tr>
                        </thead>
                        <tbody>
                          {table.columns.map((col) => (
                            <tr key={col.name} className="border-t">
                              <td className="py-2 font-mono text-xs">
                                {col.name}
                              </td>
                              <td className="py-2 text-gray-600">{col.type}</td>
                              <td className="py-2">
                                <div className="flex gap-1">
                                  {col.primary_key && (
                                    <span className="inline-flex items-center gap-1 bg-yellow-100 text-yellow-700 text-xs px-2 py-0.5 rounded">
                                      <Key size={10} />
                                      PK
                                    </span>
                                  )}
                                  {col.foreign_key && (
                                    <span className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded">
                                      <ArrowRight size={10} />
                                      {col.foreign_key}
                                    </span>
                                  )}
                                  {!col.nullable && (
                                    <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded">
                                      NOT NULL
                                    </span>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Query tester */}
            <div className="mb-6">
              <h3 className="font-semibold text-lg mb-3">Query Tester</h3>
              <div className="bg-white rounded-lg border p-4">
                <textarea
                  value={sqlQuery}
                  onChange={(e) => setSqlQuery(e.target.value)}
                  placeholder="SELECT * FROM customers LIMIT 10"
                  className="w-full font-mono text-sm border rounded-lg p-3 mb-3"
                  rows={4}
                />
                <button
                  onClick={handleExecuteQuery}
                  disabled={!sqlQuery.trim() || isLoading}
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                >
                  <Play size={16} />
                  Execute
                </button>

                {queryResult && (
                  <div className="mt-4">
                    {queryResult.error ? (
                      <div className="bg-red-50 text-red-700 p-3 rounded-lg">
                        {queryResult.error}
                      </div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="bg-gray-50">
                              {queryResult.columns.map((col) => (
                                <th
                                  key={col}
                                  className="px-3 py-2 text-left font-medium"
                                >
                                  {col}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {queryResult.rows.slice(0, 20).map((row, i) => (
                              <tr key={i} className="border-t">
                                {row.map((cell, j) => (
                                  <td key={j} className="px-3 py-2">
                                    {String(cell)}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="text-xs text-gray-500 mt-2">
                          {queryResult.row_count} rows
                          {queryResult.row_count > 20 && ' (showing first 20)'}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <Database size={48} className="mb-4 text-gray-300" />
            <p>Select a database to view schema</p>
          </div>
        )}
      </div>

      {/* Create modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h3 className="text-lg font-semibold mb-4">Create Sample Database</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2"
                  placeholder="Database name"
                />
              </div>
              <p className="text-sm text-gray-500">
                This will create a sample SQLite database with customers,
                products, orders, and sales data for testing.
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!newName.trim() || isLoading}
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
