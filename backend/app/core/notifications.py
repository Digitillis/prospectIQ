"""Email notification service for ProspectIQ.

Sends transactional emails via the Resend API (plain HTTP, no SDK).
All functions are async and safe to fire-and-forget — errors are logged
but never raised to the caller.

Usage:
    from backend.app.core.notifications import notify_hot_prospect
    await notify_hot_prospect(
        company_name="Acme Corp",
        pqs_score=82,
        personalization_hooks=["Just hired a VP of Ops", "Using SAP"],
        workspace_email="you@yourdomain.com",
    )
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

_RESEND_EMAILS_URL = "https://api.resend.com/emails"
_DEFAULT_FROM = "ProspectIQ <notifications@prospectiq.ai>"


def _from_address() -> str:
    """Return the From address, preferring FROM_EMAIL env var."""
    return os.environ.get("FROM_EMAIL", _DEFAULT_FROM)


# ---------------------------------------------------------------------------
# Core send helper
# ---------------------------------------------------------------------------

async def send_email(to: str, subject: str, html_body: str) -> bool:
    """POST an email to the Resend API.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        html_body: Full HTML body string.

    Returns:
        True if the API returned 2xx, False otherwise.
    """
    settings = get_settings()
    api_key = settings.resend_api_key

    if not api_key:
        logger.warning(
            "resend_api_key is not configured — skipping email notification "
            "(set RESEND_API_KEY in .env to enable)"
        )
        return False

    payload: dict[str, Any] = {
        "from": _from_address(),
        "to": [to],
        "subject": subject,
        "html": html_body,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _RESEND_EMAILS_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            logger.info(
                f"Email sent via Resend: subject={subject!r} to={to!r} "
                f"status={response.status_code}"
            )
            return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            f"Resend API returned an error: status={exc.response.status_code} "
            f"body={exc.response.text[:300]!r} subject={subject!r} to={to!r}"
        )
    except httpx.RequestError as exc:
        logger.error(
            f"Network error sending email via Resend: {exc} "
            f"subject={subject!r} to={to!r}"
        )
    except Exception as exc:
        logger.error(
            f"Unexpected error in send_email: {exc} "
            f"subject={subject!r} to={to!r}",
            exc_info=True,
        )

    return False


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _base_template(title: str, body_html: str) -> str:
    """Wrap content in a simple, clean HTML shell with inline styles."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="max-width:600px;width:100%;border-radius:8px;overflow:hidden;
                      box-shadow:0 1px 3px rgba(0,0,0,.15);">

          <!-- Header -->
          <tr>
            <td style="background:#0f172a;padding:24px 32px;">
              <span style="color:#3b82f6;font-size:18px;font-weight:700;
                           letter-spacing:.5px;">ProspectIQ</span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="background:#ffffff;padding:32px;">
              {body_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;">
              <p style="margin:0;font-size:12px;color:#94a3b8;text-align:center;">
                ProspectIQ &mdash; AI-powered B2B prospecting
                &nbsp;&bull;&nbsp;
                <a href="https://prospectiq.ai" style="color:#3b82f6;text-decoration:none;">
                  prospectiq.ai
                </a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _heading(text: str) -> str:
    return (
        f'<h2 style="margin:0 0 16px;font-size:20px;font-weight:700;color:#0f172a;">'
        f"{text}</h2>"
    )


def _paragraph(text: str) -> str:
    return (
        f'<p style="margin:0 0 12px;font-size:15px;line-height:1.6;color:#334155;">'
        f"{text}</p>"
    )


def _badge(text: str, color: str = "#3b82f6") -> str:
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'font-size:13px;font-weight:600;padding:4px 12px;border-radius:9999px;">'
        f"{text}</span>"
    )


def _stat_row(label: str, value: str) -> str:
    return f"""
    <tr>
      <td style="padding:8px 0;font-size:14px;color:#64748b;border-bottom:1px solid #f1f5f9;">
        {label}
      </td>
      <td style="padding:8px 0;font-size:14px;font-weight:600;color:#0f172a;
                 text-align:right;border-bottom:1px solid #f1f5f9;">
        {value}
      </td>
    </tr>"""


def _cta_button(text: str, href: str = "https://prospectiq.ai") -> str:
    return f"""
    <p style="margin:24px 0 0;">
      <a href="{href}"
         style="display:inline-block;background:#3b82f6;color:#fff;font-size:15px;
                font-weight:600;padding:12px 28px;border-radius:6px;text-decoration:none;">
        {text}
      </a>
    </p>"""


# ---------------------------------------------------------------------------
# Notification functions
# ---------------------------------------------------------------------------

async def notify_hot_prospect(
    company_name: str,
    pqs_score: int,
    personalization_hooks: list[str],
    workspace_email: str,
) -> bool:
    """Fire when a company crosses the 70+ PQS threshold (hot_prospect bucket).

    Args:
        company_name: Display name of the company.
        pqs_score: The Prospect Quality Score (0-100).
        personalization_hooks: List of signal strings to show the rep.
        workspace_email: Recipient — workspace owner's email.

    Returns:
        True if the email was accepted by Resend, False otherwise.
    """
    score_color = "#16a34a" if pqs_score >= 85 else "#d97706"
    hooks_html = "".join(
        f'<li style="margin:4px 0;font-size:14px;color:#334155;">{hook}</li>'
        for hook in personalization_hooks
    ) or '<li style="color:#94a3b8;font-size:14px;">No signals recorded</li>'

    body = f"""
    {_heading(f"Hot prospect detected: {company_name}")}
    {_paragraph(
        f"{company_name} scored <strong>{pqs_score} / 100</strong> on the Prospect Quality Score "
        f"(hot threshold: 70+). Time to personalise your outreach."
    )}
    <p style="margin:0 0 8px;">
      {_badge(f"PQS {pqs_score}", color=score_color)}
    </p>
    <h3 style="margin:24px 0 8px;font-size:15px;font-weight:600;color:#0f172a;">
      Personalisation signals
    </h3>
    <ul style="margin:0;padding-left:20px;">
      {hooks_html}
    </ul>
    {_cta_button("View company in ProspectIQ")}
    """

    return await send_email(
        to=workspace_email,
        subject=f"Hot prospect: {company_name} scored {pqs_score} PQS",
        html_body=_base_template(f"Hot prospect: {company_name}", body),
    )


async def notify_reply_received(
    company_name: str,
    contact_name: str,
    reply_preview: str,
    workspace_email: str,
) -> bool:
    """Fire when the Instantly webhook delivers an email_replied event.

    Args:
        company_name: The company the replying contact belongs to.
        contact_name: Full name (or email) of the contact who replied.
        reply_preview: First ~300 chars of the reply body.
        workspace_email: Recipient — workspace owner's email.

    Returns:
        True if the email was accepted by Resend, False otherwise.
    """
    preview_safe = reply_preview[:300] if reply_preview else "(no preview available)"

    body = f"""
    {_heading(f"Reply from {contact_name}")}
    {_paragraph(
        f"<strong>{contact_name}</strong> at <strong>{company_name}</strong> "
        f"just replied to your outreach."
    )}
    <div style="background:#f8fafc;border-left:4px solid #3b82f6;
                padding:16px 20px;border-radius:0 6px 6px 0;margin:20px 0;">
      <p style="margin:0;font-size:14px;line-height:1.7;color:#475569;
                font-style:italic;">
        &ldquo;{preview_safe}&rdquo;
      </p>
    </div>
    {_paragraph("Log in to ProspectIQ to view the full thread and draft a personalised follow-up.")}
    {_cta_button("View reply & respond")}
    """

    return await send_email(
        to=workspace_email,
        subject=f"Reply from {contact_name} ({company_name})",
        html_body=_base_template(f"Reply from {contact_name}", body),
    )


async def notify_draft_ready_for_approval(
    count: int,
    workspace_email: str,
) -> bool:
    """Daily digest when more than 5 drafts are waiting for approval.

    Args:
        count: Number of drafts currently awaiting approval.
        workspace_email: Recipient — workspace owner's email.

    Returns:
        True if the email was accepted by Resend, False otherwise.
    """
    body = f"""
    {_heading(f"{count} drafts awaiting your approval")}
    {_paragraph(
        f"You have <strong>{count} outreach draft{'s' if count != 1 else ''}</strong> "
        f"queued up in ProspectIQ that need a quick review before they go out."
    )}
    {_paragraph(
        "Review and approve them now to keep your pipeline moving — "
        "approved drafts are sent on schedule."
    )}
    <table width="100%" cellpadding="0" cellspacing="0"
           style="margin:20px 0;border-radius:6px;overflow:hidden;
                  border:1px solid #e2e8f0;">
      <tbody>
        {_stat_row("Drafts pending approval", str(count))}
      </tbody>
    </table>
    {_cta_button(f"Review {count} draft{'s' if count != 1 else ''}")}
    """

    return await send_email(
        to=workspace_email,
        subject=f"Action needed: {count} outreach drafts await your approval",
        html_body=_base_template("Drafts awaiting approval", body),
    )


async def notify_workspace_invite(
    invitee_email: str,
    workspace_name: str,
    inviter_email: str,
    invite_url: str,
) -> bool:
    """Send a workspace invitation email.

    Args:
        invitee_email: Recipient — person being invited.
        workspace_name: Human-readable workspace name shown in email.
        inviter_email: Email of the person who sent the invite.
        invite_url: One-time acceptance URL containing the token.

    Returns:
        True if the email was accepted by Resend, False otherwise.
    """
    body = f"""
    {_heading(f"You've been invited to {workspace_name}")}
    {_paragraph(
        f"<strong>{inviter_email}</strong> has invited you to join "
        f"<strong>{workspace_name}</strong> on ProspectIQ."
    )}
    {_paragraph(
        "ProspectIQ is an AI-powered B2B prospecting platform that researches, "
        "qualifies, and drafts personalised outreach for your sales pipeline."
    )}
    {_cta_button("Accept invitation", href=invite_url)}
    {_paragraph(
        '<span style="font-size:13px;color:#94a3b8;">'
        "This invitation link expires in 7 days. "
        "If you weren't expecting this, you can safely ignore this email."
        "</span>"
    )}
    """

    return await send_email(
        to=invitee_email,
        subject=f"{inviter_email} invited you to {workspace_name} on ProspectIQ",
        html_body=_base_template(f"Invitation to {workspace_name}", body),
    )


async def notify_welcome(
    user_email: str,
    workspace_name: str,
    full_name: str,
) -> bool:
    """Welcome email sent immediately after a new workspace is created.

    Args:
        user_email: The new user's email address.
        workspace_name: The workspace name they chose.
        full_name: First name or display name (used in greeting).

    Returns:
        True if the email was accepted by Resend, False otherwise.
    """
    first_name = full_name.split()[0] if full_name else "there"

    body = f"""
    {_heading(f"Welcome to ProspectIQ, {first_name}!")}
    {_paragraph(
        f"Your workspace <strong>{workspace_name}</strong> is ready. "
        f"ProspectIQ will research, qualify, and draft personalised outreach "
        f"for your manufacturing sales pipeline — automatically."
    )}
    <h3 style="margin:24px 0 8px;font-size:15px;font-weight:600;color:#0f172a;">
      Get started in 3 steps
    </h3>
    <ol style="margin:0 0 20px;padding-left:20px;">
      <li style="margin:6px 0;font-size:14px;color:#334155;">
        <strong>Configure your ICP</strong> — set the industries and company sizes you target
      </li>
      <li style="margin:6px 0;font-size:14px;color:#334155;">
        <strong>Run your first pipeline</strong> — ProspectIQ finds and scores prospects automatically
      </li>
      <li style="margin:6px 0;font-size:14px;color:#334155;">
        <strong>Review &amp; approve drafts</strong> — send personalised emails with one click
      </li>
    </ol>
    {_paragraph(
        "Questions? Reply to this email or reach us at "
        '<a href="mailto:avi@digitillis.com" style="color:#3b82f6;">avi@digitillis.com</a>.'
    )}
    {_cta_button("Open your dashboard")}
    """

    return await send_email(
        to=user_email,
        subject=f"Welcome to ProspectIQ — your workspace is ready",
        html_body=_base_template("Welcome to ProspectIQ", body),
    )


async def notify_pipeline_health(
    total_companies: int,
    qualified: int,
    hot_prospects: int,
    weekly_outreach: int,
    workspace_email: str,
) -> bool:
    """Weekly pipeline health summary.

    Args:
        total_companies: Total companies tracked in the workspace.
        qualified: Companies that have cleared the ICP scoring threshold.
        hot_prospects: Companies in the hot_prospect bucket (PQS 70+).
        weekly_outreach: Emails sent or queued in the past 7 days.
        workspace_email: Recipient — workspace owner's email.

    Returns:
        True if the email was accepted by Resend, False otherwise.
    """
    qualification_rate = (
        round(qualified / total_companies * 100) if total_companies else 0
    )
    hot_rate = round(hot_prospects / qualified * 100) if qualified else 0

    body = f"""
    {_heading("Your weekly pipeline summary")}
    {_paragraph("Here's how your ProspectIQ pipeline looked over the past 7 days.")}

    <table width="100%" cellpadding="0" cellspacing="0"
           style="margin:20px 0;border-radius:6px;overflow:hidden;
                  border:1px solid #e2e8f0;">
      <tbody>
        {_stat_row("Total companies tracked", f"{total_companies:,}")}
        {_stat_row("Qualified (ICP match)", f"{qualified:,} &nbsp;({qualification_rate}%)")}
        {_stat_row("Hot prospects (PQS 70+)", f"{hot_prospects:,} &nbsp;({hot_rate}% of qualified)")}
        {_stat_row("Outreach this week", f"{weekly_outreach:,} emails")}
      </tbody>
    </table>

    {_paragraph(
        "Keep the momentum going — review your hot prospects and approve any pending drafts."
    )}
    {_cta_button("Open ProspectIQ dashboard")}
    """

    return await send_email(
        to=workspace_email,
        subject=f"Weekly pipeline: {hot_prospects} hot prospects, {weekly_outreach} emails sent",
        html_body=_base_template("Weekly pipeline summary", body),
    )
