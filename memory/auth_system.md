---
name: ProspectIQ Auth System
description: Auth architecture — Supabase JWT (not Auth0), WorkspaceMiddleware, what's missing vs Digitillis
type: project
---

ProspectIQ has a complete, functional auth system that pre-existed the billing SDK work. Pattern mirrors Digitillis but uses Supabase Auth instead of Auth0.

## What exists and works

- **Login**: `dashboard/app/login/page.tsx` — email/password via `supabase.auth.signInWithPassword()`
- **Signup**: `dashboard/app/signup/page.tsx` → `POST /api/auth/signup` — creates workspace + owner member row
- **Invite**: `dashboard/app/invite/[token]/page.tsx` — token-based invite flow
- **Route protection**: `dashboard/middleware.ts` — SSR session check, redirects unauthenticated → `/login`
- **Backend JWT**: `backend/app/core/auth.py` — HS256 decode via `SUPABASE_JWT_SECRET`, raises 401 on invalid/expired
- **API key auth**: `X-API-Key` header, SHA-256 hashed, validated against `workspace_api_keys` table
- **WorkspaceMiddleware**: populates `WorkspaceContext` ContextVar per request — billing router reads from this
- **Session storage**: localStorage (Supabase client, `persistSession: true`, key: `"prospectiq-auth"`)

## How billing connects
`_get_workspace_id()` in `backend/app/api/routes/billing.py` reads from `WorkspaceContext`, which WorkspaceMiddleware populates from the Supabase JWT. The chain is: JWT → WorkspaceMiddleware → WorkspaceContext → billing router.

## What's missing vs Digitillis
- No `AUTH_DEMO_MODE` fallback
- No Auth0 / enterprise SSO
- No subdomain-based tier routing
- Password reset flow not built (login + signup exist, reset missing)
- ~60% of data routes (companies, approvals, analytics) rely on implicit WorkspaceMiddleware context rather than explicit `require_workspace_member()` dependency — returns 400 not 401 if auth header missing

**Why:** ProspectIQ uses Supabase natively — simpler and appropriate for this product. Auth0 is not needed.
