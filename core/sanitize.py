"""
Input sanitization utilities.
Strips HTML tags and dangerous content from user-provided text fields.
"""
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"(?:javascript|data):", re.IGNORECASE)


def strip_tags(value):
    """Remove HTML tags from a string."""
    if not value:
        return value
    return _HTML_TAG_RE.sub("", str(value))


def sanitize_text(value, max_length=None):
    """Strip HTML tags and optionally truncate."""
    if not value:
        return value
    cleaned = strip_tags(str(value)).strip()
    # Remove javascript: and data: URI schemes
    cleaned = _SCRIPT_RE.sub("", cleaned)
    if max_length:
        cleaned = cleaned[:max_length]
    return cleaned
