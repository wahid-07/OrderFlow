export const OFFLINE_EVENT = 'orderflow:offline-detected'

export function reportNetworkFailure(error: unknown): void {
  if (error instanceof TypeError) {
    window.dispatchEvent(new Event(OFFLINE_EVENT))
  }
}