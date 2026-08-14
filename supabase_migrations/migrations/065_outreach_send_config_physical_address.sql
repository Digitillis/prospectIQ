-- Migration 065: sender_physical_address on outreach_send_config
--
-- CAN-SPAM (a)(5)'s required physical mailing address was stored only in
-- config/outreach_guidelines.yaml, a file on the Railway container's local
-- filesystem. The service has no attached persistent volume (Railpack
-- build, no Dockerfile/railway.toml declaring one, confirmed via Railway's
-- own service config) -- any value written to it via
-- PATCH /api/settings/outreach-guidelines is silently lost on the next
-- redeploy, for any reason, reverting to whatever's committed in git. That
-- PATCH endpoint's own code comment says it exists so this can be fixed
-- "without engineer/deploy access once sending is blocked on it" -- a
-- promise the file-based storage could not keep, since the very next
-- deploy (unrelated or not) would re-break it silently.
--
-- Moves physical_address onto outreach_send_config, which already holds
-- every other admin-tunable, per-workspace, DB-backed value (daily_limit,
-- batch_size, sender_pool, notes) and survives redeploys the way a
-- Supabase-hosted table naturally does. Additive only -- the YAML field
-- is left in place (marked deprecated in the same change) rather than
-- removed, so a stale reader isn't silently broken by a missing key.

ALTER TABLE outreach_send_config
    ADD COLUMN IF NOT EXISTS sender_physical_address TEXT;

COMMENT ON COLUMN outreach_send_config.sender_physical_address IS
    'CAN-SPAM 7704(a)(5) required physical mailing address, appended to '
    'every outbound send by backend/app/core/unsubscribe.py''s '
    'compliance_footer_text(). Source of truth as of migration 065 -- '
    'config/outreach_guidelines.yaml''s sender.physical_address is '
    'deprecated and no longer read. Edit this column directly, or via '
    'PATCH /api/settings/outreach-guidelines {"sender_physical_address": '
    '"..."}, which now writes here.';
