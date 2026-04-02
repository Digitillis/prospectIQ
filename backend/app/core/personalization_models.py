"""Pydantic models for the Personalization Engine.

Separate from models.py to keep personalization concerns isolated
and allow independent iteration.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class TriggerEvent(BaseModel):
    """A buying trigger identified from company research."""

    trigger_type: str  # growth | pain | tech | timing
    description: str
    urgency: str  # immediate | near_term | background
    confidence: float = 0.0
    source_text: str = ""
    priority_rank: int = 0


class PersonalizationHook(BaseModel):
    """A single personalized outreach opening sentence."""

    hook_text: str
    persona_target: str   # e.g. vp_ops, plant_manager, executive
    trigger_reference: str
    tone: str             # specific | empathetic | provocative
    confidence: float = 0.0


class PersonalizationResult(BaseModel):
    """Full output from PersonalizationEngine.run_full_pipeline()."""

    company_id: str
    readiness_score: int = 0          # 0-100
    readiness_breakdown: dict = Field(default_factory=dict)
    triggers: list[TriggerEvent] = Field(default_factory=list)
    hooks: list[PersonalizationHook] = Field(default_factory=list)
    personas_found: list[str] = Field(default_factory=list)
    contacts_updated: int = 0
    generated_at: str = ""            # ISO 8601
    cost_usd: float = 0.0


class BatchResult(BaseModel):
    """Result of a batch personalization run."""

    processed: int = 0
    updated: int = 0
    errors: int = 0
    total_cost_usd: float = 0.0
    avg_readiness_score: float = 0.0
    error_details: list[dict] = Field(default_factory=list)


class PersonalizationStatus(BaseModel):
    """Lightweight status check for a single company."""

    company_id: str
    readiness_score: int = 0
    triggers: list[TriggerEvent] = Field(default_factory=list)
    hooks: list[PersonalizationHook] = Field(default_factory=list)
    personas_found: list[str] = Field(default_factory=list)
    last_run_at: Optional[str] = None
    contacts_count: int = 0


class PersonalizationLeaderboardItem(BaseModel):
    """One row in the personalization readiness leaderboard."""

    company_id: str
    company_name: str
    cluster: Optional[str] = None
    tranche: Optional[str] = None
    readiness_score: int = 0
    trigger_count: int = 0
    hook_count: int = 0
    contact_count: int = 0
    personas_found: list[str] = Field(default_factory=list)
    last_run_at: Optional[str] = None
    pqs_total: int = 0


class ManualTriggerInput(BaseModel):
    """Input for manually adding a trigger to a company."""

    trigger_type: str
    description: str
    urgency: str
    source: str = "manual"
