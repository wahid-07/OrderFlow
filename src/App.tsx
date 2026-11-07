import { AuthProvider } from './context/AuthProvider'
import { useAuth } from './context/useAuth'
import { LoginPage } from './components/LoginPage'
import CataloguePage from './CataloguePage'
import { AlertCircle, LoaderCircle, LogOut } from 'lucide-react'

function AppContent() {
  const { isAuthenticated, loading, profileError, logout, profile } = useAuth()

  if (loading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '12px',
          color: '#245c46',
          fontFamily: 'inherit',
        }}
      >
        <LoaderCircle className="spin" size={28} aria-hidden="true" />
        <p style={{ fontSize: '14px', fontWeight: 600 }}>Connecting to OrderFlow…</p>
      </div>
    )
  }

  if (!isAuthenticated) {
    return (
      <>
        {profileError && (
          <div
            role="alert"
            style={{
              maxWidth: '440px',
              margin: '24px auto 0',
              padding: '12px 16px',
              background: '#fff0e9',
              border: '1px solid #f8c3b4',
              borderRadius: '8px',
              color: '#c95d43',
              fontSize: '13px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
            }}
          >
            <AlertCircle size={18} aria-hidden="true" />
            <span>{profileError}</span>
          </div>
        )}
        <LoginPage />
      </>
    )
  }

  if (profile && !['retailer', 'order_desk'].includes(profile.role)) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '16px',
          padding: '24px',
          textAlign: 'center',
        }}
      >
        <AlertCircle size={32} color="#c95d43" aria-hidden="true" />
        <h2>Unrecognized Role</h2>
        <p>Your user profile has role "{profile.role}" which does not have access to OrderFlow.</p>
        <button
          type="button"
          onClick={() => void logout()}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 16px',
            background: '#245c46',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          <LogOut size={16} aria-hidden="true" /> Sign out
        </button>
      </div>
    )
  }

  return <CataloguePage />
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}

export default App
