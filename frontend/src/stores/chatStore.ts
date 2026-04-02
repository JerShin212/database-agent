import { create } from 'zustand'
import type { Conversation, Message } from '../types'
import { chatApi } from '../services/api'

interface ChatState {
  conversations: Conversation[]
  currentConversation: Conversation | null
  messages: Message[]
  isLoading: boolean
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
  isLoading: false,
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
      isLoading: true,
      error: null,
    })

    try {
      const response = await chatApi.sendMessage(
        message,
        currentConversation?.id || null,
        collectionIds || null,
        databaseId || null,
      )

      if (response.error) {
        set({ error: response.error, isLoading: false })
        return
      }

      const assistantMessage: Message = {
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content: response.content,
        tool_calls: response.tool_calls.length > 0 ? response.tool_calls : undefined,
        created_at: new Date().toISOString(),
      }

      set({
        messages: [...get().messages, assistantMessage],
        isLoading: false,
      })

      // Reload conversations to get updated list
      get().loadConversations()

      // Update current conversation
      if (response.conversation_id) {
        set({
          currentConversation: {
            id: response.conversation_id,
            title: message.slice(0, 50),
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        })
      }
    } catch (error) {
      set({
        isLoading: false,
        error: 'Failed to send message',
      })
    }
  },

  clearError: () => set({ error: null }),
}))
