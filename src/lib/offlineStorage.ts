import { openDB, type DBSchema, type IDBPDatabase } from 'idb'
import { apiFetch, ApiError } from './api'

export type OutboxOrderStatus =
  | 'waiting_connection'
  | 'syncing'
  | 'synced'
  | 'needs_attention'

export interface OutboxOrder {
  idempotency_key: string
  userId: string
  retailerId: string
  retailerName: string
  items: Array<{ sku: string; quantity: number }>
  orderSource: 'retailer' | 'salesman' | 'offline_sync'
  salesmanId?: string | null
  status: OutboxOrderStatus
  errorMessage?: string | null
  conflictDetails?: string | null
  submittedOrderNumber?: string | null
  isBeingEdited?: boolean
  createdAt: string
  updatedAt: string
}

export interface CachedCatalogueRecord {
  key: string
  userId: string | null
  role: string | null
  retailerId: string | null
  items: any[]
  syncedAt: string
}

export interface AssignedRetailer {
  id: string
  name: string
  external_ref: string
  phone?: string | null
  address?: string | null
  credit_limit: string
  current_outstanding: string
  available_credit: string
  credit_utilization_percent: string
}

export interface CachedSalesmanRetailersRecord {
  key: string
  salesmanId: string
  retailers: AssignedRetailer[]
  syncedAt: string
}

export interface SalesmanVisitNoteItem {
  id: string
  salesmanId: string
  retailerId: string
  retailerName?: string
  note: string
  synced: boolean
  createdAt: string
}

interface OrderFlowDB extends DBSchema {
  'catalogue-cache': {
    key: string
    value: CachedCatalogueRecord
  }
  'cart-drafts': {
    key: string
    value: { cart: Record<string, number>; updatedAt: string }
  }
  'outbox-orders': {
    key: string
    value: OutboxOrder
    indexes: { 'by-user': string; 'by-status': string }
  }
  'salesman-retailers': {
    key: string
    value: CachedSalesmanRetailersRecord
  }
  'salesman-notes': {
    key: string
    value: SalesmanVisitNoteItem
    indexes: { 'by-salesman': string }
  }
}

const DB_NAME = 'orderflow-offline-v2'
const DB_VERSION = 2

let dbPromise: Promise<IDBPDatabase<OrderFlowDB>> | null = null

// -------------------------------------------------------------------------
// Active User Session Tracking (Account Isolation)
// -------------------------------------------------------------------------
let activeOfflineUserId: string | null = null

export function setActiveOfflineUserId(userId: string | null): void {
  activeOfflineUserId = userId
}

export function getActiveOfflineUserId(): string | null {
  return activeOfflineUserId
}

function getDB(): Promise<IDBPDatabase<OrderFlowDB>> {
  if (!dbPromise) {
    dbPromise = openDB<OrderFlowDB>(DB_NAME, DB_VERSION, {
      upgrade(db, oldVersion) {
        if (oldVersion < 1) {
          if (!db.objectStoreNames.contains('catalogue-cache')) {
            db.createObjectStore('catalogue-cache', { keyPath: 'key' })
          }
          if (!db.objectStoreNames.contains('cart-drafts')) {
            db.createObjectStore('cart-drafts')
          }
        }
        if (oldVersion < 2) {
          if (!db.objectStoreNames.contains('outbox-orders')) {
            const outboxStore = db.createObjectStore('outbox-orders', {
              keyPath: 'idempotency_key',
            })
            outboxStore.createIndex('by-user', 'userId')
            outboxStore.createIndex('by-status', 'status')
          }
          if (!db.objectStoreNames.contains('salesman-retailers')) {
            db.createObjectStore('salesman-retailers', { keyPath: 'key' })
          }
          if (!db.objectStoreNames.contains('salesman-notes')) {
            const notesStore = db.createObjectStore('salesman-notes', {
              keyPath: 'id',
            })
            notesStore.createIndex('by-salesman', 'salesmanId')
          }
        }
      },
    })
  }
  return dbPromise
}

// -------------------------------------------------------------------------
// Catalogue Caching with Strict Role, User and Retailer Isolation
// -------------------------------------------------------------------------
export async function saveCachedCatalogue(
  userId: string | null,
  role: string | null,
  retailerId: string | null,
  items: any[],
): Promise<void> {
  const db = await getDB()
  const key = `cat_${role || 'anon'}_${userId || 'none'}_${retailerId || 'global'}`
  await db.put('catalogue-cache', {
    key,
    userId,
    role,
    retailerId,
    items,
    syncedAt: new Date().toISOString(),
  })
}

export async function getCachedCatalogue(
  userId: string | null,
  role: string | null,
  retailerId: string | null,
): Promise<{ items: any[]; syncedAt: string } | null> {
  const db = await getDB()
  const key = `cat_${role || 'anon'}_${userId || 'none'}_${retailerId || 'global'}`
  const record = await db.get('catalogue-cache', key)
  if (!record) return null
  return { items: record.items, syncedAt: record.syncedAt }
}

// -------------------------------------------------------------------------
// Cart Drafts Scoped by User and Retailer Context
// -------------------------------------------------------------------------
export async function saveCartDraftForUser(
  userId: string,
  retailerId: string | null,
  cart: Record<string, number>,
): Promise<void> {
  const db = await getDB()
  const key = `${userId}_${retailerId || 'default'}`
  const safeCart = Object.fromEntries(
    Object.entries(cart).filter(
      ([, quantity]) => Number.isSafeInteger(quantity) && quantity > 0,
    ),
  )
  await db.put('cart-drafts', { cart: safeCart, updatedAt: new Date().toISOString() }, key)
}

export async function loadCartDraftForUser(
  userId: string,
  retailerId: string | null,
): Promise<Record<string, number>> {
  const db = await getDB()
  const key = `${userId}_${retailerId || 'default'}`
  const record = await db.get('cart-drafts', key)
  return record?.cart ?? {}
}

// -------------------------------------------------------------------------
// Outbox & Offline Sync
// -------------------------------------------------------------------------
export async function queueOutboxOrder(order: OutboxOrder): Promise<void> {
  const db = await getDB()
  await db.put('outbox-orders', order)
  window.dispatchEvent(new CustomEvent('orderflow:outbox-updated'))
}

export async function getOutboxOrders(userId?: string): Promise<OutboxOrder[]> {
  const db = await getDB()
  const all = await db.getAll('outbox-orders')
  if (userId) {
    return all.filter((o) => o.userId === userId)
  }
  return all
}

export async function updateOutboxOrderStatus(
  idempotencyKey: string,
  status: OutboxOrderStatus,
  patch?: Partial<OutboxOrder>,
): Promise<void> {
  const db = await getDB()
  const existing = await db.get('outbox-orders', idempotencyKey)
  if (existing) {
    const updated: OutboxOrder = {
      ...existing,
      ...patch,
      status,
      updatedAt: new Date().toISOString(),
    }
    await db.put('outbox-orders', updated)
    window.dispatchEvent(new CustomEvent('orderflow:outbox-updated'))
  }
}

export async function markOrderUnderReview(idempotencyKey: string): Promise<void> {
  const db = await getDB()
  const existing = await db.get('outbox-orders', idempotencyKey)
  if (existing) {
    await db.put('outbox-orders', {
      ...existing,
      isBeingEdited: true,
      updatedAt: new Date().toISOString(),
    })
    window.dispatchEvent(new CustomEvent('orderflow:outbox-updated'))
  }
}

export async function supersedeOutboxOrder(oldIdempotencyKey: string): Promise<void> {
  const db = await getDB()
  await db.delete('outbox-orders', oldIdempotencyKey)
  window.dispatchEvent(new CustomEvent('orderflow:outbox-updated'))
}

export async function removeOutboxOrder(idempotencyKey: string): Promise<void> {
  const db = await getDB()
  await db.delete('outbox-orders', idempotencyKey)
  window.dispatchEvent(new CustomEvent('orderflow:outbox-updated'))
}

// -------------------------------------------------------------------------
// Salesman Local Storage
// -------------------------------------------------------------------------
export async function saveSalesmanRetailers(
  salesmanId: string,
  retailers: AssignedRetailer[],
): Promise<void> {
  const db = await getDB()
  const key = `salesman_${salesmanId}`
  await db.put('salesman-retailers', {
    key,
    salesmanId,
    retailers,
    syncedAt: new Date().toISOString(),
  })
}

export async function getSalesmanRetailers(
  salesmanId: string,
): Promise<{ retailers: AssignedRetailer[]; syncedAt: string } | null> {
  const db = await getDB()
  const key = `salesman_${salesmanId}`
  const record = await db.get('salesman-retailers', key)
  if (!record) return null
  return { retailers: record.retailers, syncedAt: record.syncedAt }
}

export async function saveSalesmanNoteLocally(
  note: SalesmanVisitNoteItem,
): Promise<void> {
  const db = await getDB()
  await db.put('salesman-notes', note)
}

export async function getSalesmanNotesLocally(
  salesmanId: string,
): Promise<SalesmanVisitNoteItem[]> {
  const db = await getDB()
  const index = db.transaction('salesman-notes').store.index('by-salesman')
  return await index.getAll(salesmanId)
}

// -------------------------------------------------------------------------
// Data Isolation / Clear on Logout
// Preserves unsynced orders and unsynced notes; purges cached credentials and drafts.
// -------------------------------------------------------------------------
export async function clearUserOfflineData(
  userId?: string,
  salesmanId?: string | null,
): Promise<void> {
  const db = await getDB()

  if (userId) {
    // 1. Clear ONLY synced outbox orders for this user; preserve unsynced
    const orders = await getOutboxOrders(userId)
    for (const o of orders) {
      if (o.status === 'synced') {
        await db.delete('outbox-orders', o.idempotency_key)
      }
    }

    // 2. Clear cart drafts belonging to this user
    const cartKeys = await db.getAllKeys('cart-drafts')
    for (const k of cartKeys) {
      if (typeof k === 'string' && (k.startsWith(`${userId}_`) || k === 'default-user_default')) {
        await db.delete('cart-drafts', k)
      }
    }

    // 3. Clear cached catalogue prices for this user to prevent leakage across logins
    const catKeys = await db.getAllKeys('catalogue-cache')
    for (const k of catKeys) {
      if (typeof k === 'string' && k.includes(`_${userId}_`)) {
        await db.delete('catalogue-cache', k)
      }
    }
  }

  // 4. Clear sensitive salesman cache (assigned retailers and synced notes)
  if (salesmanId) {
    await db.delete('salesman-retailers', `salesman_${salesmanId}`)
    const notes = await getSalesmanNotesLocally(salesmanId)
    for (const n of notes) {
      if (n.synced) {
        await db.delete('salesman-notes', n.id)
      }
      // Unsynced notes are preserved until network sync succeeds
    }
  }
}

// -------------------------------------------------------------------------
// Outbox Synchronization Engine with Account Isolation
// -------------------------------------------------------------------------
let isSyncInProgress = false

export async function syncOutboxOrders(
  forceRetry = false,
  explicitUserId?: string,
): Promise<{
  syncedCount: number
  failedCount: number
}> {
  if (isSyncInProgress || !navigator.onLine) {
    return { syncedCount: 0, failedCount: 0 }
  }

  // Strictly enforce user isolation: Never sync without an authenticated user context
  const currentUserId = explicitUserId ?? activeOfflineUserId
  if (!currentUserId) {
    return { syncedCount: 0, failedCount: 0 }
  }

  isSyncInProgress = true
  let syncedCount = 0
  let failedCount = 0

  try {
    const orders = await getOutboxOrders(currentUserId)
    const pendingOrders = orders.filter((o) => {
      // Must match current authenticated user
      if (o.userId !== currentUserId) {
        return false
      }
      // Never resubmit an order that is actively being reviewed or edited in cart
      if (o.isBeingEdited) {
        return false
      }
      return (
        o.status === 'waiting_connection' ||
        o.status === 'syncing' ||
        (forceRetry && o.status === 'needs_attention')
      )
    })

    for (const order of pendingOrders) {
      await updateOutboxOrderStatus(order.idempotency_key, 'syncing')

      try {
        const payload: Record<string, any> = {
          items: order.items,
          retailer_id: order.retailerId,
          idempotency_key: order.idempotency_key,
          order_source: order.orderSource,
        }

        const res = await apiFetch<any>('/orders', {
          method: 'POST',
          body: JSON.stringify(payload),
        })

        await updateOutboxOrderStatus(order.idempotency_key, 'synced', {
          submittedOrderNumber: res.order_number,
          errorMessage: null,
          conflictDetails: null,
          isBeingEdited: false,
        })
        syncedCount++
      } catch (err) {
        failedCount++

        if (err instanceof ApiError) {
          if (err.status === 401) {
            // Authentication expired: preserve order, require re-authentication
            await updateOutboxOrderStatus(order.idempotency_key, 'needs_attention', {
              errorMessage: 'Authentication expired or required. Please sign in to resume sync.',
              conflictDetails: '401 Unauthorized',
            })
          } else if (err.status === 409) {
            // Conflict (e.g. key collision or payload mismatch): clear conflict path
            await updateOutboxOrderStatus(order.idempotency_key, 'needs_attention', {
              errorMessage: `Order conflict: ${err.detail || 'The order conflicts with existing server records.'}. Review cart to resolve.`,
              conflictDetails: err.detail,
            })
          } else if (err.status === 400 || err.status === 403) {
            // Client error / authorization error: requires user intervention
            await updateOutboxOrderStatus(order.idempotency_key, 'needs_attention', {
              errorMessage: `Validation error (${err.status}): ${err.detail || 'Order validation failed'}. User review required.`,
              conflictDetails: err.detail,
            })
          } else if (err.status >= 500) {
            // Temporary server error: keep as waiting_connection for automatic retry
            await updateOutboxOrderStatus(order.idempotency_key, 'waiting_connection', {
              errorMessage: `Server temporarily unavailable (${err.status}): ${err.detail || 'Will retry automatically.'}`,
            })
          } else {
            await updateOutboxOrderStatus(order.idempotency_key, 'needs_attention', {
              errorMessage: err.detail || 'Order synchronization failed.',
              conflictDetails: err.detail,
            })
          }
        } else {
          // Temporary network failure (fetch abort, DNS drop, offline): retry automatically
          const errorMsg = err instanceof Error ? err.message : 'Network error'
          await updateOutboxOrderStatus(order.idempotency_key, 'waiting_connection', {
            errorMessage: `Connection issue: ${errorMsg}. Will retry automatically when connection restores.`,
          })
        }
      }
    }
  } finally {
    isSyncInProgress = false
    window.dispatchEvent(new CustomEvent('orderflow:outbox-updated'))
  }

  return { syncedCount, failedCount }
}

// Auto-trigger sync on network reconnect for the currently active user
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    if (activeOfflineUserId) {
      void syncOutboxOrders(false, activeOfflineUserId)
    }
  })
}
