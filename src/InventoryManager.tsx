import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  CircleAlert,
  History,
  LoaderCircle,
  PackagePlus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { apiFetch } from './lib/api'
import { reportNetworkFailure } from './networkStatus'

export type InventoryItem = {
  sku: string
  name: string
  pack_label: string
  order_unit: string
  available_stock: number
  is_out_of_stock: boolean
  is_low_stock: boolean
  on_hand_stock?: number
  reserved_stock?: number
  low_stock_threshold?: number
  updated_at?: string
}

export type StockMovement = {
  id: string
  sku: string
  movement_type: string
  quantity: number
  on_hand_before: number
  on_hand_after: number
  reserved_before: number
  reserved_after: number
  reference_id: string | null
  reason: string | null
  created_at: string
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

const movementTypeLabels: Record<string, string> = {
  receive: 'Stock Received',
  adjustment: 'Audit Adjustment',
  reserve: 'Order Reservation',
  release_reservation: 'Reservation Released',
  deduct_approved: 'Order Fulfilled / Deducted',
}

export function InventoryManager() {
  const [items, setItems] = useState<InventoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'low' | 'out'>('all')
  const [reloadKey, setReloadKey] = useState(0)

  // Modals state
  const [receiveModalItem, setReceiveModalItem] = useState<InventoryItem | null>(null)
  const [receiveQty, setReceiveQty] = useState('10')
  const [receiveReason, setReceiveReason] = useState('')
  const [receiveSubmitting, setReceiveSubmitting] = useState(false)
  const [receiveError, setReceiveError] = useState('')

  const [adjustModalItem, setAdjustModalItem] = useState<InventoryItem | null>(null)
  const [adjustOnHand, setAdjustOnHand] = useState('0')
  const [adjustReason, setAdjustReason] = useState('')
  const [adjustSubmitting, setAdjustSubmitting] = useState(false)
  const [adjustError, setAdjustError] = useState('')

  const [thresholdModalItem, setThresholdModalItem] = useState<InventoryItem | null>(null)
  const [thresholdVal, setThresholdVal] = useState('10')
  const [thresholdSubmitting, setThresholdSubmitting] = useState(false)
  const [thresholdError, setThresholdError] = useState('')

  const [historyItem, setHistoryItem] = useState<InventoryItem | null>(null)
  const [historyList, setHistoryList] = useState<StockMovement[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function loadInventory() {
      setLoading(true)
      setError('')
      try {
        const data = await apiFetch<InventoryItem[]>('/inventory', {
          signal: controller.signal,
        })
        setItems(data)
      } catch (err) {
        if (!controller.signal.aborted) {
          reportNetworkFailure(err)
          setError(
            err instanceof Error ? err.message : 'Failed to load live inventory.'
          )
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    void loadInventory()
    return () => controller.abort()
  }, [reloadKey])

  async function handleReceiveSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!receiveModalItem) return
    const qty = parseInt(receiveQty, 10)
    if (isNaN(qty) || qty <= 0) {
      setReceiveError('Please enter a valid positive quantity of cases.')
      return
    }

    setReceiveSubmitting(true)
    setReceiveError('')
    try {
      const updated = await apiFetch<InventoryItem>('/inventory/receive', {
        method: 'POST',
        body: JSON.stringify({
          sku: receiveModalItem.sku,
          quantity: qty,
          reason: receiveReason.trim() || undefined,
        }),
      })
      setItems((prev) =>
        prev.map((i) => (i.sku === updated.sku ? { ...i, ...updated } : i))
      )
      setReceiveModalItem(null)
    } catch (err) {
      reportNetworkFailure(err)
      setReceiveError(
        err instanceof Error ? err.message : 'Failed to receive stock.'
      )
    } finally {
      setReceiveSubmitting(false)
    }
  }

  async function handleAdjustSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!adjustModalItem) return
    const newCount = parseInt(adjustOnHand, 10)
    if (isNaN(newCount) || newCount < 0) {
      setAdjustError('Please enter a valid non-negative stock count.')
      return
    }
    if (adjustReason.trim().length < 3) {
      setAdjustError('A mandatory reason (minimum 3 characters) is required for audit adjustments.')
      return
    }

    setAdjustSubmitting(true)
    setAdjustError('')
    try {
      const updated = await apiFetch<InventoryItem>('/inventory/adjust', {
        method: 'POST',
        body: JSON.stringify({
          sku: adjustModalItem.sku,
          new_on_hand: newCount,
          reason: adjustReason.trim(),
        }),
      })
      setItems((prev) =>
        prev.map((i) => (i.sku === updated.sku ? { ...i, ...updated } : i))
      )
      setAdjustModalItem(null)
    } catch (err) {
      reportNetworkFailure(err)
      setAdjustError(
        err instanceof Error ? err.message : 'Failed to adjust stock count.'
      )
    } finally {
      setAdjustSubmitting(false)
    }
  }

  async function handleThresholdSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!thresholdModalItem) return
    const threshold = parseInt(thresholdVal, 10)
    if (isNaN(threshold) || threshold < 0) {
      setThresholdError('Please enter a valid non-negative threshold value.')
      return
    }

    setThresholdSubmitting(true)
    setThresholdError('')
    try {
      const updated = await apiFetch<InventoryItem>(
        `/inventory/${thresholdModalItem.sku}/threshold`,
        {
          method: 'PATCH',
          body: JSON.stringify({
            low_stock_threshold: threshold,
          }),
        }
      )
      setItems((prev) =>
        prev.map((i) => (i.sku === updated.sku ? { ...i, ...updated } : i))
      )
      setThresholdModalItem(null)
    } catch (err) {
      reportNetworkFailure(err)
      setThresholdError(
        err instanceof Error ? err.message : 'Failed to update alert threshold.'
      )
    } finally {
      setThresholdSubmitting(false)
    }
  }

  async function openHistory(item: InventoryItem) {
    setHistoryItem(item)
    setHistoryList([])
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const data = await apiFetch<StockMovement[]>(
        `/inventory/${item.sku}/history`
      )
      setHistoryList(data)
    } catch (err) {
      reportNetworkFailure(err)
      setHistoryError(
        err instanceof Error ? err.message : 'Failed to fetch ledger history.'
      )
    } finally {
      setHistoryLoading(false)
    }
  }

  const filteredItems = items.filter((item) => {
    const matchesQuery =
      item.sku.toLowerCase().includes(search.toLowerCase()) ||
      item.name.toLowerCase().includes(search.toLowerCase())
    if (!matchesQuery) return false

    if (filter === 'low') return item.is_low_stock && !item.is_out_of_stock
    if (filter === 'out') return item.is_out_of_stock
    return true
  })

  const lowCount = items.filter((i) => i.is_low_stock && !i.is_out_of_stock).length
  const outCount = items.filter((i) => i.is_out_of_stock).length

  return (
    <div className="inventory-manager-container">
      {/* Top statistics summary */}
      <div className="inventory-summary-cards">
        <div className="inv-stat-card">
          <div className="inv-stat-icon total"><Boxes size={18} /></div>
          <div>
            <span>Total SKUs</span>
            <strong>{items.length}</strong>
          </div>
        </div>
        <div className="inv-stat-card">
          <div className="inv-stat-icon ok"><CheckCircle2 size={18} /></div>
          <div>
            <span>In Stock (Healthy)</span>
            <strong>{items.length - lowCount - outCount}</strong>
          </div>
        </div>
        <div className="inv-stat-card">
          <div className="inv-stat-icon low"><AlertTriangle size={18} /></div>
          <div>
            <span>Low Stock</span>
            <strong className={lowCount > 0 ? 'text-amber' : ''}>{lowCount}</strong>
          </div>
        </div>
        <div className="inv-stat-card">
          <div className="inv-stat-icon out"><CircleAlert size={18} /></div>
          <div>
            <span>Out of Stock</span>
            <strong className={outCount > 0 ? 'text-coral' : ''}>{outCount}</strong>
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="inventory-toolbar">
        <div className="inventory-search-wrap">
          <Search size={15} className="inv-search-icon" aria-hidden="true" />
          <input
            type="text"
            className="inventory-search-input"
            placeholder="Search by SKU or product name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              type="button"
              className="inv-search-clear"
              onClick={() => setSearch('')}
              aria-label="Clear search"
            >
              <X size={14} />
            </button>
          )}
        </div>

        <div className="inv-filter-tabs">
          <button
            type="button"
            className={filter === 'all' ? 'inv-filter-btn active' : 'inv-filter-btn'}
            onClick={() => setFilter('all')}
          >
            All items
          </button>
          <button
            type="button"
            className={filter === 'low' ? 'inv-filter-btn active' : 'inv-filter-btn'}
            onClick={() => setFilter('low')}
          >
            Low stock {lowCount > 0 && <span className="inv-badge">{lowCount}</span>}
          </button>
          <button
            type="button"
            className={filter === 'out' ? 'inv-filter-btn active' : 'inv-filter-btn'}
            onClick={() => setFilter('out')}
          >
            Out of stock {outCount > 0 && <span className="inv-badge out">{outCount}</span>}
          </button>
        </div>

        <button
          className="orders-refresh"
          type="button"
          onClick={() => setReloadKey((k) => k + 1)}
          title="Refresh inventory"
        >
          <RefreshCw size={15} aria-hidden="true" />
        </button>
      </div>

      {loading && (
        <div className="orders-state">
          <LoaderCircle className="spin" size={21} aria-hidden="true" />
          <p>Loading inventory…</p>
        </div>
      )}

      {error && (
        <div className="orders-state" role="alert">
          <CircleAlert size={20} aria-hidden="true" />
          <h2>Inventory unavailable</h2>
          <p>{error}</p>
          <button type="button" onClick={() => setReloadKey((k) => k + 1)}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && filteredItems.length === 0 && (
        <div className="orders-state">
          <Boxes size={21} aria-hidden="true" />
          <h2>No matching inventory items</h2>
          <p>Try clearing your search query or filters.</p>
        </div>
      )}

      {!loading && !error && filteredItems.length > 0 && (
        <div className="inventory-table-wrap">
          <table className="inventory-table" role="table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Product Name</th>
                <th>Physical On-Hand</th>
                <th>Reserved</th>
                <th>Live Available</th>
                <th>Low Threshold</th>
                <th>Status</th>
                <th className="th-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.map((item) => (
                <tr key={item.sku} className={item.is_out_of_stock ? 'row-out' : item.is_low_stock ? 'row-low' : ''}>
                  <td className="sku-cell">
                    <strong>{item.sku}</strong>
                    <small>{item.pack_label}</small>
                  </td>
                  <td className="name-cell">{item.name}</td>
                  <td className="num-cell">
                    <strong>{item.on_hand_stock ?? 0}</strong> {item.order_unit}s
                  </td>
                  <td className="num-cell">
                    <span className="reserved-tag">
                      {item.reserved_stock ?? 0} {item.order_unit}s
                    </span>
                  </td>
                  <td className="num-cell available-cell">
                    <strong className={item.available_stock <= 0 ? 'text-coral' : item.is_low_stock ? 'text-amber' : 'text-forest'}>
                      {item.available_stock} {item.order_unit}s
                    </strong>
                  </td>
                  <td className="num-cell threshold-cell">
                    <span>{item.low_stock_threshold ?? 10}</span>
                    <button
                      type="button"
                      className="inline-action-btn"
                      title="Configure low-stock alert threshold"
                      onClick={() => {
                        setThresholdModalItem(item)
                        setThresholdVal(String(item.low_stock_threshold ?? 10))
                        setThresholdError('')
                      }}
                    >
                      <SlidersHorizontal size={13} />
                    </button>
                  </td>
                  <td>
                    {item.is_out_of_stock ? (
                      <span className="inv-status-pill out">Out of Stock</span>
                    ) : item.is_low_stock ? (
                      <span className="inv-status-pill low">Low Stock</span>
                    ) : (
                      <span className="inv-status-pill ok">Healthy</span>
                    )}
                  </td>
                  <td className="actions-cell">
                    <div className="inv-action-btn-group">
                      <button
                        type="button"
                        className="inv-btn-primary"
                        onClick={() => {
                          setReceiveModalItem(item)
                          setReceiveQty('10')
                          setReceiveReason('')
                          setReceiveError('')
                        }}
                        title={`Receive stock for ${item.sku}`}
                      >
                        <PackagePlus size={14} /> Receive
                      </button>
                      <button
                        type="button"
                        className="inv-btn-secondary"
                        onClick={() => {
                          setAdjustModalItem(item)
                          setAdjustOnHand(String(item.on_hand_stock ?? 0))
                          setAdjustReason('')
                          setAdjustError('')
                        }}
                        title={`Adjust on-hand count for ${item.sku}`}
                      >
                        Adjust
                      </button>
                      <button
                        type="button"
                        className="inv-btn-icon"
                        onClick={() => void openHistory(item)}
                        title={`View movement audit ledger for ${item.sku}`}
                      >
                        <History size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Receive Stock Modal */}
      {receiveModalItem && (
        <div className="inv-modal-overlay" role="dialog" aria-modal="true">
          <div className="inv-modal-card">
            <div className="inv-modal-header">
              <div>
                <p className="orders-overline">STOCK INWARD</p>
                <h3>Receive Inventory: {receiveModalItem.sku}</h3>
                <small>{receiveModalItem.name}</small>
              </div>
              <button
                type="button"
                className="inv-modal-close"
                onClick={() => setReceiveModalItem(null)}
              >
                <X size={18} />
              </button>
            </div>
            <form onSubmit={handleReceiveSubmit}>
              <div className="inv-form-group">
                <label htmlFor="receive-qty">Quantity Received ({receiveModalItem.order_unit}s)</label>
                <input
                  id="receive-qty"
                  type="number"
                  min="1"
                  required
                  value={receiveQty}
                  onChange={(e) => setReceiveQty(e.target.value)}
                />
              </div>
              <div className="inv-form-group">
                <label htmlFor="receive-reason">Reference / Supplier Invoice (Optional)</label>
                <input
                  id="receive-reason"
                  type="text"
                  maxLength={500}
                  placeholder="e.g. PO-2026-991, Delivery Chalan #104"
                  value={receiveReason}
                  onChange={(e) => setReceiveReason(e.target.value)}
                />
              </div>

              {receiveError && <p className="decision-error">{receiveError}</p>}

              <div className="inv-modal-actions">
                <button
                  type="button"
                  className="inv-btn-cancel"
                  onClick={() => setReceiveModalItem(null)}
                  disabled={receiveSubmitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="approve-order-button"
                  disabled={receiveSubmitting}
                >
                  {receiveSubmitting ? 'Receiving…' : 'Confirm Receipt'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Adjust Stock Modal */}
      {adjustModalItem && (
        <div className="inv-modal-overlay" role="dialog" aria-modal="true">
          <div className="inv-modal-card">
            <div className="inv-modal-header">
              <div>
                <p className="orders-overline">AUDIT ADJUSTMENT</p>
                <h3>Adjust Physical Count: {adjustModalItem.sku}</h3>
                <small>{adjustModalItem.name}</small>
              </div>
              <button
                type="button"
                className="inv-modal-close"
                onClick={() => setAdjustModalItem(null)}
              >
                <X size={18} />
              </button>
            </div>
            <form onSubmit={handleAdjustSubmit}>
              <div className="inv-info-banner">
                <div>
                  <span>Current Physical: <strong>{adjustModalItem.on_hand_stock ?? 0}</strong></span>
                  <span>Currently Reserved: <strong>{adjustModalItem.reserved_stock ?? 0}</strong></span>
                </div>
                <small>New physical count cannot be lower than reserved cases.</small>
              </div>

              <div className="inv-form-group">
                <label htmlFor="adjust-on-hand">New Physical On-Hand Count ({adjustModalItem.order_unit}s)</label>
                <input
                  id="adjust-on-hand"
                  type="number"
                  min={adjustModalItem.reserved_stock ?? 0}
                  required
                  value={adjustOnHand}
                  onChange={(e) => setAdjustOnHand(e.target.value)}
                />
              </div>

              <div className="inv-form-group">
                <label htmlFor="adjust-reason">Mandatory Audit Reason (min 3 chars)</label>
                <textarea
                  id="adjust-reason"
                  required
                  minLength={3}
                  maxLength={500}
                  placeholder="e.g. Physical inventory audit cycle count, Damaged box write-off..."
                  value={adjustReason}
                  onChange={(e) => setAdjustReason(e.target.value)}
                />
              </div>

              {adjustError && <p className="decision-error">{adjustError}</p>}

              <div className="inv-modal-actions">
                <button
                  type="button"
                  className="inv-btn-cancel"
                  onClick={() => setAdjustModalItem(null)}
                  disabled={adjustSubmitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="approve-order-button"
                  disabled={adjustSubmitting}
                >
                  {adjustSubmitting ? 'Saving…' : 'Record Adjustment'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Threshold Modal */}
      {thresholdModalItem && (
        <div className="inv-modal-overlay" role="dialog" aria-modal="true">
          <div className="inv-modal-card">
            <div className="inv-modal-header">
              <div>
                <p className="orders-overline">ALERT CONFIGURATION</p>
                <h3>Low-Stock Alert Threshold: {thresholdModalItem.sku}</h3>
              </div>
              <button
                type="button"
                className="inv-modal-close"
                onClick={() => setThresholdModalItem(null)}
              >
                <X size={18} />
              </button>
            </div>
            <form onSubmit={handleThresholdSubmit}>
              <div className="inv-form-group">
                <label htmlFor="threshold-val">Low-Stock Alert Level ({thresholdModalItem.order_unit}s)</label>
                <input
                  id="threshold-val"
                  type="number"
                  min="0"
                  required
                  value={thresholdVal}
                  onChange={(e) => setThresholdVal(e.target.value)}
                />
                <small className="help-text">
                  When available cases drop below or equal to this count, a warning indicator will trigger.
                </small>
              </div>

              {thresholdError && <p className="decision-error">{thresholdError}</p>}

              <div className="inv-modal-actions">
                <button
                  type="button"
                  className="inv-btn-cancel"
                  onClick={() => setThresholdModalItem(null)}
                  disabled={thresholdSubmitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="approve-order-button"
                  disabled={thresholdSubmitting}
                >
                  {thresholdSubmitting ? 'Saving…' : 'Save Threshold'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Movement History Ledger Drawer */}
      {historyItem && (
        <div className="inv-drawer-backdrop" onClick={() => setHistoryItem(null)}>
          <aside className="inv-history-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="inv-drawer-header">
              <div>
                <p className="orders-overline">STOCK LEDGER</p>
                <h3>{historyItem.sku} Movement History</h3>
                <small>{historyItem.name}</small>
              </div>
              <button
                type="button"
                className="inv-modal-close"
                onClick={() => setHistoryItem(null)}
                aria-label="Close ledger"
              >
                <X size={18} />
              </button>
            </div>

            {historyLoading && (
              <div className="orders-state">
                <LoaderCircle className="spin" size={20} />
                <p>Loading ledger entries…</p>
              </div>
            )}

            {historyError && (
              <div className="orders-state" role="alert">
                <CircleAlert size={18} />
                <p>{historyError}</p>
              </div>
            )}

            {!historyLoading && !historyError && historyList.length === 0 && (
              <div className="orders-state">
                <History size={20} />
                <p>No stock movement entries recorded yet.</p>
              </div>
            )}

            {!historyLoading && !historyError && historyList.length > 0 && (
              <div className="ledger-entries-list">
                {historyList.map((entry) => (
                  <div key={entry.id} className="ledger-entry-card">
                    <div className="ledger-top-row">
                      <span className={`ledger-type-badge type-${entry.movement_type}`}>
                        {movementTypeLabels[entry.movement_type] || entry.movement_type}
                      </span>
                      <span className="ledger-date">{formatDate(entry.created_at)}</span>
                    </div>

                    <div className="ledger-numbers">
                      <div>
                        <span>Delta Qty:</span>
                        <strong className={entry.quantity > 0 ? 'text-forest' : entry.quantity < 0 ? 'text-coral' : ''}>
                          {entry.quantity > 0 ? `+${entry.quantity}` : entry.quantity}
                        </strong>
                      </div>
                      <div>
                        <span>On-hand:</span>
                        <strong>{entry.on_hand_before} → {entry.on_hand_after}</strong>
                      </div>
                      <div>
                        <span>Reserved:</span>
                        <strong>{entry.reserved_before} → {entry.reserved_after}</strong>
                      </div>
                    </div>

                    {(entry.reference_id || entry.reason) && (
                      <div className="ledger-notes">
                        {entry.reference_id && <span className="ref-tag">Ref: {entry.reference_id}</span>}
                        {entry.reason && <p className="reason-text">{entry.reason}</p>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}

