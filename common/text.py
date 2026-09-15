from __future__ import annotations

import re

_HASHTAG_RE = re.compile(r"(?<![\w#])#(\w*[^\W\d]\w*)")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
HASHTAG_NAME_RE = re.compile(r"^\w*[^\W\d]\w*$")


def extract_hashtags(text: str | None) -> list[str]:
    """Unique, lower-cased hashtags (without '#') in order of appearance."""
    seen: dict[str, None] = {}
    for tag in _HASHTAG_RE.findall(text or ""):
        seen.setdefault(tag.lower(), None)
    return list(seen)


def normalize_username(value: str) -> str:
    cleaned = (value or "").strip().lstrip("@").lower()
    if not USERNAME_RE.match(cleaned):
        raise ValueError(f"Invalid Instagram username {value!r}: use 1-30 letters, digits, '.' or '_'.")
    return cleaned


def normalize_hashtag(value: str) -> str:
    cleaned = (value or "").strip().lstrip("#").lower()
    if not cleaned or len(cleaned) > 100 or not HASHTAG_NAME_RE.match(cleaned):
        raise ValueError(f"Invalid hashtag {value!r}.")
    return cleaned
