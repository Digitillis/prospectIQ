"""Run research on instantly_leadfinder companies — batched, budget-capped.

Prioritises by pqs_total (highest first) so we research the best-fit companies
while the budget lasts. Each batch commits its own pipeline_runs row so a killed
process loses at most one batch (~$1.25) worth of cost tracking.
"""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(".env"))

import time
from datetime import datetime
from backend.app.core.database import Database
from backend.app.agents.research import ResearchAgent

BATCH_SIZE = 50       # companies per execute() — ~$1.25 max exposure per batch
MAX_COMPANIES = 280   # hard cap matching $7 budget ($0.025/company)

db = Database()

# Fetch unresearched instantly_leadfinder companies, best PQS first
all_ids: list[str] = []
offset = 0
while len(all_ids) < MAX_COMPANIES:
    want = min(1000, MAX_COMPANIES - len(all_ids))
    result = (
        db.client.table("companies")
        .select("id, pqs_total")
        .eq("campaign_name", "instantly_leadfinder")
        .is_("research_summary", "null")
        .order("pqs_total", desc=True)
        .range(offset, offset + want - 1)
        .execute()
    )
    batch = result.data
    all_ids.extend([c["id"] for c in batch])
    if len(batch) < want:
        break
    offset += want

total = len(all_ids)
if total == 0:
    print("No unresearched companies to process.")
    exit(0)

est_cost = total * 0.025
print(f"Queued {total} companies (best PQS first, capped at {MAX_COMPANIES})")
print(f"Estimated cost: ${est_cost:.2f} | batches of {BATCH_SIZE}: {-(-total // BATCH_SIZE)}")
print()

total_processed = 0
total_errors = 0
total_cost = 0.0

for batch_num, start in enumerate(range(0, total, BATCH_SIZE), 1):
    chunk = all_ids[start: start + BATCH_SIZE]
    batch_id = f"instantly_{datetime.utcnow().strftime('%Y%m%d')}_{batch_num:04d}"

    print(
        f"[{datetime.utcnow().strftime('%H:%M:%S')}] "
        f"Batch {batch_num}/{-(-total // BATCH_SIZE)} — "
        f"companies {start+1}–{min(start+BATCH_SIZE, total)} of {total}"
    )

    agent = ResearchAgent(batch_id=batch_id)
    result = agent.execute(company_ids=chunk)

    total_processed += result.processed
    total_errors += result.errors
    total_cost += result.total_cost_usd

    print(
        f"  → {result.processed} done, {result.errors} errors, "
        f"${result.total_cost_usd:.4f} this batch | "
        f"running: {total_processed} done, ${total_cost:.4f} spent"
    )

    if start + BATCH_SIZE < total:
        time.sleep(2)

print()
print(f"Done. {total_processed}/{total} researched | {total_errors} errors | ${total_cost:.4f} total cost")
