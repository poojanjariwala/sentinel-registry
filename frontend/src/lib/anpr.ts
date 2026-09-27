import { api } from './api'

export interface PlateDetection {
  crop_id: string
  bbox: [number, number, number, number] // [x1, y1, x2, y2]
  plate_text: string
  plate_raw: string
  plate_normalized: string
  confidence: number
  yolo_confidence: number
  timestamp: string
  stream_id?: string | null
  camera_id?: string | null
  crop_base64: string
  video_timestamp_sec?: number
}

export interface CachedPlate {
  crop_id: string
  stream_id: string | null
  camera_id: string | null
  plate_text: string
  plate_raw: string
  confidence: number
  yolo_confidence: number
  timestamp: string
  bbox: [number, number, number, number]
  crop_base64: string
}

export interface AnprStatus {
  global_enabled: boolean
  stream_active: boolean
  active_stream_count: number
  active_streams: string[]
  cached_plates_count: number
  model: string
  ocr_engine: string
}

export async function getAnprStatus(streamId?: string): Promise<AnprStatus> {
  const qs = streamId ? `?stream_id=${encodeURIComponent(streamId)}` : ''
  const r = await api.get<{ data: AnprStatus }>(`/anpr/status${qs}`)
  return r.data
}

export async function toggleAnpr(enabled: boolean, streamId?: string | null): Promise<boolean> {
  const r = await api.post<{ data: { enabled: boolean } }>('/anpr/toggle', {
    stream_id: streamId ?? null,
    enabled,
  })
  return r.data.enabled
}

export async function detectFrame(
  imageBase64: string,
  streamId?: string | null,
  cameraId?: string | null,
  confThreshold: number = 0.25,
): Promise<{ anpr_active: boolean; plate_count: number; detections: PlateDetection[]; alerts_fired: number }> {
  const r = await api.post<{
    data: { anpr_active: boolean; plate_count: number; detections: PlateDetection[]; alerts_fired: number }
  }>('/anpr/detect-frame', {
    image_base64: imageBase64,
    stream_id: streamId,
    camera_id: cameraId,
    conf_threshold: confThreshold,
    persist_observation: true,
  })
  return r.data
}

export async function getCachedCrops(streamId?: string, limit: number = 30): Promise<CachedPlate[]> {
  const params = new URLSearchParams()
  if (streamId) params.set('stream_id', streamId)
  params.set('limit', String(limit))
  const r = await api.get<{ data: CachedPlate[] }>(`/anpr/cache?${params}`)
  return r.data
}

export async function clearAnprCache(): Promise<void> {
  await api.post('/anpr/cache/clear')
}

export async function analyzeFile(
  file: File,
  confThreshold: number = 0.25,
): Promise<{
  type: 'image' | 'video'
  filename: string
  plate_count?: number
  detections?: PlateDetection[]
  annotated_image?: string
  total_frames_analyzed?: number
  detected_plates?: PlateDetection[]
  total_unique_plates?: number
}> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('conf_threshold', String(confThreshold))
  const r = await api.upload<{
    data: {
      type: 'image' | 'video'
      filename: string
      plate_count?: number
      detections?: PlateDetection[]
      annotated_image?: string
      total_frames_analyzed?: number
      detected_plates?: PlateDetection[]
      total_unique_plates?: number
    }
  }>('/anpr/analyze-file', fd)
  return r.data
}
