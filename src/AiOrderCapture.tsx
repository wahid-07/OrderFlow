import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Camera,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  ClipboardCheck,
  LoaderCircle,
  MessageSquareText,
  Mic,
  Sparkles,
  Square,
  Upload,
  Volume2,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import './AiOrderCapture.css'
import { useAuth } from './context/useAuth'
import { ApiError, apiFetch } from './lib/api'
import { reportNetworkFailure } from './networkStatus'

type Unit = 'case' | 'piece' | 'unknown'

type CaptureCandidate = {
  sku: string
  name: string
  pack_label: string
  order_unit: string
  confidence: number
}

type CaptureLine = {
  line_id: string
  original_text: string
  quantity: string | null
  unit: Unit
  matched_sku: string | null
  matched_name: string | null
  confidence: number
  candidates: CaptureCandidate[]
  needs_clarification: boolean
  clarification_question: string | null
  clarification_options: Array<'piece' | 'case'>
  matched_via?: 'retailer_alias' | 'global_alias' | 'ai_match' | 'demo_parser' | 'none'
}

type CaptureResponse = {
  capture_id: string
  source: 'gemini' | 'demo_parser' | 'sku_alias'
  review_required: true
  order_placed: false
  lines: CaptureLine[]
}

type CatalogueProduct = {
  sku: string
  name: string
  pack_label: string
}

type Props = {
  onBackToCatalogue: () => void
  onAddToCart: (items: Array<{ sku: string; quantity: number }>) => void
}

const sampleOrder =
  'bhaiya 5 peti biscuit chhota, 2 peti washing powder 1 kilo, chai patti 250 wala 1 peti'

function formatTimer(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function AiOrderCapture({ onBackToCatalogue, onAddToCart }: Props) {
  const { profile } = useAuth()
  const isOrderDesk =
    profile?.role === 'order_desk' ||
    profile?.role === 'distributor_admin' ||
    profile?.role === 'super_admin'

  const [activeTab, setActiveTab] = useState<'text' | 'photo' | 'voice'>('text')
  const [rawText, setRawText] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)

  // Voice recording state
  const [isRecording, setIsRecording] = useState(false)
  const [recordingSeconds, setRecordingSeconds] = useState(0)
  const [audioFile, setAudioFile] = useState<File | Blob | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioFileName, setAudioFileName] = useState<string>('')
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const recordingTimerRef = useRef<number | null>(null)
  const audioInputRef = useRef<HTMLInputElement>(null)

  const [capture, setCapture] = useState<CaptureResponse | null>(null)
  const [selectedSku, setSelectedSku] = useState<Record<string, string>>({})
  const [selectedUnit, setSelectedUnit] = useState<Record<string, Unit>>({})
  const [quantityOverrides, setQuantityOverrides] = useState<Record<string, string>>({})
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Phase 3D: Catalogue picker & Alias learning state
  const [catalogueProducts, setCatalogueProducts] = useState<CatalogueProduct[]>([])
  const [showCataloguePicker, setShowCataloguePicker] = useState<Record<string, boolean>>({})
  const [aliasText, setAliasText] = useState<Record<string, string>>({})
  const [aliasIsGlobal, setAliasIsGlobal] = useState<Record<string, boolean>>({})
  const [aliasStatus, setAliasStatus] = useState<
    Record<string, 'idle' | 'saving' | 'saved' | 'duplicate' | 'conflict' | 'error'>
  >({})
  const [aliasFeedback, setAliasFeedback] = useState<Record<string, string>>({})

  useEffect(() => {
    // Pre-fetch active catalogue products for manual selection
    apiFetch<{ items?: CatalogueProduct[] }>('/catalogue')
      .then((data) => {
        if (data.items) {
          setCatalogueProducts(data.items)
        }
      })
      .catch(() => {
        // Fallback silently if offline or unauthenticated
      })
  }, [])

  function handleFileSelected(file: File) {
    setError('')
    const allowedTypes = ['image/jpeg', 'image/png', 'image/webp']
    if (!allowedTypes.includes(file.type)) {
      setError('Unsupported format. Please upload a JPEG, PNG, or WebP image.')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      setError('Image file size exceeds the 10 MB limit.')
      return
    }
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
    }
    setSelectedFile(file)
    setPreviewUrl(URL.createObjectURL(file))
  }

  function clearSelectedFile() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
    }
    setSelectedFile(null)
    setPreviewUrl(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (cameraInputRef.current) cameraInputRef.current.value = ''
  }

  async function startRecording() {
    setError('')
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError('Microphone access is not supported in this browser.')
        return
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')
        ? 'audio/ogg;codecs=opus'
        : 'audio/webm'

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder
      audioChunksRef.current = []

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      recorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType })
        if (audioUrl) {
          URL.revokeObjectURL(audioUrl)
        }
        setAudioFile(audioBlob)
        setAudioUrl(URL.createObjectURL(audioBlob))
        const timestamp = new Date().toISOString().slice(11, 19).replace(/:/g, '')
        setAudioFileName(`voice_order_${timestamp}.webm`)
        stream.getTracks().forEach((track) => track.stop())
      }

      recorder.start(250)
      setIsRecording(true)
      setRecordingSeconds(0)

      recordingTimerRef.current = window.setInterval(() => {
        setRecordingSeconds((prev) => prev + 1)
      }, 1000)
    } catch (micErr) {
      setError(
        micErr instanceof Error
          ? `Microphone error: ${micErr.message}`
          : 'Could not access microphone. Please check browser permissions.',
      )
    }
  }

  function stopRecording() {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current)
        recordingTimerRef.current = null
      }
    }
  }

  function handleAudioFileSelected(file: File) {
    setError('')
    if (file.size > 25 * 1024 * 1024) {
      setError('Audio file size exceeds the 25 MB limit.')
      return
    }
    const allowedExts = ['.ogg', '.mp3', '.m4a', '.wav', '.webm', '.aac']
    const hasValidExt = allowedExts.some((ext) => file.name.toLowerCase().endsWith(ext))
    if (!file.type.startsWith('audio/') && !hasValidExt) {
      setError('Unsupported format. Please upload OGG, MP3, M4A, WAV, or WebM audio.')
      return
    }

    if (audioUrl) {
      URL.revokeObjectURL(audioUrl)
    }
    setAudioFile(file)
    setAudioUrl(URL.createObjectURL(file))
    setAudioFileName(file.name)
  }

  function clearSelectedAudio() {
    if (isRecording) {
      stopRecording()
    }
    if (audioUrl) {
      URL.revokeObjectURL(audioUrl)
    }
    setAudioFile(null)
    setAudioUrl(null)
    setAudioFileName('')
    setRecordingSeconds(0)
    if (audioInputRef.current) audioInputRef.current.value = ''
  }

  function resetCaptureState() {
    setCapture(null)
    setConfirmed({})
    setAliasStatus({})
    setAliasFeedback({})
    setAliasText({})
    setShowCataloguePicker({})
  }

  async function parseOrder() {
    if (!rawText.trim()) return

    setLoading(true)
    setError('')
    resetCaptureState()

    try {
      const result = await apiFetch<CaptureResponse>('/ai/order-captures', {
        method: 'POST',
        body: JSON.stringify({ raw_text: rawText }),
      })
      setCapture(result)
      setSelectedSku(
        Object.fromEntries(
          result.lines
            .filter((line) => line.matched_sku)
            .map((line) => [line.line_id, line.matched_sku as string]),
        ),
      )
      setSelectedUnit(
        Object.fromEntries(
          result.lines
            .filter((line) => line.unit !== 'unknown')
            .map((line) => [line.line_id, line.unit]),
        ),
      )
      setQuantityOverrides({})
    } catch (parseError) {
      reportNetworkFailure(parseError)
      setError(
        parseError instanceof Error ? parseError.message : 'Could not parse this order.',
      )
    } finally {
      setLoading(false)
    }
  }

  async function parseImageOrder() {
    if (!selectedFile) return

    setLoading(true)
    setError('')
    resetCaptureState()

    try {
      const formData = new FormData()
      formData.append('file', selectedFile)

      const result = await apiFetch<CaptureResponse>('/ai/order-captures/image', {
        method: 'POST',
        body: formData,
      })
      setCapture(result)
      setSelectedSku(
        Object.fromEntries(
          result.lines
            .filter((line) => line.matched_sku)
            .map((line) => [line.line_id, line.matched_sku as string]),
        ),
      )
      setSelectedUnit(
        Object.fromEntries(
          result.lines
            .filter((line) => line.unit !== 'unknown')
            .map((line) => [line.line_id, line.unit]),
        ),
      )
      setQuantityOverrides({})
    } catch (parseError) {
      reportNetworkFailure(parseError)
      setError(
        parseError instanceof Error
          ? parseError.message
          : 'Could not parse this handwritten note.',
      )
    } finally {
      setLoading(false)
    }
  }

  async function parseAudioOrder() {
    if (!audioFile) return

    setLoading(true)
    setError('')
    resetCaptureState()

    try {
      const formData = new FormData()
      const fileName =
        audioFileName ||
        (audioFile instanceof File ? audioFile.name : 'voice_order.webm')
      formData.append('file', audioFile, fileName)

      const result = await apiFetch<CaptureResponse>('/ai/order-captures/audio', {
        method: 'POST',
        body: formData,
      })
      setCapture(result)
      setSelectedSku(
        Object.fromEntries(
          result.lines
            .filter((line) => line.matched_sku)
            .map((line) => [line.line_id, line.matched_sku as string]),
        ),
      )
      setSelectedUnit(
        Object.fromEntries(
          result.lines
            .filter((line) => line.unit !== 'unknown')
            .map((line) => [line.line_id, line.unit]),
        ),
      )
      setQuantityOverrides({})
    } catch (parseError) {
      reportNetworkFailure(parseError)
      setError(
        parseError instanceof Error
          ? parseError.message
          : 'Could not transcribe this voice order.',
      )
    } finally {
      setLoading(false)
    }
  }

  function updateSku(lineId: string, sku: string) {
    setSelectedSku((current) => ({ ...current, [lineId]: sku }))
    setConfirmed((current) => ({ ...current, [lineId]: false }))
    // Reset alias status for this line when SKU is changed
    setAliasStatus((current) => ({ ...current, [lineId]: 'idle' }))
    setAliasFeedback((current) => ({ ...current, [lineId]: '' }))
  }

  function updateUnit(lineId: string, unit: Unit) {
    setSelectedUnit((current) => ({ ...current, [lineId]: unit }))
    setConfirmed((current) => ({ ...current, [lineId]: false }))
  }

  // Phase 3D: Save Alias with User Consent
  async function saveAlias(lineId: string, canonicalSku: string, rawText: string) {
    const phrase = (aliasText[lineId] ?? rawText).trim()
    if (!phrase) return

    setAliasStatus((prev) => ({ ...prev, [lineId]: 'saving' }))
    setAliasFeedback((prev) => ({ ...prev, [lineId]: '' }))

    try {
      const isGlobal = isOrderDesk ? Boolean(aliasIsGlobal[lineId]) : false
      const res = await apiFetch<{
        id: string
        alias: string
        canonical_sku: string
        is_global: boolean
      }>('/ai/aliases', {
        method: 'POST',
        body: JSON.stringify({
          alias: phrase,
          canonical_sku: canonicalSku,
          is_global: isGlobal,
        }),
      })

      setAliasStatus((prev) => ({ ...prev, [lineId]: 'saved' }))
      setAliasFeedback((prev) => ({
        ...prev,
        [lineId]: `Remembered! "${phrase}" will automatically match ${canonicalSku} in future orders${
          res.is_global ? ' (distributor-wide)' : ''
        }.`,
      }))
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setAliasStatus((prev) => ({ ...prev, [lineId]: 'conflict' }))
        setAliasFeedback((prev) => ({ ...prev, [lineId]: err.detail }))
      } else {
        const message = err instanceof Error ? err.message : 'Failed to save alias'
        setAliasStatus((prev) => ({ ...prev, [lineId]: 'error' }))
        setAliasFeedback((prev) => ({ ...prev, [lineId]: message }))
      }
    }
  }

  function addConfirmedLines() {
    if (!capture) return
    const items = capture.lines.map((line) => ({
      sku: selectedSku[line.line_id],
      quantity: Number(quantityOverrides[line.line_id] ?? line.quantity),
    }))
    onAddToCart(items)
  }

  const lineReadiness =
    capture?.lines.map((line) => {
      const quantity = Number(quantityOverrides[line.line_id] ?? line.quantity)
      const unit = selectedUnit[line.line_id] ?? line.unit
      const ready = Boolean(selectedSku[line.line_id]) && quantity > 0 && unit !== 'unknown'
      const caseQuantity = unit === 'case' && Number.isInteger(quantity)
      return {
        line,
        quantity,
        unit,
        ready,
        caseQuantity,
        isConfirmed: confirmed[line.line_id] === true && ready,
      }
    }) ?? []
  const allConfirmed = lineReadiness.length > 0 && lineReadiness.every((line) => line.isConfirmed)
  const allCases = lineReadiness.every((line) => line.unit === 'case' && line.caseQuantity)
  const canAddToCart = allConfirmed && allCases
  const confirmedCount = lineReadiness.filter((line) => line.isConfirmed).length

  if (!capture) {
    return (
      <section className="ai-capture-page">
        <div className="ai-breadcrumb">
          <button type="button" className="ai-breadcrumb-link" onClick={onBackToCatalogue}>
            Catalogue
          </button>
          <span>/</span>
          <b>AI order capture</b>
        </div>
        <div className="ai-page-heading">
          <div>
            <p className="ai-overline">ORDER INTAKE</p>
            <h1>Capture an order</h1>
            <p>
              Paste text, photograph a handwritten note, or speak a voice order. Every line stays editable for review.
            </p>
          </div>
          <div className="ai-heading-icon">
            {activeTab === 'voice' ? (
              <Mic size={23} aria-hidden="true" />
            ) : activeTab === 'photo' ? (
              <Camera size={23} aria-hidden="true" />
            ) : (
              <MessageSquareText size={23} aria-hidden="true" />
            )}
          </div>
        </div>

        <div className="capture-mode-tabs" role="tablist" aria-label="Input method">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'text'}
            className={`capture-mode-tab ${activeTab === 'text' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('text')
              setError('')
            }}
          >
            <MessageSquareText size={16} aria-hidden="true" />
            <span>Text message</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'photo'}
            className={`capture-mode-tab ${activeTab === 'photo' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('photo')
              setError('')
            }}
          >
            <Camera size={16} aria-hidden="true" />
            <span>Handwritten photo</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'voice'}
            className={`capture-mode-tab ${activeTab === 'voice' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('voice')
              setError('')
            }}
          >
            <Mic size={16} aria-hidden="true" />
            <span>Voice note</span>
          </button>
        </div>

        {activeTab === 'text' ? (
          <div className="capture-compose">
            <div className="capture-compose-header">
              <div>
                <span className="compose-step">01</span>
                <h2>Order message</h2>
              </div>
              <button
                className="sample-order-button"
                type="button"
                onClick={() => setRawText(sampleOrder)}
              >
                Load sample order
              </button>
            </div>
            <label className="sr-only" htmlFor="order-message">
              Paste the retailer's order message
            </label>
            <textarea
              id="order-message"
              value={rawText}
              onChange={(event) => setRawText(event.target.value)}
              placeholder="Paste a WhatsApp order message…"
              maxLength={4000}
            />
            <div className="compose-footer">
              <span>{rawText.length} / 4,000</span>
              <button
                className="parse-order-button"
                type="button"
                disabled={!rawText.trim() || loading}
                onClick={parseOrder}
              >
                {loading ? (
                  <LoaderCircle size={16} className="spin" aria-hidden="true" />
                ) : (
                  <Sparkles size={16} aria-hidden="true" />
                )}
                {loading ? 'Parsing order' : 'Parse order'}
                {!loading && <ArrowRight size={15} aria-hidden="true" />}
              </button>
            </div>
          </div>
        ) : activeTab === 'photo' ? (
          <div className="capture-compose">
            <div className="capture-compose-header">
              <div>
                <span className="compose-step">01</span>
                <h2>Handwritten order note</h2>
              </div>
              {selectedFile && (
                <button
                  className="sample-order-button"
                  type="button"
                  onClick={clearSelectedFile}
                >
                  <X size={14} aria-hidden="true" /> Change photo
                </button>
              )}
            </div>

            <input
              type="file"
              ref={fileInputRef}
              accept="image/jpeg,image/png,image/webp"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleFileSelected(file)
              }}
            />
            <input
              type="file"
              ref={cameraInputRef}
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleFileSelected(file)
              }}
            />

            {!selectedFile ? (
              <div
                className={`photo-dropzone ${isDragging ? 'dragging' : ''}`}
                onDragOver={(e) => {
                  e.preventDefault()
                  setIsDragging(true)
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setIsDragging(false)
                  const file = e.dataTransfer.files?.[0]
                  if (file) handleFileSelected(file)
                }}
              >
                <div className="dropzone-icon-wrap">
                  <Camera size={28} aria-hidden="true" />
                  <Upload size={22} aria-hidden="true" />
                </div>
                <h3>Photograph or upload handwritten note</h3>
                <p>
                  Supports Hindi, Hinglish & English handwriting · JPEG, PNG or WebP up to 10 MB
                </p>

                <div className="photo-dropzone-actions">
                  <button
                    type="button"
                    className="photo-action-btn primary"
                    onClick={() => cameraInputRef.current?.click()}
                  >
                    <Camera size={16} aria-hidden="true" />
                    <span>Take photo</span>
                  </button>
                  <button
                    type="button"
                    className="photo-action-btn secondary"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Upload size={16} aria-hidden="true" />
                    <span>Choose file</span>
                  </button>
                </div>
              </div>
            ) : (
              <div className="photo-preview-card">
                {previewUrl && (
                  <img
                    src={previewUrl}
                    alt="Handwritten order note preview"
                    className="photo-preview-img"
                  />
                )}
                <div className="photo-preview-details">
                  <span className="photo-preview-filename">{selectedFile.name}</span>
                  <span className="photo-preview-size">
                    {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB ·{' '}
                    {selectedFile.type || 'image'}
                  </span>
                </div>
              </div>
            )}

            <div className="compose-footer">
              <span>{selectedFile ? 'Ready to analyze' : 'No photo selected'}</span>
              <button
                className="parse-order-button"
                type="button"
                disabled={!selectedFile || loading}
                onClick={parseImageOrder}
              >
                {loading ? (
                  <LoaderCircle size={16} className="spin" aria-hidden="true" />
                ) : (
                  <Sparkles size={16} aria-hidden="true" />
                )}
                {loading ? 'Analyzing handwriting' : 'Parse handwritten note'}
                {!loading && <ArrowRight size={15} aria-hidden="true" />}
              </button>
            </div>
          </div>
        ) : (
          <div className="capture-compose">
            <div className="capture-compose-header">
              <div>
                <span className="compose-step">01</span>
                <h2>Voice order recording</h2>
              </div>
              {audioFile && (
                <button
                  className="sample-order-button"
                  type="button"
                  onClick={clearSelectedAudio}
                >
                  <X size={14} aria-hidden="true" /> Clear audio
                </button>
              )}
            </div>

            <input
              type="file"
              ref={audioInputRef}
              accept="audio/*,.ogg,.mp3,.m4a,.wav,.webm"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleAudioFileSelected(file)
              }}
            />

            {!audioFile ? (
              <div className="voice-record-panel">
                {isRecording ? (
                  <div className="recording-live-box">
                    <div className="recording-pulse-indicator" aria-hidden="true" />
                    <span className="recording-timer">{formatTimer(recordingSeconds)}</span>
                    <p className="recording-hint">Listening... Speak your order in Hindi or English</p>
                    <button
                      type="button"
                      className="recording-stop-btn"
                      onClick={stopRecording}
                    >
                      <Square size={16} aria-hidden="true" />
                      <span>Stop recording</span>
                    </button>
                  </div>
                ) : (
                  <div className="voice-idle-box">
                    <div className="voice-record-btn-wrap">
                      <button
                        type="button"
                        className="voice-record-trigger-btn"
                        onClick={startRecording}
                        aria-label="Start recording voice note"
                      >
                        <Mic size={32} aria-hidden="true" />
                      </button>
                      <span className="voice-btn-label">Tap microphone to speak order</span>
                    </div>
                    <p className="voice-instruction">
                      Supports Hindi, Hinglish and English voice orders (e.g. "भैया 5 पेटी बिस्कुट, 2 पेटी वाशिंग पाउडर")
                    </p>

                    <div className="voice-upload-divider">
                      <span>or upload voice note</span>
                    </div>

                    <button
                      type="button"
                      className="photo-action-btn secondary"
                      onClick={() => audioInputRef.current?.click()}
                    >
                      <Upload size={16} aria-hidden="true" />
                      <span>Upload audio file (OGG, MP3, M4A, WAV, WebM)</span>
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="audio-preview-card">
                <div className="audio-preview-header">
                  <div className="audio-icon-wrap">
                    <Volume2 size={24} aria-hidden="true" />
                  </div>
                  <div className="audio-details">
                    <span className="audio-title">{audioFileName || 'Recorded voice order'}</span>
                    <span className="audio-meta">
                      {audioFile instanceof File
                        ? `${(audioFile.size / (1024 * 1024)).toFixed(2)} MB · ${audioFile.type || 'audio'}`
                        : `Recorded message · ${formatTimer(recordingSeconds || 0)}`}
                    </span>
                  </div>
                </div>

                {audioUrl && (
                  <audio
                    controls
                    src={audioUrl}
                    className="audio-preview-player"
                    preload="metadata"
                  />
                )}
              </div>
            )}

            <div className="compose-footer">
              <span>{audioFile ? 'Ready to transcribe' : isRecording ? 'Recording audio…' : 'No audio recorded'}</span>
              <button
                className="parse-order-button"
                type="button"
                disabled={!audioFile || loading || isRecording}
                onClick={parseAudioOrder}
              >
                {loading ? (
                  <LoaderCircle size={16} className="spin" aria-hidden="true" />
                ) : (
                  <Sparkles size={16} aria-hidden="true" />
                )}
                {loading ? 'Transcribing voice' : 'Parse voice order'}
                {!loading && <ArrowRight size={15} aria-hidden="true" />}
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="capture-error" role="alert">
            <CircleAlert size={17} aria-hidden="true" />
            {error}
          </div>
        )}

        <div className="capture-safety-note">
          <span className="safety-mark">
            <ClipboardCheck size={17} aria-hidden="true" />
          </span>
          <div>
            <strong>Review before adding to cart</strong>
            <p>Unclear units will be asked about. Voice, photo, and text orders are always reviewed before anything is added to cart.</p>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="ai-capture-page">
      <div className="ai-breadcrumb">
        <button type="button" className="ai-breadcrumb-link" onClick={onBackToCatalogue}>
          Catalogue
        </button>
        <span>/</span>
        <span>AI order capture</span>
        <span>/</span>
        <b>Review matches</b>
      </div>
      <div className="ai-page-heading review-page-heading">
        <div>
          <p className="ai-overline">ORDER INTAKE · STEP 02</p>
          <h1>Review matched lines</h1>
          <p>Confirm each product and unit before anything enters your cart.</p>
        </div>
        <span
          className={
            capture.source === 'gemini'
              ? 'parser-source gemini-source'
              : 'parser-source'
          }
        >
          <span />
          {capture.source === 'gemini'
            ? activeTab === 'voice'
              ? 'Gemini Audio'
              : activeTab === 'photo'
              ? 'Gemini Vision'
              : 'Gemini'
            : capture.source === 'sku_alias'
            ? 'SKU Alias'
            : 'Demo parser'}
        </span>
      </div>

      <div className="review-required-banner" role="status">
        <span className="review-required-icon">
          <ClipboardCheck size={18} aria-hidden="true" />
        </span>
        <div>
          <strong>Review required before placing an order</strong>
          <p>No order has been created. Confirm every match and unit below.</p>
        </div>
        <span className="review-progress">
          {confirmedCount} / {capture.lines.length} confirmed
        </span>
      </div>

      {capture.source === 'demo_parser' && (
        <div className="demo-parser-note">
          Gemini is not configured. This preview uses a limited local parser; its confidence values are examples, not model scores.
        </div>
      )}

      <div className="capture-review-layout">
        <div className="capture-lines">
          {lineReadiness.map(
            ({ line, quantity, unit, ready, caseQuantity, isConfirmed }, index) => {
              const chosenSku = selectedSku[line.line_id]
              const initialSku = line.matched_sku
              const isCorrected = Boolean(chosenSku && chosenSku !== initialSku)

              return (
                <article
                  className={
                    isConfirmed
                      ? 'capture-line-card line-confirmed'
                      : 'capture-line-card'
                  }
                  key={line.line_id}
                >
                  <div className="capture-line-heading">
                    <span className="line-number">
                      LINE {String(index + 1).padStart(2, '0')}
                    </span>
                    {isConfirmed ? (
                      <span className="confirmed-state">
                        <BadgeCheck size={14} aria-hidden="true" /> Confirmed
                      </span>
                    ) : (
                      <span className="confidence-state">
                        {Math.round(line.confidence * 100)}% match
                      </span>
                    )}
                  </div>

                  <blockquote>{line.original_text}</blockquote>

                  {line.candidates.length > 0 ? (
                    <div
                      className="candidate-list"
                      role="group"
                      aria-label={`SKU candidates for line ${index + 1}`}
                    >
                      {line.candidates.map((candidate) => (
                        <button
                          className={
                            chosenSku === candidate.sku
                              ? 'candidate-option selected'
                              : 'candidate-option'
                          }
                          type="button"
                          key={candidate.sku}
                          aria-pressed={chosenSku === candidate.sku}
                          onClick={() => updateSku(line.line_id, candidate.sku)}
                        >
                          <span className="candidate-radio" />
                          <span className="candidate-copy">
                            <strong>{candidate.name}</strong>
                            <small>
                              {candidate.sku} · {candidate.pack_label}
                            </small>
                          </span>
                          <span className="candidate-score">
                            {Math.round(candidate.confidence * 100)}%
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="unmatched-notice">
                      <CircleAlert size={16} aria-hidden="true" />
                      No catalogue match. Select a product below or edit the line.
                    </div>
                  )}

                  {/* Manual Catalogue Product Selection Dropdown */}
                  {catalogueProducts.length > 0 && (
                    <div className="catalogue-picker-toggle-wrap">
                      <button
                        type="button"
                        className="catalogue-picker-toggle-btn"
                        onClick={() =>
                          setShowCataloguePicker((prev) => ({
                            ...prev,
                            [line.line_id]: !prev[line.line_id],
                          }))
                        }
                      >
                        {showCataloguePicker[line.line_id] ? (
                          <>
                            <ChevronUp size={14} aria-hidden="true" /> Close catalogue list
                          </>
                        ) : (
                          <>
                            <ChevronDown size={14} aria-hidden="true" /> Select different product from catalogue…
                          </>
                        )}
                      </button>

                      {showCataloguePicker[line.line_id] && (
                        <div className="catalogue-select-container">
                          <select
                            className="catalogue-dropdown-select"
                            value={chosenSku ?? ''}
                            onChange={(e) => {
                              if (e.target.value) {
                                updateSku(line.line_id, e.target.value)
                              }
                            }}
                          >
                            <option value="" disabled>
                              -- Choose from all active products --
                            </option>
                            {catalogueProducts.map((p) => (
                              <option key={p.sku} value={p.sku}>
                                {p.name} ({p.sku}) · {p.pack_label}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Phase 3D: Human Correction & Alias Learning Prompt */}
                  {isCorrected && (
                    <div
                      className="alias-learning-card"
                      role="region"
                      aria-label="Remember SKU correction"
                    >
                      <div className="alias-learning-header">
                        <Sparkles size={15} aria-hidden="true" />
                        <strong>Remember this correction for future orders?</strong>
                      </div>
                      <p className="alias-learning-help">
                        Save <em>"{line.original_text}"</em> as an alias for{' '}
                        <strong>{chosenSku}</strong> so future orders match automatically.
                      </p>

                      <div className="alias-learning-actions">
                        <div className="alias-phrase-field">
                          <label htmlFor={`alias-phrase-${line.line_id}`}>
                            Alias phrase:
                          </label>
                          <input
                            id={`alias-phrase-${line.line_id}`}
                            type="text"
                            value={aliasText[line.line_id] ?? line.original_text}
                            onChange={(e) =>
                              setAliasText((prev) => ({
                                ...prev,
                                [line.line_id]: e.target.value,
                              }))
                            }
                            placeholder="Phrase to remember…"
                          />
                        </div>

                        {isOrderDesk && (
                          <label className="alias-global-toggle">
                            <input
                              type="checkbox"
                              checked={aliasIsGlobal[line.line_id] ?? false}
                              onChange={(e) =>
                                setAliasIsGlobal((prev) => ({
                                  ...prev,
                                  [line.line_id]: e.target.checked,
                                }))
                              }
                            />
                            <span>Distributor-wide global alias</span>
                          </label>
                        )}

                        <button
                          type="button"
                          className={`save-alias-action-btn ${
                            aliasStatus[line.line_id] === 'saved' ? 'saved' : ''
                          }`}
                          disabled={
                            aliasStatus[line.line_id] === 'saving' ||
                            aliasStatus[line.line_id] === 'saved'
                          }
                          onClick={() =>
                            saveAlias(line.line_id, chosenSku, line.original_text)
                          }
                        >
                          {aliasStatus[line.line_id] === 'saving' ? (
                            <LoaderCircle size={14} className="spin" aria-hidden="true" />
                          ) : aliasStatus[line.line_id] === 'saved' ? (
                            <BadgeCheck size={14} aria-hidden="true" />
                          ) : (
                            <Sparkles size={14} aria-hidden="true" />
                          )}
                          <span>
                            {aliasStatus[line.line_id] === 'saving'
                              ? 'Saving…'
                              : aliasStatus[line.line_id] === 'saved'
                              ? 'Alias saved'
                              : 'Remember correction'}
                          </span>
                        </button>
                      </div>

                      {aliasFeedback[line.line_id] && (
                        <div
                          className={`alias-feedback-banner ${aliasStatus[line.line_id]}`}
                          role="status"
                        >
                          {aliasStatus[line.line_id] === 'saved' ? (
                            <BadgeCheck size={15} aria-hidden="true" />
                          ) : (
                            <CircleAlert size={15} aria-hidden="true" />
                          )}
                          <span>{aliasFeedback[line.line_id]}</span>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="capture-line-controls">
                    <label className="capture-quantity-label">
                      Quantity
                      <input
                        type="number"
                        min="0.001"
                        step="0.001"
                        value={
                          quantityOverrides[line.line_id] ?? line.quantity ?? ''
                        }
                        onChange={(event) => {
                          setQuantityOverrides((current) => ({
                            ...current,
                            [line.line_id]: event.target.value,
                          }))
                          setConfirmed((current) => ({
                            ...current,
                            [line.line_id]: false,
                          }))
                        }}
                      />
                    </label>
                    <div className="capture-unit-wrap">
                      <span>Order unit</span>
                      {line.unit === 'unknown' ? (
                        <div
                          className="unit-choices"
                          role="group"
                          aria-label={
                            line.clarification_question ?? 'Choose an order unit'
                          }
                        >
                          {line.clarification_options.map((option) => (
                            <button
                              type="button"
                              key={option}
                              aria-pressed={unit === option}
                              className={
                                unit === option
                                  ? 'unit-choice selected'
                                  : 'unit-choice'
                              }
                              onClick={() => updateUnit(line.line_id, option)}
                            >
                              {quantity || ''} {option === 'piece' ? 'pieces' : 'cases'}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <span className="known-unit">
                          {unit === 'case' ? 'Cases' : 'Pieces'}
                        </span>
                      )}
                    </div>
                  </div>

                  {line.clarification_question &&
                    line.unit === 'unknown' &&
                    unit === 'unknown' && (
                      <p className="unit-question">
                        <CircleAlert size={15} aria-hidden="true" />
                        {line.clarification_question}
                      </p>
                    )}

                  {unit === 'piece' && (
                    <p className="unit-limitation">
                      Piece-to-case conversion is not configured. This line cannot be added to the case-based cart yet.
                    </p>
                  )}
                  {unit === 'case' && quantity > 0 && !caseQuantity && (
                    <p className="unit-limitation">
                      Case quantities must be whole numbers in this preview.
                    </p>
                  )}

                  <div className="line-confirm-row">
                    <span>
                      {ready
                        ? `Selected: ${unit === 'case' ? 'cases' : 'pieces'}`
                        : 'Match, quantity, and unit are required'}
                    </span>
                    <button
                      className={
                        isConfirmed
                          ? 'confirm-line-button confirmed'
                          : 'confirm-line-button'
                      }
                      type="button"
                      disabled={!ready}
                      aria-pressed={isConfirmed}
                      onClick={() =>
                        setConfirmed((current) => ({
                          ...current,
                          [line.line_id]: !current[line.line_id],
                        }))
                      }
                    >
                      {isConfirmed ? (
                        <>
                          <BadgeCheck size={15} aria-hidden="true" /> Match confirmed
                        </>
                      ) : (
                        'Confirm match'
                      )}
                    </button>
                  </div>
                </article>
              )
            },
          )}
        </div>

        <aside className="capture-review-summary">
          <p className="ai-overline">HUMAN CHECK</p>
          <h2>Ready for cart?</h2>
          <div className="review-summary-count">
            <span>{confirmedCount}</span>
            <small>of {capture.lines.length} lines confirmed</small>
          </div>
          {!allCases && (
            <p className="summary-blocker">
              Every line must use cases before it can enter this cart.
            </p>
          )}
          <button
            className="add-confirmed-button"
            type="button"
            disabled={!canAddToCart}
            onClick={addConfirmedLines}
          >
            Add confirmed cases to cart <ArrowRight size={16} aria-hidden="true" />
          </button>
          <button
            className="edit-capture-button"
            type="button"
            onClick={() => setCapture(null)}
          >
            <ArrowLeft size={15} aria-hidden="true" /> Edit or re-record order
          </button>
          <p className="no-order-note">
            This only adds reviewed items to your cart. It does not place an order.
          </p>
        </aside>
      </div>
    </section>
  )
}

export default AiOrderCapture
