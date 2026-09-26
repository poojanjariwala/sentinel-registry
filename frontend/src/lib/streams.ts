import { useEffect, useRef, useState } from 'react'
import Hls from 'hls.js'
import { api } from './api'

export interface StreamRow {
  stream_id: string
  camera_id: string
  label: string
  camera_name: string
  camera_code: string
  district: string | null
  department: string
  department_id: string
  vms_system: string
  protocol: string
  is_live: boolean
  enabled: boolean
  status: string
  latency_ms: number | null
  analytics_enabled: boolean
  last_probe_at: string | null
}

export interface WatchInfo {
  session_id: string
  stream_id: string
  protocol: string
  hls_url: string
  label: string
}

export interface WallSummary {
  wall_id: string
  name: string
  tiles: { stream_id: string; slot: number }[]
}

export const watch = (streamId: string) =>
  api.post<{ data: WatchInfo }>(`/streams/${streamId}/watch`).then((r) => r.data)

export const heartbeat = (sessionId: string) =>
  api.post<{ data: { session_id: string } }>(`/streams/sessions/${sessionId}/heartbeat`).then((r) => r.data)

export const stopWatch = (sessionId: string) =>
  api.post<{ data: { session_id: string } }>(`/streams/sessions/${sessionId}/stop`).then((r) => r.data)

export const listWalls = () =>
  api.get<{ data: WallSummary[] }>('/streams/walls').then((r) => r.data)

export const createWall = (name: string, tiles: { stream_id: string; slot: number }[]) =>
  api.post<{ data: WallSummary }>('/streams/walls', { name, tiles }).then((r) => r.data)

export const deleteWall = (wallId: string) =>
  api.delete<{ data: { wall_id: string } }>(`/streams/walls/${wallId}`).then((r) => r.data)

export function stopOnUnload(sessionId: string | null) {
  if (!sessionId) return
  try {
    const t = localStorage.getItem('sentinel_token')
    // keepalive so the stop survives tab close
    fetch(`/api/v1/streams/sessions/${sessionId}/stop`, {
      method: 'POST',
      keepalive: true,
      headers: t ? { Authorization: `Bearer ${t}` } : {},
    }).catch(() => {})
  } catch {
    /* ignore */
  }
}

/**
 * Attach an HLS stream to a video element with bounded auto-reconnect and
 * session heartbeat. Stops the session on unmount.
 *
 * Reliability model (ADR-007 etiquette + flicker fix):
 * - exactly ONE watch session per tile; retries reuse the same session
 *   instead of creating a new one per attempt (no session leaks);
 * - 403 (invalid/expired viewer session or bad token) = operator action
 *   required, no auto-retry storm;
 * - 502 GRID_COOLDOWN (origin watch-time quota) = stop cleanly, no retry;
 * - 404 = segment rolled off the rolling window: player skips it quietly;
 * - other fatal network errors = bounded backoff, same session.
 */
export type StreamState = 'connecting' | 'live' | 'error' | 'cooldown' | 'idle'
const MAX_RETRY_ATTEMPTS = 6

// Segment-level failures are routine on a rolling window (segments roll off
// while we fetch); they must never trip the fatal path.
function isSegmentGap(details: string | undefined): boolean {
  return !!details && (details.includes('fragment') || details.includes('segment') || details.includes('gapTag'))
}

export function useHlsStream(streamId: string | null, enabled = true) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [state, setState] = useState<StreamState>('idle')
  const [session, setSession] = useState<WatchInfo | null>(null)
  const sessionRef = useRef<WatchInfo | null>(null)

  useEffect(() => {
    sessionRef.current = session
  }, [session])

  useEffect(() => {
    if (!streamId || !enabled) {
      setState('idle')
      return
    }
    let disposed = false
    let hls: Hls | null = null
    let hbTimer: number | null = null
    let retry: number | null = null
    let attempt = 0
    setState('connecting')

    const endSession = () => {
      const s = sessionRef.current
      if (s) {
        stopOnUnload(s.session_id)
        setSession(null)
      }
    }

    const cleanupHls = () => {
      if (hls) {
        hls.destroy()
        hls = null
      }
    }

    const begin = async () => {
      try {
        // One session per tile: reuse it across retries, stop it exactly once.
        let info = sessionRef.current
        if (!info) {
          info = await watch(streamId)
          if (disposed) {
            stopOnUnload(info.session_id)
            return
          }
          sessionRef.current = info
          setSession(info)
        }
        const video = videoRef.current
        if (!video) return

        const full = `/api/v1/streams/hls/${streamId}/${info.session_id}/index.m3u8`

        const attach = (url: string) => {
          if (Hls.isSupported()) {
            hls = new Hls({ lowLatencyMode: true, backBufferLength: 30 })
            hls.loadSource(url)
            hls.attachMedia(video)
            hls.on(Hls.Events.MANIFEST_PARSED, () => {
              attempt = 0
              setState('live')
              video.play().catch(() => {})
            })
            hls.on(Hls.Events.ERROR, (_e, data) => {
              if (!data.fatal) return
              console.warn('[hls] fatal', data.type, data.details, data.response?.code)
              cleanupHls()
              const status = data.response?.code
              if (isSegmentGap(data.details) && status === 404) {
                // rolling-window gap: reload the playlist, keep the session
                retry = window.setTimeout(() => {
                  if (!disposed) attach(url)
                }, 1500)
                return
              }
              if (status === 403) {
                // Viewer session/token rejected server-side: retrying cannot
                // help; the operator must start the feed again.
                setState('error')
                endSession()
                return
              }
              if (status === 502) {
                // Gateway refused upstream (grid watch-time quota/auth): the
                // origin is off-limits until cooldown passes - stop cleanly.
                setState('cooldown')
                endSession()
                return
              }
              setState('error')
              scheduleRetry()
            })
          } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = url
            video.addEventListener('loadedmetadata', () => {
              setState('live')
              video.play().catch(() => {})
            })
            video.addEventListener('error', () => {
              setState('error')
              scheduleRetry()
            })
          } else {
            setState('error')
          }
        }
        attach(full)
      } catch {
        // watch() failed (network/auth) - bounded retry with same session id
        setState('error')
        scheduleRetry()
      }
    }

    const scheduleRetry = () => {
      if (disposed) return
      attempt += 1
      if (attempt > MAX_RETRY_ATTEMPTS) {
        // Give up WITHOUT killing the session: the operator sees the tile in
        // the error state and can retry manually without leaking sessions.
        setState('error')
        return
      }
      const delay = Math.min(30000, 2000 * attempt)
      retry = window.setTimeout(() => {
        if (!disposed) begin()
      }, delay)
    }

    hbTimer = window.setInterval(() => {
      const s = sessionRef.current
      if (s) heartbeat(s.session_id).catch(() => {})
    }, 30000)

    begin()

    return () => {
      disposed = true
      if (retry) window.clearTimeout(retry)
      if (hbTimer) window.clearInterval(hbTimer)
      cleanupHls()
      const s = sessionRef.current
      if (s) stopOnUnload(s.session_id)
      sessionRef.current = null
      setSession(null)
      setState('idle')
    }
  }, [streamId, enabled])

  return { videoRef, state, session }
}
