/**
 * Typed EventSource wrapper for pipeline streaming.
 * Returns a cleanup function — call it to close the connection.
 * Auto-reconnects on transient disconnect with exponential backoff (Bug 1).
 */

import type { PipelineEvent } from './types'

/** Prefix emitted by pipeline_runner._emit_token_warning() — must stay in sync with the Python constant. */
export const TOKEN_BUDGET_WARNING_PREFIX = '[token_budget]'

export interface SSEHandlers {
  onStageStart: (stage: string, label: string) => void
  onStageDone: (stage: string, count?: number, productsFound?: number) => void
  onProgress: (stage: string, current: number, total?: number, detail?: string) => void
  onError: (message: string) => void
  /** Called when the pipeline finishes. `warnings` carries provider-fallback messages. */
  onDone: (searchId: string, fromCache?: boolean, warnings?: string[]) => void
  onWarning?: (message: string) => void
  /** Called when the pipeline returned a cached result — all stages can be marked complete. */
  onCacheHit?: () => void
  /** Called on every successful SSE message — use to reset watchdog timers. */
  onHeartbeat?: () => void
  /** Called when attempting to reconnect after a transient disconnect. */
  onReconnecting?: (attempt: number) => void
}

const MAX_RECONNECT_ATTEMPTS = 6
const BASE_RECONNECT_DELAY_MS = 1_000

export function connectSSE(searchId: string, handlers: SSEHandlers): () => void {
  const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
  let es: EventSource | null = null
  let attempt = 0
  let cancelled = false
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function connect(isReconnect: boolean): void {
    if (cancelled) return
    const url = `${BASE}/api/search/${searchId}/stream${isReconnect ? '?reconnect=true' : ''}`
    es = new EventSource(url)

    es.onmessage = (evt) => {
      attempt = 0  // reset backoff counter on any successful message
      handlers.onHeartbeat?.()

      if (evt.data === '[DONE]') {
        es!.close()
        handlers.onDone(searchId)
        return
      }
      try {
        const event = JSON.parse(evt.data) as PipelineEvent
        if (event.type === 'stage_start') {
          const stage = event.data.stage ?? ''
          if (stage === 'cache_hit') {
            handlers.onCacheHit?.()
          } else {
            handlers.onStageStart(stage, (event.data.label as string) ?? '')
          }
        } else if (event.type === 'stage_done') {
          const stage = event.data.stage ?? ''
          if (stage !== 'cache_hit') {
            handlers.onStageDone(
              stage,
              event.data.count as number | undefined,
              event.data.products_found as number | undefined,
            )
          }
        } else if (event.type === 'progress') {
          handlers.onProgress(
            event.data.stage ?? '',
            (event.data.current as number) ?? 0,
            event.data.total as number | undefined,
            event.data.detail as string | undefined,
          )
        } else if (event.type === 'error') {
          handlers.onError((event.data.message as string) ?? 'Pipeline error')
          es!.close()
        } else if (event.type === 'done') {
          es!.close()
          const warnings = Array.isArray(event.data.pipeline_warnings)
            ? (event.data.pipeline_warnings as string[])
            : undefined
          handlers.onDone(searchId, event.data.from_cache === true, warnings)
        } else if (event.type === 'log') {
          const msg = (event.data.message as string) ?? ''
          if (msg.startsWith(TOKEN_BUDGET_WARNING_PREFIX) && msg.includes('exceeds') && handlers.onWarning) {
            handlers.onWarning(msg)
          }
        }
      } catch {
        // ignore parse errors on malformed SSE frames
      }
    }

    es.onerror = () => {
      es!.close()
      es = null
      if (cancelled) return
      if (attempt >= MAX_RECONNECT_ATTEMPTS) {
        handlers.onError('Lost connection to API after several retries. Check the server is running.')
        return
      }
      const delay = Math.min(BASE_RECONNECT_DELAY_MS * Math.pow(2, attempt), 30_000)
      attempt++
      handlers.onReconnecting?.(attempt)
      reconnectTimer = setTimeout(() => connect(true), delay)
    }
  }

  connect(false)

  return () => {
    cancelled = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    es?.close()
    es = null
  }
}
