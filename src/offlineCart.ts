import { openDB, type DBSchema } from 'idb'

type CartDraft = Record<string, number>

interface OrderFlowLocalDatabase extends DBSchema {
  'cart-drafts': {
    key: 'retailer-cart'
    value: CartDraft
  }
}

const database = openDB<OrderFlowLocalDatabase>('orderflow-offline', 1, {
  upgrade(db) {
    db.createObjectStore('cart-drafts')
  },
})

export async function loadCartDraft(): Promise<CartDraft> {
  const db = await database
  return (await db.get('cart-drafts', 'retailer-cart')) ?? {}
}

export async function saveCartDraft(cart: CartDraft): Promise<void> {
  const db = await database
  const safeCart = Object.fromEntries(
    Object.entries(cart).filter(([, quantity]) => Number.isSafeInteger(quantity) && quantity > 0),
  )
  await db.put('cart-drafts', safeCart, 'retailer-cart')
}