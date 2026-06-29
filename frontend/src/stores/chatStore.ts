import { create } from 'zustand'
import type { Conversation, Message, ImageAttachment } from '../types'
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
    databaseId?: string,
    image?: ImageAttachment | null
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

  sendMessage: async (
    message: string,
    collectionIds?: string[],
    databaseId?: string,
    image?: ImageAttachment | null
  ) => {
    const { currentConversation, messages } = get()

    // Add user message optimistically
    const userMessage: Message = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: message,
      created_at: new Date().toISOString(),
      imageUrl: image ? `data:${image.media_type};base64,${image.data}` : undefined,
    }

    // Placeholder assistant message, filled in live as events stream in
    const assistantId = `msg-${Date.now()}`
    const assistantMessage: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
    }

    set({
      messages: [...messages, userMessage, assistantMessage],
      isLoading: true,
      error: null,
    })

    const updateAssistant = (update: (msg: Message) => Message) => {
      set({
        messages: get().messages.map((m) => (m.id === assistantId ? update(m) : m)),
      })
    }

    let conversationId: string | null = null
    let streamError: string | null = null

    try {
      await chatApi.sendMessageStream(
        message,
        currentConversation?.id || null,
        collectionIds || null,
        databaseId || null,
        image || null,
        (event) => {
          if (event.type === 'metadata' && event.conversation_id) {
            conversationId = event.conversation_id
          } else if (event.type === 'content' && event.content) {
            updateAssistant((m) => ({ ...m, content: m.content + event.content }))
          } else if (event.type === 'tool_call' && event.tool) {
            updateAssistant((m) => ({
              ...m,
              tool_calls: [
                ...(m.tool_calls || []),
                {
                  tool: event.tool!,
                  args: event.args || {},
                  result: event.result || '',
                  agent: event.agent,
                },
              ],
            }))
          } else if (event.type === 'chart' && event.spec) {
            updateAssistant((m) => ({
              ...m,
              charts: [...(m.charts || []), event.spec!],
            }))
          } else if (event.type === 'action' && event.action === 'form_suggestion') {
            updateAssistant((m) => ({
              ...m,
              formSuggestions: [
                ...(m.formSuggestions || []),
                {
                  form_id: event.form_id || '',
                  form_name: event.form_name || 'Form',
                  redirect_url: event.redirect_url || '#',
                  prefill: event.prefill || {},
                },
              ],
            }))
          } else if (event.type === 'error' && event.error) {
            streamError = event.error
          }
        },
      )

      if (streamError) {
        set({ error: streamError, isLoading: false })
        return
      }

      set({ isLoading: false })

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
    } catch (error) {
      // Drop the empty placeholder on transport failure
      set({
        messages: get().messages.filter(
          (m) => m.id !== assistantId || m.content || m.tool_calls?.length
        ),
        isLoading: false,
        error: 'Failed to send message',
      })
    }
  },

  clearError: () => set({ error: null }),
}))
