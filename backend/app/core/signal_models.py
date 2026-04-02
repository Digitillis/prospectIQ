"""Signal monitoring data models for ProspectIQ.

Defines Pydantic models and enums for the buying signal / trigger engine.
Signals represent detected events that indicate a company is more likely to
buy NOW — job postings, funding rounds, tech changes, news mentions, etc.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ============================================================
# Enums
# ============================================================

class SignalType(str, Enum):
    JOB_POSTING = "job_posting"           # hiring signals
    FUNDING = "funding"                    # investment rounds
    TECH_CHANGE = "tech_change"            # technology adoption/change
    NEWS_MENTION = "news_mention"          # press mentions
    LEADERSHIP_CHANGE = "leadership_change"  # executive hire/departure
    EXPANSION = "expansion"                # new facility, geographic expansion
    PAIN_SIGNAL = "pain_signal"            # explicit pain expressed online
    REGULATORY = "regulatory"             # compliance/regulatory event
    PARTNERSHIP = "partnership"           # new partner/customer announced


class SignalUrgency(str, Enum):
    IMMEDIATE = "immediate"    # act within 48h
    NEAR_TERM = "near_term"    # act within 2 weeks
    BACKGROUND = "background"  # good to know, no urgency


# ============================================================
# Core Signal Models
# ============================================================

class CompanySignal(BaseModel):
    """A single detected buying signal for a company."""

    id: str
    company_id: str
    workspace_id: str
    signal_type: SignalType
    urgency: SignalUrgency
    title: str                   # e.g. "Hired VP of Operations"
    description: str             # 1–3 sentence summary
    source_url: Optional[str] = None
    source_name: str             # "LinkedIn", "Apollo", "News", "Manual"
    signal_score: float          # 0.0–1.0 strength
    is_read: bool = False
    is_actioned: bool = False
    actioned_at: Optional[datetime] = None
    detected_at: datetime
    expires_at: Optional[datetime] = None   # signals can decay
    created_at: Optional[datetime] = None


class SignalSummary(BaseModel):
    """Aggregated signal summary for a single company — used in Hot Prospects view."""

    company_id: str
    company_name: str
    cluster: str
    total_signals: int
    unread_signals: int
    max_urgency: str             # "immediate" | "near_term" | "background"
    composite_score: float       # weighted sum of signal scores
    latest_signal_at: datetime
    signals: List[CompanySignal] = Field(default_factory=list)


class BatchScanResult(BaseModel):
    """Result of a batch signal scan across multiple companies."""

    companies_scanned: int = 0
    signals_created: int = 0
    signals_skipped: int = 0
    cost_usd: float = 0.0
    batch_id: str = ""
    duration_seconds: float = 0.0
    errors: int = 0


class SignalStats(BaseModel):
    """Aggregate stats for the signals dashboard header."""

    total_unread: int = 0
    by_urgency: dict = Field(default_factory=lambda: {
        "immediate": 0,
        "near_term": 0,
        "background": 0,
    })
    by_type: dict = Field(default_factory=dict)
    hot_companies: int = 0       # companies with at least one immediate signal


class ManualSignalInput(BaseModel):
    """Request body for adding a manually-observed signal."""

    company_id: str
    signal_type: str
    title: str
    description: str
    urgency: str = "background"
    source_url: Optional[str] = None
    source_name: str = "Manual"
    signal_score: float = 0.7
