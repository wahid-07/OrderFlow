import { useState, useEffect, useMemo } from 'react'
import {
  Users,
  Search,
  FileText,
  Cloud,
  CloudOff,
  LogOut,
  ShoppingBag,
  ArrowLeft,
  AlertCircle,
  RefreshCw,
  Phone,
  MapPin,
  X,
} from 'lucide-react'
import { useAuth } from './context/useAuth'
import { apiFetch } from './lib/api'
import {
  saveSalesmanRetailers,
  getSalesmanRetailers,
  saveSalesmanNoteLocally,
  getSalesmanNotesLocally,
  getOutboxOrders,
  type AssignedRetailer,
} from './lib/offlineStorage'
import { OutboxDrawer } from './components/OutboxDrawer'
import CataloguePage from './CataloguePage'
import './SalesmanPortal.css'

interface VisitNote {
  id: string
  retailer_id: string
  retailer_name?: string
  note: string
  created_at: string
}

export function SalesmanPortal() {
  const { profile, logout } = useAuth()
  const [retailers, setRetailers] = useState<AssignedRetailer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [isOnline, setIsOnline] = useState(navigator.onLine)
  const [lastSynced, setLastSynced] = useState<string | null>(null)

  // Outbox modal state
  const [outboxOpen, setOutboxOpen] = useState(false)
  const [pendingOutboxCount, setPendingOutboxCount] = useState(0)

  // Visit Note modal state
  const [activeNoteRetailer, setActiveNoteRetailer] = useState<AssignedRetailer | null>(null)
  const [noteContent, setNoteContent] = useState('')
  const [savingNote, setSavingNote] = useState(false)
  const [pastNotes, setPastNotes] = useState<VisitNote[]>([])

  // Ordering mode state (Order for Retailer)
  const [activeOrderingRetailer, setActiveOrderingRetailer] = useState<AssignedRetailer | null>(null)

  const salesmanId = profile?.salesman_id || 'default-salesman'

  useEffect(() => {
    let active = true

    const updateCount = async () => {
      const orders = await getOutboxOrders(profile?.id)
      if (!active) return
      const pending = orders.filter(
        (o) => o.status === 'waiting_connection' || o.status === 'needs_attention',
      )
      setPendingOutboxCount(pending.length)
    }

    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)
    const handleOutboxUpdate = () => void updateCount()

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    window.addEventListener('orderflow:outbox-updated', handleOutboxUpdate)

    void updateCount()

    return () => {
      active = false
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener('orderflow:outbox-updated', handleOutboxUpdate)
    }
  }, [profile?.id])

  useEffect(() => {
    let active = true

    async function loadRetailers() {
      setLoading(true)
      setError(null)

      if (navigator.onLine) {
        try {
          const data = await apiFetch<{ source: string; retailers: AssignedRetailer[] }>(
            '/salesman/assigned-retailers',
          )
          if (!active) return
          setRetailers(data.retailers)
          const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          setLastSynced(now)
          await saveSalesmanRetailers(salesmanId, data.retailers)
        } catch (err) {
          if (!active) return
          // Fall back to offline cached retailers
          const cached = await getSalesmanRetailers(salesmanId)
          if (!active) return
          if (cached) {
            setRetailers(cached.retailers)
            setLastSynced(new Date(cached.syncedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
          } else {
            setError(err instanceof Error ? err.message : 'Could not fetch assigned retailers.')
          }
        } finally {
          if (active) setLoading(false)
        }
      } else {
        // Offline mode
        const cached = await getSalesmanRetailers(salesmanId)
        if (!active) return
        if (cached) {
          setRetailers(cached.retailers)
          setLastSynced(new Date(cached.syncedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
        } else {
          setError('No offline cache found for assigned retailers. Please connect online to download your list.')
        }
        setLoading(false)
      }
    }

    void loadRetailers()

    return () => {
      active = false
    }
  }, [salesmanId])

  const filteredRetailers = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return retailers
    return retailers.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.external_ref.toLowerCase().includes(q) ||
        (r.phone && r.phone.includes(q)),
    )
  }, [retailers, search])

  const openNoteModal = async (retailer: AssignedRetailer) => {
    setActiveNoteRetailer(retailer)
    setNoteContent('')

    if (navigator.onLine) {
      try {
        const res = await apiFetch<{ source: string; notes: VisitNote[] }>(
          `/salesman/visit-notes?retailer_id=${retailer.id}`,
        )
        setPastNotes(res.notes)
      } catch {
        // Load locally
        const local = await getSalesmanNotesLocally(salesmanId)
        setPastNotes(
          local
            .filter((n) => n.retailerId === retailer.id)
            .map((n) => ({
              id: n.id,
              retailer_id: n.retailerId,
              note: n.note,
              created_at: n.createdAt,
            })),
        )
      }
    } else {
      const local = await getSalesmanNotesLocally(salesmanId)
      setPastNotes(
        local
          .filter((n) => n.retailerId === retailer.id)
          .map((n) => ({
            id: n.id,
            retailer_id: n.retailerId,
            note: n.note,
            created_at: n.createdAt,
          })),
      )
    }
  }

  const handleSaveNote = async () => {
    if (!activeNoteRetailer || !noteContent.trim()) return
    setSavingNote(true)

    const noteText = noteContent.trim()
    const now = new Date().toISOString()
    const noteId = `note-${Date.now()}`

    if (navigator.onLine) {
      try {
        await apiFetch('/salesman/visit-notes', {
          method: 'POST',
          body: JSON.stringify({
            retailer_id: activeNoteRetailer.id,
            note: noteText,
          }),
        })
      } catch {
        // Save locally if remote call fails
        await saveSalesmanNoteLocally({
          id: noteId,
          salesmanId,
          retailerId: activeNoteRetailer.id,
          retailerName: activeNoteRetailer.name,
          note: noteText,
          synced: false,
          createdAt: now,
        })
      }
    } else {
      // Save locally offline
      await saveSalesmanNoteLocally({
        id: noteId,
        salesmanId,
        retailerId: activeNoteRetailer.id,
        retailerName: activeNoteRetailer.name,
        note: noteText,
        synced: false,
        createdAt: now,
      })
    }

    setSavingNote(false)
    setActiveNoteRetailer(null)
    setNoteContent('')
  }

  // If ordering context is active for a retailer, render CataloguePage in that retailer's context!
  if (activeOrderingRetailer) {
    return (
      <div>
        <div
          style={{
            background: '#194533',
            color: '#ffffff',
            padding: '8px 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '13px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button
              type="button"
              onClick={() => setActiveOrderingRetailer(null)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                background: '#245c46',
                color: '#ffffff',
                border: 'none',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <ArrowLeft size={14} /> Back to My Retailers
            </button>
            <span>
              Ordering on behalf of: <strong>{activeOrderingRetailer.name}</strong> ({activeOrderingRetailer.external_ref})
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span>Available Credit: ₹{activeOrderingRetailer.available_credit}</span>
            <button
              type="button"
              onClick={() => setOutboxOpen(true)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                background: '#245c46',
                color: '#ffffff',
                border: 'none',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <Cloud size={14} /> Sync Outbox ({pendingOutboxCount})
            </button>
          </div>
        </div>

        <CataloguePage
          salesmanRetailerContext={{
            id: activeOrderingRetailer.id,
            name: activeOrderingRetailer.name,
            external_ref: activeOrderingRetailer.external_ref,
          }}
        />

        <OutboxDrawer
          isOpen={outboxOpen}
          onClose={() => setOutboxOpen(false)}
          userId={profile?.id}
        />
      </div>
    )
  }

  return (
    <div className="salesman-portal">
      <header className="salesman-topbar">
        <div className="salesman-brand">
          <span className="salesman-brand-mark">O</span>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <strong style={{ fontSize: '16px', color: '#1d2925' }}>OrderFlow</strong>
              <span className="salesman-role-pill">Salesman Field Portal</span>
            </div>
            <div style={{ fontSize: '12px', color: '#6f7a73' }}>
              {profile?.salesman_name || 'Field Representative'}
            </div>
          </div>
        </div>

        <div className="salesman-topbar-actions">
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '12px',
              color: isOnline ? '#245c46' : '#c95d43',
              background: isOnline ? '#e6f0e9' : '#fff0e9',
              padding: '4px 10px',
              borderRadius: '12px',
              fontWeight: 600,
            }}
          >
            {isOnline ? <Cloud size={14} /> : <CloudOff size={14} />}
            {isOnline ? 'Online' : 'Offline Mode'}
            {lastSynced && <span style={{ color: '#6f7a73', fontWeight: 400 }}>· Synced {lastSynced}</span>}
          </div>

          <button
            type="button"
            className="salesman-outbox-btn"
            onClick={() => setOutboxOpen(true)}
            title="Open offline sync queue"
          >
            <Cloud size={15} />
            <span>Outbox</span>
            {pendingOutboxCount > 0 && (
              <span className="salesman-outbox-badge">{pendingOutboxCount}</span>
            )}
          </button>

          <button
            type="button"
            className="salesman-signout-btn"
            onClick={() => void logout()}
          >
            <LogOut size={15} /> Sign out
          </button>
        </div>
      </header>

      <main className="salesman-body">
        <section className="salesman-hero">
          <div className="salesman-hero-header">
            <div>
              <h1>Assigned Retailers ({retailers.length})</h1>
              <p>Select a retailer to take an order, record a field visit, or check available credit.</p>
            </div>

            <div className="salesman-search-bar">
              <Search size={16} color="#6f7a73" />
              <input
                type="text"
                placeholder="Search by retailer name, code, or phone…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
        </section>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '48px 0', color: '#6f7a73' }}>
            <RefreshCw size={24} className="spin" style={{ marginBottom: '8px' }} />
            <p>Loading assigned retailers…</p>
          </div>
        ) : error ? (
          <div
            style={{
              padding: '16px',
              borderRadius: '8px',
              background: '#fff0e9',
              border: '1px solid #f8c3b4',
              color: '#c95d43',
            }}
          >
            <AlertCircle size={20} style={{ marginBottom: '8px' }} />
            <p style={{ margin: 0 }}>{error}</p>
          </div>
        ) : filteredRetailers.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '48px 0', color: '#6f7a73' }}>
            <Users size={36} style={{ marginBottom: '8px', opacity: 0.5 }} />
            <p>No retailers matched your search.</p>
          </div>
        ) : (
          <div className="retailers-grid">
            {filteredRetailers.map((r) => {
              const utilPercent = Number(r.credit_utilization_percent || 0)
              const isHighUtil = utilPercent > 80

              return (
                <div key={r.id} className="retailer-card">
                  <div className="retailer-card-header">
                    <div>
                      <h3>{r.name}</h3>
                      <span className="retailer-ref-badge">{r.external_ref}</span>
                    </div>
                  </div>

                  <div className="retailer-card-contact">
                    {r.phone && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                        <Phone size={13} color="#6f7a73" /> {r.phone}
                      </div>
                    )}
                    {r.address && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <MapPin size={13} color="#6f7a73" /> {r.address}
                      </div>
                    )}
                  </div>

                  <div className="retailer-credit-widget">
                    <div className="credit-row">
                      <span>Credit limit:</span>
                      <strong>₹{Number(r.credit_limit).toLocaleString('en-IN')}</strong>
                    </div>
                    <div className="credit-row">
                      <span>Outstanding:</span>
                      <strong>₹{Number(r.current_outstanding).toLocaleString('en-IN')}</strong>
                    </div>
                    <div className="credit-row">
                      <span>Available:</span>
                      <strong style={{ color: Number(r.available_credit) > 0 ? '#245c46' : '#c95d43' }}>
                        ₹{Number(r.available_credit).toLocaleString('en-IN')}
                      </strong>
                    </div>

                    <div className="credit-progress-track">
                      <div
                        className={`credit-progress-bar ${isHighUtil ? 'high' : ''}`}
                        style={{ width: `${Math.min(utilPercent, 100)}%` }}
                      />
                    </div>
                  </div>

                  <div className="retailer-actions">
                    <button
                      type="button"
                      className="order-for-retailer-btn"
                      onClick={() => setActiveOrderingRetailer(r)}
                    >
                      <ShoppingBag size={15} /> Order for Retailer
                    </button>
                    <button
                      type="button"
                      className="note-for-retailer-btn"
                      onClick={() => void openNoteModal(r)}
                      title="Add field visit note"
                    >
                      <FileText size={16} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </main>

      {/* Field Visit Note Modal */}
      {activeNoteRetailer && (
        <div className="note-modal-overlay" onClick={() => setActiveNoteRetailer(null)}>
          <div className="note-modal" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <h2>Field Visit Note</h2>
              <button
                type="button"
                onClick={() => setActiveNoteRetailer(null)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6f7a73' }}
              >
                <X size={18} />
              </button>
            </div>
            <p>
              Recording note for <strong>{activeNoteRetailer.name}</strong> ({activeNoteRetailer.external_ref})
            </p>

            <textarea
              placeholder="Record notes from your visit: shelf display, competitor activity, retailer feedback, promises made…"
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              disabled={savingNote}
            />

            <div className="note-modal-actions">
              <button
                type="button"
                onClick={() => setActiveNoteRetailer(null)}
                style={{
                  padding: '8px 16px',
                  background: '#f4f6f2',
                  border: '1px solid #e0e6df',
                  borderRadius: '6px',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveNote}
                disabled={savingNote || !noteContent.trim()}
                style={{
                  padding: '8px 16px',
                  background: '#245c46',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: savingNote || !noteContent.trim() ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                }}
              >
                {savingNote ? 'Saving…' : 'Save Note'}
              </button>
            </div>

            {pastNotes.length > 0 && (
              <div className="note-history-list">
                <strong style={{ fontSize: '13px', color: '#1d2925' }}>Previous Visit Notes</strong>
                {pastNotes.map((n) => (
                  <div key={n.id} className="note-history-item">
                    <div>{n.note}</div>
                    <div className="note-history-meta">
                      {new Date(n.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Outbox Drawer */}
      <OutboxDrawer
        isOpen={outboxOpen}
        onClose={() => setOutboxOpen(false)}
        userId={profile?.id}
        onEditOrderInCart={(outboxOrder) => {
          const matchingRetailer = retailers.find((r) => r.id === outboxOrder.retailerId)
          if (matchingRetailer) {
            setActiveOrderingRetailer(matchingRetailer)
            setOutboxOpen(false)
          } else {
            window.alert('Cannot edit: This retailer is no longer in your active assignments.')
          }
        }}
      />
    </div>
  )
}

export default SalesmanPortal

