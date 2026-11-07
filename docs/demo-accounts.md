# Demo Accounts & Authentication Setup

## Architecture

OrderFlow uses **Supabase Auth** for identity management (email/password or OTP) and **PostgreSQL** for application roles and retailer tenancy isolation.

### Linking Supabase Users to OrderFlow Profiles

When a user signs in via Supabase Auth:
1. Supabase issues a verified JWT containing the user's UUID in the `sub` claim.
2. The frontend sends this JWT as `Authorization: Bearer <access_token>` to `GET /auth/me`.
3. The FastAPI backend verifies the asymmetric JWT against Supabase's JWKS (`/.well-known/jwks.json`).
4. The backend queries the `users` table where `users.auth_subject = token.sub` and `users.is_active = true`.
5. The user's role (`retailer` or `order_desk`) and `retailer_id` are returned to the client.

### Step-by-Step Account Setup

1. **Create users in Supabase Dashboard**:
   - Navigate to **Authentication > Users** in your Supabase project dashboard.
   - Click **Add User > Create User** (e.g., `retailer@example.com` and `orderdesk@example.com`).
   - Copy each created user's **User UID** (a UUID like `e3b0c442-98fc-1c14-9afb-4c7fa430b832`).

2. **Link users in PostgreSQL database**:
   Connect to your PostgreSQL database and insert or update the `users` table:

   ```sql
   -- 1. Ensure the demo retailer exists
   INSERT INTO retailers (id, name, external_ref, is_active, created_at)
   VALUES ('a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d', 'Demo Retailer Store', 'DEMO-RETAILER', true, NOW())
   ON CONFLICT (external_ref) DO NOTHING;

   -- 2. Link Retailer user (replace <SUPABASE_RETAILER_UID> with actual UUID from Supabase)
   INSERT INTO users (id, auth_subject, role, email, retailer_id, is_active, created_at)
   VALUES (
     gen_random_uuid(),
     '<SUPABASE_RETAILER_UID>',
     'retailer',
     'retailer@example.com',
     (SELECT id FROM retailers WHERE external_ref = 'DEMO-RETAILER'),
     true,
     NOW()
   )
   ON CONFLICT (auth_subject) DO UPDATE
   SET role = 'retailer', retailer_id = (SELECT id FROM retailers WHERE external_ref = 'DEMO-RETAILER'), is_active = true;

   -- 3. Link Order Desk user (replace <SUPABASE_ORDERDESK_UID> with actual UUID from Supabase)
   INSERT INTO users (id, auth_subject, role, email, retailer_id, is_active, created_at)
   VALUES (
     gen_random_uuid(),
     '<SUPABASE_ORDERDESK_UID>',
     'order_desk',
     'orderdesk@example.com',
     NULL,
     true,
     NOW()
   )
   ON CONFLICT (auth_subject) DO UPDATE
   SET role = 'order_desk', retailer_id = NULL, is_active = true;
   ```

3. **Configure Environment Variables**:
   - In root `.env`:
     ```env
     VITE_API_BASE_URL=/api
     VITE_SUPABASE_URL=https://<your-project-ref>.supabase.co
     VITE_SUPABASE_ANON_KEY=<your-anon-key>
     ```
   - In `backend/.env`:
     ```env
     DATABASE_URL=postgresql+psycopg://postgres:<password>@localhost:5432/orderflow
     SUPABASE_URL=https://<your-project-ref>.supabase.co
     ORDERFLOW_CORS_ORIGINS=http://localhost:5173
     ```

4. **Test Logins**:
   - Sign in as `retailer@example.com`: Verified access to Catalogue, AI order capture, Cart quote, and submitted orders.
   - Sign in as `orderdesk@example.com`: Verified access to Order Desk dashboard, review queue, Hold/Release actions, Approval/Rejection, and Tally CSV download.
