import { createContext } from 'react'
import type { Session, User } from '@supabase/supabase-js'

export type UserRole = 'retailer' | 'order_desk' | 'salesman' | 'distributor_admin' | 'super_admin'

export type UserProfile = {
    id: string
    role: UserRole
    retailer_id: string | null
    email?: string | null
    salesman_id?: string | null
    salesman_name?: string | null
}

export type RetailerRegistrationData = {
    ownerName: string
    shopName: string
    phone: string
    address: string
    email: string
    password: string
}

export type RetailerProfileData = {
    ownerName: string
    shopName: string
    phone: string
    address: string
}

export type RegistrationResult = {
    success: boolean
    needsEmailVerification?: boolean
    error?: string
}

export interface AuthContextType {
    session: Session | null
    user: User | null
    profile: UserProfile | null
    role: UserRole | null
    retailerId: string | null
    loading: boolean
    isAuthenticated: boolean
    isUnlinkedProfile: boolean
    profileError: string | null
    isConfigured: boolean
    login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>
    registerRetailer: (data: RetailerRegistrationData) => Promise<RegistrationResult>
    completeRetailerProfile: (data: RetailerProfileData) => Promise<{ success: boolean; error?: string }>
    logout: () => Promise<void>
    refreshProfile: () => Promise<UserProfile | null>
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined)
