import {
    ArrowRight,
    ClipboardCheck,
    Cloud,
    CloudOff,
    LogOut,
    Minus,
    Plus,
    Search,
    ShoppingBag,
    Sparkles,
    X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import AiOrderCapture from './AiOrderCapture'
import './CataloguePage.css'
import { useAuth } from './context/useAuth'
import { apiFetch } from './lib/api'
import { OFFLINE_EVENT, reportNetworkFailure } from './networkStatus'
import { loadCartDraft, saveCartDraft } from './offlineCart'
import {
    OrderConfirmation,
    OrderDesk,
    OrderDetail,
    type DemoOrder,
} from './OrderDesk'

type CatalogueProduct = {
  sku: string
  name: string
  category: string
  brand?: string | null
  pack_label: string
  order_unit: string
  unit_price: string
  stock_quantity: number
  gst_status: string
  scheme_label: string | null
  image_url: string
}

type CatalogueResponse = {
  source: 'database'
  items: CatalogueProduct[]
}

type QuoteLine = {
  sku: string
  name: string
  order_unit: string
  requested_quantity: number
  paid_quantity: number
  free_quantity: number
  delivered_quantity: number
  unit_price: string
  subtotal: string
  discount: string
  free_value: string
  total: string
  scheme_label: string | null
}

type CartQuote = {
  source: 'database' | 'demo_fixture'
  lines: QuoteLine[]
  subtotal: string
  discount_total: string
  free_quantity: number
  free_value: string
  total: string
}

type CaptureCartItem = {
  sku: string
  quantity: number
}

const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

const ORDERED_CATEGORIES = [
  'All items',
  'Biscuits & Cookies',
  'Snacks & Namkeen',
  'Tea & Beverages',
  'Home Care',
  'Personal Care',
  'Chocolates & Confectionery',
  'Food Essentials',
  'Instant Foods',
] as const

function CataloguePage() {
  const { role, user, logout } = useAuth()
  const isOrderDesk = role === 'order_desk'

  const [products, setProducts] = useState<CatalogueProduct[]>([])
  const [source, setSource] = useState<CatalogueResponse['source'] | null>(null)
  const [loading, setLoading] = useState(!isOrderDesk)
  const [error, setError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [search, setSearch] = useState('')
  const [activeCategory, setActiveCategory] = useState('All items')
  const [cart, setCart] = useState<Record<string, number>>({})
  const [mobileCartOpen, setMobileCartOpen] = useState(false)
  const [quote, setQuote] = useState<CartQuote | null>(null)
  const [quoteLoading, setQuoteLoading] = useState(false)
  const [quoteError, setQuoteError] = useState(false)
  const [quoteSourceMismatch, setQuoteSourceMismatch] = useState(false)
  const [quoteReloadKey, setQuoteReloadKey] = useState(0)
  const [activeView, setActiveView] = useState<
    'catalogue' | 'ai_capture' | 'order_desk' | 'order_detail' | 'order_confirmation'
  >(isOrderDesk ? 'order_desk' : 'catalogue')
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null)
  const [submittedOrder, setSubmittedOrder] = useState<DemoOrder | null>(null)
  const [orderSubmitting, setOrderSubmitting] = useState(false)
  const [orderSubmitError, setOrderSubmitError] = useState('')
  const [cartReady, setCartReady] = useState(false)
  const [isOnline, setIsOnline] = useState(navigator.onLine)

  const currentView: 'catalogue' | 'ai_capture' | 'order_desk' | 'order_detail' | 'order_confirmation' =
    isOrderDesk && (activeView === 'catalogue' || activeView === 'ai_capture')
      ? 'order_desk'
      : activeView

  useEffect(() => {
    let active = true
    void loadCartDraft()
      .then((draft) => {
        if (active) setCart(draft)
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setCartReady(true)
      })

    return () => { active = false }
  }, [])

  useEffect(() => {
    if (cartReady) void saveCartDraft(cart).catch(() => undefined)
  }, [cart, cartReady])

  useEffect(() => {
    const handleOffline = () => {
      setIsOnline(false)
      setQuote(null)
      setQuoteError(false)
      setQuoteLoading(false)
    }
    const handleOnline = () => {
      setIsOnline(true)
      setError(false)
      setReloadKey((key) => key + 1)
      if (Object.values(cart).some((quantity) => quantity > 0)) {
        setQuote(null)
        setQuoteError(false)
        setQuoteLoading(true)
      }
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    window.addEventListener(OFFLINE_EVENT, handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener(OFFLINE_EVENT, handleOffline)
    }
  }, [cart])

  useEffect(() => {
    if (isOrderDesk) return

    const controller = new AbortController()

    async function loadCatalogue() {
      setLoading(true)
      setError(false)

      try {
        const payload = await apiFetch<CatalogueResponse>('/catalogue', {
          signal: controller.signal,
        })
        setProducts(payload.items)
        setSource(payload.source)
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(true)
          reportNetworkFailure(loadError)
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    void loadCatalogue()
    return () => controller.abort()
  }, [isOrderDesk, reloadKey])

  useEffect(() => {
    if (isOrderDesk) return

    const items = Object.entries(cart)
      .filter(([, quantity]) => quantity > 0)
      .map(([sku, quantity]) => ({ sku, quantity }))

    if (items.length === 0 || !isOnline || !source) return

    const controller = new AbortController()

    async function loadQuote() {
      try {
        const nextQuote = await apiFetch<CartQuote>('/cart/quote', {
          method: 'POST',
          body: JSON.stringify({ items }),
          signal: controller.signal,
        })
        if (nextQuote.source !== source) {
          setQuote(null)
          setQuoteSourceMismatch(true)
          return
        }
        setQuoteSourceMismatch(false)
        setQuote(nextQuote)
      } catch (quoteRequestError) {
        if (!controller.signal.aborted) {
          setQuoteError(true)
          reportNetworkFailure(quoteRequestError)
        }
      } finally {
        if (!controller.signal.aborted) setQuoteLoading(false)
      }
    }

    void loadQuote()
    return () => controller.abort()
  }, [cart, isOnline, isOrderDesk, quoteReloadKey, source])

  const categories = [
    ...ORDERED_CATEGORIES,
    ...Array.from(new Set(products.map((product) => product.category))).filter(
      (category) => !ORDERED_CATEGORIES.includes(category as (typeof ORDERED_CATEGORIES)[number])
    ),
  ]
  const filteredProducts = products.filter((product) => {
    const matchesCategory =
      activeCategory === 'All items' || product.category === activeCategory
    const query = search.trim().toLowerCase()
    const matchesSearch =
      !query ||
      `${product.name} ${product.sku} ${product.pack_label} ${product.brand ?? ''} ${product.category}`
        .toLowerCase()
        .includes(query)

    return matchesCategory && matchesSearch
  })
  const cartCount = Object.values(cart).reduce((total, quantity) => total + quantity, 0)
  const cartProducts = products.filter((product) => (cart[product.sku] ?? 0) > 0)
  const quoteLinesBySku = new Map((quote?.lines ?? []).map((line) => [line.sku, line]))
  const quoteTotalText = !isOnline
    ? 'Offline'
    : quoteSourceMismatch
      ? 'Unavailable'
      : quoteLoading
        ? 'Calculating…'
        : quoteError
          ? 'Unavailable'
          : cartCount > 0 && !quote
            ? 'Calculating…'
            : currency.format(Number(quote?.total ?? 0))

  function changeQuantity(sku: string, delta: number) {
    if (!cartReady) return
    const nextCart = { ...cart }
    const nextQuantity = (nextCart[sku] ?? 0) + delta
    if (nextQuantity <= 0) delete nextCart[sku]
    else nextCart[sku] = nextQuantity

    const hasItems = Object.values(nextCart).some((quantity) => quantity > 0)
    setCart(nextCart)
    setQuote(null)
    setQuoteError(false)
    setQuoteSourceMismatch(false)
    setQuoteLoading(hasItems && isOnline)
  }

  function retryQuote() {
    if (!isOnline || quoteSourceMismatch) return
    setQuote(null)
    setQuoteError(false)
    setQuoteSourceMismatch(false)
    setQuoteLoading(true)
    setQuoteReloadKey((key) => key + 1)
  }

  async function submitCart() {
    if (
      !isOnline ||
      !quote ||
      quoteLoading ||
      quoteError ||
      quoteSourceMismatch ||
      cartCount === 0 ||
      orderSubmitting
    ) return

    setOrderSubmitting(true)
    setOrderSubmitError('')
    try {
      const order = await apiFetch<DemoOrder>('/orders', {
        method: 'POST',
        body: JSON.stringify({
          items: Object.entries(cart).map(([sku, quantity]) => ({ sku, quantity })),
        }),
      })
      setSubmittedOrder(order)
      setCart({})
      setQuote(null)
      setQuoteLoading(false)
      setQuoteError(false)
      setQuoteSourceMismatch(false)
      setMobileCartOpen(false)
      setActiveView('order_confirmation')
    } catch (submitError) {
      reportNetworkFailure(submitError)
      setOrderSubmitError(
        submitError instanceof Error ? submitError.message : 'Could not submit this order.',
      )
    } finally {
      setOrderSubmitting(false)
    }
  }

  function addCaptureItems(items: CaptureCartItem[]) {
    const nextCart = { ...cart }
    for (const item of items) {
      nextCart[item.sku] = (nextCart[item.sku] ?? 0) + item.quantity
    }
    setCart(nextCart)
    setQuote(null)
    setQuoteError(false)
    setQuoteSourceMismatch(false)
    setQuoteLoading(isOnline)
    setActiveView('catalogue')
    setMobileCartOpen(true)
  }

  return (
    <div className="storefront">
      <header className="topbar">
        <a className="brand" href={isOrderDesk ? "#orders" : "#catalogue"} aria-label={isOrderDesk ? "OrderFlow order desk" : "OrderFlow catalogue"}>
          <span className="brand-mark" aria-hidden="true">O</span>
          <span className="brand-name">OrderFlow</span>
          <span className="brand-divider" />
          <span className="brand-caption">{isOrderDesk ? 'ORDER DESK PORTAL' : 'RETAILER PORTAL'}</span>
        </a>

        {!isOrderDesk && (
          <div className="topbar-nav" role="tablist" aria-label="Retailer workspace">
            <button
              className={currentView === 'catalogue' ? 'topbar-tab active' : 'topbar-tab'}
              type="button"
              role="tab"
              aria-selected={currentView === 'catalogue'}
              onClick={() => setActiveView('catalogue')}
            >
              <ShoppingBag size={15} aria-hidden="true" /> Catalogue
            </button>
            <button
              className={currentView === 'ai_capture' ? 'topbar-tab active' : 'topbar-tab'}
              type="button"
              role="tab"
              aria-selected={currentView === 'ai_capture'}
              onClick={() => setActiveView('ai_capture')}
            >
              <Sparkles size={15} aria-hidden="true" /> AI order
            </button>
            <button
              className={['order_desk', 'order_detail'].includes(currentView) ? 'topbar-tab active' : 'topbar-tab'}
              type="button"
              role="tab"
              aria-selected={['order_desk', 'order_detail'].includes(currentView)}
              onClick={() => setActiveView('order_desk')}
            >
              <ClipboardCheck size={15} aria-hidden="true" /> My orders
            </button>
          </div>
        )}

        <div className="topbar-meta">
          <span className={isOrderDesk ? 'account-dot order-desk' : 'account-dot'}>
            {isOrderDesk ? 'OD' : 'R'}
          </span>
          <span>{user?.email ?? (isOrderDesk ? 'Order Desk user' : 'Retailer account')}</span>
        </div>

        <button
          className="topbar-logout-btn"
          type="button"
          onClick={() => void logout()}
          title="Sign out of OrderFlow"
        >
          <LogOut size={14} aria-hidden="true" />
          <span>Sign out</span>
        </button>

        <div className={isOnline ? 'connection-indicator online' : 'connection-indicator offline'} role="status" aria-live="polite">
          {isOnline ? <Cloud size={15} aria-hidden="true" /> : <CloudOff size={15} aria-hidden="true" />}
          {isOnline ? 'Online' : 'Offline'}
        </div>

        {!isOrderDesk && (
          <button
            className="top-cart-button"
            type="button"
            onClick={() => { setActiveView('catalogue'); setMobileCartOpen(true) }}
            aria-label={`Open cart, ${cartCount} items`}
          >
            <ShoppingBag size={18} aria-hidden="true" />
            <span className="top-cart-label">Cart</span>
            <span className="cart-count">{cartCount}</span>
          </button>
        )}
      </header>

      <main className="page-wrap" id="catalogue">
        {!isOnline && (
          <div className="offline-banner" role="status">
            <CloudOff size={16} aria-hidden="true" />
            <span>Offline draft saved locally. Quotes, AI capture, and order submission need a connection.</span>
          </div>
        )}
        {currentView === 'catalogue' ? (
          <>
        <div className="page-heading">
          <div>
            <div className="breadcrumbs"><span>Retailer</span><span>/</span><b>Catalogue</b></div>
            <h1>Catalogue</h1>
            <p className="page-subtitle">Find the essentials for your next order.</p>
          </div>
          {source === 'database' && (
            <div className="demo-mark"><span /> Seeded database</div>
          )}
        </div>

        <div className="fixture-note" role="note">
          <span className="fixture-note-label">PREVIEW DATA</span>
          <span>Prices and stock are illustrative. GST rates are not configured.</span>
        </div>

        <div className="catalogue-layout">
          <section className="catalogue-main" aria-label="Product catalogue">
            <div className="catalogue-tools">
              <label className="search-box">
                <Search size={18} aria-hidden="true" />
                <span className="sr-only">Search catalogue</span>
                <input
                  type="search"
                  placeholder="Search products or SKU"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <kbd>/</kbd>
              </label>
              <div className="result-count" aria-live="polite">
                {loading ? 'Loading catalogue' : `${filteredProducts.length} items`}
              </div>
            </div>

            <div className="category-tabs" role="group" aria-label="Filter by category">
              {categories.map((category) => (
                <button
                  className={activeCategory === category ? 'category-tab active' : 'category-tab'}
                  type="button"
                  key={category}
                  aria-pressed={activeCategory === category}
                  onClick={() => setActiveCategory(category)}
                >
                  {category}
                </button>
              ))}
            </div>

            {error && (
              <div className="catalogue-state" role="alert">
                <div className="state-icon">!</div>
                <h2>Catalogue unavailable</h2>
                <p>Could not reach the catalogue service.</p>
                <button type="button" className="text-button" onClick={() => setReloadKey((key) => key + 1)}>
                  Try again
                </button>
              </div>
            )}

            {loading && !error && (
              <div className="product-grid" aria-label="Loading products" aria-busy="true">
                {[0, 1, 2].map((item) => <div className="product-skeleton" key={item} />)}
              </div>
            )}

            {!loading && !error && filteredProducts.length === 0 && (
              <div className="catalogue-state">
                <div className="state-icon"><Search size={20} aria-hidden="true" /></div>
                <h2>No matching products</h2>
                <p>Try a different search or category.</p>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => { setSearch(''); setActiveCategory('All items') }}
                >
                  Clear filters
                </button>
              </div>
            )}

            {!loading && !error && filteredProducts.length > 0 && (
              <div className="product-grid">
                {filteredProducts.map((product, index) => {
                  const quantity = cart[product.sku] ?? 0
                  return (
                    <article className="product-card" key={product.sku} style={{ animationDelay: `${index * 55}ms` }}>
                      <div className="product-photo">
                        <img src={product.image_url} alt={product.name} loading="lazy" />
                        <span className="photo-category">{product.category}</span>
                        <span className={`stock-indicator ${product.stock_quantity <= 0 ? 'out-of-stock' : ''}`}>
                          <span /> {product.stock_quantity <= 0 ? 'Out of stock' : `${product.stock_quantity} cases`}
                        </span>
                      </div>
                      <div className="product-content">
                        <div className="product-topline">
                          <span className="product-sku">{product.sku}</span>
                          {product.brand && <span className="product-brand-tag">{product.brand}</span>}
                          <span className="gst-label">GST · {product.gst_status}</span>
                        </div>
                        <h2>{product.name}</h2>
                        <p className="pack-detail">{product.pack_label} · sold by {product.order_unit}</p>
                        {product.scheme_label ? (
                          <div className="scheme-label"><span className="scheme-symbol">%</span>{product.scheme_label}</div>
                        ) : (
                          <div className="no-scheme">No scheme listed</div>
                        )}
                        <div className="product-buy-row">
                          <div className="price-block">
                            <strong>{currency.format(Number(product.unit_price))}</strong>
                            <span>per {product.order_unit}</span>
                          </div>
                          {product.stock_quantity <= 0 ? (
                            <button
                              className="add-button out-of-stock"
                              type="button"
                              disabled
                              aria-label={`${product.name} is out of stock`}
                            >
                              Out of stock
                            </button>
                          ) : quantity === 0 ? (
                            <button
                              className="add-button"
                              type="button"
                              disabled={!cartReady}
                              onClick={() => changeQuantity(product.sku, 1)}
                              aria-label={`Add ${product.name} to cart`}
                            >
                              <Plus size={16} aria-hidden="true" /> Add
                            </button>
                          ) : (
                            <div className="quantity-control" aria-label={`${quantity} cases of ${product.name}`}>
                              <button type="button" disabled={!cartReady} onClick={() => changeQuantity(product.sku, -1)} aria-label={`Remove one ${product.name}`}>
                                <Minus size={15} aria-hidden="true" />
                              </button>
                              <span aria-live="polite">{quantity}</span>
                              <button
                                type="button"
                                disabled={!cartReady || quantity >= product.stock_quantity}
                                onClick={() => changeQuantity(product.sku, 1)}
                                aria-label={`Add one ${product.name}`}
                              >
                                <Plus size={15} aria-hidden="true" />
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </section>

          {mobileCartOpen && <button className="cart-backdrop" type="button" aria-label="Close cart" onClick={() => setMobileCartOpen(false)} />}
          <aside className={mobileCartOpen ? 'cart-panel mobile-open' : 'cart-panel'} aria-label="Shopping cart">
            <div className="cart-heading">
              <div>
                <p className="cart-overline">YOUR ORDER</p>
                <h2>Cart <span>{cartCount}</span></h2>
              </div>
              <button className="cart-close" type="button" onClick={() => setMobileCartOpen(false)} aria-label="Close cart">
                <X size={19} aria-hidden="true" />
              </button>
            </div>

            {cartProducts.length === 0 ? (
              <div className="cart-empty">
                <div className="empty-bag"><ShoppingBag size={22} aria-hidden="true" /></div>
                <h3>Your cart is empty</h3>
                <p>Add products to start building an order.</p>
              </div>
            ) : (
              <div className="cart-lines">
                {cartProducts.map((product) => (
                  <div className="cart-line" key={product.sku}>
                    <div className="cart-line-copy">
                      <strong>{product.name}</strong>
                      <span>{currency.format(Number(product.unit_price))} / {product.order_unit}</span>
                      {quoteLinesBySku.get(product.sku)?.free_quantity ? (
                        <span className="cart-line-bonus">
                          {quoteLinesBySku.get(product.sku)?.paid_quantity} paid +{' '}
                          {quoteLinesBySku.get(product.sku)?.free_quantity} free
                        </span>
                      ) : null}
                    </div>
                    <div className="cart-line-controls">
                      <button type="button" onClick={() => changeQuantity(product.sku, -1)} aria-label={`Remove one ${product.name}`}>
                        <Minus size={13} aria-hidden="true" />
                      </button>
                      <span>{cart[product.sku]}</span>
                      <button type="button" onClick={() => changeQuantity(product.sku, 1)} aria-label={`Add one ${product.name}`}>
                        <Plus size={13} aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="cart-footer">
              <div className="subtotal-row">
                <span>Subtotal</span>
                <strong>
                  {!isOnline
                    ? 'Unavailable offline'
                    : quoteSourceMismatch
                      ? 'Pricing needs database integration'
                    : quoteLoading
                      ? 'Calculating…'
                      : quoteError
                        ? 'Unavailable'
                        : currency.format(Number(quote?.subtotal ?? 0))}
                </strong>
              </div>
              {quote && Number(quote.discount_total) > 0 && (
                <div className="cart-adjustment-row">
                  <span>Scheme discount</span>
                  <strong>−{currency.format(Number(quote.discount_total))}</strong>
                </div>
              )}
              {quote && quote.free_quantity > 0 && (
                <div className="cart-adjustment-row">
                  <span>Free cases</span>
                  <strong>{quote.free_quantity}</strong>
                </div>
              )}
              <div className="cart-grand-total">
                <span>Total before GST</span>
                <strong>{quoteTotalText}</strong>
              </div>
              <p>
                {!isOnline
                  ? 'Cart draft is saved on this device. Reconnect for server pricing and order submission.'
                  : quoteSourceMismatch
                    ? 'Catalogue prices are from PostgreSQL, but cart quotes still use demo pricing. Submission is disabled until both use the same database data.'
                  : quoteError
                    ? 'Could not get a server quote. Your cart quantities are unchanged.'
                    : 'Server-calculated. Demo prices only; GST is not included.'}
              </p>
              {quoteError && !quoteSourceMismatch && (
                <button
                  className="text-button quote-retry"
                  type="button"
                  onClick={retryQuote}
                >
                  Retry quote
                </button>
              )}
              {orderSubmitError && <p className="order-submit-error" role="alert">{orderSubmitError}</p>}
              {cartCount > 0 && (
                <button
                  className="submit-order-button"
                  type="button"
                  disabled={
                    !isOnline ||
                    !quote ||
                    quoteLoading ||
                    quoteError ||
                    quoteSourceMismatch ||
                    orderSubmitting
                  }
                  onClick={submitCart}
                >
                  {orderSubmitting ? 'Submitting…' : 'Submit for review'}
                  {!orderSubmitting && <ArrowRight size={15} aria-hidden="true" />}
                </button>
              )}
              <button className="continue-browse-button" type="button" onClick={() => setMobileCartOpen(false)}>
                Continue browsing
              </button>
            </div>
          </aside>
        </div>
          </>
        ) : currentView === 'ai_capture' ? (
          <AiOrderCapture
            onBackToCatalogue={() => setActiveView('catalogue')}
            onAddToCart={addCaptureItems}
          />
        ) : currentView === 'order_desk' ? (
          <OrderDesk onOpenOrder={(orderId) => {
            setSelectedOrderId(orderId)
            setActiveView('order_detail')
          }} />
        ) : currentView === 'order_detail' && selectedOrderId ? (
          <OrderDetail
            orderId={selectedOrderId}
            onBack={() => setActiveView('order_desk')}
          />
        ) : currentView === 'order_confirmation' && submittedOrder ? (
          <OrderConfirmation
            order={submittedOrder}
            onOpenOrder={() => {
              setSelectedOrderId(submittedOrder.id)
              setActiveView('order_detail')
            }}
            onOpenDesk={() => setActiveView('order_desk')}
            onNewOrder={() => setActiveView('catalogue')}
          />
        ) : (
          <OrderDesk onOpenOrder={(orderId) => {
            setSelectedOrderId(orderId)
            setActiveView('order_detail')
          }} />
        )}
      </main>

      {currentView === 'catalogue' && !isOrderDesk && (
        <button className="mobile-cart-dock" type="button" onClick={() => setMobileCartOpen(true)}>
          <span><ShoppingBag size={18} aria-hidden="true" /> Cart <b>{cartCount}</b></span>
          <strong>{quoteTotalText}</strong>
        </button>
      )}
    </div>
  )
}

export default CataloguePage