"""Signal Monitor API routes for ProspectIQ.

Endpoints for the Signal Monitoring / Trigger Engine — surfaces buying signals
(job postings, funding rounds, tech stack changes, news mentions, etc.) for
companies in the database and ranks hot prospects.

Endpoints:
    GET  /api/signals                   — paginated signal feed
    GET  /api/signals/hot-prospects     — companies ranked by signal composite score
    GET  /api/signals/stats             — aggregate badge stats
    GET  /api/signals/company/{id}      — all signals for one company
    POST /api/signals/scan/{id}         — trigger immediate scan for one company
    POST /api/signals/scan-batch        — run batch scan
    PATCH /api/signals/{id}/read        — mark signal read
    PATCH /api/signals/{id}/action      — mark signal actioned
    POST /api/signals/manual            — add manually-observed signal
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.signal_models import (
    BatchScanResult,
    CompanySignal,
    ManualSignalInput,
    SignalStats,
    SignalSummary,
    SignalType,
    SignalUrgency,
)
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["signals"])

_DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def get_db() -> Database:
    return Database(workspace_id=None)  # workspace_id column not in schema


def _ws() -> str:
    return get_workspace_id() or _DEFAULT_WORKSPACE_ID


def _row_to_signal(row: dict, workspace_id: str) -> CompanySignal | None:
    """Convert a DB row to a CompanySignal, returning None on parse failure."""
    try:
        det_raw = row.get("detected_at") or row.get("created_at") or datetime.now(timezone.utc).isoformat()
        if isinstance(det_raw, str):
            det = datetime.fromisoformat(det_raw.replace("Z", "+00:00"))
        else:
            det = datetime.now(timezone.utc)

        act_raw = row.get("actioned_at")
        actioned_at = None
        if act_raw:
            try:
                actioned_at = datetime.fromisoformat(act_raw.replace("Z", "+00:00"))
            except Exception:
                pass

        exp_raw = row.get("expires_at")
        expires_at = None
        if exp_raw:
            try:
                expires_at = datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))
            except Exception:
                pass

        return CompanySignal(
            id=row["id"],
            company_id=row["company_id"],
            workspace_id=row.get("workspace_id") or workspace_id,
            signal_type=SignalType(row["signal_type"]),
            urgency=SignalUrgency(row["urgency"]),
            title=row["title"],
            description=row.get("description") or "",
            source_url=row.get("source_url"),
            source_name=row.get("source_name") or "system",
            signal_score=row.get("signal_score") or 0.5,
            is_read=row.get("is_read", False),
            is_actioned=row.get("is_actioned", False),
            actioned_at=actioned_at,
            detected_at=det,
            expires_at=expires_at,
        )
    except Exception as e:
        logger.debug(f"_row_to_signal: parse failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ScanBatchRequest(BaseModel):
    limit: int = 50


# ---------------------------------------------------------------------------
# GET /api/signals
# ---------------------------------------------------------------------------

@router.get("/api/signals")
async def list_signals(
    urgency: Optional[str] = Query(None, description="Filter by urgency"),
    signal_type: Optional[str] = Query(None, description="Filter by signal type"),
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    cluster: Optional[str] = Query(None, description="Filter by company cluster"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List signals across all companies, sorted by urgency then detected_at DESC."""
    db = get_db()
    ws = _ws()

    try:
        query = (
            db.client.table("company_signals")
            .select("*, companies(name, campaign_cluster, cluster, sub_sector, tier)")
            .order("detected_at", desc=True)
        )

        if urgency:
            query = query.eq("urgency", urgency)
        if signal_type:
            query = query.eq("signal_type", signal_type)
        if is_read is not None:
            query = query.eq("is_read", is_read)

        rows = query.range(offset, offset + limit - 1).execute().data or []

        # Optional cluster filter (requires join data)
        if cluster:
            def _company_cluster(row: dict) -> str:
                c = row.get("companies") or {}
                return (
                    c.get("campaign_cluster")
                    or c.get("cluster")
                    or c.get("sub_sector")
                    or ""
                )
            rows = [r for r in rows if _company_cluster(r).lower() == cluster.lower()]

        signals = [_row_to_signal(r, ws) for r in rows]
        signals = [s for s in signals if s is not None]

        return {"data": [s.model_dump() for s in signals], "count": len(signals)}

    except Exception as e:
        logger.error(f"list_signals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/signals/hot-prospects
# ---------------------------------------------------------------------------

@router.get("/api/signals/hot-prospects")
async def get_hot_prospects(
    limit: int = Query(20, ge=1, le=100),
):
    """Return companies ranked by composite signal score (immediate signals first)."""
    ws = _ws()
    try:
        from backend.app.agents.signal_monitor import SignalMonitorAgent
        agent = SignalMonitorAgent(workspace_id=ws)
        summaries = agent.get_hot_prospects(workspace_id=ws, limit=limit)
        return {"data": [s.model_dump() for s in summaries], "count": len(summaries)}
    except Exception as e:
        logger.error(f"get_hot_prospects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/signals/stats
# ---------------------------------------------------------------------------

@router.get("/api/signals/stats")
async def get_signal_stats():
    """Return aggregate stats: total_unread, by_urgency, by_type, hot_companies."""
    ws = _ws()
    try:
        from backend.app.agents.signal_monitor import SignalMonitorAgent
        agent = SignalMonitorAgent(workspace_id=ws)
        stats = agent.get_signal_stats(workspace_id=ws)
        return stats.model_dump()
    except Exception as e:
        logger.error(f"get_signal_stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/signals/company/{company_id}
# ---------------------------------------------------------------------------

@router.get("/api/signals/company/{company_id}")
async def get_company_signals(company_id: str):
    """Return all signals for a specific company."""
    db = get_db()
    ws = _ws()

    try:
        rows = (
            db.client.table("company_signals")
            .select("*")
            .eq("company_id", company_id)
            .order("detected_at", desc=True)
            .execute()
            .data or []
        )
        signals = [_row_to_signal(r, ws) for r in rows]
        signals = [s for s in signals if s is not None]
        return {"data": [s.model_dump() for s in signals], "count": len(signals)}
    except Exception as e:
        logger.error(f"get_company_signals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /api/signals/scan/{company_id}
# ---------------------------------------------------------------------------

@router.post("/api/signals/scan/{company_id}")
async def scan_company(company_id: str):
    """Trigger an immediate signal scan for a single company."""
    ws = _ws()
    try:
        from backend.app.agents.signal_monitor import SignalMonitorAgent
        agent = SignalMonitorAgent(workspace_id=ws)
        new_signals = agent.scan_company(company_id=company_id, workspace_id=ws)
        return {
            "data": [s.model_dump() for s in new_signals],
            "count": len(new_signals),
            "message": f"Scan complete — {len(new_signals)} new signal(s) detected",
        }
    except Exception as e:
        logger.error(f"scan_company: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /api/signals/scan-batch
# ---------------------------------------------------------------------------

@router.post("/api/signals/scan-batch")
async def scan_batch(body: ScanBatchRequest = ScanBatchRequest()):
    """Run a batch signal scan across unscanned companies."""
    ws = _ws()
    try:
        from backend.app.agents.signal_monitor import SignalMonitorAgent
        agent = SignalMonitorAgent(workspace_id=ws)
        result: BatchScanResult = agent.scan_batch(workspace_id=ws, limit=body.limit)
        return result.model_dump()
    except Exception as e:
        logger.error(f"scan_batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# PATCH /api/signals/{signal_id}/read
# ---------------------------------------------------------------------------

@router.patch("/api/signals/{signal_id}/read")
async def mark_read(signal_id: str):
    """Mark a signal as read."""
    ws = _ws()
    try:
        from backend.app.agents.signal_monitor import SignalMonitorAgent
        agent = SignalMonitorAgent(workspace_id=ws)
        agent.mark_signal_read(signal_id=signal_id, workspace_id=ws)
        return {"message": "Signal marked as read", "signal_id": signal_id}
    except Exception as e:
        logger.error(f"mark_read: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# PATCH /api/signals/{signal_id}/action
# ---------------------------------------------------------------------------

@router.patch("/api/signals/{signal_id}/action")
async def mark_action(signal_id: str):
    """Mark a signal as actioned."""
    ws = _ws()
    try:
        from backend.app.agents.signal_monitor import SignalMonitorAgent
        agent = SignalMonitorAgent(workspace_id=ws)
        agent.mark_signal_actioned(signal_id=signal_id, workspace_id=ws)
        return {"message": "Signal marked as actioned", "signal_id": signal_id}
    except Exception as e:
        logger.error(f"mark_action: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /api/signals/manual
# ---------------------------------------------------------------------------

@router.post("/api/signals/manual")
async def add_manual_signal(body: ManualSignalInput):
    """Add a manually-observed buying signal."""
    ws = _ws()
    try:
        from backend.app.agents.signal_monitor import SignalMonitorAgent
        agent = SignalMonitorAgent(workspace_id=ws)
        signal = agent.add_manual_signal(inp=body, workspace_id=ws)
        if not signal:
            raise HTTPException(status_code=500, detail="Failed to save signal")
        return {"data": signal.model_dump(), "message": "Manual signal added"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"add_manual_signal: {e}")
        raise HTTPException(status_code=500, detail=str(e))
