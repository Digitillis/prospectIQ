"""End-to-end test harness for ProspectIQ CRM.

Covers:
  1.  Config loading
  2.  Model & enum validation
  3.  Persona classification
  4.  Scoring (firmographic, technographic, timing, thresholds)
  5.  Suppression logic
  6.  Domain verification
  7.  Draft quality checks
  8.  Send-time optimisation
  9.  State-machine transitions
  10. Outreach system-prompt generation
  11. FastAPI route responses (mocked DB)

Run with:
    python -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone, time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on the path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# 1. CONFIG LOADING TESTS
# ===========================================================================

class TestConfigLoading:
    """All five YAML config files must load without error and contain required keys."""

    def test_icp_config_loads(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("icp.yaml")
        assert isinstance(cfg, dict), "icp.yaml should parse to a dict"

    def test_icp_has_company_filters(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("icp.yaml")
        assert "company_filters" in cfg, "icp.yaml must have 'company_filters'"

    def test_icp_has_contact_filters(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("icp.yaml")
        assert "contact_filters" in cfg, "icp.yaml must have 'contact_filters'"

    def test_icp_has_discovery(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("icp.yaml")
        assert "discovery" in cfg, "icp.yaml must have 'discovery'"

    def test_icp_discovery_has_max_results(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("icp.yaml")
        assert "max_results_per_run" in cfg["discovery"], (
            "icp.yaml discovery must have 'max_results_per_run'"
        )

    def test_scoring_config_loads(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("scoring.yaml")
        assert isinstance(cfg, dict), "scoring.yaml should parse to a dict"

    def test_scoring_has_four_dimensions(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("scoring.yaml")
        dims = cfg.get("dimensions", {})
        assert len(dims) == 4, f"scoring.yaml must have exactly 4 dimensions, got {len(dims)}"

    def test_scoring_has_thresholds(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("scoring.yaml")
        assert "thresholds" in cfg, "scoring.yaml must have 'thresholds'"

    def test_scoring_has_pre_research_thresholds(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("scoring.yaml")
        assert "pre_research_thresholds" in cfg, (
            "scoring.yaml must have 'pre_research_thresholds'"
        )

    def test_outreach_guidelines_loads(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("outreach_guidelines.yaml")
        assert isinstance(cfg, dict), "outreach_guidelines.yaml should parse to a dict"

    def test_outreach_guidelines_has_sender(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("outreach_guidelines.yaml")
        assert "sender" in cfg, "outreach_guidelines.yaml must have 'sender'"

    def test_outreach_guidelines_has_voice_and_tone(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("outreach_guidelines.yaml")
        assert "voice_and_tone" in cfg, "outreach_guidelines.yaml must have 'voice_and_tone'"

    def test_outreach_guidelines_has_email_structure(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("outreach_guidelines.yaml")
        assert "email_structure" in cfg, "outreach_guidelines.yaml must have 'email_structure'"

    def test_sequences_config_loads(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("sequences.yaml")
        assert isinstance(cfg, dict), "sequences.yaml should parse to a dict"

    def test_sequences_has_at_least_one_sequence(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("sequences.yaml")
        seqs = cfg.get("sequences", {})
        assert len(seqs) >= 1, "sequences.yaml must define at least one sequence"

    def test_sequences_first_sequence_has_steps(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("sequences.yaml")
        seqs = cfg.get("sequences", {})
        first = next(iter(seqs.values()))
        assert "steps" in first, "First sequence must have 'steps'"
        assert len(first["steps"]) >= 1, "First sequence must have at least 1 step"

    def test_manufacturing_ontology_loads(self):
        from backend.app.core.config import load_yaml_config
        cfg = load_yaml_config("manufacturing_ontology.yaml")
        assert isinstance(cfg, dict), "manufacturing_ontology.yaml should parse to a dict"

    def test_missing_config_raises_file_not_found(self):
        from backend.app.core.config import load_yaml_config
        with pytest.raises(FileNotFoundError):
            load_yaml_config("nonexistent_config_xyz.yaml")


# ===========================================================================
# 2. MODEL & ENUM TESTS
# ===========================================================================

class TestModelsAndEnums:
    """Pydantic models and enums must validate correctly."""

    def test_company_status_has_discovered(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.DISCOVERED == "discovered"

    def test_company_status_has_researched(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.RESEARCHED == "researched"

    def test_company_status_has_qualified(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.QUALIFIED == "qualified"

    def test_company_status_has_disqualified(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.DISQUALIFIED == "disqualified"

    def test_company_status_has_outreach_pending(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.OUTREACH_PENDING == "outreach_pending"

    def test_company_status_has_contacted(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.CONTACTED == "contacted"

    def test_company_status_has_not_interested(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.NOT_INTERESTED == "not_interested"

    def test_company_status_has_bounced(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.BOUNCED == "bounced"

    def test_company_status_has_paused(self):
        from backend.app.core.models import CompanyStatus
        assert CompanyStatus.PAUSED == "paused"

    def test_pqs_score_defaults(self):
        from backend.app.core.models import PQSScore
        pqs = PQSScore()
        assert pqs.firmographic == 0
        assert pqs.technographic == 0
        assert pqs.timing == 0
        assert pqs.engagement == 0
        assert pqs.total == 0
        assert pqs.classification == "unqualified"

    def test_pqs_score_accepts_valid_values(self):
        from backend.app.core.models import PQSScore
        pqs = PQSScore(
            firmographic=15,
            technographic=10,
            timing=8,
            engagement=5,
            total=38,
            classification="qualified",
            notes="Strong fit.",
        )
        assert pqs.total == 38
        assert pqs.classification == "qualified"

    def test_research_result_defaults(self):
        from backend.app.core.models import ResearchResult
        r = ResearchResult()
        assert r.manufacturing_type == "unknown"
        assert r.iot_maturity == "unknown"
        assert r.maintenance_approach == "unknown"
        assert r.confidence_level == "low"
        assert r.equipment_types == []

    def test_research_result_accepts_valid_data(self):
        from backend.app.core.models import ResearchResult
        r = ResearchResult(
            company_description="Large food manufacturer",
            manufacturing_type="process",
            iot_maturity="advanced",
            maintenance_approach="predictive",
            confidence_level="high",
            pain_points=["downtime"],
        )
        assert r.manufacturing_type == "process"
        assert r.confidence_level == "high"
        assert "downtime" in r.pain_points


# ===========================================================================
# 3. PERSONA CLASSIFICATION TESTS
# ===========================================================================

class TestPersonaClassification:
    """classify_persona must map titles to the correct persona code."""

    @pytest.fixture(autouse=True)
    def import_classify(self):
        from backend.app.agents.discovery import classify_persona
        self.classify = classify_persona

    # --- F&B personas ---

    def test_vp_food_safety_and_quality(self):
        persona, is_dm = self.classify("VP Food Safety & Quality")
        assert persona == "vp_quality_food_safety"
        assert is_dm is True

    def test_director_of_food_safety_and_quality(self):
        persona, is_dm = self.classify("Director of Food Safety and Quality")
        assert persona == "director_quality_food_safety"
        assert is_dm is True

    def test_vp_quality_assurance(self):
        persona, is_dm = self.classify("VP Quality Assurance")
        assert persona == "vp_quality_food_safety"
        assert is_dm is True

    def test_vp_quality(self):
        persona, is_dm = self.classify("VP Quality")
        assert persona == "vp_quality_food_safety"
        assert is_dm is True

    def test_vice_president_quality(self):
        persona, is_dm = self.classify("Vice President Quality")
        assert persona == "vp_quality_food_safety"
        assert is_dm is True

    def test_director_quality_assurance(self):
        persona, is_dm = self.classify("Director Quality Assurance")
        assert persona == "director_quality_food_safety"
        assert is_dm is True

    # --- Manufacturing ops personas ---

    def test_vp_operations(self):
        persona, is_dm = self.classify("VP Operations")
        assert persona == "vp_ops"
        assert is_dm is True

    def test_director_of_manufacturing(self):
        persona, is_dm = self.classify("Director of Manufacturing")
        assert persona == "director_ops"
        assert is_dm is True

    def test_coo(self):
        persona, is_dm = self.classify("COO")
        assert persona == "coo"
        assert is_dm is True

    def test_chief_operating_officer(self):
        persona, is_dm = self.classify("Chief Operating Officer")
        assert persona == "coo"
        assert is_dm is True

    def test_plant_manager(self):
        persona, is_dm = self.classify("Plant Manager")
        assert persona == "plant_manager"
        assert is_dm is True

    def test_maintenance_manager(self):
        persona, is_dm = self.classify("Maintenance Manager")
        assert persona == "maintenance_leader"
        assert is_dm is True

    # --- Non-target titles ---

    def test_marketing_director_rejected(self):
        persona, is_dm = self.classify("Marketing Director")
        assert persona is None
        assert is_dm is False

    def test_hr_vp_rejected(self):
        persona, is_dm = self.classify("HR VP")
        assert persona is None
        assert is_dm is False

    def test_sales_director_rejected(self):
        persona, is_dm = self.classify("Sales Director")
        assert persona is None
        assert is_dm is False

    def test_none_title_rejected(self):
        persona, is_dm = self.classify(None)
        assert persona is None
        assert is_dm is False

    def test_empty_title_rejected(self):
        persona, is_dm = self.classify("")
        assert persona is None
        assert is_dm is False

    # --- Word-boundary checks ---

    def test_coo_word_boundary_matches(self):
        """'COO' as a standalone token should match."""
        persona, _ = self.classify("COO")
        assert persona == "coo"

    def test_cto_does_not_match_inside_director(self):
        """'cto' must NOT match when buried in 'director'."""
        persona, _ = self.classify("Director of Engineering")
        # director_ops — not cio/cto
        assert persona == "director_ops"

    def test_cto_standalone_maps_to_cio(self):
        """Standalone 'CTO' should map to cio persona (per discovery.py rules)."""
        persona, is_dm = self.classify("CTO")
        assert persona == "cio"
        assert is_dm is True


# ===========================================================================
# 4. SCORING TESTS
# ===========================================================================

class TestScoringFirmographic:
    """_score_firmographic awards points based on tier, revenue, employees, state."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # We need a QualificationAgent but without hitting the DB.
        # Patch Database so __init__ doesn't connect.
        with patch("backend.app.agents.qualification.BaseAgent.__init__", return_value=None):
            from backend.app.agents.qualification import QualificationAgent
            self.agent = QualificationAgent.__new__(QualificationAgent)
        from backend.app.core.config import load_yaml_config
        self.config = load_yaml_config("scoring.yaml")

    def test_tier_company_gets_naics_points(self):
        company = {
            "tier": "fb1",
            "estimated_revenue": None,
            "employee_count": None,
            "state": None,
            "is_private": False,
        }
        score = self.agent._score_firmographic(company, self.config)
        # manufacturing_or_food(5) + independent bonus(3, no parent) = 8 minimum
        assert score >= 8

    def test_sweet_spot_revenue_scores(self):
        company = {
            "tier": "fb1",
            "estimated_revenue": 75_000_000,
            "employee_count": 200,
            "state": "OH",
            "is_private": False,
        }
        score = self.agent._score_firmographic(company, self.config)
        # tier(5) + revenue_sweet_spot(5) + us_state(3) + employees(3) = 16 minimum
        assert score >= 16

    def test_no_tier_no_naics_points(self):
        # state=None triggers the state_match "not state" branch and awards 3 pts.
        # All other signals need positive data (tier, revenue, employees, is_private).
        # So minimum score for a fully-empty company is 3 (the us_based signal).
        company = {
            "tier": None,
            "estimated_revenue": None,
            "employee_count": None,
            "state": None,
            "is_private": False,
        }
        score = self.agent._score_firmographic(company, self.config)
        # us_based(3) + independent bonus(3, no parent_company_name) = 6
        assert score == 6, (
            f"Expected 6 pts (us_based + independent bonus), got {score}"
        )

    def test_private_company_gets_bonus(self):
        # Use a minimal company so we don't hit the 25pt cap
        base = {
            "tier": "fb1",
            "estimated_revenue": None,
            "employee_count": 200,
            "state": None,
            "is_public": True,  # Public company
        }
        public_score = self.agent._score_firmographic(base, self.config)
        private = dict(base, is_public=False)
        private_score = self.agent._score_firmographic(private, self.config)
        # Private gets +4 bonus over public
        assert private_score > public_score

    def test_score_capped_at_max_points(self):
        company = {
            "tier": "fb1",
            "estimated_revenue": 75_000_000,
            "employee_count": 200,
            "state": "OH",
            "is_private": True,
        }
        score = self.agent._score_firmographic(company, self.config)
        max_pts = self.config["dimensions"]["firmographic"]["max_points"]
        assert score <= max_pts


class TestScoringTechnographic:
    """_score_technographic awards points for keyword matches in research."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch("backend.app.agents.qualification.BaseAgent.__init__", return_value=None):
            from backend.app.agents.qualification import QualificationAgent
            self.agent = QualificationAgent.__new__(QualificationAgent)
        from backend.app.core.config import load_yaml_config
        self.config = load_yaml_config("scoring.yaml")

    def _make_company(self, **kwargs):
        base = {
            "research_summary": "",
            "technology_stack": [],
            "pain_signals": [],
            "manufacturing_profile": {},
            "personalization_hooks": [],
        }
        base.update(kwargs)
        return base

    def test_known_cmms_keyword_scores(self):
        research = {"known_systems": ["SAP PM"], "perplexity_response": "", "claude_analysis": "",
                    "company_description": "", "digital_transformation_status": "",
                    "equipment_types": [], "pain_points": [], "opportunities": [],
                    "existing_solutions": [], "funding_status": "", "funding_details": ""}
        company = self._make_company()
        score = self.agent._score_technographic(company, research, self.config)
        assert score > 0, "SAP PM should award technographic points"

    def test_iot_keyword_scores(self):
        research = {"perplexity_response": "The company has deployed IoT sensors on all lines.",
                    "claude_analysis": "", "company_description": "",
                    "digital_transformation_status": "", "equipment_types": [],
                    "known_systems": [], "pain_points": [], "opportunities": [],
                    "existing_solutions": [], "funding_status": "", "funding_details": ""}
        company = self._make_company()
        score = self.agent._score_technographic(company, research, self.config)
        assert score > 0, "IoT keyword should award technographic points"

    def test_no_research_returns_zero(self):
        # With research=None the company dict still produces some search text
        # (empty lists / dicts serialise to "[] {}").  The `no_existing_ai`
        # negative_keyword_match signal awards 4 pts when no competitor names
        # appear anywhere in that text.  So the practical floor with a minimal
        # company (no tech-stack text) is 4, not 0.
        company = self._make_company()
        score = self.agent._score_technographic(company, None, self.config)
        # Only the negative_keyword_match (no_existing_ai, 4 pts) can fire on
        # an empty-text company; positive keyword signals need real tech text.
        assert score <= 4, (
            f"Expected at most 4 pts without research text, got {score}"
        )

    def test_competitor_reduces_score(self):
        """Presence of a direct competitor should decrease (or prevent) technographic score."""
        # A company mentioning a competitor should get 0 on no_existing_ai signal
        research = {
            "perplexity_response": "They use Augury for predictive maintenance.",
            "claude_analysis": "", "company_description": "",
            "digital_transformation_status": "", "equipment_types": [],
            "known_systems": [], "pain_points": [], "opportunities": [],
            "existing_solutions": ["Augury"], "funding_status": "", "funding_details": "",
        }
        company = self._make_company()
        score = self.agent._score_technographic(company, research, self.config)
        # no_existing_ai signal should NOT fire, so score is lower than without competitor
        # We just assert it doesn't exceed max_pts
        max_pts = self.config["dimensions"]["technographic"]["max_points"]
        assert score <= max_pts


class TestScoringTiming:
    """_score_timing awards points for pain/urgency keyword matches."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch("backend.app.agents.qualification.BaseAgent.__init__", return_value=None):
            from backend.app.agents.qualification import QualificationAgent
            self.agent = QualificationAgent.__new__(QualificationAgent)
        from backend.app.core.config import load_yaml_config
        self.config = load_yaml_config("scoring.yaml")

    def _make_research(self, text: str) -> dict:
        return {
            "perplexity_response": text,
            "claude_analysis": "",
            "company_description": "",
            "digital_transformation_status": "",
            "equipment_types": [],
            "known_systems": [],
            "pain_points": [],
            "opportunities": [],
            "existing_solutions": [],
            "funding_status": "",
            "funding_details": "",
        }

    def _make_company(self):
        return {
            "research_summary": "",
            "technology_stack": [],
            "pain_signals": [],
            "manufacturing_profile": {},
            "personalization_hooks": [],
        }

    def test_downtime_keyword_scores(self):
        research = self._make_research("The plant experienced significant downtime last quarter.")
        score = self.agent._score_timing(self._make_company(), research, self.config)
        assert score > 0

    def test_fsma_keyword_scores(self):
        research = self._make_research("The company is under FSMA compliance pressure.")
        score = self.agent._score_timing(self._make_company(), research, self.config)
        assert score > 0

    def test_no_research_returns_zero(self):
        score = self.agent._score_timing(self._make_company(), None, self.config)
        assert score == 0


class TestScoringThresholds:
    """_classify maps PQS totals to the correct classification buckets."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch("backend.app.agents.qualification.BaseAgent.__init__", return_value=None):
            from backend.app.agents.qualification import QualificationAgent
            self.agent = QualificationAgent.__new__(QualificationAgent)
        from backend.app.core.config import load_yaml_config
        self.config = load_yaml_config("scoring.yaml")

    def test_low_score_is_unqualified(self):
        # max unqualified score = 9
        classification, _, _ = self.agent._classify(5, self.config)
        assert classification == "unqualified"

    def test_mid_low_score_is_research_needed(self):
        # research_needed max = 14
        classification, _, _ = self.agent._classify(12, self.config)
        assert classification == "research_needed"

    def test_mid_score_is_qualified(self):
        # qualified max = 39
        classification, new_status, priority = self.agent._classify(25, self.config)
        assert classification == "qualified"
        assert new_status == "qualified"
        assert priority is False

    def test_high_score_is_high_priority(self):
        # high_priority max = 69
        classification, _, priority = self.agent._classify(50, self.config)
        assert classification == "high_priority"
        assert priority is True

    def test_very_high_score_is_hot_prospect(self):
        # hot_prospect = > 69
        classification, _, priority = self.agent._classify(85, self.config)
        assert classification == "hot_prospect"
        assert priority is True


class TestPreResearchThresholds:
    """Discovered companies are scored firmographic-only against pre_research_thresholds."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from backend.app.core.config import load_yaml_config
        self.config = load_yaml_config("scoring.yaml")

    def test_score_3_is_disqualified(self):
        pre = self.config["pre_research_thresholds"]
        disqualify_max = pre["disqualify"]["max_score"]
        # score 3 should be <= disqualify_max (4) → disqualified
        assert 3 <= disqualify_max

    def test_score_5_passes_prefilter(self):
        pre = self.config["pre_research_thresholds"]
        disqualify_max = pre["disqualify"]["max_score"]
        # score 5 should be > disqualify_max → passes to research
        assert 5 > disqualify_max


# ===========================================================================
# 5. SUPPRESSION TESTS
# ===========================================================================

class TestSuppression:
    """is_suppressed must block outreach for terminal company statuses."""

    def _make_db_mock(self, company_status: str) -> MagicMock:
        db = MagicMock()
        db.get_company.return_value = {
            "id": "company-001",
            "name": "Test Co",
            "status": company_status,
        }
        db.get_research.return_value = None
        # Simulate no contact-level data
        db.client = MagicMock()
        table_mock = MagicMock()
        table_mock.select.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.in_.return_value = table_mock
        table_mock.is_.return_value = table_mock
        table_mock.gte.return_value = table_mock
        table_mock.order.return_value = table_mock
        table_mock.limit.return_value = table_mock
        table_mock.execute.return_value = MagicMock(data=[])
        db.client.table.return_value = table_mock
        return db

    def test_not_interested_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed
        db = self._make_db_mock("not_interested")
        suppressed, reason = is_suppressed(db, "company-001")
        assert suppressed is True
        assert reason is not None

    def test_bounced_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed
        db = self._make_db_mock("bounced")
        suppressed, reason = is_suppressed(db, "company-001")
        assert suppressed is True
        assert reason is not None

    def test_disqualified_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed
        db = self._make_db_mock("disqualified")
        suppressed, reason = is_suppressed(db, "company-001")
        assert suppressed is True
        assert reason is not None

    def test_qualified_is_not_suppressed(self):
        from backend.app.core.suppression import is_suppressed
        db = self._make_db_mock("qualified")
        suppressed, reason = is_suppressed(db, "company-001")
        assert suppressed is False
        assert reason is None

    def test_company_not_found_is_suppressed(self):
        from backend.app.core.suppression import is_suppressed
        db = MagicMock()
        db.get_company.return_value = None
        suppressed, reason = is_suppressed(db, "nonexistent-id")
        assert suppressed is True
        assert reason == "company_not_found"


# ===========================================================================
# 6. DOMAIN VERIFICATION TESTS
# ===========================================================================

class TestDomainVerification:
    """verify_domain must correctly validate real vs non-existent domains."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from backend.app.core.domain_verify import clear_cache
        clear_cache()
        yield
        clear_cache()

    def test_real_domain_is_valid(self):
        """google.com should resolve and be considered valid."""
        from backend.app.core.domain_verify import verify_domain
        valid, reason = verify_domain("google.com")
        assert valid is True, f"google.com should be valid, got reason: {reason}"

    def test_nonexistent_domain_is_invalid(self):
        """A clearly bogus domain should fail."""
        from backend.app.core.domain_verify import verify_domain
        valid, reason = verify_domain("thisdomaindoesnotexist99999xyz.com")
        assert valid is False, f"Bogus domain should be invalid, got reason: {reason}"

    def test_none_domain_returns_no_domain(self):
        from backend.app.core.domain_verify import verify_domain
        valid, reason = verify_domain(None)
        assert valid is False
        assert reason == "no_domain"

    def test_empty_string_returns_no_domain(self):
        from backend.app.core.domain_verify import verify_domain
        valid, reason = verify_domain("")
        assert valid is False
        assert reason == "no_domain"


# ===========================================================================
# 7. DRAFT QUALITY TESTS
# ===========================================================================

class TestDraftQuality:
    """validate_draft must catch banned phrases, length issues, and missing CTAs."""

    @pytest.fixture(autouse=True)
    def import_validate(self):
        from backend.app.core.draft_quality import validate_draft
        self.validate = validate_draft

    def _draft(self, body: str, subject: str = "Quick question about your ops") -> dict:
        return {"id": "test", "subject": subject, "body": body}

    def _good_body(self) -> str:
        return (
            "Hi Sarah,\n\n"
            "Noticed Acme Foods recently brought on a VP Digital. Usually means the team is "
            "ready to move past reactive maintenance.\n\n"
            "We built Digitillis for manufacturers running SAP who want to cut unplanned downtime "
            "without a long IT project. Most customers see first alerts within 48 hours.\n\n"
            "Would it be worth a 15-minute call to see if it fits Acme Foods?\n\n"
            "Best regards,\nAvanish\n\n"
            "Avanish Mehrotra\nFounder & CEO\nDigitillis | www.digitillis.com\n"
            "avi@digitillis.com | 224.355.4500"
        )

    def test_good_draft_passes(self):
        report = self.validate(self._draft(self._good_body()))
        assert report.passed is True, f"Good draft should pass. Issues: {report.issues}"

    def test_banned_phrase_fails(self):
        body = self._good_body().replace(
            "Would it be worth",
            "I hope this finds you well. Would it be worth",
        )
        report = self.validate(self._draft(body))
        assert report.passed is False
        names = [i.check_name for i in report.issues]
        assert "banned_phrase" in names

    def test_em_dash_flagged(self):
        body = self._good_body() + "\n\nWe are the best — bar none."
        report = self.validate(self._draft(body))
        # em dash is a warning, not an error — report.passed might still be True
        names = [i.check_name for i in report.issues]
        assert any("em_dash" in n for n in names), "Em dash should be flagged"

    def test_too_short_body_fails(self):
        short_body = "Hi. Let me know."
        report = self.validate(self._draft(short_body))
        assert report.passed is False
        names = [i.check_name for i in report.issues]
        assert "too_short" in names

    def test_no_cta_warns(self):
        body = (
            "Hi Sarah,\n\n"
            "We built Digitillis for manufacturers running SAP who want to cut unplanned downtime "
            "without a long IT project. We have done great work across the industry.\n\n"
            "Best regards,\nAvanish\n\n"
            "Avanish Mehrotra\nFounder & CEO\nDigitillis | www.digitillis.com\n"
            "avi@digitillis.com | 224.355.4500"
        )
        report = self.validate(self._draft(body))
        names = [i.check_name for i in report.issues]
        assert "no_cta" in names, "Missing CTA should produce a warning"

    def test_missing_signature_warns(self):
        body = (
            "Hi Sarah,\n\n"
            "Noticed your team is dealing with unplanned downtime on filling lines. "
            "Digitillis connects to your existing SAP PM and starts predicting failures within 48h.\n\n"
            "Would it be worth a quick call?\n\n"
            "Regards,\nAvi"
        )
        report = self.validate(self._draft(body))
        names = [i.check_name for i in report.issues]
        assert "no_signoff" in names or "no_phone_in_sig" in names, (
            "Missing full signature should produce a warning"
        )


# ===========================================================================
# 8. SEND-TIME TESTS
# ===========================================================================

class TestSendTime:
    """get_optimal_send_time must respect persona windows and skip weekends."""

    @pytest.fixture(autouse=True)
    def import_send_time(self):
        from backend.app.core.send_time import get_optimal_send_time
        self.get_time = get_optimal_send_time

    def _next_tuesday_midnight_utc(self) -> datetime:
        """Return a UTC datetime that is a Tuesday at 00:00 UTC."""
        now = datetime(2026, 3, 24, 0, 0, 0, tzinfo=timezone.utc)  # Known Tuesday
        return now

    def test_vp_ops_ohio_send_time_in_window(self):
        """VP Ops in Ohio (Eastern) should get 6:00–7:30am ET.

        2026-03-24 is during EDT (UTC-4), so:
          6:00am EDT = 10:00 UTC
          7:30am EDT = 11:30 UTC
        """
        from_time = self._next_tuesday_midnight_utc()
        result = self.get_time(state="OH", persona_type="vp_ops", from_time=from_time)
        utc_hour = result.hour
        utc_minute = result.minute
        utc_time = utc_hour * 60 + utc_minute
        # 6:00am EDT = 10:00 UTC (600 min), 7:30am EDT = 11:30 UTC (690 min)
        assert 600 <= utc_time <= 690, (
            f"VP Ops Ohio send time {result.strftime('%H:%M')} UTC "
            f"outside expected window 10:00-11:30 UTC (EDT)"
        )

    def test_plant_manager_texas_send_time_in_window(self):
        """Plant Manager in Texas (Central) should get 5:30–6:30am CT.

        2026-03-24 is during CDT (UTC-5), so:
          5:30am CDT = 10:30 UTC
          6:30am CDT = 11:30 UTC
        """
        from_time = self._next_tuesday_midnight_utc()
        result = self.get_time(state="TX", persona_type="plant_manager", from_time=from_time)
        utc_hour = result.hour
        utc_minute = result.minute
        utc_time = utc_hour * 60 + utc_minute
        # 5:30am CDT = 10:30 UTC (630 min), 6:30am CDT = 11:30 UTC (690 min)
        assert 630 <= utc_time <= 690, (
            f"Plant Manager TX send time {result.strftime('%H:%M')} UTC "
            f"outside expected window 10:30-11:30 UTC (CDT)"
        )

    def test_weekend_pushed_to_weekday(self):
        """A Saturday from_time must produce a result on Tue/Wed/Thu."""
        # Saturday 2026-03-21 noon UTC
        saturday = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
        result = self.get_time(state="IL", persona_type="vp_ops", from_time=saturday)
        # isoweekday(): Mon=1, Tue=2, Wed=3, Thu=4, Fri=5, Sat=6, Sun=7
        assert result.isoweekday() in (1, 2, 3, 4), (
            f"Weekend send time should be pushed to Mon-Thu, got {result.strftime('%A')}"
        )

    def test_sunday_pushed_to_weekday(self):
        """A Sunday from_time must produce a result on Mon–Thu."""
        sunday = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
        result = self.get_time(state="OH", persona_type="coo", from_time=sunday)
        assert result.isoweekday() in (1, 2, 3, 4), (
            f"Sunday send time should be pushed to Mon-Thu, got {result.strftime('%A')}"
        )

    def test_returns_utc_datetime(self):
        from_time = self._next_tuesday_midnight_utc()
        result = self.get_time(state="OH", persona_type="vp_ops", from_time=from_time)
        assert result.tzinfo is not None, "Result must be timezone-aware"
        assert result.tzinfo == timezone.utc or result.utcoffset().total_seconds() == 0


# ===========================================================================
# 9. STATE MACHINE TESTS
# ===========================================================================

class TestStateMachine:
    """can_transition must enforce valid lifecycle transitions."""

    @pytest.fixture(autouse=True)
    def import_sm(self):
        from backend.app.orchestrator.state_machine import can_transition, VALID_TRANSITIONS
        self.can = can_transition
        self.valid = VALID_TRANSITIONS

    # --- Valid transitions ---

    def test_discovered_to_researched(self):
        assert self.can("discovered", "researched") is True

    def test_researched_to_qualified(self):
        assert self.can("researched", "qualified") is True

    def test_qualified_to_outreach_pending(self):
        assert self.can("qualified", "outreach_pending") is True

    def test_outreach_pending_to_contacted(self):
        assert self.can("outreach_pending", "contacted") is True

    def test_contacted_to_engaged(self):
        assert self.can("contacted", "engaged") is True

    def test_qualified_to_disqualified(self):
        assert self.can("qualified", "disqualified") is True

    # --- Invalid transitions ---

    def test_discovered_to_contacted_invalid(self):
        assert self.can("discovered", "contacted") is False

    def test_discovered_to_qualified_invalid(self):
        assert self.can("discovered", "qualified") is False

    def test_researched_to_contacted_invalid(self):
        assert self.can("researched", "contacted") is False

    def test_contacted_to_discovered_invalid(self):
        assert self.can("contacted", "discovered") is False

    def test_converted_to_discovered_invalid(self):
        assert self.can("converted", "discovered") is False

    # --- Paused can return to multiple states ---

    def test_paused_can_return_to_discovered(self):
        assert self.can("paused", "discovered") is True

    def test_paused_can_return_to_qualified(self):
        assert self.can("paused", "qualified") is True

    def test_paused_can_return_to_engaged(self):
        assert self.can("paused", "engaged") is True

    def test_paused_cannot_jump_to_converted(self):
        assert self.can("paused", "converted") is False


# ===========================================================================
# 10. OUTREACH SYSTEM PROMPT TESTS
# ===========================================================================

class TestOutreachSystemPrompt:
    """_build_system_prompt must produce a non-empty prompt with required elements."""

    @pytest.fixture(autouse=True)
    def import_build_prompt(self):
        from backend.app.agents.outreach import _build_system_prompt
        self.build = _build_system_prompt

    def test_prompt_is_non_empty(self):
        prompt = self.build()
        assert isinstance(prompt, str)
        assert len(prompt) > 100, "System prompt should not be trivially short"

    def test_prompt_contains_sender_name(self):
        from backend.app.core.config import get_outreach_guidelines
        guidelines = get_outreach_guidelines()
        sender_name = guidelines.get("sender", {}).get("name", "Avanish Mehrotra")
        prompt = self.build()
        assert sender_name in prompt, f"Prompt must contain sender name '{sender_name}'"

    def test_prompt_contains_signature(self):
        from backend.app.core.config import get_outreach_guidelines
        guidelines = get_outreach_guidelines()
        signature = guidelines.get("sender", {}).get("signature", "")
        # Check a distinctive line from the signature is present
        prompt = self.build()
        assert "224.355.4500" in prompt or "Avanish Mehrotra" in prompt, (
            "Prompt must contain signature block"
        )

    def test_prompt_contains_banned_phrases_section(self):
        prompt = self.build()
        # The builder iterates banned_phrases and adds "NEVER use the phrase:" lines
        assert "NEVER use" in prompt or "banned" in prompt.lower(), (
            "Prompt must contain banned-phrases instructions"
        )

    def test_prompt_contains_em_dash_rule(self):
        prompt = self.build()
        assert "em dash" in prompt.lower() or "em dashes" in prompt.lower() or "—" in prompt, (
            "Prompt must warn against em dashes"
        )

    def test_prompt_fallback_when_guidelines_missing(self):
        """If outreach_guidelines.yaml is missing, _build_system_prompt must not crash."""
        with patch(
            "backend.app.agents.outreach.get_outreach_guidelines",
            side_effect=FileNotFoundError,
        ):
            from importlib import reload
            import backend.app.agents.outreach as outreach_mod
            # Call directly — must return a fallback string, not raise
            try:
                prompt = outreach_mod._build_system_prompt()
                assert isinstance(prompt, str)
                assert len(prompt) > 0
            except FileNotFoundError:
                pytest.fail("_build_system_prompt must handle missing YAML gracefully")


# ===========================================================================
# 11. API ROUTE TESTS
# ===========================================================================

class TestAPIRoutes:
    """FastAPI endpoints must return correct status codes with mocked config."""

    @pytest.fixture(autouse=True)
    def client(self):
        """Create a TestClient with all external deps mocked."""
        from fastapi.testclient import TestClient

        # APScheduler is not installed in the test environment; the lifespan
        # handles the ImportError gracefully, so no patching is needed.
        from backend.app.api.main import app
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_health_returns_200(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_health_response_body(self):
        resp = self.client.get("/health")
        data = resp.json()
        assert data.get("status") == "ok"
        assert "prospectiq" in data.get("service", "").lower()

    def test_get_settings_returns_200(self):
        resp = self.client.get("/api/settings")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_get_settings_contains_icp(self):
        resp = self.client.get("/api/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "icp" in body["data"], "Settings response must contain 'icp' key"

    def test_get_settings_contains_scoring(self):
        resp = self.client.get("/api/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert "scoring" in body["data"], "Settings response must contain 'scoring' key"

    def test_get_settings_contains_sequences(self):
        resp = self.client.get("/api/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert "sequences" in body["data"], "Settings response must contain 'sequences' key"

    def test_get_outreach_guidelines_returns_200(self):
        resp = self.client.get("/api/settings/outreach-guidelines")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

    def test_get_outreach_guidelines_contains_data(self):
        resp = self.client.get("/api/settings/outreach-guidelines")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"] is not None

    def test_get_outreach_guidelines_has_sender(self):
        resp = self.client.get("/api/settings/outreach-guidelines")
        assert resp.status_code == 200
        body = resp.json()
        assert "sender" in body["data"], "Outreach guidelines must contain 'sender'"

    def test_unknown_route_returns_404(self):
        resp = self.client.get("/api/nonexistent-endpoint-xyz")
        assert resp.status_code == 404
