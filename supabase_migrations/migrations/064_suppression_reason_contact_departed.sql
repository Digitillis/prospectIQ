-- Add contact_departed as a valid suppression reason.
-- Required for auto-suppress of departed/retired contacts detected via IMAP reply.
ALTER TABLE suppression_log
    DROP CONSTRAINT IF EXISTS suppression_log_reason_check;

ALTER TABLE suppression_log
    ADD CONSTRAINT suppression_log_reason_check CHECK (
        reason IN (
            'hard_bounce_contact',
            'hard_bounce_domain',
            'manual_block',
            'unsubscribe',
            'spam_complaint',
            'soft_bounce',
            'contact_departed'
        )
    );
