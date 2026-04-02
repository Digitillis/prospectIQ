-- Migration 023: Auth Hardening
-- Adds auth_audit_log and login_attempts tables for session auditing
-- and persistent rate limiting.
--
-- Copyright © 2026 ProspectIQ. All rights reserved.
-- Authors: Avanish Mehrotra & ProspectIQ Technical Team

-- ---------------------------------------------------------------------------
-- Auth audit log
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS auth_audit_log (
  id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID         REFERENCES workspaces(id) ON DELETE SET NULL,
  user_id      UUID,
  event_type   VARCHAR(50)  NOT NULL,
  ip_address   TEXT,
  user_agent   TEXT,
  metadata     JSONB        NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Most queries filter by workspace + time or by user + time
CREATE INDEX IF NOT EXISTS idx_auth_audit_workspace
  ON auth_audit_log (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_auth_audit_user
  ON auth_audit_log (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_auth_audit_event_type
  ON auth_audit_log (event_type, created_at DESC);

-- ---------------------------------------------------------------------------
-- Login attempts (persistent rate limiting — survives restarts)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS login_attempts (
  id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  identifier    TEXT         NOT NULL,         -- hashed email or IP
  attempt_type  VARCHAR(20)  NOT NULL,         -- 'email' or 'ip'
  attempted_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  success       BOOLEAN      NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_identifier
  ON login_attempts (identifier, attempted_at DESC);

-- Partial index for fast failure lookups (lockout logic reads only failures)
CREATE INDEX IF NOT EXISTS idx_login_attempts_failures
  ON login_attempts (identifier, attempted_at DESC)
  WHERE success = FALSE;

-- ---------------------------------------------------------------------------
-- Row-level security: users may only read their own audit rows
-- ---------------------------------------------------------------------------

ALTER TABLE auth_audit_log ENABLE ROW LEVEL SECURITY;

-- Service-role key bypasses RLS — used by the backend
-- Authenticated users can read only their own rows
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'auth_audit_log' AND policyname = 'auth_audit_log_self_read'
  ) THEN
    CREATE POLICY auth_audit_log_self_read
      ON auth_audit_log
      FOR SELECT
      USING (user_id = auth.uid());
  END IF;
END
$$;

-- login_attempts is internal-only; no RLS needed (service role only)
