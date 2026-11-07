import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  CircleAlert,
  Clock3,
  FileCheck2,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import './OrderDesk.css'
import { useAuth } from './context/useAuth'
import { apiFetch, apiFetchBlob } from './lib/api'
import { reportNetworkFailure } from './networkStatus'

export type OrderStatus = 'pending_review' | 'credit_hold' | 'approved' | 'rejected'

export type OrderLine = {
  sku: string
  name: string
  order_unit: string
  requested_quantity: number
  paid_quantity: number
  free_quantity: number
  delivered_quantity: number
  unit_price: string
  subtotal: string
  discount: string
  free_value: string
  total: string
  scheme_label: string | null
}

export type DemoOrder = {
  source: 'demo_memory'
  id: string
  order_number: string
  retailer_name: string
  status: OrderStatus
  created_at: string
  updated_at: string
  subtotal: string
  discount_total: string
  free_quantity: number
  free_value: string
  total: string
  note: string | null
  lines: OrderLine[]
}

type OrderListResponse = {
  source: 'demo_memory'
  orders: DemoOrder[]
}

type Props = {
  onOpenOrder: (orderId: string) => void
}

const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

const statusNames: Record<OrderStatus, string> = {
  pending_review: 'Needs review',
  credit_hold: 'Credit hold',
  approved: 'Approved',
  rejected: 'Rejected',
}

const filters: Array<{ value: OrderStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All orders' },
  { value: 'pending_review', label: 'Needs review' },
  { value: 'credit_hold', label: 'Credit hold' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
]

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function OrderDesk({ onOpenOrder }: Props) {
  const { role } = useAuth()
  const isOrderDesk = role === 'order_desk'
  const [orders, setOrders] = useState<DemoOrder[]>([])
  const [activeFilter, setActiveFilter] = useState<OrderStatus | 'all'>('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    async function loadOrders() {
      setLoading(true)
      setError(false)
      try {
        const result = await apiFetch<OrderListResponse>('/orders', { signal: controller.signal })
        setOrders(result.orders)
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(true)
          reportNetworkFailure(loadError)
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    void loadOrders()
    return () => controller.abort()
  }, [reloadKey])

  const visibleOrders = orders.filter(
    (order) => activeFilter === 'all' || order.status === activeFilter,
  )
  const needsReview = orders.filter((order) => order.status === 'pending_review').length
  const onHold = orders.filter((order) => order.status === 'credit_hold').length

  return (
    <section className="orders-page">
      <div className="orders-breadcrumb">
        <span>{isOrderDesk ? 'Distributor' : 'Retailer'}</span>
        <span>/</span>
        <b>{isOrderDesk ? 'Order desk' : 'My orders'}</b>
      </div>
      <div className="orders-heading">
        <div>
          <p className="orders-overline">{isOrderDesk ? 'DISTRIBUTOR WORKSPACE' : 'RETAILER ORDERS'}</p>
          <h1>{isOrderDesk ? 'Order desk' : 'My orders'}</h1>
          <p>{isOrderDesk ? 'Review submitted orders before approval.' : 'Track your submitted orders and status.'}</p>
        </div>
        <button className="orders-refresh" type="button" onClick={() => setReloadKey((key) => key + 1)} aria-label="Refresh orders">
          <RefreshCw size={17} aria-hidden="true" />
        </button>
      </div>



      <div className="orders-summary-strip">
        <div><span className="summary-icon review-icon"><Clock3 size={16} aria-hidden="true" /></span><span>Needs review</span><strong>{needsReview}</strong></div>
        <div><span className="summary-icon hold-icon"><ShieldAlert size={16} aria-hidden="true" /></span><span>On hold</span><strong>{onHold}</strong></div>
        <div><span className="summary-icon all-icon"><FileCheck2 size={16} aria-hidden="true" /></span><span>Total orders</span><strong>{orders.length}</strong></div>
      </div>

      <div className="orders-toolbar">
        <div className="order-filters" role="group" aria-label="Filter orders by status">
          {filters.map((filter) => (
            <button
              key={filter.value}
              type="button"
              className={activeFilter === filter.value ? 'order-filter active' : 'order-filter'}
              aria-pressed={activeFilter === filter.value}
              onClick={() => setActiveFilter(filter.value)}
            >
              {filter.label}
              {filter.value === 'pending_review' && needsReview > 0 && <span>{needsReview}</span>}
              {filter.value === 'credit_hold' && onHold > 0 && <span>{onHold}</span>}
            </button>
          ))}
        </div>
        <span className="orders-count">{visibleOrders.length} shown</span>
      </div>

      {error && (
        <div className="orders-state" role="alert">
          <CircleAlert size={20} aria-hidden="true" />
          <h2>Order desk unavailable</h2>
          <p>The order service could not be reached.</p>
          <button type="button" onClick={() => setReloadKey((key) => key + 1)}>Retry</button>
        </div>
      )}

      {loading && !error && (
        <div className="orders-state" role="status">
          <LoaderCircle className="spin" size={21} aria-hidden="true" />
          <p>Loading orders</p>
        </div>
      )}

      {!loading && !error && visibleOrders.length === 0 && (
        <div className="orders-state">
          <div className="orders-empty-icon"><FileCheck2 size={21} aria-hidden="true" /></div>
          <h2>{orders.length === 0 ? 'No orders to review' : 'No orders in this view'}</h2>
          <p>{orders.length === 0 ? 'Orders submitted from the retailer cart will appear here.' : 'Choose another status filter.'}</p>
          {orders.length > 0 && <button type="button" onClick={() => setActiveFilter('all')}>Show all orders</button>}
        </div>
      )}

      {!loading && !error && visibleOrders.length > 0 && (
        <div className="orders-table" role="table" aria-label="Orders">
          <div className="orders-table-head" role="row">
            <span role="columnheader">Order</span>
            <span role="columnheader">Retailer</span>
            <span role="columnheader">Submitted</span>
            <span role="columnheader">Status</span>
            <span role="columnheader">Total</span>
            <span role="columnheader" className="orders-table-action-head"> </span>
          </div>
          {visibleOrders.map((order) => (
            <div className="orders-table-row" role="row" key={order.id}>
              <span className="order-number-cell" role="cell">{order.order_number}<small>{order.lines.length} lines</small></span>
              <span className="order-retailer-cell" role="cell">{order.retailer_name}</span>
              <span className="order-date-cell" role="cell">{formatDate(order.created_at)}</span>
              <span role="cell"><span className={`order-status status-${order.status}`}>{statusNames[order.status]}</span></span>
              <strong className="order-total-cell" role="cell">{currency.format(Number(order.total))}</strong>
              <span role="cell" className="order-open-cell">
                <button type="button" onClick={() => onOpenOrder(order.id)} aria-label={`Review ${order.order_number}`}>
                  Review <ArrowRight size={14} aria-hidden="true" />
                </button>
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

type DetailProps = {
  orderId: string
  onBack: () => void
}

export function OrderDetail({ orderId, onBack }: DetailProps) {
  const { role } = useAuth()
  const isOrderDesk = role === 'order_desk'
  const [order, setOrder] = useState<DemoOrder | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [downloadingCsv, setDownloadingCsv] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function loadOrder() {
      setLoading(true)
      setError('')
      try {
        const result = await apiFetch<DemoOrder>(`/orders/${orderId}`, { signal: controller.signal })
        setOrder(result)
      } catch (loadError) {
        if (!controller.signal.aborted) {
          reportNetworkFailure(loadError)
          setError(loadError instanceof Error ? loadError.message : 'This order could not be loaded.')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    void loadOrder()
    return () => controller.abort()
  }, [orderId])

  async function applyDecision(action: 'approve' | 'reject' | 'place_on_hold' | 'release_hold') {
    setSaving(true)
    setError('')
    try {
      const result = await apiFetch<DemoOrder>(`/orders/${orderId}/decision`, {
        method: 'PATCH',
        body: JSON.stringify({ action, note: note.trim() || null }),
      })
      setOrder(result)
      setNote('')
    } catch (decisionError) {
      reportNetworkFailure(decisionError)
      setError(decisionError instanceof Error ? decisionError.message : 'The order status could not be updated.')
    } finally {
      setSaving(false)
    }
  }

  async function handleDownloadCsv() {
    if (!order) return
    setDownloadingCsv(true)
    setError('')
    try {
      const blob = await apiFetchBlob(`/orders/${order.id}/tally.csv`)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${order.order_number}_tally.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (csvError) {
      setError(csvError instanceof Error ? csvError.message : 'Could not download Tally CSV.')
    } finally {
      setDownloadingCsv(false)
    }
  }

  if (loading) {
    return <div className="orders-state"><LoaderCircle className="spin" size={21} aria-hidden="true" /><p>Loading order</p></div>
  }
  if (error && !order) {
    return <div className="orders-state" role="alert"><CircleAlert size={20} aria-hidden="true" /><h2>Order unavailable</h2><p>{error}</p><button type="button" onClick={onBack}>Back</button></div>
  }
  if (!order) return null

  const canReview = isOrderDesk && (order.status === 'pending_review' || order.status === 'credit_hold')

  return (
    <section className="order-detail-page">
      <div className="orders-breadcrumb">
        <button type="button" onClick={onBack}>{isOrderDesk ? 'Order desk' : 'My orders'}</button>
        <span>/</span>
        <b>{order.order_number}</b>
      </div>
      <div className="order-detail-heading">
        <div>
          <p className="orders-overline">ORDER DETAIL</p>
          <h1>{order.order_number}</h1>
          <p>{order.retailer_name} · submitted {formatDate(order.created_at)}</p>
        </div>
        <span className={`order-status status-${order.status}`}>{statusNames[order.status]}</span>
      </div>

      {order.source === 'demo_memory' && (
        <div className="orders-preview-note"><span /> Demo record. It will be lost when the API restarts.</div>
      )}

      <div className="order-detail-layout">
        <div className="order-detail-lines">
          <div className="detail-lines-heading"><h2>Order lines</h2><span>{order.lines.length} items</span></div>
          {order.lines.map((line) => (
            <div className="detail-order-line" key={`${order.id}-${line.sku}`}>
              <div className="detail-product-copy">
                <strong>{line.name}</strong>
                <span>{line.sku} · {line.order_unit}</span>
              </div>
              <div className="detail-line-quantity"><strong>{line.paid_quantity}</strong><span>paid</span></div>
              <div className="detail-line-quantity"><strong>{line.free_quantity}</strong><span>free</span></div>
              <div className="detail-line-total"><strong>{currency.format(Number(line.total))}</strong><span>{line.scheme_label ?? 'No scheme'}</span></div>
            </div>
          ))}

          {order.note && <div className="order-desk-note"><strong>Desk note</strong><p>{order.note}</p></div>}
        </div>

        <aside className="order-review-panel">
          <p className="orders-overline">ORDER SUMMARY</p>
          <div className="detail-total-row"><span>Subtotal</span><strong>{currency.format(Number(order.subtotal))}</strong></div>
          {Number(order.discount_total) > 0 && (
            <div className="detail-total-row discount"><span>Scheme discount</span><strong>−{currency.format(Number(order.discount_total))}</strong></div>
          )}
          {order.free_quantity > 0 && (
            <div className="detail-total-row"><span>Free cases</span><strong>{order.free_quantity}</strong></div>
          )}
          <div className="detail-total-row grand"><span>Total before GST</span><strong>{currency.format(Number(order.total))}</strong></div>
          <p className="detail-gst-note">GST is not included in this demo quote.</p>

          {canReview && (
            <>
              <label className="desk-note-label" htmlFor="desk-note">Desk note <span>Optional</span></label>
              <textarea
                id="desk-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={500}
                placeholder="Add context for this decision"
              />
              {error && <p className="decision-error" role="alert">{error}</p>}
              <div className="decision-actions">
                {order.status === 'pending_review' ? (
                  <>
                    <button className="approve-order-button" type="button" disabled={saving} onClick={() => applyDecision('approve')}>
                      <BadgeCheck size={16} aria-hidden="true" /> Approve order
                    </button>
                    <button className="hold-order-button" type="button" disabled={saving} onClick={() => applyDecision('place_on_hold')}>
                      <ShieldAlert size={15} aria-hidden="true" /> Place on hold
                    </button>
                    <button className="reject-order-button" type="button" disabled={saving} onClick={() => applyDecision('reject')}>
                      Reject order
                    </button>
                  </>
                ) : (
                  <>
                    <div className="hold-explanation"><ShieldAlert size={16} aria-hidden="true" />Release the manual hold to return this order to review.</div>
                    <button className="approve-order-button" type="button" disabled={saving} onClick={() => applyDecision('release_hold')}>
                      Release hold <ArrowRight size={15} aria-hidden="true" />
                    </button>
                    <button className="reject-order-button" type="button" disabled={saving} onClick={() => applyDecision('reject')}>
                      Reject order
                    </button>
                  </>
                )}
              </div>
            </>
          )}

          {order.status === 'approved' && isOrderDesk && (
            <>
              <div className="approved-message"><BadgeCheck size={17} aria-hidden="true" /> Approved for export</div>
              <button
                type="button"
                className="tally-export-button"
                disabled={downloadingCsv}
                onClick={handleDownloadCsv}
              >
                <ArrowDownToLine size={16} aria-hidden="true" />
                {downloadingCsv ? 'Downloading…' : 'Download Tally CSV'}
              </button>
              <p className="detail-gst-note">Starter CSV columns; confirm the target Tally mapping before production use.</p>
            </>
          )}

          {order.status === 'approved' && !isOrderDesk && (
            <div className="approved-message"><BadgeCheck size={17} aria-hidden="true" /> Order approved by distributor</div>
          )}

          {order.status === 'rejected' && (
            <div className="rejected-message"><CircleAlert size={16} aria-hidden="true" /> This order was rejected.</div>
          )}
        </aside>
      </div>

      <button className="detail-back-button" type="button" onClick={onBack}>
        <ArrowLeft size={15} aria-hidden="true" /> Back to {isOrderDesk ? 'order desk' : 'my orders'}
      </button>
    </section>
  )
}

type ConfirmationProps = {
  order: DemoOrder
  onOpenOrder: () => void
  onOpenDesk: () => void
  onNewOrder: () => void
}

export function OrderConfirmation({ order, onOpenOrder, onOpenDesk, onNewOrder }: ConfirmationProps) {
  const { role } = useAuth()
  const isOrderDesk = role === 'order_desk'

  return (
    <section className="order-confirmation-page">
      <div className="orders-breadcrumb"><span>Retailer</span><span>/</span><b>Order submitted</b></div>
      <div className="confirmation-mark"><BadgeCheck size={28} aria-hidden="true" /></div>
      <p className="orders-overline">SUBMITTED FOR REVIEW</p>
      <h1>Order sent to the desk</h1>
      <p className="confirmation-copy">Your order has been received. It has not been approved or placed with the distributor yet.</p>

      <div className="confirmation-summary">
        <div><span>Order number</span><strong>{order.order_number}</strong></div>
        <div><span>Status</span><strong><span className={`order-status status-${order.status}`}>{statusNames[order.status]}</span></strong></div>
        <div><span>Lines</span><strong>{order.lines.length}</strong></div>
        <div><span>Total before GST</span><strong>{currency.format(Number(order.total))}</strong></div>
      </div>

      <div className="confirmation-actions">
        <button className="approve-order-button" type="button" onClick={onOpenOrder}>View order detail <ArrowRight size={15} aria-hidden="true" /></button>
        <button className="confirmation-secondary" type="button" onClick={onOpenDesk}>
          {isOrderDesk ? 'Open order desk' : 'View my orders'}
        </button>
        <button className="confirmation-secondary" type="button" onClick={onNewOrder}>Start another order</button>
      </div>
      <p className="confirmation-demo-note"><CircleAlert size={14} aria-hidden="true" /> Demo order is stored in memory and clears when the API restarts.</p>
    </section>
  )
}