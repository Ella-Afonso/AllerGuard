"""Thin optional summary phrasing over deterministic daily evidence."""

from collections.abc import Callable

from src.domain.diary import DiaryEntry
from src.domain.models import DraftSource

SummaryPolisher = Callable[[DiaryEntry], str]


def polish_diary(
    diary: DiaryEntry, polisher: SummaryPolisher | None = None, *, model_id: str = ""
) -> DiaryEntry:
    """Optional unverified narrative; typed facts remain the sole authority.

    No live model is configured by default. Runtime callers must opt in with
    a polisher and its actual model identifier. Any ordinary failure falls back.
    """
    if polisher is None or not model_id.strip():
        return diary
    try:
        summary = polisher(diary)
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 1000:
            return diary
        return DiaryEntry.model_validate(
            {
                **diary.model_dump(),
                "summary": summary,
                "summary_source": DraftSource.MODEL,
                "summary_model_id": model_id,
            }
        )
    except Exception:
        # Phrasing is optional; it never prevents the deterministic record being filed.
        return diary
