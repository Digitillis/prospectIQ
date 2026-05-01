-- Migration 033: outbound_eligible_contacts — hard SQL gate for outreach pipeline
--
-- Replaces the boolean is_outreach_eligible column as the query target for outreach.
-- The outreach agent reads ONLY from this table, making it physically impossible to
-- query an ineligible contact, regardless of what Python code does.
--
-- contacts remains the system of record (everything Apollo returns).
-- outbound_eligible_contacts is the system of action (only verified, eligible contacts).
--
-- Refresh: call refresh_outbound_eligible(workspace_id) after any gate-relevant update.
-- A trigger on contacts fires this automatically on is_outreach_eligible / email_status
-- / email_name_verified changes.

CREATE TABLE IF NOT EXISTS outbound_eligible_contacts (
    contact_id      UUID PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    workspace_id    UUID NOT NULL,
    company_id      UUID,
    promoted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    gate_status     JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Denormalized for fast outreach queries (avoids JOIN on hot path)
    email           TEXT,
    full_name       TEXT,
    first_name      TEXT,
    contact_tier    TEXT,
    persona_type    TEXT,
    is_decision_maker BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_oec_workspace ON outbound_eligible_contacts (workspace_id);
CREATE INDEX IF NOT EXISTS idx_oec_company   ON outbound_eligible_contacts (workspace_id, company_id);

-- ── Stored procedure: evaluate all gates and upsert/delete from eligible table ──

CREATE OR REPLACE FUNCTION refresh_outbound_eligible(p_workspace_id UUID DEFAULT NULL)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    -- Remove contacts that no longer pass gates
    DELETE FROM outbound_eligible_contacts oec
    WHERE (p_workspace_id IS NULL OR oec.workspace_id = p_workspace_id)
      AND NOT EXISTS (
          SELECT 1 FROM contacts c
          WHERE c.id = oec.contact_id
            AND c.is_outreach_eligible = TRUE
            AND (c.email_name_verified IS NULL OR c.email_name_verified = TRUE)
            AND c.email_status NOT IN ('invalid', 'bounce')
            AND c.email IS NOT NULL
            AND c.status NOT IN ('excluded', 'unsubscribed', 'bounced')
      );

    -- Insert/update contacts that now pass all gates
    INSERT INTO outbound_eligible_contacts (
        contact_id, workspace_id, company_id, promoted_at, gate_status,
        email, full_name, first_name, contact_tier, persona_type, is_decision_maker
    )
    SELECT
        c.id,
        c.workspace_id,
        c.company_id,
        NOW(),
        jsonb_build_object(
            'is_outreach_eligible', c.is_outreach_eligible,
            'email_name_verified',  COALESCE(c.email_name_verified, TRUE),
            'email_status',         COALESCE(c.email_status, 'unknown'),
            'contact_tier',         COALESCE(c.contact_tier, 'target'),
            'has_email',            (c.email IS NOT NULL),
            'evaluated_at',         NOW()
        ),
        c.email,
        c.full_name,
        c.first_name,
        c.contact_tier,
        c.persona_type,
        COALESCE(c.is_decision_maker, FALSE)
    FROM contacts c
    WHERE (p_workspace_id IS NULL OR c.workspace_id = p_workspace_id)
      AND c.is_outreach_eligible = TRUE
      AND (c.email_name_verified IS NULL OR c.email_name_verified = TRUE)
      AND COALESCE(c.email_status, 'unknown') NOT IN ('invalid', 'bounce')
      AND c.email IS NOT NULL
      AND COALESCE(c.status, '') NOT IN ('excluded', 'unsubscribed', 'bounced')
    ON CONFLICT (contact_id) DO UPDATE SET
        promoted_at       = NOW(),
        gate_status       = EXCLUDED.gate_status,
        email             = EXCLUDED.email,
        full_name         = EXCLUDED.full_name,
        first_name        = EXCLUDED.first_name,
        contact_tier      = EXCLUDED.contact_tier,
        persona_type      = EXCLUDED.persona_type,
        is_decision_maker = EXCLUDED.is_decision_maker;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- ── Trigger: auto-refresh when a contact's gate-relevant fields change ──

CREATE OR REPLACE FUNCTION trg_refresh_contact_eligibility()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- Only fire on gate-relevant column changes
    IF (TG_OP = 'DELETE') THEN
        DELETE FROM outbound_eligible_contacts WHERE contact_id = OLD.id;
        RETURN OLD;
    END IF;

    IF (
        NEW.is_outreach_eligible IS DISTINCT FROM OLD.is_outreach_eligible OR
        NEW.email_name_verified  IS DISTINCT FROM OLD.email_name_verified  OR
        NEW.email_status         IS DISTINCT FROM OLD.email_status         OR
        NEW.email                IS DISTINCT FROM OLD.email                OR
        NEW.status               IS DISTINCT FROM OLD.status
    ) THEN
        -- Evaluate gates inline (same logic as refresh_outbound_eligible)
        IF (
            NEW.is_outreach_eligible = TRUE AND
            (NEW.email_name_verified IS NULL OR NEW.email_name_verified = TRUE) AND
            COALESCE(NEW.email_status, 'unknown') NOT IN ('invalid', 'bounce') AND
            NEW.email IS NOT NULL AND
            COALESCE(NEW.status, '') NOT IN ('excluded', 'unsubscribed', 'bounced')
        ) THEN
            INSERT INTO outbound_eligible_contacts (
                contact_id, workspace_id, company_id, promoted_at, gate_status,
                email, full_name, first_name, contact_tier, persona_type, is_decision_maker
            ) VALUES (
                NEW.id, NEW.workspace_id, NEW.company_id, NOW(),
                jsonb_build_object(
                    'is_outreach_eligible', NEW.is_outreach_eligible,
                    'email_name_verified',  COALESCE(NEW.email_name_verified, TRUE),
                    'email_status',         COALESCE(NEW.email_status, 'unknown'),
                    'contact_tier',         COALESCE(NEW.contact_tier, 'target'),
                    'has_email',            TRUE,
                    'evaluated_at',         NOW()
                ),
                NEW.email, NEW.full_name, NEW.first_name,
                NEW.contact_tier, NEW.persona_type,
                COALESCE(NEW.is_decision_maker, FALSE)
            )
            ON CONFLICT (contact_id) DO UPDATE SET
                promoted_at       = NOW(),
                gate_status       = EXCLUDED.gate_status,
                email             = EXCLUDED.email,
                full_name         = EXCLUDED.full_name,
                first_name        = EXCLUDED.first_name,
                contact_tier      = EXCLUDED.contact_tier,
                persona_type      = EXCLUDED.persona_type,
                is_decision_maker = EXCLUDED.is_decision_maker;
        ELSE
            -- Contact no longer passes gates — remove from eligible set
            DELETE FROM outbound_eligible_contacts WHERE contact_id = NEW.id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_contact_eligibility ON contacts;
CREATE TRIGGER trg_contact_eligibility
    AFTER UPDATE OR DELETE ON contacts
    FOR EACH ROW
    EXECUTE FUNCTION trg_refresh_contact_eligibility();

-- ── Initial population: backfill all currently eligible contacts ──
SELECT refresh_outbound_eligible();
