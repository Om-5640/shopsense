/**
 * Typed EventSource wrapper for pipeline streaming.
 * Returns a cleanup function — call it to close the connection.
 */

import type { PipelineEvent } from './types'

export interface SSEHandlers {
  onStageStart: (stage: string, label: string) => void
  onStageDone: (stage: string, count?: number, productsFound?: number) => void
  onProgress: (stage: string, current: number, total?: number, detail?: string) => void
  onError: (message: string) => void
  onDone: (searchId: string) => void
  onWarning?: (message: string) => void
}

export function connectSSE(searchId: string, handlers: SSEHandlers, reconnect = false): () => void {
  const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
  const url = `${BASE}/api/search/${searchId}/stream${reconnect ? '?reconnect=true' : ''}`
  const es = new EventSource(url)

  es.onmessage = (evt) => {
    if (evt.data === '[DONE]') {
      es.close()
      handlers.onDone(searchId)
      return
    }
    try {
      const event = JSON.parse(evt.data) as PipelineEvent
      if (event.type === 'stage_start') {
        handlers.onStageStart(event.data.stage ?? '', (event.data.label as string) ?? '')
      } else if (event.type === 'stage_done') {
        handlers.onStageDone(
          event.data.stage ?? '',
          event.data.count as number | undefined,
          event.data.products_found as number | undefined,
        )
      } else if (event.type === 'progress') {
        handlers.onProgress(
          event.data.stage ?? '',
          (event.data.current as number) ?? 0,
          event.data.total as number | undefined,
          event.data.detail as string | undefined,
        )
      } else if (event.type === 'error') {
        handlers.onError((event.data.message as string) ?? 'Pipeline error')
        es.close()
      } else if (event.type === 'log') {
        const msg = (event.data.message as string) ?? ''
        if (msg.includes('[token_budget]') && msg.includes('exceeds') && handlers.onWarning) {
          handlers.onWarning(msg)
        }
      }
    } catch {
      // ignore parse errors on malformed SSE frames
    }
  }

  es.onerror = () => {
    es.close()
    handlers.onError('Lost connection to API. Check the server is running.')
  }

  return () => es.close()
}
