# Copyright © 2026 ProspectIQ. All rights reserved.
# Authors: Avanish Mehrotra & ProspectIQ Technical Team
"""Ghostwriting Engine — voice calibration and AI-powered content generation.

Generates LinkedIn posts and short-form thought leadership content calibrated
to the user's writing style, extracted from writing samples they provide.

Usage:
    engine = GhostwritingEngine()
    profile = await engine.calibrate_voice(workspace_id, samples)
    post = await engine.generate_post(workspace_id, topic="AI in manufacturing")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.core.database import Database
from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class VoiceProfile:
    """Extracted voice characteristics for a workspace."""

    def __init__(
        self,
        profile_id: str,
        workspace_id: str,
        writing_samples: list[str],
        tone: str,
        avg_sentence_length: str,
        vocabulary_level: str,
        structural_patterns: str,
        signature_phrases: list[str],
        calibrated_at: datetime | None,
    ):
        self.profile_id = profile_id
        self.workspace_id = workspace_id
        self.writing_samples = writing_samples
        self.tone = tone
        self.avg_sentence_length = avg_sentence_length
        self.vocabulary_level = vocabulary_level
        self.structural_patterns = structural_patterns
        self.signature_phrases = signature_phrases
        self.calibrated_at = calibrated_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "workspace_id": self.workspace_id,
            "writing_samples": self.writing_samples,
            "tone": self.tone,
            "avg_sentence_length": self.avg_sentence_length,
            "vocabulary_level": self.vocabulary_level,
            "structural_patterns": self.structural_patterns,
            "signature_phrases": self.signature_phrases,
            "calibrated_at": self.calibrated_at.isoformat() if self.calibrated_at else None,
        }


class GhostwrittenPost:
    """A single AI-generated post in the user's voice."""

    def __init__(
        self,
        post_id: str,
        workspace_id: str,
        topic: str,
        content_type: str,
        generated_content: str,
        hook_line: str,
        word_count: int,
        status: str,
        created_at: str | None = None,
    ):
        self.post_id = post_id
        self.workspace_id = workspace_id
        self.topic = topic
        self.content_type = content_type
        self.generated_content = generated_content
        self.hook_line = hook_line
        self.word_count = word_count
        self.status = status
        self.created_at = created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "post_id": self.post_id,
            "workspace_id": self.workspace_id,
            "topic": self.topic,
            "content_type": self.content_type,
            "generated_content": self.generated_content,
            "hook_line": self.hook_line,
            "word_count": self.word_count,
            "status": self.status,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Default voice (used when no profile exists)
# ---------------------------------------------------------------------------

_DEFAULT_VOICE_STYLE = {
    "tone": "authoritative",
    "avg_sentence_length": "medium",
    "vocabulary_level": "technical",
    "structural_patterns": "paragraphs",
    "signature_phrases": [],
}

_DEMO_TOPIC = "manufacturing digital transformation"

_CONTENT_TYPE_LABELS = {
    "linkedin_post": "LinkedIn post",
    "short_article": "short article",
    "thread": "LinkedIn thread",
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class GhostwritingEngine:
    """Voice calibration and content generation powered by Claude."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Voice calibration
    # ------------------------------------------------------------------

    async def calibrate_voice(
        self,
        workspace_id: str,
        samples: list[str],
    ) -> VoiceProfile:
        """Analyse writing samples and persist an extracted voice profile.

        Uses claude-sonnet-4-6 to extract tone, sentence length, vocabulary
        level, structural patterns, and up to 5 signature phrases.
        """
        import anthropic

        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)

        samples_text = "\n\n---\n\n".join(
            f"Sample {i + 1}:\n{s.strip()}" for i, s in enumerate(samples[:5])
        )

        prompt = f"""You are a writing style analyst. Analyse these writing samples and extract the author's voice profile.

{samples_text}

Return a JSON object with exactly these fields:
{{
  "tone": "<one of: formal | conversational | authoritative | inspiring>",
  "avg_sentence_length": "<one of: short | medium | long>",
  "vocabulary_level": "<one of: simple | technical | mixed>",
  "structural_patterns": "<one of: bullet_lists | paragraphs | numbered | mixed>",
  "signature_phrases": ["<phrase 1>", "<phrase 2>"]  // up to 5 characteristic phrases found verbatim or nearly verbatim in the samples
}}

Return only valid JSON. No explanation, no markdown fences."""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            style = json.loads(raw)
        except Exception as e:
            logger.warning(f"Voice calibration LLM call failed: {e} — using defaults")
            style = _DEFAULT_VOICE_STYLE.copy()

        now = datetime.now(timezone.utc)
        db = Database(workspace_id=workspace_id)

        # Upsert: one profile per workspace (update if exists, insert if not)
        existing = (
            db.client.table("voice_profiles")
            .select("id")
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
        )

        payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "writing_samples": samples[:5],
            "extracted_style": style,
            "calibrated_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        if existing.data:
            profile_id = existing.data[0]["id"]
            db.client.table("voice_profiles").update(payload).eq("id", profile_id).execute()
        else:
            result = db.client.table("voice_profiles").insert(payload).execute()
            profile_id = result.data[0]["id"]

        return VoiceProfile(
            profile_id=profile_id,
            workspace_id=workspace_id,
            writing_samples=samples[:5],
            tone=style.get("tone", "authoritative"),
            avg_sentence_length=style.get("avg_sentence_length", "medium"),
            vocabulary_level=style.get("vocabulary_level", "mixed"),
            structural_patterns=style.get("structural_patterns", "paragraphs"),
            signature_phrases=style.get("signature_phrases", [])[:5],
            calibrated_at=now,
        )

    # ------------------------------------------------------------------
    # Post generation
    # ------------------------------------------------------------------

    async def generate_post(
        self,
        workspace_id: str,
        topic: str,
        content_type: str = "linkedin_post",
        voice_profile_id: str | None = None,
        target_persona: str | None = None,
        include_cta: bool = True,
    ) -> GhostwrittenPost:
        """Generate content using the workspace's calibrated voice profile.

        Falls back to a demo post about manufacturing if no profile exists.
        """
        import anthropic

        profile = await self.get_voice_profile(workspace_id)
        style = _build_style_description(profile)

        content_label = _CONTENT_TYPE_LABELS.get(content_type, "LinkedIn post")
        audience_line = f"Target audience: {target_persona}." if target_persona else ""
        cta_line = "End with a natural, non-salesy call-to-action that invites engagement." if include_cta else "Do not include an explicit call-to-action."

        # Character guidance per type
        length_guidance = {
            "linkedin_post": "Keep it under 1,300 characters (ideal LinkedIn length).",
            "short_article": "Write 250–400 words.",
            "thread": "Write 5–8 short punchy posts, each separated by a blank line and numbered (1/, 2/, …).",
        }.get(content_type, "Keep it under 1,300 characters.")

        prompt = f"""You are a ghostwriter. Write a {content_label} about "{topic}" in this exact voice:

{style}

{audience_line}
{cta_line}
{length_guidance}

Rules:
- Sound like a real person, not a marketing department
- Do NOT use buzzwords like "synergy", "leverage", "game-changer" unless the voice profile uses them
- Keep it authentic and specific — avoid vague generalities
- Preserve any signature phrases from the voice profile where they fit naturally

Write only the post content. No preamble, no explanation."""

        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            generated_content = response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Post generation failed: {e}")
            generated_content = _demo_fallback_content(topic, content_type)

        hook_line = _extract_hook(generated_content)
        word_count = len(generated_content.split())
        now = datetime.now(timezone.utc)

        db = Database(workspace_id=workspace_id)
        insert_payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "voice_profile_id": (
                voice_profile_id
                or (profile.profile_id if profile else None)
            ),
            "topic": topic,
            "content_type": content_type,
            "generated_content": generated_content,
            "hook_line": hook_line,
            "word_count": word_count,
            "status": "draft",
            "created_at": now.isoformat(),
        }
        result = db.client.table("ghostwritten_posts").insert(insert_payload).execute()
        post_id = result.data[0]["id"]

        return GhostwrittenPost(
            post_id=post_id,
            workspace_id=workspace_id,
            topic=topic,
            content_type=content_type,
            generated_content=generated_content,
            hook_line=hook_line,
            word_count=word_count,
            status="draft",
            created_at=now.isoformat(),
        )

    # ------------------------------------------------------------------
    # Regeneration with feedback
    # ------------------------------------------------------------------

    async def regenerate(
        self,
        post_id: str,
        workspace_id: str,
        feedback: str,
    ) -> GhostwrittenPost:
        """Regenerate a post incorporating user feedback.

        Loads the original post and voice profile, then re-runs generation
        with the feedback directive appended.
        """
        import anthropic

        db = Database(workspace_id=workspace_id)
        result = (
            db.client.table("ghostwritten_posts")
            .select("*")
            .eq("id", post_id)
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise ValueError(f"Post {post_id} not found in workspace {workspace_id}")

        row = result.data[0]
        profile = await self.get_voice_profile(workspace_id)
        style = _build_style_description(profile)

        content_label = _CONTENT_TYPE_LABELS.get(row["content_type"], "LinkedIn post")
        prompt = f"""You are a ghostwriter. Here is a {content_label} you previously wrote:

---
{row['generated_content']}
---

The author wants you to revise it with this feedback: "{feedback}"

Rewrite the full post incorporating this feedback. Keep the same voice:

{style}

Write only the revised post content. No preamble."""

        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            generated_content = response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Regeneration failed: {e}")
            generated_content = row["generated_content"]

        hook_line = _extract_hook(generated_content)
        word_count = len(generated_content.split())

        db.client.table("ghostwritten_posts").update({
            "generated_content": generated_content,
            "hook_line": hook_line,
            "word_count": word_count,
        }).eq("id", post_id).execute()

        return GhostwrittenPost(
            post_id=post_id,
            workspace_id=workspace_id,
            topic=row["topic"],
            content_type=row["content_type"],
            generated_content=generated_content,
            hook_line=hook_line,
            word_count=word_count,
            status=row.get("status", "draft"),
            created_at=row.get("created_at"),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_posts(
        self,
        workspace_id: str,
        limit: int = 20,
    ) -> list[GhostwrittenPost]:
        """List generated posts for a workspace, newest first."""
        db = Database(workspace_id=workspace_id)
        result = (
            db.client.table("ghostwritten_posts")
            .select("*")
            .eq("workspace_id", workspace_id)
            .neq("status", "archived")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        posts = []
        for row in (result.data or []):
            posts.append(GhostwrittenPost(
                post_id=row["id"],
                workspace_id=row["workspace_id"],
                topic=row["topic"],
                content_type=row["content_type"],
                generated_content=row["generated_content"],
                hook_line=row.get("hook_line") or _extract_hook(row["generated_content"]),
                word_count=row.get("word_count") or len(row["generated_content"].split()),
                status=row.get("status", "draft"),
                created_at=row.get("created_at"),
            ))
        return posts

    async def get_voice_profile(self, workspace_id: str) -> VoiceProfile | None:
        """Return the workspace's calibrated voice profile, or None if not set."""
        db = Database(workspace_id=workspace_id)
        result = (
            db.client.table("voice_profiles")
            .select("*")
            .eq("workspace_id", workspace_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None

        row = result.data[0]
        style = row.get("extracted_style") or {}
        calibrated_at = None
        if row.get("calibrated_at"):
            try:
                calibrated_at = datetime.fromisoformat(row["calibrated_at"].replace("Z", "+00:00"))
            except Exception:
                pass

        return VoiceProfile(
            profile_id=row["id"],
            workspace_id=row["workspace_id"],
            writing_samples=row.get("writing_samples") or [],
            tone=style.get("tone", "authoritative"),
            avg_sentence_length=style.get("avg_sentence_length", "medium"),
            vocabulary_level=style.get("vocabulary_level", "mixed"),
            structural_patterns=style.get("structural_patterns", "paragraphs"),
            signature_phrases=style.get("signature_phrases", [])[:5],
            calibrated_at=calibrated_at,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_style_description(profile: VoiceProfile | None) -> str:
    """Convert a VoiceProfile into a plain-text style directive for the LLM."""
    if profile is None:
        return (
            "Tone: authoritative and professional. "
            "Sentence length: medium. "
            "Vocabulary: technical but accessible. "
            "Structure: well-formed paragraphs. "
            "No signature phrases."
        )

    phrases_line = (
        f"Characteristic phrases to echo where natural: {', '.join(repr(p) for p in profile.signature_phrases)}"
        if profile.signature_phrases
        else "No specific signature phrases identified."
    )

    return (
        f"Tone: {profile.tone}. "
        f"Sentence length: {profile.avg_sentence_length}. "
        f"Vocabulary level: {profile.vocabulary_level}. "
        f"Structural pattern: {profile.structural_patterns}. "
        f"{phrases_line}"
    )


def _extract_hook(content: str) -> str:
    """Extract the first sentence or line as the hook/preview."""
    # Try first sentence
    for delim in (".", "!", "?", "\n"):
        idx = content.find(delim)
        if idx > 20:
            return content[: idx + 1].strip()
    return content[:120].strip()


def _demo_fallback_content(topic: str, content_type: str) -> str:
    """Return a static fallback post when generation fails."""
    if content_type == "thread":
        return (
            "1/ Manufacturing plants don't have a data problem. They have a signal problem.\n\n"
            "2/ Every machine is already broadcasting what it needs. We just stopped listening.\n\n"
            "3/ Digital transformation isn't about replacing people — it's about giving them better ears.\n\n"
            "4/ The plants winning right now are the ones that treat sensor data as a first-class citizen.\n\n"
            "5/ What's your biggest barrier to acting on machine data in real time?"
        )
    return (
        f"Most conversations about {topic} start with technology. I think that's the wrong place to start.\n\n"
        "The plants I've seen transform fastest didn't buy new software first. They identified the one decision "
        "their operators make every shift that costs the most when it's wrong — and fixed that decision first.\n\n"
        "Technology follows clarity. Clarity doesn't follow technology.\n\n"
        "What's the one decision in your facility you'd most like better data for?"
    )
