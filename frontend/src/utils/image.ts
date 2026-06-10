import type { ImageAttachment } from '../types'

const MAX_EDGE = 1568 // Claude vision's optimal max edge; keeps payloads small
const JPEG_QUALITY = 0.85

/**
 * Downscale an image file (if needed) and return it as a base64 attachment.
 * Re-encodes to JPEG to keep the request body well under size limits.
 */
export async function fileToImageAttachment(file: File): Promise<ImageAttachment> {
  const bitmap = await createImageBitmap(file)

  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height))
  const width = Math.round(bitmap.width * scale)
  const height = Math.round(bitmap.height * scale)

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas not supported')
  ctx.drawImage(bitmap, 0, 0, width, height)
  bitmap.close()

  const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY)
  return {
    data: dataUrl.split(',')[1],
    media_type: 'image/jpeg',
  }
}
