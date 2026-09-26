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

export const watch = (streamId: string) =>
  api.post<{ data: WatchInfo }>(`/streams/${streamId}/watch`).then((r) => r.data)

export const heartbeat = (sessionId: string) =>
  api.post<{ data: { session_id: string } }>(`/streams/sessions/${sessionId}/heartbeat`).then((r) => r.data)

export const stopWatch = (sessionId: string) =>
  api.post<{ data: { session_id: string } }>(`/streams/sessions/${sessionId}/stop`).then((r) => r.data)

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
 * Grid etiquette (ADR-007): the origin enforces a per-account watch-time
 * quota, so retries are capped and gateway refusals (quota/auth) surface as
 * a distinct 'cooldown' state instead of an infinite retry storm.
 */
export type StreamState = 'connecting' | 'live' | 'error' | 'cooldown' | 'idle'
const MAX_RETRY_ATTEMPTS = 6

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
        const info = await watch(streamId)
        if (disposed) {
          stopOnUnload(info.session_id)
          return
        }
        setSession(info)
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
              console.warn('[hls] fatal', data.type, data.details)
              cleanupHls()
              const status = data.response?.code
              if (status === 502 || status === 403) {
                // Gateway refused the upstream (grid quota/auth): retrying
                // cannot help until the cooldown passes - stop cleanly.
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
        setState('error')
        scheduleRetry()
      }
    }

    const scheduleRetry = () => {
      if (disposed) return
      attempt += 1
      if (attempt > MAX_RETRY_ATTEMPTS) {
        // Give up - keeps the origin (and the watch-time quota) unharmed.
        endSession()
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
      setSession(null)
      setState('idle')
    }
  }, [streamId, enabled])

  return { videoRef, state, session }
}
