# OrderFlow Technical Design Document

## Purpose

Build an ordering product for distributors and retailers, with a retailer purchase flow, an AI-assisted order capture flow, an order review desk, and Tally CSV export.

## Stated requirements

- Product name: OrderFlow. Tagline: Smart ordering for distributors & retailers.
- Core screens: Login/OTP, Retailer Dashboard, Catalogue, Cart & Order Confirmation, AI Order Capture, AI Review/SKU Matching, Order Desk, and Order Detail/Tally Export.
- Catalogue presentation includes price, stock, scheme, and GST indication.
- Scheme calculations run on the backend, not in the client.
- Schemes include buy-X-get-Y and quantity-threshold discounts. The examples in the project brief are illustrative; exact production values must come from configured scheme data.
- AI order capture returns candidate SKU matches, quantities, confidence, and alternatives. Orders require human confirmation before placement.
- Unclear units must be asked about, not guessed.
- A retailer-specific SKU alias may be saved after desk confirmation.
- The order desk supports review and approval, with credit-hold handling to be defined.
- Order detail supports Tally CSV export.
- Proposed stack: React, TypeScript, Vite, Tailwind CSS, FastAPI, PostgreSQL, Supabase Auth/OTP, Gemini, PWA with IndexedDB, Vercel, Render or Railway, and pytest/Vitest.

## Assumptions

- Python 3.12 or newer is the backend runtime target. The current local runtime is Python 3.13.1.
- Local development uses a frontend at `localhost:5173` and an API at `localhost:8000`; CORS defaults are development-only.
- Local PostgreSQL is configured through the ignored `backend/.env`; no database credentials are tracked. A production database/provider is still to be selected and provisioned.
- Supabase Auth is the selected identity provider. The API accepts asymmetric ES256 or RS256 Supabase JWTs from the project's JWKS endpoint; the Supabase project must use one of these signing algorithms.
- Supabase user identity is stored as `users.auth_subject`; application roles are assigned in the OrderFlow database and are not trusted from editable user metadata.
- Gemini uses the Google GenAI Interactions API with structured JSON output and defaults to `gemini-3.8-flash`; without a Gemini key, local development uses a clearly labeled deterministic parser for the three brief examples.
- No external service credentials are present. OTP delivery, live PostgreSQL access, Gemini calls, and deployment remain unconfigured until credentials and provider setup are supplied.
- UUID primary keys, exact-case unique retailer aliases, JSON scheme definitions, and decimal quantities are implementation assumptions. Role names, workflow states, and business validation rules remain open.
- Demo catalogue data and demo accounts, if added, will be labeled as fixtures and not treated as client-provided business facts.
- Scheme rounding uses decimal half-up to two currency places. The demo buy-X-get-Y rule repeats once per complete threshold, and the discount threshold applies inclusively; these behaviors follow the supplied examples.
- The order-desk demo stores orders in process memory because PostgreSQL is not provisioned. Demo states are `pending_review`, `credit_hold`, `approved`, and `rejected`; placing on hold is a manual action, with no inferred credit-limit policy.
- The starter Tally CSV uses generic order-line columns and is downloadable only after approval. Target Tally column mapping is still to be confirmed.
- IndexedDB stores only the cart's SKU-to-quantity draft. The service worker caches static assets, product images, and successful read-only catalogue responses; it never queues mutations or offline orders.
- The service worker is registered only in production builds. Vite dev and preview proxy `/api` to local FastAPI; deployment must provide an equivalent same-origin proxy or set `VITE_API_BASE_URL` and configure CORS.
- The current `Product` schema has no stock, category, order-unit, image, or product-to-scheme columns. Catalogue stock (`340`, `85`, `0`) and display metadata are mapped by SKU; legacy seeded schemes map by exact name/type, with optional `definition.sku` preferred for future scheme records.
- `/catalogue` now reads active products and retailer-specific prices from PostgreSQL for `DEMO-RETAILER`. `/cart/quote` remains a demo-fixture calculation; the frontend blocks checkout when response sources differ.

## Decisions still needed

- Define roles and permissions for retailers, salesmen, and distributor desk users.
- Define source-of-truth and refresh behavior for prices, stock, retailer-specific prices, and GST.
- Define production scheme stacking and effective dates, and confirm whether the demo threshold semantics apply to every configured scheme.
- Define order states, credit-limit policy, and who can approve or release a credit hold.
- Define how AI quantities map to pack sizes and when confidence requires manual review; the explicit rule is to ask when the unit is unclear.
- Confirm the Tally CSV column mapping and encoding expected by the target installation.
- Confirm production order-state transitions, authorization for desk actions, credit-hold policy, and whether export must be restricted to approved orders.
- Confirm offline data retention age and synchronization/conflict behavior for salesman mode.
- Confirm deployment providers and environment-variable ownership.

## Current implementation

The repository provides the frontend toolchain, SQLAlchemy models for the stated core entities, a lazy database-session dependency, Supabase JWT verification with database-backed role lookup, an authenticated profile endpoint, PostgreSQL-backed `/catalogue` reads for seeded products and retailer prices, demo `/cart/quote` and `/orders` endpoints, `/ai/order-captures` with structured Gemini parsing or a labeled local demo parser, and a production-only installable PWA shell. Catalogue stock and display metadata are SKU mappings because those fields do not exist in `Product`; scheme mapping uses exact legacy seed names/types or an optional `definition.sku`. The frontend blocks order submission when DB catalogue and demo quote sources differ. Captures require review and never create orders; ambiguous units are returned as clarification questions. Orders are persisted in PostgreSQL and exported as generic CSV only when approved. and exported as generic CSV only when approved. Offline support caches read-only catalogue data and stores cart drafts in IndexedDB; mutations remain online-only. GST remains unconfigured. Persisted AI captures, SKU alias learning, OTP UI/flow, formal database migrations, GST configuration, and offline order synchronization remain outstanding.