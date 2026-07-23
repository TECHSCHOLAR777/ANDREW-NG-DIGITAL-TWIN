-- 016_auth_users.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Real accounts, mapped to the existing tenant/memory model.
--
-- The app has always identified a person by a random browser tenant id. That
-- gives per-browser continuity but nothing that survives a cleared cache or
-- follows a person to another device. This adds credential accounts that each
-- own exactly one tenant, so a signed-in user keeps one memory graph everywhere.
--
-- WHY ONE TENANT PER USER
-- Retrieval, the context graph, sessions, and the memory policy are already
-- scoped by tenant_id. Binding an account to a single tenant reuses all of that
-- isolation untouched: authentication decides WHICH tenant a request runs as,
-- and every existing tenant-scoped query keeps working.
--
-- ANONYMOUS MERGE
-- A guest who signs up can adopt the anonymous tenant their browser was already
-- using, so the context built before signing up is not thrown away. The signup
-- path passes that tenant id and it becomes the account's tenant when it exists
-- and is not already claimed.
--
-- Auth.js runs in the Next.js layer with JWT sessions, so no adapter tables
-- (accounts/sessions/verification) are needed here; only the credential user
-- record and its tenant binding live in the database.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS app_users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL,
    -- Case-insensitive uniqueness without lowercasing what the user typed.
    email_lower   TEXT GENERATED ALWAYS AS (lower(email)) STORED,
    password_hash TEXT NOT NULL,
    name          TEXT,
    tenant_id     UUID NOT NULL REFERENCES tenants(id),
    -- Optional context captured at signup ("what should the twin remember about
    -- you?"). Injected into the persona profile at chat time; never a password
    -- or other sensitive material.
    context       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_email_lower ON app_users (email_lower);
CREATE INDEX IF NOT EXISTS idx_app_users_tenant ON app_users (tenant_id);
