"""Email HTML rendering utilities.

Converts plain-text email bodies to HTML so Resend delivers multipart
(text/plain + text/html) messages. Supports:
  - [Link text](https://url)  →  <a href="url">Link text</a>
  - Blank lines              →  paragraph breaks
  - Single newlines          →  <br>
  - Raw URLs (http/https)    →  auto-linked

All other content is HTML-escaped to prevent injection.
"""

from __future__ import annotations

import html
import re

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_RAW_URL_RE = re.compile(r'(?<!["\(])(https?://\S+?)(?=[)\s,]|$)')

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 14px; color: #222; line-height: 1.6; }}
  a {{ color: #1a73e8; }}
  p {{ margin: 0 0 12px 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def plain_to_html(text: str) -> str:
    """Convert a plain-text email body to an HTML string.

    Designed to be safe: HTML-escapes all content before processing
    markdown-style links, so user input cannot inject arbitrary HTML.

    Args:
        text: Raw plain-text body (may contain [link](url) syntax).

    Returns:
        Complete HTML document string suitable for Resend's "html" field.
    """
    if not text:
        return _HTML_TEMPLATE.format(body="")

    # Split into paragraphs on blank lines first (preserves structure)
    paragraphs = re.split(r"\n\s*\n", text.strip())
    html_paragraphs = []

    for para in paragraphs:
        # Escape HTML entities in each paragraph
        escaped = html.escape(para)

        # Restore markdown links: [text](url) — applied AFTER escaping so the
        # url goes through html.escape (& → &amp; etc.) before we inject it.
        # Re-escape the url inside href to be safe.
        def _replace_link(m: re.Match) -> str:
            link_text = m.group(1)  # already escaped by html.escape above
            raw_url = html.unescape(m.group(2))  # unescape &amp; back for the href
            safe_url = html.escape(raw_url, quote=True)
            return f'<a href="{safe_url}">{link_text}</a>'

        escaped = _LINK_RE.sub(
            lambda m: _replace_link(m),
            escaped,
        )

        # Auto-link bare URLs that weren't already wrapped in [text](url)
        def _autolink(m: re.Match) -> str:
            raw_url = html.unescape(m.group(1))
            safe_url = html.escape(raw_url, quote=True)
            display = html.escape(raw_url)
            return f'<a href="{safe_url}">{display}</a>'

        escaped = _RAW_URL_RE.sub(_autolink, escaped)

        # Convert remaining newlines to <br>
        escaped = escaped.replace("\n", "<br>\n")
        html_paragraphs.append(f"<p>{escaped}</p>")

    body_html = "\n".join(html_paragraphs)
    return _HTML_TEMPLATE.format(body=body_html)
