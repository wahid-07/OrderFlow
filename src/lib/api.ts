import { supabase } from './supabase'

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }
}

export async function getAccessToken(): Promise<string | null> {
  try {
    const { data, error } = await supabase.auth.getSession()
    if (error || !data.session) return null
    return data.session.access_token
  } catch {
    return null
  }
}

async function prepareHeaders(customHeaders?: HeadersInit): Promise<Headers> {
  const headers = new Headers(customHeaders)

  const token = await getAccessToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  return headers
}

export async function apiFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${apiBaseUrl}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`
  const headers = await prepareHeaders(options.headers)

  if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    try {
      const errorBody = (await response.json()) as { detail?: string }
      if (errorBody?.detail) {
        detail = errorBody.detail
      }
    } catch {
      // Body wasn't JSON, use status text if present
      if (response.statusText) {
        detail = response.statusText
      }
    }

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent('orderflow:session-expired'))
    }

    throw new ApiError(response.status, detail)
  }

  return (await response.json()) as T
}

export async function apiFetchBlob(endpoint: string, options: RequestInit = {}): Promise<Blob> {
  const url = `${apiBaseUrl}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`
  const headers = await prepareHeaders(options.headers)

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    try {
      const errorBody = (await response.json()) as { detail?: string }
      if (errorBody?.detail) {
        detail = errorBody.detail
      }
    } catch {
      if (response.statusText) {
        detail = response.statusText
      }
    }

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent('orderflow:session-expired'))
    }

    throw new ApiError(response.status, detail)
  }

  return await response.blob()
}

