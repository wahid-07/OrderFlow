import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { AuthContext, type AuthContextType, type UserProfile } from './auth-context'
import { apiFetch, ApiError } from '../lib/api'
import { isSupabaseConfigured, supabase } from '../lib/supabase'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchProfile = useCallback(async (): Promise<{ profile: UserProfile | null; error?: string }> => {
    try {
      const data = await apiFetch<UserProfile>('/auth/me')
      setProfile(data)
      setProfileError(null)
      return { profile: data }
    } catch (err) {
      let message = 'Could not link OrderFlow profile.'
      if (err instanceof ApiError) {
        if (err.status === 403) {
          message =
            'Your account is verified with Supabase, but no active OrderFlow profile was found in the database. Please contact your administrator.'
        } else if (err.status === 401) {
          message = 'Your session has expired. Please sign in again.'
        } else {
          message = err.detail
        }
      } else if (err instanceof Error) {
        message = err.message
      }
      setProfile(null)
      setProfileError(message)
      return { profile: null, error: message }
    }
  }, [])

  useEffect(() => {
    let mounted = true

    async function initializeAuth() {
      if (!isSupabaseConfigured) {
        if (mounted) {
          setLoading(false)
        }
        return
      }

      try {
        const { data, error } = await supabase.auth.getSession()
        if (error) {
          if (mounted) setLoading(false)
          return
        }

        if (mounted && data.session) {
          setSession(data.session)
          setUser(data.session.user)
          await fetchProfile()
        }
      } catch {
        // network or initialization issue
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    void initializeAuth()

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (event, newSession) => {
      if (!mounted) return

      if (event === 'SIGNED_OUT' || !newSession) {
        setSession(null)
        setUser(null)
        setProfile(null)
        setProfileError(null)
        setLoading(false)
        return
      }

      setSession(newSession)
      setUser(newSession.user)

      if (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED' || event === 'USER_UPDATED') {
        await fetchProfile()
      }
      setLoading(false)
    })

    const handleSessionExpired = () => {
      void supabase.auth.signOut()
      setSession(null)
      setUser(null)
      setProfile(null)
      setProfileError('Your session has expired. Please log in again.')
    }

    window.addEventListener('orderflow:session-expired', handleSessionExpired)

    return () => {
      mounted = false
      subscription.unsubscribe()
      window.removeEventListener('orderflow:session-expired', handleSessionExpired)
    }
  }, [fetchProfile])

  const login = async (
    email: string,
    password: string,
  ): Promise<{ success: boolean; error?: string }> => {
    if (!isSupabaseConfigured) {
      return {
        success: false,
        error:
          'Supabase credentials are not configured. Please add VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY to your environment.',
      }
    }

    setProfileError(null)

    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (error) {
      return { success: false, error: error.message }
    }

    if (!data.session) {
      return { success: false, error: 'Login succeeded but no active session was returned.' }
    }

    setSession(data.session)
    setUser(data.user)

    // Link backend profile immediately
    const profileResult = await fetchProfile()
    if (!profileResult.profile) {
      return {
        success: false,
        error:
          profileResult.error ??
          'Supabase login was successful, but no active OrderFlow database profile is linked to this account.',
      }
    }

    return { success: true }
  }

  const logout = async (): Promise<void> => {
    try {
      await supabase.auth.signOut()
    } catch {
      // ignore logout errors
    } finally {
      setSession(null)
      setUser(null)
      setProfile(null)
      setProfileError(null)
    }
  }

  const isAuthenticated = Boolean(session && profile)
  const role = profile?.role ?? null
  const retailerId = profile?.retailer_id ?? null

  const value: AuthContextType = {
    session,
    user,
    profile,
    role,
    retailerId,
    loading,
    isAuthenticated,
    profileError,
    isConfigured: isSupabaseConfigured,
    login,
    logout,
    refreshProfile: async () => {
      const res = await fetchProfile()
      return res.profile
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

