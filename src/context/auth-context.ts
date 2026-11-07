import { createContext } from 'react'
import type { Session, User } from '@supabase/supabase-js'

export type UserRole = 'retailer' | 'order_desk'

export type UserProfile = {
    id: string
    role: UserRole
    retailer_id: string | null
    email?: string | null
}

export interface AuthContextType {
    session: Session | null
    user: User | null
    profile: UserProfile | null
    role: UserRole | null
    retailerId: string | null
    loading: boolean
    isAuthenticated: boolean
    profileError: string | null
    isConfigured: boolean
    login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>
    logout: () => Promise<void>
    refreshProfile: () => Promise<UserProfile | null>
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined)
