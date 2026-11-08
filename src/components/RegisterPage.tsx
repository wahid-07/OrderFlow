import { useState, type FormEvent } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  LoaderCircle,
  Lock,
  Mail,
  MapPin,
  Phone,
  ShieldCheck,
  Store,
  User as UserIcon,
} from 'lucide-react'
import { useAuth } from '../context/useAuth'
import './RegisterPage.css'

type Props = {
  onNavigateToLogin: () => void
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const PHONE_CHARS_REGEX = /^[0-9+() -]+$/

export function RegisterPage({ onNavigateToLogin }: Props) {
  const { registerRetailer, isConfigured } = useAuth()

  const [ownerName, setOwnerName] = useState('')
  const [shopName, setShopName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [address, setAddress] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [emailVerificationSent, setEmailVerificationSent] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const validate = (): boolean => {
    const errors: Record<string, string> = {}

    const cleanOwner = ownerName.trim()
    const cleanShop = shopName.trim()
    const cleanEmail = email.trim()
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

    if (!cleanEmail) {
      errors.email = 'Email address is required.'
    } else if (!EMAIL_REGEX.test(cleanEmail)) {
      errors.email = 'Please enter a valid email address.'
    }

    if (!cleanPhone) {
      errors.phone = 'Mobile number is required.'
    } else if (!PHONE_CHARS_REGEX.test(phone.trim()) || cleanPhone.length < 10 || cleanPhone.length > 13) {
      errors.phone = 'Please enter a valid 10-digit mobile number.'
    }

    if (!cleanAddress) {
      errors.address = 'Shop address is required.'
    } else if (cleanAddress.length < 5) {
      errors.address = 'Please enter a full shop address (at least 5 characters).'
    }

    if (!password) {
      errors.password = 'Password is required.'
    } else if (password.length < 8) {
      errors.password = 'Password must be at least 8 characters long.'
    }

    if (!confirmPassword) {
      errors.confirmPassword = 'Confirm password is required.'
    } else if (password !== confirmPassword) {
      errors.confirmPassword = 'Passwords do not match.'
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
      const result = await registerRetailer({
        ownerName: ownerName.trim(),
        shopName: shopName.trim(),
        email: email.trim(),
        phone: phone.trim(),
        address: address.trim(),
        password,
      })

      if (!result.success) {
        setErrorMessage(result.error ?? 'Registration failed. Please check your information.')
      } else if (result.needsEmailVerification) {
        setEmailVerificationSent(true)
      }
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : 'A network error occurred during registration. Please try again.',
      )
    } finally {
      setLoading(false)
    }
  }

  if (emailVerificationSent) {
    return (
      <div className="register-container">
        <div className="register-card" style={{ textAlign: 'center' }}>
          <div className="register-brand" style={{ justifyContent: 'center' }}>
            <span className="brand-mark" aria-hidden="true">O</span>
            <span className="brand-name">OrderFlow</span>
          </div>

          <div style={{ margin: '24px 0 16px', display: 'flex', justifyContent: 'center' }}>
            <div
              style={{
                width: '56px',
                height: '56px',
                borderRadius: '50%',
                background: '#e6f0e9',
                display: 'grid',
                placeItems: 'center',
                color: '#245c46',
              }}
            >
              <CheckCircle2 size={32} />
            </div>
          </div>

          <h1 style={{ fontSize: '22px', fontWeight: 600, color: '#1d2925', margin: '0 0 10px' }}>
            Verify Your Email
          </h1>

          <p style={{ fontSize: '14px', color: '#6f7a73', lineHeight: 1.5, margin: '0 0 16px' }}>
            We have sent a verification link to <strong>{email.trim()}</strong>.
          </p>

          <div
            style={{
              background: '#f8faf8',
              border: '1px solid #e0e6df',
              borderRadius: '8px',
              padding: '14px 16px',
              fontSize: '13px',
              color: '#34403b',
              lineHeight: 1.5,
              textAlign: 'left',
              marginBottom: '24px',
            }}
          >
            <strong>What to do next:</strong>
            <ol style={{ margin: '8px 0 0 18px', padding: 0 }}>
              <li>Open your email and click the confirmation link.</li>
              <li>Return here and sign in to activate your retailer account.</li>
            </ol>
          </div>

          <button
            type="button"
            className="register-submit-button"
            style={{ width: '100%' }}
            onClick={onNavigateToLogin}
          >
            Proceed to Sign In
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="register-container">
      <div className="register-card">
        <header className="register-header">
          <div className="register-brand">
            <span className="brand-mark" aria-hidden="true">O</span>
            <span className="brand-name">OrderFlow</span>
          </div>
          <h1>Retailer Registration</h1>
          <p className="register-subtitle">
            Create an independent retailer account to access wholesale FMCG distribution pricing
          </p>
        </header>

        {!isConfigured && (
          <div className="register-warning" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <div>
              <strong>Supabase environment setup required</strong>
              <p>
                Add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to your{' '}
                <code>.env</code> file to enable live registration.
              </p>
            </div>
          </div>
        )}

        {errorMessage && (
          <div className="register-error" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <span>{errorMessage}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="register-form" noValidate>
          <div className="form-grid">
            {/* Owner Name */}
            <div className="form-group">
              <label htmlFor="reg-owner">Owner / Contact Name *</label>
              <div className="input-wrap">
                <UserIcon className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="reg-owner"
                  type="text"
                  value={ownerName}
                  onChange={(e) => {
                    setOwnerName(e.target.value)
                    if (fieldErrors.ownerName) setFieldErrors((prev) => ({ ...prev, ownerName: '' }))
                  }}
                  placeholder="e.g. Ramesh Kumar"
                  autoComplete="name"
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
              <label htmlFor="reg-shop">Shop / Store Name *</label>
              <div className="input-wrap">
                <Store className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="reg-shop"
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

            {/* Email Address */}
            <div className="form-group">
              <label htmlFor="reg-email">Email Address *</label>
              <div className="input-wrap">
                <Mail className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="reg-email"
                  type="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    if (fieldErrors.email) setFieldErrors((prev) => ({ ...prev, email: '' }))
                  }}
                  placeholder="name@store.com"
                  autoComplete="email"
                  required
                  disabled={loading}
                />
              </div>
              {fieldErrors.email && (
                <span className="field-error-text">{fieldErrors.email}</span>
              )}
            </div>

            {/* Mobile Number */}
            <div className="form-group">
              <label htmlFor="reg-phone">Mobile Number *</label>
              <div className="input-wrap">
                <Phone className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="reg-phone"
                  type="tel"
                  value={phone}
                  onChange={(e) => {
                    setPhone(e.target.value)
                    if (fieldErrors.phone) setFieldErrors((prev) => ({ ...prev, phone: '' }))
                  }}
                  placeholder="10-digit mobile number"
                  autoComplete="tel"
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
            <label htmlFor="reg-address">Shop / Delivery Address *</label>
            <div className="input-wrap">
              <MapPin className="input-icon" size={17} aria-hidden="true" />
              <input
                id="reg-address"
                type="text"
                value={address}
                onChange={(e) => {
                  setAddress(e.target.value)
                  if (fieldErrors.address) setFieldErrors((prev) => ({ ...prev, address: '' }))
                }}
                placeholder="Shop number, Street, Market area, City"
                autoComplete="street-address"
                required
                disabled={loading}
              />
            </div>
            {fieldErrors.address && (
              <span className="field-error-text">{fieldErrors.address}</span>
            )}
          </div>

          <div className="form-grid">
            {/* Password */}
            <div className="form-group">
              <label htmlFor="reg-password">Password (min. 8 characters) *</label>
              <div className="input-wrap">
                <Lock className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="reg-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value)
                    if (fieldErrors.password) setFieldErrors((prev) => ({ ...prev, password: '' }))
                  }}
                  placeholder="••••••••"
                  autoComplete="new-password"
                  required
                  disabled={loading}
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  disabled={loading}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {fieldErrors.password && (
                <span className="field-error-text">{fieldErrors.password}</span>
              )}
            </div>

            {/* Confirm Password */}
            <div className="form-group">
              <label htmlFor="reg-confirm-password">Confirm Password *</label>
              <div className="input-wrap">
                <Lock className="input-icon" size={17} aria-hidden="true" />
                <input
                  id="reg-confirm-password"
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => {
                    setConfirmPassword(e.target.value)
                    if (fieldErrors.confirmPassword) {
                      setFieldErrors((prev) => ({ ...prev, confirmPassword: '' }))
                    }
                  }}
                  placeholder="••••••••"
                  autoComplete="new-password"
                  required
                  disabled={loading}
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowConfirmPassword((prev) => !prev)}
                  aria-label={showConfirmPassword ? 'Hide password' : 'Show password'}
                  disabled={loading}
                >
                  {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {fieldErrors.confirmPassword && (
                <span className="field-error-text">{fieldErrors.confirmPassword}</span>
              )}
            </div>
          </div>

          <button
            type="submit"
            className="register-submit-button"
            disabled={loading || !isConfigured}
          >
            {loading ? (
              <>
                <LoaderCircle className="spin" size={17} aria-hidden="true" />
                <span>Creating Account…</span>
              </>
            ) : (
              <span>Create Retailer Account</span>
            )}
          </button>

          <div className="register-switch-view">
            <span>Already have an account?</span>{' '}
            <button
              type="button"
              className="link-button"
              onClick={onNavigateToLogin}
              disabled={loading}
            >
              Sign In
            </button>
          </div>
        </form>

        <footer className="register-footer">
          <div className="register-security-notice">
            <ShieldCheck size={16} aria-hidden="true" />
            <span>Instant retailer activation with isolated PostgreSQL credentials</span>
          </div>
        </footer>
      </div>
    </div>
  )
}
