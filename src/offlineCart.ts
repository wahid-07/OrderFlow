import {
  saveCartDraftForUser,
  loadCartDraftForUser,
} from './lib/offlineStorage'

type CartDraft = Record<string, number>

export async function loadCartDraft(userId = 'default-user', retailerId: string | null = null): Promise<CartDraft> {
  return await loadCartDraftForUser(userId, retailerId)
}

export async function saveCartDraft(
  cart: CartDraft,
  userId = 'default-user',
  retailerId: string | null = null,
): Promise<void> {
  await saveCartDraftForUser(userId, retailerId, cart)
}
