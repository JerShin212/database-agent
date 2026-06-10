import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, ImagePlus, X } from 'lucide-react'
import { useChatStore } from '../../stores/chatStore'
import { useSettingsStore } from '../../stores/settingsStore'
import { fileToImageAttachment } from '../../utils/image'
import type { ImageAttachment } from '../../types'
import MessageList from './MessageList'
import clsx from 'clsx'

export default function ChatInterface() {
  const [input, setInput] = useState('')
  const [image, setImage] = useState<ImageAttachment | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const {
    messages,
    isLoading,
    sendMessage,
  } = useChatStore()

  const { selectedDatabaseId, selectedCollectionIds } = useSettingsStore()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if ((!input.trim() && !image) || isLoading) return

    const message = input.trim() || 'What is this? Find related documents.'
    setInput('')
    const attachedImage = image
    setImage(null)

    await sendMessage(
      message,
      selectedCollectionIds.length > 0 ? selectedCollectionIds : undefined,
      selectedDatabaseId || undefined,
      attachedImage
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file
    if (!file) return
    try {
      setImage(await fileToImageAttachment(file))
    } catch {
      // Ignore unreadable files; the user can retry with another image
    }
  }

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [input])

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <MessageList
          messages={messages}
          isLoading={isLoading}
        />
      </div>

      {/* Input */}
      <div className="border-t bg-white p-4">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
          {image && (
            <div className="mb-2 inline-block relative">
              <img
                src={`data:${image.media_type};base64,${image.data}`}
                alt="Attached"
                className="h-20 rounded-lg border border-gray-300 object-cover"
              />
              <button
                type="button"
                onClick={() => setImage(null)}
                className="absolute -top-2 -right-2 bg-gray-700 text-white rounded-full p-0.5 hover:bg-gray-900"
                aria-label="Remove image"
              >
                <X size={14} />
              </button>
            </div>
          )}
          <div className="relative flex items-end gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={handleFileChange}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isLoading}
              className={clsx(
                'p-3 rounded-lg transition-colors border',
                image
                  ? 'border-blue-400 text-blue-600 bg-blue-50'
                  : 'border-gray-300 text-gray-500 hover:text-blue-600 hover:border-blue-300'
              )}
              title="Attach an image (e.g. a photo of a machine to find its manual)"
            >
              <ImagePlus size={20} />
            </button>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={image ? 'Ask about the attached image...' : 'Ask about your data...'}
              rows={1}
              className={clsx(
                'flex-1 resize-none rounded-lg border border-gray-300 px-4 py-3',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'max-h-40 overflow-y-auto'
              )}
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={(!input.trim() && !image) || isLoading}
              className={clsx(
                'p-3 rounded-lg transition-colors',
                (input.trim() || image) && !isLoading
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-gray-100 text-gray-400 cursor-not-allowed'
              )}
            >
              {isLoading ? (
                <Loader2 size={20} className="animate-spin" />
              ) : (
                <Send size={20} />
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
