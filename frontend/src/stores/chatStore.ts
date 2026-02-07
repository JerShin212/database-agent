import { create } from 'zustand'
import type { Conversation, Message, ToolCall, ChatStreamChunk } from '../types'
import { chatApi } from '../services/api'

interface ChatState {
  conversations: Conversation[]
  currentConversation: Conversation | null
  messages: Message[]
  isStreaming: boolean
  streamingContent: string
  streamingToolCalls: ToolCall[]
  error: string | null

  // Actions
  loadConversations: () => Promise<void>
  selectConversation: (id: string) => Promise<void>
  startNewConversation: () => void
  deleteConversation: (id: string) => Promise<void>
  sendMessage: (
    message: string,
    collectionIds?: string[],
    databaseId?: string
  ) => Promise<void>
  clearError: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  currentConversation: null,
  messages: [],
  isStreaming: false,
  streamingContent: '',
  streamingToolCalls: [],
  error: null,

  loadConversations: async () => {
    try {
      const conversations = await chatApi.getConversations()
      set({ conversations })
    } catch (error) {
      set({ error: 'Failed to load conversations' })
    }
  },

  selectConversation: async (id: string) => {
    try {
      const conversation = await chatApi.getConversation(id)
      set({
        currentConversation: conversation,
        messages: conversation.messages || [],
      })
    } catch (error) {
      set({ error: 'Failed to load conversation' })
    }
  },

  startNewConversation: () => {
    set({
      currentConversation: null,
      messages: [],
      streamingContent: '',
      streamingToolCalls: [],
    })
  },

  deleteConversation: async (id: string) => {
    try {
      await chatApi.deleteConversation(id)
      const { conversations, currentConversation } = get()
      set({
        conversations: conversations.filter((c) => c.id !== id),
        ...(currentConversation?.id === id
          ? { currentConversation: null, messages: [] }
          : {}),
      })
    } catch (error) {
      set({ error: 'Failed to delete conversation' })
    }
  },

  sendMessage: async (message: string, collectionIds?: string[], databaseId?: string) => {
    const { currentConversation, messages } = get()

    // Add user message optimistically
    const userMessage: Message = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: message,
      created_at: new Date().toISOString(),
    }

    set({
      messages: [...messages, userMessage],
      isStreaming: true,
      streamingContent: '',
      streamingToolCalls: [],
      error: null,
    })

    let conversationId = currentConversation?.id || null
    let assistantContent = ''
    const toolCalls: ToolCall[] = []

    try {
      await chatApi.streamChat(
        message,
        conversationId,
        collectionIds || null,
        databaseId || null,
        (chunk: ChatStreamChunk) => {
          switch (chunk.type) {
            case 'metadata':
              conversationId = chunk.conversation_id || conversationId
              break

            case 'content':
              assistantContent += chunk.content || ''
              set({ streamingContent: assistantContent })
              break

            case 'tool_call':
              toolCalls.push({
                tool: chunk.tool || '',
                args: chunk.args || {},
                result: chunk.result || '',
              })
              set({ streamingToolCalls: [...toolCalls] })
              break

            case 'error':
              set({ error: chunk.error || 'An error occurred' })
              break

            case 'done':
              // Finalize the assistant message
              const assistantMessage: Message = {
                id: `msg-${Date.now()}`,
                role: 'assistant',
                content: assistantContent,
                tool_calls: toolCalls.length > 0 ? toolCalls : undefined,
                created_at: new Date().toISOString(),
              }

              const updatedMessages = [...get().messages, assistantMessage]
              set({
                messages: updatedMessages,
                isStreaming: false,
                streamingContent: '',
                streamingToolCalls: [],
              })

              // Reload conversations to get updated list
              get().loadConversations()

              // Update current conversation
              if (conversationId) {
                set({
                  currentConversation: {
                    id: conversationId,
                    title: message.slice(0, 50),
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                  },
                })
              }
              break
          }
        }
      )
    } catch (error) {
      set({
        isStreaming: false,
        error: 'Failed to send message',
      })
    }
  },

  clearError: () => set({ error: null }),
}))
