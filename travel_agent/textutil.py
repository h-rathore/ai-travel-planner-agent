"""Small text helpers shared by the travel agent modules."""

import re
import unicodedata


def normalize(value) -> str:
    """Casefold, strip punctuation, collapse whitespace. Non-strings -> ''."""
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def has_phrase(normalized_text: str, phrase: str) -> bool:
    """True if `phrase` occurs in `normalized_text` as whole word(s).

    Unlike `phrase in text`, "art" does not match "heart" and "park" does
    not match "parking".
    """
    needle = normalize(phrase)
    if not needle:
        return False
    return (
        re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", normalized_text)
        is not None
    )


def tokens(value) -> frozenset:
    return frozenset(normalize(value).split())
