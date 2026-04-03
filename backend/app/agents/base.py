"""Base agent class for ProspectIQ agents.

All agents inherit from BaseAgent and implement the `run` method.
Provides common functionality: logging, cost tracking, error handling.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from rich.console import Console

from backend.app.core.database import Database
from backend.app.core.cost_tracker import log_cost

# Pipeline scripts set WORKSPACE_ID so all records are scoped to the right workspace.
# Falls back to the default workspace if not set.
_DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

console = Console()
logger = logging.getLogger(__name__)


class AgentResult:
    """Result of an agent run."""

    def __init__(self):
        self.success: bool = True
        self.processed: int = 0
        self.skipped: int = 0
        self.errors: int = 0
        self.details: list[dict] = []
        self.batch_id: str = ""
        self.duration_seconds: float = 0.0
        self.total_cost_usd: float = 0.0

    def add_detail(self, company_name: str, status: str, message: str = ""):
        self.details.append({
            "company": company_name,
            "status": status,
            "message": message,
        })

    def summary(self) -> str:
        return (
            f"Processed: {self.processed} | Skipped: {self.skipped} | "
            f"Errors: {self.errors} | Duration: {self.duration_seconds:.1f}s | "
            f"Cost: ${self.total_cost_usd:.4f}"
        )


class BaseAgent(ABC):
    """Abstract base class for all ProspectIQ agents."""

    agent_name: str = "base"

    def __init__(self, batch_id: str | None = None, workspace_id: str | None = None):
        ws_id = workspace_id or os.environ.get("WORKSPACE_ID") or _DEFAULT_WORKSPACE_ID
        # workspace_id column does not exist in the current schema (single-tenant deployment)
        # Pass None so Database._filter_ws is a no-op
        self.db = Database(workspace_id=None)
        self.workspace_id = ws_id
        self.batch_id = batch_id or f"{self.agent_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.logger = logging.getLogger(f"prospectiq.{self.agent_name}")
        self._cost_accumulator: float = 0.0
        self._monitor = None  # Set by execute() — available to run() for per-company log_error()

    @abstractmethod
    def run(self, **kwargs) -> AgentResult:
        """Execute the agent's main logic.

        Must be implemented by each agent subclass.
        Returns an AgentResult with processing stats.
        """
        ...

    def track_cost(
        self,
        provider: str,
        model: str | None = None,
        endpoint: str | None = None,
        company_id: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> float:
        """Track an API cost and return the estimated cost.

        Args:
            provider: API provider name
            model: Model name
            endpoint: API endpoint
            company_id: Associated company ID
            input_tokens: Input token count
            output_tokens: Output token count

        Returns:
            Estimated cost in USD.
        """
        from backend.app.core.cost_tracker import estimate_cost

        cost = estimate_cost(provider, model, input_tokens, output_tokens)
        self._cost_accumulator += cost

        log_cost(
            provider=provider,
            model=model,
            endpoint=endpoint,
            company_id=company_id,
            batch_id=self.batch_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            workspace_id=self.workspace_id,
        )

        return cost

    def execute(self, **kwargs) -> AgentResult:
        """Execute the agent with timing, logging, error handling, and pipeline monitoring.

        This is the public entry point. It wraps `run()` with:
        - Timing
        - Top-level error handling
        - Summary logging
        - PipelineMonitor start/finish/fail (writes to pipeline_runs table)
        """
        from backend.app.agents.monitoring import PipelineMonitor

        console.print(f"\n[bold blue]{'='*60}[/bold blue]")
        console.print(f"[bold blue]Agent: {self.agent_name}[/bold blue]")
        console.print(f"[bold blue]Batch: {self.batch_id}[/bold blue]")
        console.print(f"[bold blue]{'='*60}[/bold blue]\n")

        monitor = PipelineMonitor(agent=self.agent_name, batch_id=self.batch_id, workspace_id=self.workspace_id)
        self._monitor = monitor
        monitor.start(meta={"batch_id": self.batch_id, "kwargs": {k: str(v)[:100] for k, v in kwargs.items()}})

        start_time = time.time()
        catastrophic = False

        try:
            result = self.run(**kwargs)
        except Exception as e:
            self.logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
            monitor.fail(str(e)[:2000])
            catastrophic = True
            result = AgentResult()
            result.success = False
            result.errors = 1
            result.add_detail("N/A", "error", str(e))

        result.duration_seconds = round(time.time() - start_time, 2)
        result.batch_id = self.batch_id
        result.total_cost_usd = round(self._cost_accumulator, 4)

        if not catastrophic:
            monitor.finish(
                processed=result.processed,
                skipped=result.skipped,
                errors=result.errors,
                cost_usd=result.total_cost_usd if result.total_cost_usd else None,
            )

        # Print summary
        status_color = "green" if result.success else "red"
        console.print(f"\n[bold {status_color}]{'-'*60}[/bold {status_color}]")
        console.print(f"[bold {status_color}]{self.agent_name} complete: {result.summary()}[/bold {status_color}]")
        console.print(f"[bold {status_color}]{'-'*60}[/bold {status_color}]\n")

        return result
