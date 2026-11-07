import {
    ArrowLeft,
    ArrowRight,
    BadgeCheck,
    CircleAlert,
    ClipboardCheck,
    LoaderCircle,
    MessageSquareText,
    Sparkles,
} from 'lucide-react'
import { useState } from 'react'
import './AiOrderCapture.css'
import { apiFetch } from './lib/api'
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
}

type CaptureResponse = {
  capture_id: string
  source: 'gemini' | 'demo_parser'
  review_required: true
  order_placed: false
  lines: CaptureLine[]
}

type Props = {
  onBackToCatalogue: () => void
  onAddToCart: (items: Array<{ sku: string; quantity: number }>) => void
}

const sampleOrder =
  'bhaiya 5 peti biscuit chhota, 2 peti washing powder 1 kilo, chai patti 250 wala 1 peti'

function AiOrderCapture({ onBackToCatalogue, onAddToCart }: Props) {
  const [rawText, setRawText] = useState('')
  const [capture, setCapture] = useState<CaptureResponse | null>(null)
  const [selectedSku, setSelectedSku] = useState<Record<string, string>>({})
  const [selectedUnit, setSelectedUnit] = useState<Record<string, Unit>>({})
  const [quantityOverrides, setQuantityOverrides] = useState<Record<string, string>>({})
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function parseOrder() {
    if (!rawText.trim()) return

    setLoading(true)
    setError('')
    setCapture(null)
    setConfirmed({})

    try {
      const result = await apiFetch<CaptureResponse>('/ai/order-captures', {
        method: 'POST',
        body: JSON.stringify({ raw_text: rawText }),
      })
      setCapture(result)
      setSelectedSku(Object.fromEntries(
        result.lines
          .filter((line) => line.matched_sku)
          .map((line) => [line.line_id, line.matched_sku as string]),
      ))
      setSelectedUnit(Object.fromEntries(
        result.lines
          .filter((line) => line.unit !== 'unknown')
          .map((line) => [line.line_id, line.unit]),
      ))
      setQuantityOverrides({})
    } catch (parseError) {
      reportNetworkFailure(parseError)
      setError(parseError instanceof Error ? parseError.message : 'Could not parse this order.')
    } finally {
      setLoading(false)
    }
  }

  function updateSku(lineId: string, sku: string) {
    setSelectedSku((current) => ({ ...current, [lineId]: sku }))
    setConfirmed((current) => ({ ...current, [lineId]: false }))
  }

  function updateUnit(lineId: string, unit: Unit) {
    setSelectedUnit((current) => ({ ...current, [lineId]: unit }))
    setConfirmed((current) => ({ ...current, [lineId]: false }))
  }

  function addConfirmedLines() {
    if (!capture) return
    const items = capture.lines.map((line) => ({
      sku: selectedSku[line.line_id],
      quantity: Number(quantityOverrides[line.line_id] ?? line.quantity),
    }))
    onAddToCart(items)
  }

  const lineReadiness = capture?.lines.map((line) => {
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
          <button type="button" className="ai-breadcrumb-link" onClick={onBackToCatalogue}>Catalogue</button>
          <span>/</span>
          <b>AI order capture</b>
        </div>
        <div className="ai-page-heading">
          <div>
            <p className="ai-overline">ORDER INTAKE</p>
            <h1>Capture an order</h1>
            <p>Paste a message as received. Every match stays editable for review.</p>
          </div>
          <div className="ai-heading-icon"><MessageSquareText size={23} aria-hidden="true" /></div>
        </div>

        <div className="capture-compose">
          <div className="capture-compose-header">
            <div>
              <span className="compose-step">01</span>
              <h2>Order message</h2>
            </div>
            <button className="sample-order-button" type="button" onClick={() => setRawText(sampleOrder)}>
              Load sample order
            </button>
          </div>
          <label className="sr-only" htmlFor="order-message">Paste the retailer's order message</label>
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
              {loading ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : <Sparkles size={16} aria-hidden="true" />}
              {loading ? 'Parsing order' : 'Parse order'}
              {!loading && <ArrowRight size={15} aria-hidden="true" />}
            </button>
          </div>
        </div>

        {error && <div className="capture-error" role="alert"><CircleAlert size={17} aria-hidden="true" />{error}</div>}

        <div className="capture-safety-note">
          <span className="safety-mark"><ClipboardCheck size={17} aria-hidden="true" /></span>
          <div>
            <strong>Review before adding to cart</strong>
            <p>Unclear units will be asked about. Capturing a message never places an order.</p>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="ai-capture-page">
      <div className="ai-breadcrumb">
        <button type="button" className="ai-breadcrumb-link" onClick={onBackToCatalogue}>Catalogue</button>
        <span>/</span><span>AI order capture</span><span>/</span><b>Review matches</b>
      </div>
      <div className="ai-page-heading review-page-heading">
        <div>
          <p className="ai-overline">ORDER INTAKE · STEP 02</p>
          <h1>Review matched lines</h1>
          <p>Confirm each product and unit before anything enters your cart.</p>
        </div>
        <span className={capture.source === 'gemini' ? 'parser-source gemini-source' : 'parser-source'}>
          <span />{capture.source === 'gemini' ? 'Gemini' : 'Demo parser'}
        </span>
      </div>

      <div className="review-required-banner" role="status">
        <span className="review-required-icon"><ClipboardCheck size={18} aria-hidden="true" /></span>
        <div>
          <strong>Review required before placing an order</strong>
          <p>No order has been created. Confirm every match and unit below.</p>
        </div>
        <span className="review-progress">{confirmedCount} / {capture.lines.length} confirmed</span>
      </div>

      {capture.source === 'demo_parser' && (
        <div className="demo-parser-note">Gemini is not configured. This preview uses a limited local parser; its confidence values are examples, not model scores.</div>
      )}

      <div className="capture-review-layout">
        <div className="capture-lines">
          {lineReadiness.map(({ line, quantity, unit, ready, caseQuantity, isConfirmed }, index) => {
            const chosenSku = selectedSku[line.line_id]
            return (
              <article className={isConfirmed ? 'capture-line-card line-confirmed' : 'capture-line-card'} key={line.line_id}>
                <div className="capture-line-heading">
                  <span className="line-number">LINE {String(index + 1).padStart(2, '0')}</span>
                  {isConfirmed ? (
                    <span className="confirmed-state"><BadgeCheck size={14} aria-hidden="true" /> Confirmed</span>
                  ) : (
                    <span className="confidence-state">{Math.round(line.confidence * 100)}% match</span>
                  )}
                </div>

                <blockquote>{line.original_text}</blockquote>

                {line.candidates.length > 0 ? (
                  <div className="candidate-list" role="group" aria-label={`SKU candidates for line ${index + 1}`}>
                    {line.candidates.map((candidate) => (
                      <button
                        className={chosenSku === candidate.sku ? 'candidate-option selected' : 'candidate-option'}
                        type="button"
                        key={candidate.sku}
                        aria-pressed={chosenSku === candidate.sku}
                        onClick={() => updateSku(line.line_id, candidate.sku)}
                      >
                        <span className="candidate-radio" />
                        <span className="candidate-copy">
                          <strong>{candidate.name}</strong>
                          <small>{candidate.sku} · {candidate.pack_label}</small>
                        </span>
                        <span className="candidate-score">{Math.round(candidate.confidence * 100)}%</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="unmatched-notice"><CircleAlert size={16} aria-hidden="true" />No catalogue match. Edit the message or capture it again.</div>
                )}

                <div className="capture-line-controls">
                  <label className="capture-quantity-label">
                    Quantity
                    <input
                      type="number"
                      min="0.001"
                      step="0.001"
                      value={quantityOverrides[line.line_id] ?? line.quantity ?? ''}
                      onChange={(event) => {
                        setQuantityOverrides((current) => ({ ...current, [line.line_id]: event.target.value }))
                        setConfirmed((current) => ({ ...current, [line.line_id]: false }))
                      }}
                    />
                  </label>
                  <div className="capture-unit-wrap">
                    <span>Order unit</span>
                    {line.unit === 'unknown' ? (
                      <div className="unit-choices" role="group" aria-label={line.clarification_question ?? 'Choose an order unit'}>
                        {line.clarification_options.map((option) => (
                          <button
                            type="button"
                            key={option}
                            aria-pressed={unit === option}
                            className={unit === option ? 'unit-choice selected' : 'unit-choice'}
                            onClick={() => updateUnit(line.line_id, option)}
                          >
                            {quantity || ''} {option === 'piece' ? 'pieces' : 'cases'}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <span className="known-unit">{unit === 'case' ? 'Cases' : 'Pieces'}</span>
                    )}
                  </div>
                </div>

                {line.clarification_question && line.unit === 'unknown' && unit === 'unknown' && (
                  <p className="unit-question"><CircleAlert size={15} aria-hidden="true" />{line.clarification_question}</p>
                )}

                {unit === 'piece' && (
                  <p className="unit-limitation">Piece-to-case conversion is not configured. This line cannot be added to the case-based cart yet.</p>
                )}
                {unit === 'case' && quantity > 0 && !caseQuantity && (
                  <p className="unit-limitation">Case quantities must be whole numbers in this preview.</p>
                )}

                <div className="line-confirm-row">
                  <span>{ready ? `Selected: ${unit === 'case' ? 'cases' : 'pieces'}` : 'Match, quantity, and unit are required'}</span>
                  <button
                    className={isConfirmed ? 'confirm-line-button confirmed' : 'confirm-line-button'}
                    type="button"
                    disabled={!ready}
                    aria-pressed={isConfirmed}
                    onClick={() => setConfirmed((current) => ({ ...current, [line.line_id]: !current[line.line_id] }))}
                  >
                    {isConfirmed ? <><BadgeCheck size={15} aria-hidden="true" /> Match confirmed</> : 'Confirm match'}
                  </button>
                </div>
              </article>
            )
          })}
        </div>

        <aside className="capture-review-summary">
          <p className="ai-overline">HUMAN CHECK</p>
          <h2>Ready for cart?</h2>
          <div className="review-summary-count"><span>{confirmedCount}</span><small>of {capture.lines.length} lines confirmed</small></div>
          {!allCases && (
            <p className="summary-blocker">Every line must use cases before it can enter this cart.</p>
          )}
          <button
            className="add-confirmed-button"
            type="button"
            disabled={!canAddToCart}
            onClick={addConfirmedLines}
          >
            Add confirmed cases to cart <ArrowRight size={16} aria-hidden="true" />
          </button>
          <button className="edit-capture-button" type="button" onClick={() => setCapture(null)}>
            <ArrowLeft size={15} aria-hidden="true" /> Edit order text
          </button>
          <p className="no-order-note">This only adds reviewed items to your cart. It does not place an order.</p>
        </aside>
      </div>
    </section>
  )
}

export default AiOrderCapture