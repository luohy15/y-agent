"""Resolve a Codex badge denominator from the model context-window table."""

from typing import Optional

from storage.repository import model_context_window as window_repo


def normalize_model_name(model) -> Optional[str]:
    """Exact model id after stripping spaces and wrapping double quotes."""
    if not isinstance(model, str):
        return None
    name = model.strip().strip('"').strip()
    return name or None


def get_context_window(model) -> Optional[int]:
    """Window for a resolved model, or None when it has no row.

    A query error propagates. The caller keeps the stored window in that case.
    """
    name = normalize_model_name(model)
    if name is None:
        return None
    return window_repo.get_by_model(name)
