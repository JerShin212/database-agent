import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { User, Bot, Wrench, Loader2 } from 'lucide-react'
import type { Message, ToolCall } from '../../types'
import { useChatStore } from '../../stores/chatStore'
import clsx from 'clsx'

interface MessageListProps {
  messages: Message[]
  isLoading: boolean
}

export default function MessageList({
  messages,
  isLoading,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  if (messages.length === 0 && !isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-500">
        <Bot size={48} className="mb-4 text-gray-300" />
        <h2 className="text-xl font-semibold mb-2">Database Agent</h2>
        <p className="text-center max-w-md">
          Ask questions about your databases and document collections.
          I can execute SQL queries, search documents, and help analyze your data.
        </p>
        <div className="mt-6 grid grid-cols-2 gap-4">
          <SuggestionCard text="What tables are in the database?" />
          <SuggestionCard text="Show me the top 10 customers by orders" />
          <SuggestionCard text="Search for documents about sales" />
          <SuggestionCard text="What products have low stock?" />
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto py-6 px-4">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}

      {/* Loading indicator */}
      {isLoading && (
        <div className="mb-6 flex gap-3">
          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
            <Bot size={18} className="text-blue-600" />
          </div>
          <div className="flex-1 bg-white rounded-lg p-4 shadow-sm">
            <Loader2 size={20} className="animate-spin text-blue-500" />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className="mb-6">
      {/* Tool calls for assistant */}
      {!isUser && message.tool_calls?.map((toolCall, i) => (
        <ToolCallDisplay key={i} toolCall={toolCall} />
      ))}

      <div className={clsx('flex gap-3', isUser && 'flex-row-reverse')}>
        <div
          className={clsx(
            'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
            isUser ? 'bg-gray-200' : 'bg-blue-100'
          )}
        >
          {isUser ? (
            <User size={18} className="text-gray-600" />
          ) : (
            <Bot size={18} className="text-blue-600" />
          )}
        </div>

        <div
          className={clsx(
            'flex-1 rounded-lg p-4 shadow-sm',
            isUser ? 'bg-blue-600 text-white' : 'bg-white'
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <ReactMarkdown className="prose prose-sm max-w-none" remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  )
}

function ToolCallDisplay({ toolCall }: { toolCall: ToolCall }) {
  return (
    <div className="mb-4 ml-11">
      <div className="bg-gray-100 rounded-lg p-3 text-sm">
        <div className="flex items-center gap-2 text-gray-600 mb-2">
          <Wrench size={14} />
          <span className="font-medium">{toolCall.tool}</span>
        </div>
        {toolCall.args && Object.keys(toolCall.args).length > 0 && (
          <pre className="bg-gray-800 text-gray-200 rounded p-2 text-xs overflow-x-auto mb-2">
            {JSON.stringify(toolCall.args, null, 2)}
          </pre>
        )}
        {toolCall.result && (
          <pre className="bg-white rounded p-2 text-xs overflow-x-auto max-h-40">
            {toolCall.result.slice(0, 500)}
            {toolCall.result.length > 500 && '...'}
          </pre>
        )}
      </div>
    </div>
  )
}

function SuggestionCard({ text }: { text: string }) {
  const { sendMessage } = useChatStore()

  return (
    <button
      onClick={() => sendMessage(text)}
      className="p-3 bg-white rounded-lg border hover:border-blue-300 hover:shadow-sm transition-all text-left text-sm text-gray-600"
    >
      {text}
    </button>
  )
}
