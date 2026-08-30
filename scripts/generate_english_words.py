#!/usr/bin/env python3
"""Generate storage/src/storage/data/english_words_10k.txt from wordfreq.

Generation-time only. Runtime never imports wordfreq.

  uv run --with wordfreq python scripts/generate_english_words.py
"""

from __future__ import annotations

import re
from pathlib import Path

from wordfreq import top_n_list

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "storage" / "src" / "storage" / "data" / "english_words_10k.txt"
WORD_RE = re.compile(r"^[a-z]+$")
KEEP_SINGLE = {"a", "i"}
TARGET = 10000
# Pull extra so regex / single-letter filtering still yields 10k.
POOL = 20000


def main() -> None:
    seen: set[str] = set()
    kept: list[str] = []
    for raw in top_n_list("en", POOL):
        word = raw.lower()
        if not WORD_RE.match(word):
            continue
        if len(word) == 1 and word not in KEEP_SINGLE:
            continue
        if word in seen:
            continue
        seen.add(word)
        kept.append(word)
        if len(kept) >= TARGET:
            break
    if len(kept) < TARGET:
        raise SystemExit(f"only got {len(kept)} words after filtering")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"wrote {len(kept)} words to {OUT}")


if __name__ == "__main__":
    main()
