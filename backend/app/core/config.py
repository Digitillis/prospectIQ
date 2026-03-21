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

    # Webhook
    webhook_secret: str = ""

    # Slack notifications (optional)
    slack_webhook_url: str = ""

    # App settings
    log_level: str = "INFO"
    batch_size: int = 10

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
