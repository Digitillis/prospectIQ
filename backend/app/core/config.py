"""Configuration loader for ProspectIQ.

Loads YAML config files and environment variables.
Config files are in /config/ and are version-controlled.
"""

import os
from pathlib import Path
from functools import lru_cache

import yaml
from pydantic_settings import BaseSettings


# Project root is two levels up from this file (backend/app/core/config.py → prospectIQ/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class Settings(BaseSettings):
    """Environment-based settings loaded from .env file."""

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""  # anon key (for frontend/public access)
    supabase_service_key: str = ""  # service role key (for backend)

    # Anthropic (Claude)
    anthropic_api_key: str = ""

    # Perplexity
    perplexity_api_key: str = ""

    # Apollo.io
    apollo_api_key: str = ""

    # Instantly.ai
    instantly_api_key: str = ""

    # Resend
    resend_api_key: str = ""
    resend_webhook_secret: str = ""  # Set in Resend dashboard → Webhooks → Signing Secret

    # Webhook
    webhook_secret: str = ""

    # Slack notifications (optional)
    slack_webhook_url: str = ""

    # App settings
    log_level: str = "INFO"
    batch_size: int = 10

    # Outreach gating — set SEND_ENABLED=true in .env once mailbox warm-up completes.
    # When false, approved drafts are staged but never pushed to Instantly.
    send_enabled: bool = False

    # Send window — hours in UTC (Railway server runs UTC).
    # 8am–11am Chicago CDT (UTC-5) → SEND_WINDOW_START=13 SEND_WINDOW_END=16
    # 8am–11am Chicago CST (UTC-6, Nov–Mar) → SEND_WINDOW_START=14 SEND_WINDOW_END=17
    # Set both to 0 to disable the window check (send any time SEND_ENABLED is true).
    send_window_start: int = 0   # UTC hour to start sending (inclusive)
    send_window_end: int = 0     # UTC hour to stop sending (exclusive); 0 = no window

    # Auth — Supabase JWT secret (from Project Settings → API → JWT Secret)
    supabase_jwt_secret: str = ""

    # Default workspace for single-tenant / dev use
    default_workspace_id: str = "00000000-0000-0000-0000-000000000001"

    # Stripe billing
    stripe_secret_key: str = ""         # sk_live_... or sk_test_...
    stripe_webhook_secret: str = ""     # whsec_...
    app_base_url: str = "https://app.prospectiq.ai"

    # Stripe price IDs — set per environment after creating products in Stripe dashboard.
    # Monthly prices:
    stripe_price_starter: str = ""      # $1,500/mo
    stripe_price_growth: str = ""       # $3,500/mo
    stripe_price_scale: str = ""        # $7,500/mo
    stripe_price_api: str = ""          # $0.05/company (metered)
    # Annual prices (15% discount):
    stripe_price_starter_annual: str = ""
    stripe_price_growth_annual: str = ""
    stripe_price_scale_annual: str = ""

    # Unipile — LinkedIn automation
    unipile_api_key: str = ""
    unipile_account_id: str = ""        # LinkedIn account ID registered in Unipile
    unipile_dsn: str = ""               # Unipile DSN (e.g. api4.unipile.com:13453)
    unipile_webhook_secret: str = ""    # Shared secret for validating Unipile webhook calls

    # Gmail IMAP reply intake
    gmail_user: str = ""              # e.g. avi@digitillis.io
    gmail_app_password: str = ""      # App Password from myaccount.google.com/apppasswords

    # HubSpot CRM sync (optional)
    hubspot_api_key: str = ""           # Private app access token
    hubspot_portal_id: str = ""         # Numeric portal/account ID

    # Salesforce CRM sync (optional)
    salesforce_username: str = ""
    salesforce_password: str = ""
    salesforce_security_token: str = ""
    salesforce_domain: str = "login"    # "login" for production, "test" for sandbox
    salesforce_consumer_key: str = ""
    salesforce_consumer_secret: str = ""

    # Voyage AI — text embeddings for RAG memory store (free tier: 200M tokens/month)
    # Sign up at https://www.voyageai.com — no credit card required for free tier.
    # When not set, memory store falls back to PostgreSQL full-text search.
    voyage_api_key: str = ""

    # Sentry — error tracking and performance monitoring
    sentry_dsn: str = ""                # Get from Sentry project settings
    sentry_environment: str = "production"  # production | staging | development
    sentry_traces_sample_rate: float = 0.1  # 10% of transactions for performance monitoring

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.

    Loads from .env file first, then patches any values that were
    overridden by empty environment variables (e.g. ANTHROPIC_API_KEY
    set to '' by the shell).
    """
    from dotenv import dotenv_values

    settings = Settings()
    env_values = dotenv_values(PROJECT_ROOT / ".env")

    # Patch: if an env var is empty but .env has a value, use .env
    for field_name in settings.model_fields:
        env_key = field_name.upper()
        current = getattr(settings, field_name)
        file_val = env_values.get(env_key, "")
        if not current and file_val:
            object.__setattr__(settings, field_name, file_val)

    return settings


def load_yaml_config(filename: str) -> dict:
    """Load a YAML config file from the config directory.

    Args:
        filename: Name of the YAML file (e.g., 'icp.yaml')

    Returns:
        Parsed YAML as a dictionary.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
    """
    filepath = CONFIG_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Config file not found: {filepath}")

    with open(filepath, "r") as f:
        return yaml.safe_load(f)


@lru_cache()
def get_icp_config() -> dict:
    """Load ICP (Ideal Customer Profile) configuration."""
    return load_yaml_config("icp.yaml")


@lru_cache()
def get_scoring_config() -> dict:
    """Load PQS scoring configuration."""
    return load_yaml_config("scoring.yaml")


@lru_cache()
def get_sequences_config() -> dict:
    """Load engagement sequences configuration."""
    return load_yaml_config("sequences.yaml")


def get_outreach_guidelines() -> dict:
    """Load outreach guidelines configuration.

    NOT cached — always reads the latest version from disk so that
    edits from the dashboard are picked up immediately without restart.
    """
    return load_yaml_config("outreach_guidelines.yaml")


def get_content_guidelines() -> dict:
    """Load LinkedIn thought leadership content guidelines.

    NOT cached — reads fresh every time so dashboard edits take effect
    immediately without restarting the backend.
    """
    return load_yaml_config("content_guidelines.yaml")


def get_offer_context() -> dict:
    """Load ProspectIQ offer context — capabilities, proof points, differentiation.

    NOT cached — reads fresh every time so dashboard edits take effect
    immediately without restarting the backend.
    """
    return load_yaml_config("offer_context.yaml")


def get_linkedin_messages_guidelines() -> dict:
    """Load LinkedIn DM / connection note guidelines.

    NOT cached — reads fresh every time so dashboard edits take effect
    immediately without restarting the backend.
    """
    return load_yaml_config("linkedin_messages_guidelines.yaml")


@lru_cache()
def get_manufacturing_ontology() -> dict:
    """Load manufacturing ontology configuration."""
    return load_yaml_config("manufacturing_ontology.yaml")


def get_territory(state_code: str) -> str:
    """Deterministic territory lookup from state code.

    Args:
        state_code: Two-letter US state code (e.g., 'IL', 'OH')

    Returns:
        Territory name string.
    """
    ontology = get_manufacturing_ontology()
    territories = ontology.get("territories", {})

    for territory_name, territory_data in territories.items():
        if territory_name == "default":
            continue
        states = territory_data.get("states", [])
        if state_code.upper() in states:
            return territory_name

    return territories.get("default", "Southern US + International")
