"""Pure text normalisation helpers for recall matching."""

from __future__ import annotations

import re

NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
WHITESPACE = re.compile(r"\s+")

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "because",
        "contain",
        "contains",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "pack",
        "product",
        "recall",
        "recalled",
        "recalls",
        "the",
        "to",
        "with",
    }
)

TOKEN_SYNONYMS = {
    "groundnut": frozenset({"peanut"}),
    "peanut": frozenset({"groundnut"}),
    "sultana": frozenset({"dried", "vine", "fruit"}),
    "raisin": frozenset({"dried", "vine", "fruit"}),
    "currant": frozenset({"dried", "vine", "fruit"}),
}

PLURAL_EXCEPTIONS = {
    # A generic ``ies -> y`` rule would incorrectly turn this common food word
    # into ``browny`` and prevent an exact product match.
    "brownies": "brownie",
}


def _singularise(word: str) -> str:
    """Apply a deliberately small English plural fold."""
    if word in PLURAL_EXCEPTIONS:
        return PLURAL_EXCEPTIONS[word]

    if len(word) > 3 and word.endswith("ies"):
        return f"{word[:-3]}y"

    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]

    return word


def normalise_text(value: str) -> str:
    """Lowercase text, remove punctuation, collapse whitespace, and fold plurals."""
    lowered = value.lower()
    stripped = NON_ALPHANUMERIC.sub(" ", lowered)
    collapsed = WHITESPACE.sub(" ", stripped).strip()

    return " ".join(_singularise(word) for word in collapsed.split())


def tokenise(value: str) -> frozenset[str]:
    """Return meaningful normalised tokens plus cautious synonym expansions."""
    tokens = {token for token in normalise_text(value).split() if token and token not in STOPWORDS}

    expanded_tokens = set(tokens)

    for token in tokens:
        expanded_tokens.update(TOKEN_SYNONYMS.get(token, frozenset()))

    return frozenset(expanded_tokens)
