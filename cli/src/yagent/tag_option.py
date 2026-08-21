"""Shared repeatable-tag CLI flag plumbing (see todo 3245).

`-t/--tags` options that accept tags are `multiple=True` click options: each
occurrence is a raw string that may itself be a comma-separated list. This
module unions every occurrence's comma-split elements into one deduplicated,
order-preserving list.

Server-side `normalize_tags` (lowercase, `_`→`-`, trim, dedup) remains the
authority; `resolve_tags` only splits/trims/dedups and does not duplicate
case folding.
"""


def resolve_tags(values: tuple[str, ...]) -> list[str] | None:
    """Union-normalize repeated `-t` values (each possibly comma-separated).

    - `()` (flag never passed) → `None`, meaning "field not sent".
    - Any occurrence present, even `("",)` → a list (possibly empty `[]`),
      meaning "field sent" (an explicit clear on `update`).
    - Elements are stripped; empty elements are dropped; order-preserving
      dedup across all occurrences.
    """
    if not values:
        return None
    seen: dict[str, None] = {}
    for value in values:
        for part in value.split(','):
            tag = part.strip()
            if tag:
                seen[tag] = None
    return list(seen.keys())
