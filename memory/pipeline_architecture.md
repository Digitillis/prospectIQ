---
name: Pipeline & Sequencing Architecture
description: 3-phase sequencing system status, engagement agent gap, campaign cluster routing
type: project
---

## 3-Phase Sequencing Status

- **Phase 1** (Discovery → Research → Qualify → Enrich): ✅ Complete and running
- **Phase 2** (Webhook reply ingestion → thread update → re-sequence): ✅ Built. Blocked on `campaign_threads` migration not applied.
- **Phase 3** (HITL classification + send confirmation): ✅ Backend logic built. UI being built.

## Key Gap: Engagement Agent Send Path

The engagement agent currently routes all contacts to a **single** Instantly campaign. It needs to route per `campaign_cluster` (machinery/auto/chemicals/metals/process/fb).

**Fix needed in `backend/app/agents/engagement.py`:**
- Use `get_campaign_id_for_company(company)` to route per cluster
- If no campaign exists for a cluster, auto-provision it via Instantly API (`create_campaign()` capability exists)
- Do NOT manually create campaigns in Instantly — ProspectIQ should own campaign creation

## Campaign Cluster Mapping
| Cluster | Tiers |
|---------|-------|
| machinery | mfg1, mfg2, mfg4, mfg5, mfg8 |
| auto | mfg3 |
| metals | mfg7 |
| chemicals | pmfg1 |
| process | pmfg3, pmfg4, pmfg7, pmfg8 |
| fb | fb1, fb2, fb3, fb4, fb5 |
| other (watchlist) | mfg6, pmfg2, pmfg5, pmfg6 — manual review only |

## Pending Migration
`migrations/001_campaign_threads.sql` — creates `campaign_threads` and `thread_messages` tables. NOT YET APPLIED to Supabase. Apply via Supabase SQL editor before testing Phase 2/3.

## Instantly Env Vars Needed
```
INSTANTLY_SEQ_MACHINERY_VP_OPS=<id>
INSTANTLY_SEQ_MACHINERY_PLANT_MGMT=<id>
INSTANTLY_SEQ_AUTO_VP_OPS=<id>
INSTANTLY_SEQ_CHEMICALS_VP_OPS=<id>
```
