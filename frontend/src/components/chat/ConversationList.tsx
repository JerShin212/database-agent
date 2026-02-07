import { useEffect } from 'react'
import { Plus, MessageSquare, Trash2 } from 'lucide-react'
import { useChatStore } from '../../stores/chatStore'
import clsx from 'clsx'

export default function ConversationList() {
  const {
    conversations,
    currentConversation,
    loadConversations,
    selectConversation,
    startNewConversation,
    deleteConversation,
  } = useChatStore()

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b">
        <button
          onClick={startNewConversation}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={18} />
          New Chat
        </button>
      </div>

      {/* Conversations */}
      <div className="flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <div className="p-4 text-center text-gray-500 text-sm">
            No conversations yet
          </div>
        ) : (
          <div className="p-2">
            {conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={clsx(
                  'group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer mb-1',
                  currentConversation?.id === conversation.id
                    ? 'bg-blue-50 text-blue-700'
                    : 'hover:bg-gray-100'
                )}
                onClick={() => selectConversation(conversation.id)}
              >
                <MessageSquare size={16} className="flex-shrink-0" />
                <span className="flex-1 truncate text-sm">
                  {conversation.title || 'New conversation'}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteConversation(conversation.id)
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-100 rounded transition-opacity"
                >
                  <Trash2 size={14} className="text-red-500" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
