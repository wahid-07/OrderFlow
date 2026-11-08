import { useState, type FormEvent } from 'react'
import {
  AlertCircle,
  BadgeCheck,
  LoaderCircle,
  LogOut,
  Mail,
  MapPin,
  Phone,
  ShieldCheck,
  Store,
  User as UserIcon,
} from 'lucide-react'
import { useAuth } from '../context/useAuth'
import './RegisterPage.css'

const PHONE_CHARS_REGEX = /^[0-9+() -]+$/

export function CompleteProfilePage() {
  const { user, completeRetailerProfile, logout } = useAuth()

  const metadata = user?.user_metadata ?? {}
  const [ownerName, setOwnerName] = useState(metadata.owner_name ?? '')
  const [shopName, setShopName] = useState(metadata.shop_name ?? '')
  const [phone, setPhone] = useState(metadata.phone ?? '')
  const [address, setAddress] = useState(metadata.address ?? '')

  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const validate = (): boolean => {
    const errors: Record<string, string> = {}
    const cleanOwner = ownerName.trim()
    const cleanShop = shopName.trim()
    const cleanPhone = phone.trim().replace(/\D/g, '')
    const cleanAddress = address.trim()

    if (!cleanOwner) {
      errors.ownerName = 'Owner / Contact person name is required.'
    } else if (cleanOwner.length < 2) {
      errors.ownerName = 'Owner name must be at least 2 characters.'
    }

    if (!cleanShop) {
      errors.shopName = 'Shop / Store name is required.'
    } else if (cleanShop.length < 2) {
      errors.shopName = 'Shop name must be at least 2 characters.'
    }

    if (!cleanPhone) {
      errors.phone = 'Mobile number is required.'
    } else if (!PHONE_CHARS_REGEX.test(phone.trim()) || cleanPhone.length < 10 || cleanPhone.length > 13) {
      errors.phone = 'Please enter a valid 10-digit mobile number.'
    }

    if (!cleanAddress) {
      errors.address = 'Shop delivery address is required.'
    } else if (cleanAddress.length < 5) {
      errors.address = 'Please enter a full shop address (at least 5 characters).'
    }

    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setErrorMessage(null)

    if (!validate()) {
      return
    }

    setLoading(true)
    try {
      const result = await completeRetailerProfile({
        ownerName: ownerName.trim(),
        shopName: shopName.trim(),
        phone: phone.trim(),
        address: address.trim(),
      })

      if (!result.success) {
        setErrorMessage(result.error ?? 'Could not activate profile. Please check your information.')
      }
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : 'A network error occurred while activating your profile.',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="register-container">
      <div className="register-card">
        <header className="register-header">
          <div className="register-brand">
            <span className="brand-mark" aria-hidden="true">O</span>
            <span className="brand-name">OrderFlow</span>
          </div>
          <h1>Complete Retailer Profile</h1>
          <p className="register-subtitle">
            Your Supabase account is verified! Confirm your business details below to activate your wholesale distributor ordering access.
          </p>
        </header>

        {errorMessage && (
          <div className="register-error" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <span>{errorMessage}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="register-form" noValidate>
          {/* Verified Email Banner */}
          <div className="form-group full-width">
            <label htmlFor="comp-email">Verified Email Address</label>
            <div className="input-wrap">
              <Mail className="input-icon" size={17} aria-hidden="true" />
              <input
                id="comp-email"
                type="email"
                value={user?.email ?? ''}
                readOnly
                disabled
                style={{ background: '#f8faf8', color: '#4a5568', cursor: 'default' }}
              />
              <span
                style={{
                  position: 'absolute',
                  right: '12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  fontSize: '11px',
                  color: '#245c46',
                  fontWeight: 600,
                }}
              >
                <BadgeCheck size={16} /> Verified
              </span>
            </div>
          </div>

          <div className="form-grid">
            {/* Owner Name */}
            <div className="form-group">
              <label htmlFor="comp-owner">Owner / Contact Name *</label>
              <div className="input-wrap">
                <UserIcon className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="comp-owner"
                  type="text"
                  value={ownerName}
                  onChange={(e) => {
                    setOwnerName(e.target.value)
                    if (fieldErrors.ownerName) setFieldErrors((prev) => ({ ...prev, ownerName: '' }))
                  }}
                  placeholder="e.g. Ramesh Kumar"
                  required
                  disabled={loading}
                />
              </div>
              {fieldErrors.ownerName && (
                <span className="field-error-text">{fieldErrors.ownerName}</span>
              )}
            </div>

            {/* Shop Name */}
            <div className="form-group">
              <label htmlFor="comp-shop">Shop / Store Name *</label>
              <div className="input-wrap">
                <Store className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="comp-shop"
                  type="text"
                  value={shopName}
                  onChange={(e) => {
                    setShopName(e.target.value)
                    if (fieldErrors.shopName) setFieldErrors((prev) => ({ ...prev, shopName: '' }))
                  }}
                  placeholder="e.g. Ramesh Kirana Store"
                  required
                  disabled={loading}
                />
              </div>
              {fieldErrors.shopName && (
                <span className="field-error-text">{fieldErrors.shopName}</span>
              )}
            </div>

            {/* Mobile Number */}
            <div className="form-group full-width">
              <label htmlFor="comp-phone">Mobile Number *</label>
              <div className="input-wrap">
                <Phone className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="comp-phone"
                  type="tel"
                  value={phone}
                  onChange={(e) => {
                    setPhone(e.target.value)
                    if (fieldErrors.phone) setFieldErrors((prev) => ({ ...prev, phone: '' }))
                  }}
                  placeholder="10-digit mobile number"
                  required
                  disabled={loading}
                />
              </div>
              {fieldErrors.phone && (
                <span className="field-error-text">{fieldErrors.phone}</span>
              )}
            </div>
          </div>

          {/* Shop Address */}
          <div className="form-group full-width">
            <label htmlFor="comp-address">Shop / Delivery Address *</label>
            <div className="input-wrap">
              <MapPin className="input-icon" size={17} aria-hidden="true" />
              <input
                id="comp-address"
                type="text"
                value={address}
                onChange={(e) => {
                  setAddress(e.target.value)
                  if (fieldErrors.address) setFieldErrors((prev) => ({ ...prev, address: '' }))
                }}
                placeholder="Shop number, Street, Market area, City"
                required
                disabled={loading}
              />
            </div>
            {fieldErrors.address && (
              <span className="field-error-text">{fieldErrors.address}</span>
            )}
          </div>

          <button
            type="submit"
            className="register-submit-button"
            disabled={loading}
          >
            {loading ? (
              <>
                <LoaderCircle className="spin" size={17} aria-hidden="true" />
                <span>Activating Profile…</span>
              </>
            ) : (
              <span>Activate Retailer Account</span>
            )}
          </button>

          <div className="register-switch-view">
            <span>Signed in as {user?.email} ·</span>{' '}
            <button
              type="button"
              className="link-button"
              onClick={() => void logout()}
              disabled={loading}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}
            >
              <LogOut size={13} aria-hidden="true" /> Sign out
            </button>
          </div>
        </form>

        <footer className="register-footer">
          <div className="register-security-notice">
            <ShieldCheck size={16} aria-hidden="true" />
            <span>Retailer profile linked with PostgreSQL role isolation</span>
          </div>
        </footer>
      </div>
    </div>
  )
}

