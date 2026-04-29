# ProspectIQ Database Migrations

Apply these migrations **in order** against your Supabase project via the SQL editor
(Dashboard → SQL Editor → New query → paste → Run).

| # | File | Description | Required Before |
|---|------|-------------|----------------|
| 001 | `001_campaign_threads.sql` | Campaign threads + thread messages | — |
| 002 | `002_tranche_campaign_cluster.sql` | Tranche + campaign cluster fields | — |
| 003 | `003_protect_sent_emails.sql` | Immutable sent email trigger | — |
| 004 | `004_intelligence_confidence.sql` | Confidence lifecycle on learning_outcomes | Phase 2 |
| 005 | `005_memory_rag.sql` | pgvector extension + knowledge_items + memory_nodes | Phase 3 |
| 006 | `006_llm_qualification.sql` | LLM qualification result column on companies | Phase 4 |
| 007 | `007_linkedin_rate_limits.sql` | Provider rate limit tracking table | Phase 1 |
| 008 | `008_memory_rpc_functions.sql` | Supabase RPC functions for vector + text search | Phase 3 (after 005) |

## Notes

- **Migration 005** requires enabling the `vector` extension first:
  Supabase Dashboard → Database → Extensions → search "vector" → Enable.
  The `CREATE EXTENSION IF NOT EXISTS vector;` line in 005 is then a no-op.

- **Migration 008** must run AFTER 005 (references the `memory_nodes` table).

- All migrations are **idempotent** (`IF NOT EXISTS`, `CREATE OR REPLACE`) —
  safe to re-run if something goes wrong mid-way.

- Migrations 001–003 were from the original build. Apply 004–008 together
  in a single session for the YALC-integration features.
