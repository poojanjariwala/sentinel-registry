import { useEffect, useRef, useState } from 'react'
import {
  ScanLine,
  X,
  Upload,
  Play,
  Square,
  Sparkles,
  Layers,
  RefreshCw,
  Cpu,
  FileVideo,
  Image as ImageIcon,
} from 'lucide-react'
import {
  PlateDetection,
  analyzeFile,
  detectFrame,
  getCachedCrops,
  CachedPlate,
  clearAnprCache,
} from '../lib/anpr'
import { StreamRow, useHlsStream } from '../lib/streams'

interface AnprModalProps {
  isOpen: boolean
  onClose: () => void
  selectedStream?: StreamRow | null
  activeStreams: StreamRow[]
}

export default function AnprModal({
  isOpen,
  onClose,
  selectedStream,
  activeStreams,
}: AnprModalProps) {
  const [streamId, setStreamId] = useState<string>(selectedStream?.stream_id ?? '')
  const [confThreshold, setConfThreshold] = useState<number>(0.25)
  const [isAnprRunning, setIsAnprRunning] = useState<boolean>(false)
  const [detections, setDetections] = useState<PlateDetection[]>([])
  const [cachedCrops, setCachedCrops] = useState<CachedPlate[]>([])
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [filePreview, setFilePreview] = useState<string | null>(null)
  const [analyzingFile, setAnalyzingFile] = useState<boolean>(false)
  const [annotatedResultImg, setAnnotatedResultImg] = useState<string | null>(null)
  const [fps, setFps] = useState<number>(0)
  const [activeTab, setActiveTab] = useState<'stream' | 'upload'>('stream')

  const { videoRef, state: streamState } = useHlsStream(isOpen && activeTab === 'stream' && streamId ? streamId : null)
  const animFrameIdRef = useRef<number | null>(null)
  const lastCaptureTimeRef = useRef<number>(0)

  useEffect(() => {
    if (selectedStream) {
      setStreamId(selectedStream.stream_id)
    } else if (activeStreams.length > 0 && !streamId) {
      setStreamId(activeStreams[0].stream_id)
    }
  }, [selectedStream, activeStreams])

  // Load in-memory cached crops periodically or on change
  const refreshCache = async () => {
    try {
      const crops = await getCachedCrops(undefined, 25)
      setCachedCrops(crops)
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    if (isOpen) {
      refreshCache()
      const t = setInterval(refreshCache, 3000)
      return () => clearInterval(t)
    }
  }, [isOpen])

  // Process live stream frame loop when ANPR is toggled ON
  useEffect(() => {
    if (!isAnprRunning || activeTab !== 'stream') {
      if (animFrameIdRef.current) {
        cancelAnimationFrame(animFrameIdRef.current)
      }
      return
    }

    let isSubmitting = false
    let frameCounter = 0
    let lastFpsTime = performance.now()

    const loop = async () => {
      const now = performance.now()
      const vid = videoRef.current

      // Calculate FPS
      frameCounter++
      if (now - lastFpsTime >= 1000) {
        setFps(Math.round((frameCounter * 1000) / (now - lastFpsTime)))
        frameCounter = 0
        lastFpsTime = now
      }

      // Sample every 1200ms for YOLO + Tesseract OCR
      if (vid && vid.readyState >= 2 && !isSubmitting && now - lastCaptureTimeRef.current >= 1200) {
        lastCaptureTimeRef.current = now
        isSubmitting = true

        try {
          const offCanvas = document.createElement('canvas')
          offCanvas.width = vid.videoWidth || 640
          offCanvas.height = vid.videoHeight || 360
          const ctx = offCanvas.getContext('2d')
          if (ctx) {
            ctx.drawImage(vid, 0, 0, offCanvas.width, offCanvas.height)
            const b64 = offCanvas.toDataURL('image/jpeg', 0.8)

            const res = await detectFrame(b64, streamId, undefined, confThreshold)
            setDetections(res.detections)
            if (res.detections.length > 0) {
              refreshCache()
            }
          }
        } catch {
          /* ignore error and keep loop alive */
        } finally {
          isSubmitting = false
        }
      }

      animFrameIdRef.current = requestAnimationFrame(loop)
    }

    animFrameIdRef.current = requestAnimationFrame(loop)
    return () => {
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current)
    }
  }, [isAnprRunning, activeTab, streamId, confThreshold])

  // Handle file upload
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setSelectedFile(f)
    setAnnotatedResultImg(null)
    setDetections([])

    if (f.type.startsWith('image/')) {
      const reader = new FileReader()
      reader.onload = (ev) => setFilePreview(ev.target?.result as string)
      reader.readAsDataURL(f)
    } else {
      setFilePreview(URL.createObjectURL(f))
    }
  }

  const runFileAnalysis = async () => {
    if (!selectedFile) return
    setAnalyzingFile(true)
    try {
      const res = await analyzeFile(selectedFile, confThreshold)
      if (res.type === 'image' && res.annotated_image) {
        setAnnotatedResultImg(res.annotated_image)
        setDetections(res.detections || [])
      } else if (res.type === 'video' && res.detected_plates) {
        setDetections(res.detected_plates)
      }
      refreshCache()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setAnalyzingFile(false)
    }
  }

  const handleClearCache = async () => {
    await clearAnprCache()
    setCachedCrops([])
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm animate-fadeIn">
      <div className="flex h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-2xl">
        {/* Top Header */}
        <div className="flex items-center justify-between border-b border-line bg-canvas px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/20">
              <ScanLine className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-white">ANPR Intelligence Studio</h2>
                <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-2xs font-semibold text-emerald-300">
                  YOLO11n + pytesseract
                </span>
                <span className="rounded bg-white/10 px-2 py-0.5 text-2xs font-mono text-zinc-300">
                  In-Memory Cache
                </span>
              </div>
              <p className="text-xs text-ink-faint">
                Live number plate detection, OpenCV enhancement, cropped memory cache, and OCR extraction
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-ink-faint hover:bg-white/10 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Toolbar: Tabs & Controls */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line bg-surface px-6 py-3">
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setActiveTab('stream')
                setIsAnprRunning(false)
              }}
              className={`flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'stream'
                  ? 'bg-accent text-white shadow-sm'
                  : 'bg-canvas text-ink-muted hover:text-white'
              }`}
            >
              <Cpu className="h-3.5 w-3.5" /> Live Camera Stream
            </button>
            <button
              onClick={() => {
                setActiveTab('upload')
                setIsAnprRunning(false)
              }}
              className={`flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'upload'
                  ? 'bg-accent text-white shadow-sm'
                  : 'bg-canvas text-ink-muted hover:text-white'
              }`}
            >
              <Upload className="h-3.5 w-3.5" /> Upload Video / Image
            </button>
          </div>

          {/* ANPR Action Controls */}
          <div className="flex items-center gap-3">
            {activeTab === 'stream' && (
              <>
                <select
                  value={streamId}
                  onChange={(e) => {
                    setStreamId(e.target.value)
                    setDetections([])
                  }}
                  className="input-base max-w-xs text-xs"
                >
                  <option value="">Select Camera Stream...</option>
                  {activeStreams.map((s) => (
                    <option key={s.stream_id} value={s.stream_id}>
                      {s.label} ({s.protocol})
                    </option>
                  ))}
                </select>

                <div className="flex items-center gap-2 rounded-lg bg-canvas px-3 py-1.5 text-xs text-ink-muted">
                  <span>Conf:</span>
                  <input
                    type="range"
                    min="0.1"
                    max="0.8"
                    step="0.05"
                    value={confThreshold}
                    onChange={(e) => setConfThreshold(parseFloat(e.target.value))}
                    className="h-1.5 w-20 cursor-pointer accent-accent"
                  />
                  <span className="font-mono text-white">{Math.round(confThreshold * 100)}%</span>
                </div>

                {/* THE MAIN ON / OFF BUTTON */}
                <button
                  onClick={() => setIsAnprRunning(!isAnprRunning)}
                  className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-bold shadow-md transition-all ${
                    isAnprRunning
                      ? 'bg-red-600 text-white hover:bg-red-500 shadow-red-600/30'
                      : 'bg-emerald-600 text-white hover:bg-emerald-500 shadow-emerald-600/30'
                  }`}
                >
                  {isAnprRunning ? (
                    <>
                      <Square className="h-3.5 w-3.5 fill-current" />
                      <span>Stop ANPR Detection</span>
                    </>
                  ) : (
                    <>
                      <Play className="h-3.5 w-3.5 fill-current" />
                      <span>Start ANPR Detection</span>
                    </>
                  )}
                </button>
              </>
            )}

            {activeTab === 'upload' && (
              <div className="flex items-center gap-2">
                <input
                  type="file"
                  id="anpr-file-input"
                  accept="video/*,image/*"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <label
                  htmlFor="anpr-file-input"
                  className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-line bg-canvas px-3 py-1.5 text-xs text-white hover:bg-white/10"
                >
                  <Upload className="h-3.5 w-3.5 text-ink-faint" />
                  <span>{selectedFile ? selectedFile.name : 'Choose Video or Image'}</span>
                </label>
                <button
                  onClick={runFileAnalysis}
                  disabled={!selectedFile || analyzingFile}
                  className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-40"
                >
                  {analyzingFile ? (
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5" />
                  )}
                  <span>Run YOLO + OCR</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Main Content Area: Split View (Video Feed / Preview + In-Memory Crop Cache Panel) */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left: Video Player with Dynamic Visual Bounding Box HUD */}
          <div className="relative flex flex-1 flex-col items-center justify-center bg-black p-4">
            {activeTab === 'stream' ? (
              <div className="relative flex h-full w-full items-center justify-center">
                {/* Video Element */}
                <video
                  ref={videoRef}
                  autoPlay
                  muted
                  playsInline
                  crossOrigin="anonymous"
                  className="max-h-full max-w-full rounded-lg object-contain shadow-lg"
                />
                {streamState !== 'live' && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/70 text-xs text-white/80">
                    {streamState === 'connecting'
                      ? 'Connecting to HLS stream…'
                      : streamState === 'idle'
                      ? 'Select an active camera stream above'
                      : 'Stream offline'}
                  </div>
                )}

                {/* Overlaid HUD / Status Watermark */}
                <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 rounded-lg bg-black/70 px-3 py-1.5 text-xs text-white backdrop-blur-sm">
                  <div
                    className={`h-2.5 w-2.5 rounded-full ${
                      isAnprRunning ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-500'
                    }`}
                  />
                  <span className="font-semibold">
                    {isAnprRunning ? 'ANPR ACTIVE · YOLO11n' : 'ANPR OFF (IDLE)'}
                  </span>
                  {isAnprRunning && fps > 0 && (
                    <span className="text-2xs text-zinc-400">· {fps} FPS</span>
                  )}
                </div>

                {/* SVG Tactical Bounding Boxes Drawn Directly on the Live Feed */}
                {isAnprRunning && detections.length > 0 && videoRef.current && (
                  <svg
                    className="pointer-events-none absolute inset-0 h-full w-full"
                    viewBox={`0 0 ${videoRef.current.videoWidth || 640} ${
                      videoRef.current.videoHeight || 360
                    }`}
                    preserveAspectRatio="xMidYMid meet"
                  >
                    {detections.map((d) => {
                      const [x1, y1, x2, y2] = d.bbox
                      const w = x2 - x1
                      const h = y2 - y1
                      const corner = Math.min(16, w / 3)
                      const isHighConf = d.confidence >= 0.6
                      const strokeColor = isHighConf ? '#00e676' : '#ffb300'

                      return (
                        <g key={d.crop_id} className="animate-fadeIn">
                          {/* Main Box */}
                          <rect
                            x={x1}
                            y={y1}
                            width={w}
                            height={h}
                            fill={isHighConf ? 'rgba(0, 230, 118, 0.08)' : 'rgba(255, 179, 0, 0.08)'}
                            stroke={strokeColor}
                            strokeWidth="1.5"
                          />
                          {/* Corner Accents */}
                          <path
                            d={`M ${x1} ${y1 + corner} L ${x1} ${y1} L ${x1 + corner} ${y1}
                                M ${x2 - corner} ${y1} L ${x2} ${y1} L ${x2} ${y1 + corner}
                                M ${x1} ${y2 - corner} L ${x1} ${y2} L ${x1 + corner} ${y2}
                                M ${x2 - corner} ${y2} L ${x2} ${y2} L ${x2} ${y2 - corner}`}
                            fill="none"
                            stroke={strokeColor}
                            strokeWidth="3.5"
                            strokeLinecap="round"
                          />
                          {/* Floating Text Pill above plate */}
                          <rect
                            x={x1}
                            y={Math.max(4, y1 - 24)}
                            width={Math.max(w, 130)}
                            height="20"
                            rx="4"
                            fill="#0d1117"
                            stroke={strokeColor}
                            strokeWidth="1"
                          />
                          <text
                            x={x1 + 6}
                            y={Math.max(18, y1 - 10)}
                            fill="#ffffff"
                            fontSize="11"
                            fontWeight="bold"
                            fontFamily="monospace"
                          >
                            {d.plate_text} · {Math.round(d.confidence * 100)}%
                          </text>
                        </g>
                      )
                    })}
                  </svg>
                )}

                {/* Idle instruction when ANPR is off */}
                {!isAnprRunning && (
                  <div className="pointer-events-none absolute bottom-6 rounded-full bg-black/75 px-5 py-2 text-xs text-white/80 backdrop-blur-md">
                    Click <span className="font-bold text-emerald-400">Start ANPR Detection</span> to run the YOLO model & OCR
                  </div>
                )}
              </div>
            ) : (
              /* Upload Tab View */
              <div className="relative flex h-full w-full items-center justify-center">
                {annotatedResultImg ? (
                  <img
                    src={annotatedResultImg}
                    alt="ANPR Detection Result"
                    className="max-h-full max-w-full rounded-lg object-contain shadow-xl"
                  />
                ) : filePreview ? (
                  selectedFile?.type.startsWith('video/') ? (
                    <video
                      src={filePreview}
                      controls
                      autoPlay
                      className="max-h-full max-w-full rounded-lg object-contain shadow-xl"
                    />
                  ) : (
                    <img
                      src={filePreview}
                      alt="Uploaded File"
                      className="max-h-full max-w-full rounded-lg object-contain shadow-xl"
                    />
                  )
                ) : (
                  <div className="flex flex-col items-center justify-center text-center text-ink-muted">
                    <FileVideo className="mb-3 h-12 w-12 text-zinc-600" />
                    <p className="text-sm font-medium text-white">Upload Traffic Video or Image</p>
                    <p className="mt-1 max-w-sm text-xs text-ink-faint">
                      Upload any MP4/AVI traffic video or car photo to test the YOLO plate detector and Tesseract OCR pipeline.
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right Panel: In-Memory Cropped Plates Cache & OCR Results */}
          <aside className="flex w-96 flex-col border-l border-line bg-canvas">
            <div className="flex items-center justify-between border-b border-line bg-surface p-4">
              <div>
                <div className="flex items-center gap-2">
                  <Layers className="h-4 w-4 text-emerald-400" />
                  <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                    In-Memory Plate Cache
                  </h3>
                </div>
                <p className="text-2xs text-ink-faint">
                  Cropped plate ROIs held in RAM · No disk storage
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-2xs font-mono font-bold text-emerald-400">
                  {cachedCrops.length} cached
                </span>
                <button
                  onClick={handleClearCache}
                  title="Clear In-Memory Cache"
                  className="rounded p-1 text-ink-faint hover:bg-white/10 hover:text-white"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* List of Cached Crops */}
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {cachedCrops.length === 0 ? (
                <div className="flex h-48 flex-col items-center justify-center text-center text-ink-muted">
                  <ScanLine className="mb-2 h-8 w-8 text-zinc-600" />
                  <p className="text-xs font-medium text-white">No Plates Cached Yet</p>
                  <p className="mt-1 text-2xs text-ink-faint">
                    When plates are detected, cropped regions are cached here in RAM and OCR'd.
                  </p>
                </div>
              ) : (
                cachedCrops.map((crop) => (
                  <div
                    key={crop.crop_id}
                    className="flex gap-3 rounded-lg border border-line bg-surface p-3 transition-colors hover:border-emerald-500/40"
                  >
                    {/* Cropped Image Thumbnail from Cache */}
                    <div className="relative flex h-16 w-28 shrink-0 items-center justify-center overflow-hidden rounded border border-white/10 bg-black">
                      {crop.crop_base64 ? (
                        <img
                          src={crop.crop_base64}
                          alt={crop.plate_text}
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <ImageIcon className="h-6 w-6 text-zinc-600" />
                      )}
                      <span className="absolute bottom-0 right-0 rounded-tl bg-black/80 px-1 text-3xs font-mono text-zinc-400">
                        RAM
                      </span>
                    </div>

                    {/* Metadata & OCR Result */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between">
                        <span className="truncate font-mono text-sm font-bold tracking-wide text-white">
                          {crop.plate_text}
                        </span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-3xs font-bold ${
                            crop.confidence >= 0.6
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : 'bg-amber-500/20 text-amber-300'
                          }`}
                        >
                          {Math.round(crop.confidence * 100)}%
                        </span>
                      </div>

                      {crop.plate_raw && crop.plate_raw !== crop.plate_text && (
                        <div className="truncate text-3xs text-ink-faint font-mono">
                          Raw OCR: {crop.plate_raw}
                        </div>
                      )}

                      <div className="mt-1.5 flex items-center justify-between text-3xs text-zinc-400">
                        <span>YOLO Conf: {Math.round((crop.yolo_confidence || 0) * 100)}%</span>
                        <span>{new Date(crop.timestamp).toLocaleTimeString()}</span>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Bottom Status bar */}
            <div className="border-t border-line bg-surface p-3 text-2xs text-ink-faint">
              <div className="flex items-center justify-between">
                <span>Pipeline Engine</span>
                <span className="font-semibold text-white">YOLO11n + Tesseract</span>
              </div>
              <div className="mt-1 flex items-center justify-between">
                <span>Storage Policy</span>
                <span className="text-emerald-400">In-Memory Cache (0 disk I/O)</span>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}
