# Deployment Guide

## Readiness

The current build is a demonstration, not production-ready. PostgreSQL is not provisioned, there are no Alembic migrations, OTP UI is not implemented, order records are in-memory, role enforcement is not applied to order-desk routes, catalogue/pricing data is illustrative, and the Tally CSV mapping is unconfirmed. Do not deploy it with real customer data until these gaps are closed.

## Local production preview

Use the development API and the built frontend to exercise the production service worker:

```powershell
# Terminal 1
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --env-file .env

# Terminal 2, from the repository root
npm run build
npm run preview -- --host localhost
```

The frontend preview is at `http://localhost:4173`; FastAPI is at `http://localhost:8000`. Vite's preview proxy forwards `/api/*` to FastAPI.

## Frontend: Vercel

- Root directory: repository root.
- Install command: `npm ci`.
- Build command: `npm run build`.
- Output directory: `dist`.
- Set `VITE_API_BASE_URL=/api`.
- Configure a same-origin rewrite from `/api/:path*` to the FastAPI service, stripping the `/api` prefix. Vercel configuration is intentionally not committed because the backend hostname is not known.

The service worker is registered only in production builds. After deployment, test installability and offline behavior over HTTPS. The cache includes the app shell, public images, and successful catalogue GET responses; order mutations are never cached or queued.

## Backend: Render or Railway

- Root directory: `backend`.
- Build/install command: `python -m pip install .`.
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (adapt variable syntax to the provider).
- Configure a health check at `/health`.
- Set `DATABASE_URL`, `SUPABASE_URL`, `ORDERFLOW_CORS_ORIGINS`, `GEMINI_API_KEY`, and `GEMINI_MODEL` in the provider's secret/environment settings as needed.
- Use a managed PostgreSQL database and apply reviewed migrations before enabling persistence. No migrations are currently included.

Never commit `.env` files or put service keys in `VITE_*` variables. `VITE_API_BASE_URL` is public browser configuration, not a secret.

## Supabase

Create the project and configure the database/Auth provider before deployment. The API can verify asymmetric ES256/RS256 JWTs and looks up `users.auth_subject`, but the frontend OTP flow, user provisioning, roles/permissions, and database migrations are not implemented. Do not enable the order-desk endpoints for production until those checks are enforced server-side.

## Release checks

```powershell
npm ci
npm run lint
npm run build
cd backend
python -m pip install -e ".[dev]"
pytest
```

Then verify the deployed `/health`, catalogue proxy, quote API, auth boundary, approved-order CSV format, and service-worker offline cache. Confirm pricing, stock, GST, schemes, credit policy, order states, and Tally column mapping with the client before using production data.