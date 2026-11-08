import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import type { Session, User } from '@supabase/supabase-js'
import {
  AuthContext,
  type AuthContextType,
  type RegistrationResult,
  type RetailerProfileData,
  type RetailerRegistrationData,
  type UserProfile,
} from './auth-context'
import { apiFetch, ApiError } from '../lib/api'
import { isSupabaseConfigured, supabase } from '../lib/supabase'
import { clearUserOfflineData, setActiveOfflineUserId } from '../lib/offlineStorage'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [isUnlinkedProfile, setIsUnlinkedProfile] = useState(false)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchProfile = useCallback(async (): Promise<{ profile: UserProfile | null; error?: string }> => {
    try {
      const data = await apiFetch<UserProfile>('/auth/me')
      setProfile(data)
      setProfileError(null)
      setIsUnlinkedProfile(false)
      return { profile: data }
    } catch (err) {
      let message = 'Could not link OrderFlow profile.'
      if (err instanceof ApiError) {
        if (err.status === 403) {
          setIsUnlinkedProfile(true)
          message =
            'Your account is verified with Supabase, but no active OrderFlow profile was found in the database. Please complete your retailer profile below.'
          setProfile(null)
          setProfileError(message)
          return { profile: null, error: 'UNLINKED_PROFILE' }
        } else if (err.status === 401) {
          message = 'Your session has expired. Please sign in again.'
        } else {
          message = err.detail
        }
      } else if (err instanceof Error) {
        message = err.message
      }
      setProfile(null)
      setIsUnlinkedProfile(false)
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
          setActiveOfflineUserId(data.session.user.id)
          await fetchProfile()
        } else if (mounted) {
          setActiveOfflineUserId(null)
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
        setIsUnlinkedProfile(false)
        setProfileError(null)
        setActiveOfflineUserId(null)
        setLoading(false)
        return
      }

      setSession(newSession)
      setUser(newSession.user)
      setActiveOfflineUserId(newSession.user.id)

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
      setIsUnlinkedProfile(false)
      setActiveOfflineUserId(null)
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

    // Attempt to link profile. If unlinked, isUnlinkedProfile will be set to true.
    await fetchProfile()

    return { success: true }
  }

  const registerRetailer = async (
    data: RetailerRegistrationData,
  ): Promise<RegistrationResult> => {
    if (!isSupabaseConfigured) {
      return {
        success: false,
        error:
          'Supabase credentials are not configured. Please add VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY to your environment.',
      }
    }

    setProfileError(null)

    // 1. Create account in Supabase Auth, saving shop metadata
    const { data: authData, error: authError } = await supabase.auth.signUp({
      email: data.email,
      password: data.password,
      options: {
        data: {
          owner_name: data.ownerName,
          shop_name: data.shopName,
          phone: data.phone,
          address: data.address,
        },
      },
    })

    if (authError) {
      return { success: false, error: authError.message }
    }

    if (!authData.user) {
      return { success: false, error: 'Registration failed. No user was created.' }
    }

    // 2. Check for immediate session vs email confirmation required
    let activeSession = authData.session
    if (!activeSession) {
      // Try immediate sign-in in case user is auto-confirmed
      const { data: signInData, error: signInError } = await supabase.auth.signInWithPassword({
        email: data.email,
        password: data.password,
      })
      if (!signInError && signInData.session) {
        activeSession = signInData.session
      } else {
        // Email confirmation is required by Supabase project settings
        return {
          success: true,
          needsEmailVerification: true,
        }
      }
    }

    setSession(activeSession)
    setUser(activeSession.user)

    // 3. Register retailer profile in OrderFlow backend
    try {
      await apiFetch('/auth/register', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${activeSession.access_token}`,
        },
        body: JSON.stringify({
          shop_name: data.shopName,
          owner_name: data.ownerName,
          phone: data.phone,
          address: data.address,
          email: data.email,
        }),
      })
    } catch (err) {
      // Backend profile creation failed: clean up local session
      await supabase.auth.signOut()
      setSession(null)
      setUser(null)
      setProfile(null)
      const message = err instanceof Error ? err.message : 'Could not create retailer profile.'
      return { success: false, error: message }
    }

    // 4. Link & fetch profile
    const profileResult = await fetchProfile()
    if (!profileResult.profile) {
      return {
        success: false,
        error: profileResult.error ?? 'Profile created, but could not be loaded.',
      }
    }

    return { success: true }
  }

  const completeRetailerProfile = async (
    data: RetailerProfileData,
  ): Promise<{ success: boolean; error?: string }> => {
    if (!session?.access_token) {
      return {
        success: false,
        error: 'No active authenticated session found. Please sign in again.',
      }
    }

    setProfileError(null)

    try {
      await apiFetch('/auth/register', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          shop_name: data.shopName,
          owner_name: data.ownerName,
          phone: data.phone,
          address: data.address,
          email: user?.email,
        }),
      })

      const profileResult = await fetchProfile()
      if (!profileResult.profile) {
        return {
          success: false,
          error: profileResult.error ?? 'Profile created, but could not be loaded.',
        }
      }

      setIsUnlinkedProfile(false)
      return { success: true }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not complete retailer profile.'
      return { success: false, error: message }
    }
  }

  const logout = async (): Promise<void> => {
    try {
      if (profile?.id) {
        await clearUserOfflineData(profile.id, profile.salesman_id)
      }
      await supabase.auth.signOut()
    } catch {
      // ignore logout errors
    } finally {
      setActiveOfflineUserId(null)
      setSession(null)
      setUser(null)
      setProfile(null)
      setIsUnlinkedProfile(false)
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
    isUnlinkedProfile,
    profileError,
    isConfigured: isSupabaseConfigured,
    login,
    registerRetailer,
    completeRetailerProfile,
    logout,
    refreshProfile: async () => {
      const res = await fetchProfile()
      return res.profile
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
