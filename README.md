# OrderFlow

Smart ordering for distributors & retailers.

OrderFlow is a work-in-progress ordering platform. It currently includes a React, TypeScript, Vite, and Tailwind retailer catalogue, AI-assisted order capture, and an installable offline shell backed by FastAPI. Product workflows and business rules are tracked in [the TDD](docs/TDD.md).

## Requirements

- Node.js 20.19+ or 22.12+
- Python 3.12+
- PostgreSQL (not connected yet)

## Run the frontend

```powershell
npm install
npm run dev
```

The Vite development server runs at `http://localhost:5173`. The service worker is intentionally enabled only in production builds.

## Test the installable/offline build

```powershell
npm run build
npm run preview -- --host localhost
```

Vite serves the production preview at `http://localhost:4173`. The preview proxy routes `/api` to the local FastAPI service, matching the same-origin deployment assumption.

## Run the API

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --env-file .env
```

The API health check is available at `http://localhost:8000/health`.

The catalogue is available at `http://localhost:8000/catalogue` and reads active products and retailer prices from PostgreSQL for retailer ref `DEMO-RETAILER`. Stock values (`340`, `85`, `0`), category, case unit, and image are configured by SKU because those columns are not in the current `Product` model. GST is not configured.

`POST /cart/quote` still uses demo fixture prices and schemes. The frontend detects the source mismatch and blocks order submission instead of mixing the PostgreSQL catalogue with demo totals. Connect the quote engine to the same database products, retailer prices, and schemes before enabling checkout.

The AI capture screen posts raw message text to `POST /ai/order-captures`. Without `GEMINI_API_KEY`, the API uses a limited deterministic demo parser for the three example products. It is not a general language model. Captures always require a person to confirm each line; the endpoint never creates or places an order. Unclear units are asked about, and piece quantities cannot enter the case-based cart until pack conversion is defined.

Submitting the cart posts only SKU and quantity to `POST /orders`; the API recalculates the quote and creates a `pending_review` demo order. The Orders tab supports manual review, hold/release, approval, and rejection. Approved orders expose `GET /orders/{id}/tally.csv`; its generic column mapping is a starter and must be matched to the target Tally installation. Demo orders live in API process memory and disappear when it restarts.

## Configuration

The local API currently loads PostgreSQL settings from the ignored `backend/.env`; do not commit that file. Production still needs a managed database and deployment environment variables. The API verifies Supabase asymmetric JWTs and looks up the corresponding active OrderFlow user and role; configure `SUPABASE_URL` and `DATABASE_URL` before using `/auth/me`. To enable Gemini parsing, set `GEMINI_API_KEY` and `GEMINI_MODEL`; requests then also require a valid Supabase bearer token and active OrderFlow profile.

## Offline behavior

The PWA caches the app shell, public product images (up to 60 entries), and successful `GET /api/catalogue` responses. IndexedDB stores a local cart draft containing SKU and quantity only. Price quotes, AI capture, order submission, desk actions, and CSV export require a live API connection and are never queued offline. The cached catalogue is illustrative and may be stale. In production, route `/api` to FastAPI on the same origin, or set `VITE_API_BASE_URL` to the API host and configure its CORS allowlist.

## Checks

```powershell
npm run build
npm run lint
cd backend
pytest
```

## Project status

The retailer catalogue reads seeded PostgreSQL products and retailer prices; the UI, AI capture/review previews, schema models, Supabase JWT verification, backend demo scheme calculation, structured Gemini adapter, demo order review lifecycle, approved-only CSV download, and installable offline shell/cart draft are implemented. Scheme rules and cart quotes are not yet database-backed, so checkout is blocked on source mismatch. Supabase OTP delivery and its frontend flow, database migrations for deployment, capture/order persistence, production role enforcement, offline conflict/sync policy, confirmed Tally mapping, and deployment remain outstanding.

## Submission prep

See [deployment.md](docs/deployment.md) for provider setup and [demo-accounts.md](docs/demo-accounts.md) for the current account limitations. Create the source ZIP with:

```powershell
.\scripts\package-submission.ps1
```

The script excludes dependencies, virtual environments, caches, build output, and environment secrets; it stops if the archive is 25 MB or larger.