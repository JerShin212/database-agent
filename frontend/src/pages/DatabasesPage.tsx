import { useEffect, useState } from 'react'
import {
  Plus,
  Database,
  Trash2,
  Play,
  Table,
  Key,
  ArrowRight,
  Link,
  CheckCircle,
  XCircle,
  Loader,
  RefreshCw,
  Search,
} from 'lucide-react'
import { useDatabasesStore } from '../stores/databasesStore'
import { useConnectorsStore } from '../stores/connectorsStore'
import clsx from 'clsx'

type Tab = 'sqlite' | 'connectors'

export default function DatabasesPage() {
  const [activeTab, setActiveTab] = useState<Tab>('sqlite')

  return (
    <div className="flex h-full flex-col">
      {/* Tabs */}
      <div className="border-b bg-white px-6">
        <div className="flex gap-4">
          <button
            onClick={() => setActiveTab('sqlite')}
            className={clsx(
              'px-4 py-3 font-medium border-b-2 transition-colors',
              activeTab === 'sqlite'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            )}
          >
            SQLite Databases
          </button>
          <button
            onClick={() => setActiveTab('connectors')}
            className={clsx(
              'px-4 py-3 font-medium border-b-2 transition-colors',
              activeTab === 'connectors'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            )}
          >
            External Databases
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'sqlite' ? <SQLiteDatabasesTab /> : <ConnectorsTab />}
      </div>
    </div>
  )
}

function SQLiteDatabasesTab() {
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
      <div className="w-80 border-r bg-white overflow-y-auto">
        <div className="p-4 border-b">
          <button
            onClick={() => setShowCreateModal(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus size={18} />
            Create Sample DB
          </button>
        </div>

        <div>
          {databases.length === 0 ? (
            <div className="p-4 text-center text-gray-500 text-sm">No databases yet</div>
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
                    <div className="text-xs text-gray-500 truncate">{db.file_path}</div>
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
                      <span className="text-xs text-gray-500">({table.row_count} rows)</span>
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
                              <td className="py-2 font-mono text-xs">{col.name}</td>
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
                      <div className="bg-red-50 text-red-700 p-3 rounded-lg">{queryResult.error}</div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="bg-gray-50">
                              {queryResult.columns.map((col) => (
                                <th key={col} className="px-3 py-2 text-left font-medium">
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
                This will create a sample SQLite database with customers, products, orders, and
                sales data. <strong>The schema will be automatically indexed for semantic search.</strong>
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

function ConnectorsTab() {
  const {
    connectors,
    selectedConnector,
    tables,
    schemaSearchResults,
    isLoading,
    loadConnectors,
    createConnector,
    selectConnector,
    testConnection,
    indexSchema,
    deleteConnector,
    searchSchema,
    refreshConnector,
  } = useConnectorsStore()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showTestResult, setShowTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [connectorForm, setConnectorForm] = useState({
    name: '',
    db_type: 'postgresql' as 'sqlite' | 'postgresql' | 'mysql',
    connection_string: '',
  })

  useEffect(() => {
    loadConnectors()
  }, [loadConnectors])

  const handleCreate = async () => {
    if (!connectorForm.name.trim() || !connectorForm.connection_string.trim()) return

    try {
      await createConnector({
        ...connectorForm,
        user_id: 'e8bb8ed5-75ea-4842-8398-59d94130eb81', // Default user ID
      })
      setShowCreateModal(false)
      setConnectorForm({ name: '', db_type: 'postgresql', connection_string: '' })
    } catch (error) {
      console.error('Failed to create connector:', error)
    }
  }

  const handleTest = async (id: string) => {
    try {
      const result = await testConnection(id)
      setShowTestResult(result)
      setTimeout(() => setShowTestResult(null), 5000)
    } catch (error) {
      setShowTestResult({ success: false, message: 'Connection test failed' })
      setTimeout(() => setShowTestResult(null), 5000)
    }
  }

  const handleIndex = async (id: string) => {
    try {
      await indexSchema(id)
    } catch (error) {
      console.error('Failed to index schema:', error)
    }
  }

  const handleSearch = () => {
    if (!selectedConnector || !searchQuery.trim()) return
    searchSchema(searchQuery, selectedConnector.id)
  }

  return (
    <div className="flex h-full">
      {/* Connectors list */}
      <div className="w-80 border-r bg-white overflow-y-auto">
        <div className="p-4 border-b">
          <button
            onClick={() => setShowCreateModal(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus size={18} />
            Add Connector
          </button>
        </div>

        <div>
          {connectors.length === 0 ? (
            <div className="p-4 text-center text-gray-500 text-sm">No connectors yet</div>
          ) : (
            <div className="p-2">
              {connectors.map((connector) => (
                <div
                  key={connector.id}
                  onClick={() => selectConnector(connector.id)}
                  className={clsx(
                    'group flex items-center gap-3 px-3 py-3 rounded-lg cursor-pointer mb-1',
                    selectedConnector?.id === connector.id
                      ? 'bg-blue-50 border border-blue-200'
                      : 'hover:bg-gray-50'
                  )}
                >
                  <Link size={20} className="text-purple-500" />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{connector.name}</div>
                    <div className="text-xs text-gray-500">{connector.db_type}</div>
                    <div className="flex items-center gap-1 mt-1">
                      {connector.status === 'ready' && (
                        <span className="inline-flex items-center gap-1 bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded">
                          <CheckCircle size={10} />
                          Ready
                        </span>
                      )}
                      {connector.status === 'indexing' && (
                        <span className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded">
                          <Loader size={10} className="animate-spin" />
                          Indexing
                        </span>
                      )}
                      {connector.status === 'pending' && (
                        <span className="inline-flex items-center gap-1 bg-gray-100 text-gray-700 text-xs px-2 py-0.5 rounded">
                          Pending
                        </span>
                      )}
                      {connector.status === 'failed' && (
                        <span className="inline-flex items-center gap-1 bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded">
                          <XCircle size={10} />
                          Failed
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteConnector(connector.id)
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

      {/* Connector details */}
      <div className="flex-1 overflow-y-auto p-6">
        {selectedConnector ? (
          <div>
            <div className="mb-6 flex items-start justify-between">
              <div>
                <h2 className="text-2xl font-bold">{selectedConnector.name}</h2>
                <p className="text-gray-600 mt-1">
                  {selectedConnector.db_type} • {selectedConnector.status}
                </p>
                {selectedConnector.error_message && (
                  <p className="text-red-600 text-sm mt-2">{selectedConnector.error_message}</p>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => refreshConnector(selectedConnector.id)}
                  className="px-3 py-2 border rounded-lg hover:bg-gray-50"
                  title="Refresh"
                >
                  <RefreshCw size={16} />
                </button>
                <button
                  onClick={() => handleTest(selectedConnector.id)}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50"
                >
                  Test Connection
                </button>
                {selectedConnector.status === 'pending' && (
                  <button
                    onClick={() => handleIndex(selectedConnector.id)}
                    disabled={isLoading}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                  >
                    Index Schema
                  </button>
                )}
              </div>
            </div>

            {showTestResult && (
              <div
                className={clsx(
                  'mb-4 p-3 rounded-lg',
                  showTestResult.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                )}
              >
                {showTestResult.message}
              </div>
            )}

            {selectedConnector.status === 'indexing' && selectedConnector.indexing_progress && (
              <div className="mb-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Loader size={16} className="animate-spin text-blue-600" />
                  <span className="font-medium">Indexing Schema...</span>
                </div>
                <div className="text-sm text-gray-600">
                  Stage: {selectedConnector.indexing_progress.stage} (
                  {selectedConnector.indexing_progress.current} /{' '}
                  {selectedConnector.indexing_progress.total})
                </div>
                {selectedConnector.indexing_progress.table && (
                  <div className="text-sm text-gray-600">
                    Table: {selectedConnector.indexing_progress.table}
                    {selectedConnector.indexing_progress.column &&
                      `.${selectedConnector.indexing_progress.column}`}
                  </div>
                )}
              </div>
            )}

            {selectedConnector.status === 'ready' && (
              <>
                {/* Semantic schema search */}
                <div className="mb-6">
                  <h3 className="font-semibold text-lg mb-3">Semantic Schema Search</h3>
                  <div className="bg-white rounded-lg border p-4">
                    <div className="flex gap-2 mb-4">
                      <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
                        placeholder="Search schema semantically (e.g., 'customer email')"
                        className="flex-1 border rounded-lg px-3 py-2"
                      />
                      <button
                        onClick={handleSearch}
                        disabled={!searchQuery.trim()}
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                      >
                        <Search size={16} />
                      </button>
                    </div>

                    {schemaSearchResults.length > 0 && (
                      <div className="space-y-3">
                        {schemaSearchResults.map((result) => (
                          <div key={result.id} className="border rounded-lg p-3">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="font-mono text-sm font-medium">
                                {result.table_name}
                                {result.column_name && `.${result.column_name}`}
                              </span>
                              {result.data_type && (
                                <span className="text-xs text-gray-500">({result.data_type})</span>
                              )}
                              {result.score && (
                                <span className="ml-auto text-xs text-gray-500">
                                  {(result.score * 100).toFixed(1)}% match
                                </span>
                              )}
                            </div>
                            <p className="text-sm text-gray-600">{result.semantic_definition}</p>
                            {result.sample_values && result.sample_values.length > 0 && (
                              <div className="mt-1 text-xs text-gray-500">
                                Examples: {result.sample_values.slice(0, 3).map(String).join(', ')}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Tables list */}
                <div className="mb-6">
                  <h3 className="font-semibold text-lg mb-3">Tables ({tables.length})</h3>
                  <div className="grid gap-2">
                    {tables.map((table) => (
                      <div key={table.name} className="bg-white rounded-lg border px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Table size={18} className="text-blue-500" />
                          <span className="font-medium">{table.name}</span>
                          <span className="text-xs text-gray-500">({table.column_count} columns)</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <Link size={48} className="mb-4 text-gray-300" />
            <p>Select a connector to view details</p>
          </div>
        )}
      </div>

      {/* Create connector modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[600px]">
            <h3 className="text-lg font-semibold mb-4">Add External Database Connector</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input
                  type="text"
                  value={connectorForm.name}
                  onChange={(e) => setConnectorForm({ ...connectorForm, name: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2"
                  placeholder="Production Database"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Database Type</label>
                <select
                  value={connectorForm.db_type}
                  onChange={(e) =>
                    setConnectorForm({
                      ...connectorForm,
                      db_type: e.target.value as 'sqlite' | 'postgresql' | 'mysql',
                    })
                  }
                  className="w-full border rounded-lg px-3 py-2"
                >
                  <option value="sqlite">SQLite</option>
                  <option value="postgresql">PostgreSQL</option>
                  <option value="mysql">MySQL</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Connection String</label>
                <input
                  type="text"
                  value={connectorForm.connection_string}
                  onChange={(e) =>
                    setConnectorForm({ ...connectorForm, connection_string: e.target.value })
                  }
                  className="w-full border rounded-lg px-3 py-2 font-mono text-sm"
                  placeholder="postgresql://user:pass@host:5432/dbname"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Examples:
                  <br />
                  PostgreSQL: postgresql://user:pass@localhost:5432/mydb
                  <br />
                  MySQL: mysql://user:pass@localhost:3306/mydb
                  <br />
                  SQLite: sqlite:////app/data/sqlite/mydb.db
                </p>
              </div>
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm">
                <strong>Note:</strong> After creating the connector, you'll need to test the connection and trigger schema indexing. The system will generate semantic definitions for all tables and columns using LLM.
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
                  disabled={
                    !connectorForm.name.trim() || !connectorForm.connection_string.trim() || isLoading
                  }
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
