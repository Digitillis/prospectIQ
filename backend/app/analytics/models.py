"""Pydantic models for analytics API responses.

Shared between funnel.py, revenue.py, and the analytics routes.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Funnel models
# ---------------------------------------------------------------------------

class FunnelStage(BaseModel):
    stage_name: str
    stage_key: str
    count: int
    conversion_rate: float       # % from previous stage
    avg_days_in_stage: float
    drop_off: int                # absolute count lost vs prior stage
    is_bottleneck: bool = False


class FunnelData(BaseModel):
    stages: List[FunnelStage]
    period_days: int
    total_entered: int
    total_converted: int         # reached "replied" or beyond
    overall_conversion_rate: float
    bottleneck_stage: str        # stage with highest drop-off %


# ---------------------------------------------------------------------------
# Cohort models
# ---------------------------------------------------------------------------

class CohortRow(BaseModel):
    cohort_name: str
    count: int
    contacted_pct: float
    reply_rate: float
    interested_pct: float
    conversion_rate: float       # % reached replied or demo_scheduled
    avg_pqs: float


class CohortAnalysis(BaseModel):
    rows: List[CohortRow]
    group_by: str
    period_days: int


# ---------------------------------------------------------------------------
# Velocity models
# ---------------------------------------------------------------------------

class VelocityStage(BaseModel):
    stage_name: str
    avg_days: float
    trend: str                   # "faster" | "slower" | "stable" | "no_data"
    trend_delta_days: float      # positive = slower, negative = faster


class VelocityMetrics(BaseModel):
    stages: List[VelocityStage]
    computed_at: str


# ---------------------------------------------------------------------------
# Revenue models
# ---------------------------------------------------------------------------

class DealStage(BaseModel):
    stage: str
    count: int
    est_value_usd: float


class RevenueAttribution(BaseModel):
    pipeline_stages: List[DealStage]
    projected_arr_90d: float
    projected_arr_180d: float
    confidence_range: Tuple[float, float]
    best_performing_cluster: str
    best_performing_sequence: str
    avg_deal_size_assumption: float
    weighted_pipeline_value: float


# ---------------------------------------------------------------------------
# Activity ROI models
# ---------------------------------------------------------------------------

class ChannelROI(BaseModel):
    channel: str
    total_sent: int
    total_replied: int
    reply_rate_pct: float


class SequenceROI(BaseModel):
    sequence_name: str
    total_sent: int
    total_replied: int
    reply_rate_pct: float


class ActivityROI(BaseModel):
    by_channel: List[ChannelROI]
    by_sequence: List[SequenceROI]
    by_persona: List[dict]       # reuse existing persona breakdown shape
    by_cluster: List[dict]


# ---------------------------------------------------------------------------
# Summary model (for command center)
# ---------------------------------------------------------------------------

class AnalyticsSummary(BaseModel):
    total_pipeline: int
    total_contacted: int
    total_replied: int
    total_interested: int
    projected_arr_90d: float
    overall_conversion_rate: float
    pipeline_health: str         # "green" | "amber" | "red"
    bottleneck_stage: str
    stuck_in_research_14d: int
    best_cluster: str
