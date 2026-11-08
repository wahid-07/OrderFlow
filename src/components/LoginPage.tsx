import { useState, type FormEvent } from 'react'
import {
  AlertCircle,
  Eye,
  EyeOff,
  LoaderCircle,
  Lock,
  Mail,
  ShieldCheck,
} from 'lucide-react'
import { useAuth } from '../context/useAuth'
import './LoginPage.css'

type Props = {
  onNavigateToRegister?: () => void
}

export function LoginPage({ onNavigateToRegister }: Props) {
  const { login, isConfigured } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setErrorMessage(null)

    const cleanEmail = email.trim()
    if (!cleanEmail) {
      setErrorMessage('Please enter your email address.')
      return
    }
    if (!password) {
      setErrorMessage('Please enter your password.')
      return
    }

    setLoading(true)
    try {
      const result = await login(cleanEmail, password)
      if (!result.success) {
        setErrorMessage(result.error ?? 'Invalid email or password.')
      }
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : 'A network error occurred. Please try again.',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-container">
      <div className="login-card">
        <header className="login-header">
          <div className="login-brand">
            <span className="brand-mark" aria-hidden="true">O</span>
            <span className="brand-name">OrderFlow</span>
          </div>
          <h1>Sign In to OrderFlow</h1>
          <p className="login-subtitle">
            Secure order distribution for retailers & order desk teams
          </p>
        </header>

        {!isConfigured && (
          <div className="login-warning" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <div>
              <strong>Supabase environment setup required</strong>
              <p>
                Add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to your{' '}
                <code>.env</code> file to enable live authentication.
              </p>
            </div>
          </div>
        )}

        {errorMessage && (
          <div className="login-error" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <span>{errorMessage}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="login-form" noValidate>
          <div className="form-group">
            <label htmlFor="login-email">Email Address</label>
            <div className="input-wrap">
              <Mail className="input-icon" size={17} aria-hidden="true" />
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                autoComplete="email"
                required
                disabled={loading}
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="login-password">Password</label>
            <div className="input-wrap">
              <Lock className="input-icon" size={17} aria-hidden="true" />
              <input
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
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
          </div>

          <button
            type="submit"
            className="login-submit-button"
            disabled={loading || !isConfigured}
          >
            {loading ? (
              <>
                <LoaderCircle className="spin" size={17} aria-hidden="true" />
                <span>Authenticating…</span>
              </>
            ) : (
              <span>Sign In</span>
            )}
          </button>

          {onNavigateToRegister && (
            <div className="login-switch-view">
              <span>Don't have an account?</span>{' '}
              <button
                type="button"
                className="link-button"
                onClick={onNavigateToRegister}
                disabled={loading}
              >
                Register as Retailer
              </button>
            </div>
          )}
        </form>

        <footer className="login-footer">
          <div className="login-security-notice">
            <ShieldCheck size={16} aria-hidden="true" />
            <span>Role-verified access with PostgreSQL security isolation</span>
          </div>
        </footer>
      </div>
    </div>
  )
}

