import { useState, useEffect, useCallback } from 'react'
import {
  Cloud,
  RefreshCw,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  Clock,
  X,
  ExternalLink,
} from 'lucide-react'
import {
  getOutboxOrders,
  removeOutboxOrder,
  syncOutboxOrders,
  type OutboxOrder,
} from '../lib/offlineStorage'

interface OutboxDrawerProps {
  isOpen: boolean
  onClose: () => void
  userId?: string
  onEditOrderInCart?: (order: OutboxOrder) => void
}

export function OutboxDrawer({
  isOpen,
  onClose,
  userId,
  onEditOrderInCart,
}: OutboxDrawerProps) {
  const [orders, setOrders] = useState<OutboxOrder[]>([])
  const [syncing, setSyncing] = useState(false)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)

  const loadOrders = useCallback(async () => {
    const list = await getOutboxOrders(userId)
    setOrders(list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()))
  }, [userId])

  useEffect(() => {
    if (!isOpen) return

    let cancelled = false
    async function load() {
      const list = await getOutboxOrders(userId)
      if (!cancelled) {
        setOrders(list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()))
      }
    }

    void load()

    const handleOutboxUpdate = () => {
      void load()
    }

    window.addEventListener('orderflow:outbox-updated', handleOutboxUpdate)
    return () => {
      cancelled = true
      window.removeEventListener('orderflow:outbox-updated', handleOutboxUpdate)
    }
  }, [isOpen, userId])

  const handleSyncNow = async () => {
    setSyncing(true)
    setSyncMessage(null)
    try {
      const res = await syncOutboxOrders(true, userId)
      await loadOrders()
      if (res.syncedCount > 0 && res.failedCount === 0) {
        setSyncMessage(`Successfully synced ${res.syncedCount} order(s).`)
      } else if (res.failedCount > 0) {
        setSyncMessage(`Synced ${res.syncedCount} order(s); ${res.failedCount} need attention.`)
      } else {
        setSyncMessage('No orders waiting to sync.')
      }
    } catch {
      setSyncMessage('Sync failed. Please check network connection.')
    } finally {
      setSyncing(false)
    }
  }

  const handleDelete = async (idempotencyKey: string) => {
    if (window.confirm('Are you sure you want to discard this pending order?')) {
      await removeOutboxOrder(idempotencyKey)
      await loadOrders()
    }
  }

  if (!isOpen) return null

  const pendingCount = orders.filter(
    (o) => o.status === 'waiting_connection' || o.status === 'needs_attention',
  ).length

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        justifyContent: 'flex-end',
        background: 'rgba(29, 41, 37, 0.4)',
        backdropFilter: 'blur(2px)',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '480px',
          height: '100%',
          background: '#ffffff',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.15)',
          display: 'flex',
          flexDirection: 'column',
          padding: '24px',
          boxSizing: 'border-box',
          overflowY: 'auto',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #e0e6df',
            paddingBottom: '16px',
            marginBottom: '16px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Cloud size={22} color="#245c46" />
            <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: '#1d2925' }}>
              Offline Sync Queue
            </h2>
            {pendingCount > 0 && (
              <span
                style={{
                  background: '#c95d43',
                  color: '#ffffff',
                  fontSize: '11px',
                  fontWeight: 700,
                  padding: '2px 8px',
                  borderRadius: '12px',
                }}
              >
                {pendingCount}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: '6px',
              color: '#6f7a73',
            }}
            aria-label="Close sync queue"
          >
            <X size={20} />
          </button>
        </div>

        <div style={{ display: 'flex', gap: '12px', marginBottom: '20px' }}>
          <button
            type="button"
            onClick={handleSyncNow}
            disabled={syncing}
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              padding: '10px 16px',
              background: '#245c46',
              color: '#ffffff',
              border: 'none',
              borderRadius: '8px',
              fontWeight: 600,
              cursor: syncing ? 'not-allowed' : 'pointer',
              opacity: syncing ? 0.7 : 1,
            }}
          >
            <RefreshCw size={16} className={syncing ? 'spin' : ''} />
            {syncing ? 'Syncing with Server…' : 'Sync Queue Now'}
          </button>
        </div>

        {syncMessage && (
          <div
            style={{
              padding: '10px 14px',
              borderRadius: '6px',
              background: '#f4f6f2',
              border: '1px solid #e0e6df',
              fontSize: '13px',
              marginBottom: '16px',
              color: '#1d2925',
            }}
          >
            {syncMessage}
          </div>
        )}

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {orders.length === 0 ? (
            <div
              style={{
                textAlign: 'center',
                padding: '48px 16px',
                color: '#6f7a73',
                fontSize: '14px',
              }}
            >
              <CheckCircle2 size={36} color="#245c46" style={{ marginBottom: '12px' }} />
              <p style={{ margin: 0, fontWeight: 600 }}>Sync queue is empty</p>
              <p style={{ margin: '6px 0 0', fontSize: '13px' }}>
                Orders placed while offline will wait here and sync automatically when you reconnect.
              </p>
            </div>
          ) : (
            orders.map((order) => {
              const itemCount = order.items.reduce((s, i) => s + i.quantity, 0)
              return (
                <div
                  key={order.idempotency_key}
                  style={{
                    border: '1px solid #e0e6df',
                    borderRadius: '8px',
                    padding: '16px',
                    marginBottom: '14px',
                    background:
                      order.status === 'needs_attention'
                        ? '#fff0e9'
                        : order.status === 'synced'
                        ? '#f4f6f2'
                        : '#ffffff',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      justifyContent: 'space-between',
                      marginBottom: '8px',
                    }}
                  >
                    <div>
                      <strong style={{ fontSize: '15px', color: '#1d2925' }}>
                        {order.retailerName}
                      </strong>
                      <div style={{ fontSize: '12px', color: '#6f7a73', marginTop: '2px' }}>
                        {itemCount} item(s) · {new Date(order.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      {order.status === 'waiting_connection' && (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            background: '#f4e9b5',
                            color: '#744210',
                            fontSize: '11px',
                            fontWeight: 700,
                            padding: '3px 8px',
                            borderRadius: '6px',
                          }}
                        >
                          <Clock size={12} /> Waiting for connection
                        </span>
                      )}
                      {order.status === 'syncing' && (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            background: '#e6f0e9',
                            color: '#245c46',
                            fontSize: '11px',
                            fontWeight: 700,
                            padding: '3px 8px',
                            borderRadius: '6px',
                          }}
                        >
                          <RefreshCw size={12} className="spin" /> Syncing…
                        </span>
                      )}
                      {order.status === 'synced' && (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            background: '#e6f0e9',
                            color: '#245c46',
                            fontSize: '11px',
                            fontWeight: 700,
                            padding: '3px 8px',
                            borderRadius: '6px',
                          }}
                        >
                          <CheckCircle2 size={12} /> Synced ({order.submittedOrderNumber})
                        </span>
                      )}
                      {order.status === 'needs_attention' && (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            background: '#fff0e9',
                            color: '#c95d43',
                            fontSize: '11px',
                            fontWeight: 700,
                            padding: '3px 8px',
                            borderRadius: '6px',
                          }}
                        >
                          <AlertTriangle size={12} /> Needs attention
                        </span>
                      )}
                    </div>
                  </div>

                  {order.errorMessage && (
                    <div
                      style={{
                        margin: '10px 0',
                        padding: '10px 12px',
                        borderRadius: '6px',
                        background: '#ffffff',
                        border: '1px solid #f8c3b4',
                        color: '#c95d43',
                        fontSize: '12px',
                        lineHeight: 1.4,
                      }}
                    >
                      <strong>Conflict / Error:</strong> {order.errorMessage}
                    </div>
                  )}

                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      marginTop: '12px',
                      paddingTop: '8px',
                      borderTop: '1px solid #e0e6df',
                    }}
                  >
                    <div style={{ fontSize: '11px', color: '#6f7a73', fontFamily: 'monospace' }}>
                      Key: {order.idempotency_key.slice(0, 14)}…
                    </div>

                    <div style={{ display: 'flex', gap: '8px' }}>
                      {order.status === 'needs_attention' && onEditOrderInCart && (
                        <button
                          type="button"
                          onClick={() => onEditOrderInCart(order)}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
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
                          <ExternalLink size={13} /> Review & Edit
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => handleDelete(order.idempotency_key)}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          background: 'none',
                          border: 'none',
                          color: '#c95d43',
                          fontSize: '12px',
                          cursor: 'pointer',
                          padding: '4px 8px',
                        }}
                        title="Delete from sync queue"
                      >
                        <Trash2 size={14} /> Remove
                      </button>
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}

