"""English vocabulary service: packaged list, seed, list, bulk mark, stats."""

from __future__ import annotations

from importlib import resources
from typing import Dict, List, Optional, Sequence, Tuple

from storage.dto.english_word import EnglishWord
from storage.repository import english_word as word_repo
from storage.repository.english_word import VALID_STATUSES

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
WORD_LIST_NAME = "english_words_10k.txt"


def load_ranked_words() -> List[Tuple[int, str]]:
    """Load the packaged frequency list. Rank is 1-based line number."""
    text = resources.files("storage.data").joinpath(WORD_LIST_NAME).read_text(encoding="utf-8")
    words = [line.strip() for line in text.splitlines() if line.strip()]
    return [(i, word) for i, word in enumerate(words, start=1)]


def seed_words(
    user_id: int,
    ranked: Optional[Sequence[Tuple[int, str]]] = None,
) -> Dict[str, int]:
    if ranked is None:
        ranked = load_ranked_words()
    cleaned: List[Tuple[int, str]] = []
    seen = set()
    for rank, word in ranked:
        w = (word or "").strip().lower()
        if not w or w in seen:
            continue
        seen.add(w)
        cleaned.append((int(rank), w))
    return word_repo.seed_words(user_id, cleaned)


def list_words(
    user_id: int,
    status: Optional[str] = None,
    max_rank: Optional[int] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> List[EnglishWord]:
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    return word_repo.list_words(
        user_id,
        status=status,
        max_rank=max_rank,
        limit=limit,
        offset=offset,
        on=on,
        from_=from_,
        to=to,
        created_on=created_on,
        created_from=created_from,
        created_to=created_to,
        updated_on=updated_on,
        updated_from=updated_from,
        updated_to=updated_to,
    )


def mark_words(
    user_id: int,
    status: str,
    word_ids: Optional[Sequence[str]] = None,
    words: Optional[Sequence[str]] = None,
) -> List[EnglishWord]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    ids = [w for w in (word_ids or []) if w]
    word_values = [w for w in (words or []) if w]
    if not ids and not word_values:
        raise ValueError("word_ids or words is required")
    return word_repo.mark_words(user_id, status, word_ids=ids, words=word_values)


def stats(user_id: int) -> Dict:
    return word_repo.stats(user_id)
