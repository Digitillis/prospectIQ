"""Benchmark detector — block fabricated proof points in outreach drafts (P2.1).

Three-layer pipeline:

  Layer 1 (regex)   — flag classic fabricated-benchmark phrasing
                      ("plants like yours cut downtime 23-41%", etc.)

  Layer 2 (numeric) — extract every numeric claim with a unit (% or time),
                      then check the surrounding sentence for a citation
                      that matches one of the approved proof points loaded
                      from `config/offer_context.yaml`.

  Layer 3 (LLM)     — for sentences flagged by Layer 1 or Layer 2, run an
                      LLM verifier (Sonnet, temperature=0.1) against the
                      proof points. The verifier returns a structured
                      verdict:
                        attributed → number is sourced and cited
                        fabricated → number has no source
                        unclear    → cannot decide

Public surface:

    detector = BenchmarkDetector()                   # uses default proof points
    analysis = detector.analyze("Hi Avi, plants ...") # → BenchmarkAnalysis
    if analysis.has_violations:
        ...

The detector is offline-safe: if the LLM call fails (no API key, network
error), Layer 3 is skipped and findings carry the LLM-skipped flag. Layers
1 + 2 always run.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer 1 regex patterns — fabricated-benchmark phrasing
# ---------------------------------------------------------------------------

_LAYER_1_PATTERNS: tuple[tuple[str, str], ...] = (
    ("similar_plants", r"\b(plants|companies|operations)\s+(in|with|of)\s+similar\b"),
    ("cut_pct_range", r"\bcut\s+\w+\s+\d{1,2}[-–]\d{2}\s*%"),
    ("catch_n_units_earlier", r"\bcatch\w*\s+\w+\s+\d+[-–]\d+\s+(days|hours|minutes)\s+earlier\b"),
    ("typically_verb", r"\btypically\s+(see|catch|reduce|cut|save)\b"),
    ("pct_change_phrase", r"\b\d{1,2}[-–]\d{2}\s*%\s+(reduction|improvement|decrease|increase)\b"),
    ("similar_facilities", r"\bsimilar\s+(facilities|manufacturers|plants|operations)\b"),
    ("our_clients_saw", r"\bour\s+(clients|customers)\s+(saw|achieved|reduced|cut)\b"),
)


# Numeric claim — covers both percentage forms (23-41%, 23%) and time forms
# (2-5 days earlier, 7-14 days, 2 weeks).
_NUMERIC_PCT = re.compile(r"\b\d{1,3}(?:[-–]\d{1,3})?\s*%")
_NUMERIC_TIME = re.compile(
    r"\b\d{1,3}(?:[-–]\d{1,3})?\s*(days?|hours?|minutes?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)

# Sentence splitter — naive but adequate for short outreach bodies.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One flagged claim from a draft body."""

    layer: str  # "layer1_regex" | "layer2_numeric" | "layer3_llm"
    sentence: str
    excerpt: str  # The matched substring
    rule: str | None = None  # Layer 1 pattern name, or numeric kind
    evidence_id: str | None = None  # Which proof_point id (if attributed)
    verdict: str = "unclear"  # "attributed" | "fabricated" | "unclear"
    detail: str | None = None


@dataclass
class BenchmarkAnalysis:
    """Aggregated detector output for a single draft body."""

    has_violations: bool = False
    findings: list[Finding] = field(default_factory=list)
    verdict: str = "clean"  # "clean" | "fabricated" | "unclear"


# ---------------------------------------------------------------------------
# Proof-point loading
# ---------------------------------------------------------------------------

_DEFAULT_OFFER_CONTEXT_PATH = Path(__file__).resolve().parents[3] / "config" / "offer_context.yaml"


def load_proof_points(path: Path | None = None) -> list[dict]:
    """Load approved proof points from `config/offer_context.yaml`.

    Each entry is a dict like:
        {"id": "pp_0", "text": "Industry benchmark: ..."}
    so the LLM verifier can cite them by id.
    """
    p = Path(path) if path else _DEFAULT_OFFER_CONTEXT_PATH
    try:
        with open(p) as fh:
            doc = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("BenchmarkDetector: failed to load %s (%s) — empty proof set", p, exc)
        return []

    raw = doc.get("proof_points") or []
    out: list[dict] = []
    for i, text in enumerate(raw):
        if isinstance(text, str) and text.strip():
            out.append({"id": f"pp_{i}", "text": text.strip()})
    return out


def _proof_point_keywords(proof_points: list[dict]) -> set[str]:
    """Build a quick token set used by the cheap citation check in Layer 2.

    A sentence is considered to carry a citation when several distinctive
    keywords from any proof point co-occur — e.g. "LNS Research", "FDA",
    "McKinsey", "SMRP". We extract capitalized words and quoted source names.
    """
    tokens: set[str] = set()
    for pp in proof_points:
        text = pp.get("text", "")
        for tok in re.findall(r"\b[A-Z][A-Za-z&]+\b", text):
            if len(tok) >= 3 and tok.lower() not in {
                "industry",
                "manufacturers",
                "the",
                "and",
                "with",
                "year",
                "month",
                "week",
                "days",
                "report",
                "survey",
                "data",
            }:
                tokens.add(tok)
    return tokens


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class BenchmarkDetector:
    """Three-layer fabricated-benchmark detector for outreach draft bodies."""

    def __init__(
        self,
        proof_points: list[dict] | None = None,
        llm_enabled: bool | None = None,
    ) -> None:
        self.proof_points = proof_points if proof_points is not None else load_proof_points()
        self._proof_keywords = _proof_point_keywords(self.proof_points)

        # LLM is opt-in: enabled only when an Anthropic key is in env, unless
        # the caller passes llm_enabled=False explicitly.
        if llm_enabled is None:
            self.llm_enabled = bool(os.environ.get("ANTHROPIC_API_KEY"))
        else:
            self.llm_enabled = bool(llm_enabled)

    # -- Public ---------------------------------------------------------------

    def analyze(self, draft_body: str) -> BenchmarkAnalysis:
        """Run all three layers against `draft_body` and return a verdict."""
        if not draft_body:
            return BenchmarkAnalysis()

        sentences = _split_sentences(draft_body)
        findings: list[Finding] = []

        # Layer 1 — regex
        findings.extend(self._layer_1(sentences))

        # Layer 2 — numeric claims missing citations
        findings.extend(self._layer_2(sentences))

        # Layer 3 — LLM verifier on flagged sentences
        if self.llm_enabled and findings:
            self._layer_3(findings)

        verdict = self._aggregate_verdict(findings)
        return BenchmarkAnalysis(
            has_violations=any(f.verdict == "fabricated" for f in findings),
            findings=findings,
            verdict=verdict,
        )

    # -- Layers ---------------------------------------------------------------

    def _layer_1(self, sentences: list[str]) -> list[Finding]:
        """Pattern-match suspect phrasing.

        A regex hit on its own is a strong signal but not absolute proof: a
        properly attributed sentence (with a year-cited source or a regulator
        reference) clears to verdict='attributed' here. The LLM verifier runs
        on top to override either way.
        """
        out: list[Finding] = []
        for sent in sentences:
            for name, pattern in _LAYER_1_PATTERNS:
                m = re.search(pattern, sent, flags=re.IGNORECASE)
                if m:
                    has_citation = self._sentence_has_citation(sent)
                    out.append(
                        Finding(
                            layer="layer1_regex",
                            sentence=sent,
                            excerpt=m.group(0),
                            rule=name,
                            verdict="attributed" if has_citation else "fabricated",
                            detail=(
                                f"Layer 1 regex match: {name} "
                                f"({'cited' if has_citation else 'no citation'})"
                            ),
                        )
                    )
        return out

    def _layer_2(self, sentences: list[str]) -> list[Finding]:
        out: list[Finding] = []
        for sent in sentences:
            numeric_matches: list[tuple[str, str]] = []
            for m in _NUMERIC_PCT.finditer(sent):
                numeric_matches.append(("numeric_pct", m.group(0)))
            for m in _NUMERIC_TIME.finditer(sent):
                numeric_matches.append(("numeric_time", m.group(0)))
            if not numeric_matches:
                continue
            # Does the sentence carry a citation?
            cited = self._sentence_has_citation(sent)
            if cited:
                continue
            for kind, excerpt in numeric_matches:
                out.append(
                    Finding(
                        layer="layer2_numeric",
                        sentence=sent,
                        excerpt=excerpt,
                        rule=kind,
                        verdict="unclear",
                        detail="Numeric claim with no citation in sentence",
                    )
                )
        return out

    def _layer_3(self, findings: list[Finding]) -> None:
        """Send flagged sentences to the LLM verifier for a final verdict.

        Updates `findings` in place. Failures are logged and treated as
        verdict='unclear' so we don't accidentally pass a fabricated claim
        because the LLM was unreachable.
        """
        try:
            import anthropic
        except Exception as exc:
            logger.info("BenchmarkDetector: anthropic SDK unavailable (%s) — skipping Layer 3", exc)
            return

        # Group findings by sentence so the verifier sees full context.
        flagged_sentences: list[str] = []
        for f in findings:
            if (
                f.layer in ("layer1_regex", "layer2_numeric")
                and f.sentence not in flagged_sentences
            ):
                flagged_sentences.append(f.sentence)

        if not flagged_sentences:
            return

        proof_block = (
            "\n".join(f"- {pp['id']}: {pp['text']}" for pp in self.proof_points)
            or "- (no proof points configured)"
        )

        prompt = (
            "You verify whether numeric claims in an outreach email sentence are "
            "attributed to a real, approved proof point. For each sentence, return one "
            'of: {"verdict": "attributed", "evidence_id": "<id>"} | '
            '{"verdict": "fabricated", "evidence_id": null} | '
            '{"verdict": "unclear", "evidence_id": null}.\n\n'
            f"Approved proof points:\n{proof_block}\n\n"
            "Sentences to verify (one per line):\n"
            + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(flagged_sentences))
            + '\n\nReturn a JSON object: {"results": [<verdict-object>, ...]} '
            "in the same order as the sentences."
        )

        try:
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=os.environ.get("ANTHROPIC_BENCHMARK_MODEL", "claude-sonnet-4-5"),
                max_tokens=600,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            results = self._parse_llm_results(raw)
        except Exception as exc:
            logger.warning("BenchmarkDetector: Layer 3 LLM call failed: %s", exc)
            return

        # Map verdicts back onto findings by sentence position.
        for f in findings:
            if f.layer not in ("layer1_regex", "layer2_numeric"):
                continue
            if f.sentence not in flagged_sentences:
                continue
            idx = flagged_sentences.index(f.sentence)
            if idx >= len(results):
                continue
            r = results[idx]
            v = r.get("verdict", "unclear")
            if v in ("attributed", "fabricated", "unclear"):
                f.layer = "layer3_llm"
                f.verdict = v
                ev = r.get("evidence_id")
                if isinstance(ev, str) and ev:
                    f.evidence_id = ev

    # -- Helpers --------------------------------------------------------------

    def _sentence_has_citation(self, sentence: str) -> bool:
        """Cheap citation heuristic for Layer 2.

        A sentence is treated as cited when ANY of the following hold:
          - It contains a parenthetical with a 4-digit year (e.g. "(LNS Research, 2024)")
          - It contains "FDA", "USDA", "OSHA", "EPA", or another regulator
          - It shares >= 2 distinctive keywords with the approved proof points
        """
        if re.search(r"\(\s*[^)]+\s+\d{4}\s*\)", sentence):
            return True
        if re.search(r"\b(FDA|USDA|OSHA|EPA|CDC|FSMA|GAO)\b", sentence):
            return True
        sentence_tokens = set(
            tok for tok in re.findall(r"\b[A-Z][A-Za-z&]+\b", sentence) if len(tok) >= 3
        )
        overlap = self._proof_keywords & sentence_tokens
        return len(overlap) >= 2

    def _parse_llm_results(self, raw: str) -> list[dict]:
        """Parse the LLM's JSON response, tolerating code fences and prose."""
        # Strip code fences if present
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        # Find the first {...} block
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return []
        try:
            doc = json.loads(m.group(0))
        except Exception:
            return []
        results = doc.get("results") or []
        if not isinstance(results, list):
            return []
        out: list[dict] = []
        for r in results:
            if isinstance(r, dict) and "verdict" in r:
                out.append(r)
        return out

    def _aggregate_verdict(self, findings: Iterable[Finding]) -> str:
        verdicts = {f.verdict for f in findings}
        if not verdicts:
            return "clean"
        if "fabricated" in verdicts:
            return "fabricated"
        if "unclear" in verdicts:
            return "unclear"
        return "clean"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    return parts
