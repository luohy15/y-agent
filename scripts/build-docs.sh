#!/bin/bash
# Build docs output for the web SPA.
#   - copies docs/*.md to <out_dir>/
#   - generates <out_dir>/manifest.json with {slug, title, category?, order?} per doc
# Usage: scripts/build-docs.sh <out_dir>
set -euo pipefail

OUT_DIR="${1:-}"
if [ -z "$OUT_DIR" ]; then
    echo "Usage: $0 <out_dir>" >&2
    exit 1
fi

# Resolve repo root (the directory holding this script's parent)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCS_SRC="$REPO_ROOT/docs"

if [ ! -d "$DOCS_SRC" ]; then
    echo "build-docs: $DOCS_SRC not found" >&2
    exit 1
fi

# OUT_DIR may be relative; resolve relative to caller's CWD
mkdir -p "$OUT_DIR"
OUT_ABS="$(cd "$OUT_DIR" && pwd)"

# Clear stale files (keep dir itself)
find "$OUT_ABS" -mindepth 1 -maxdepth 1 -type f -delete 2>/dev/null || true

cp "$DOCS_SRC"/*.md "$OUT_ABS/"

python3 - "$DOCS_SRC" "$OUT_ABS" <<'PY'
import json
import os
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
out = Path(sys.argv[2])

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text):
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        fm[k] = v
    return fm, text[m.end():]


def first_h1(body):
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


items = []
for path in sorted(src.glob("*.md")):
    slug = path.stem
    text = path.read_text(encoding="utf-8")
    fm, body = parse_front_matter(text)
    title = fm.get("title") or first_h1(body) or slug
    item = {"slug": slug, "title": title}
    if fm.get("category"):
        item["category"] = fm["category"]
    if fm.get("order"):
        try:
            item["order"] = int(fm["order"])
        except ValueError:
            pass
    items.append(item)

# Stable order: by (category or "", order or 999, title)
items.sort(key=lambda it: (it.get("category") or "", it.get("order", 999), it["title"]))

(out / "manifest.json").write_text(
    json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"build-docs: wrote {len(items)} item(s) to {out}/manifest.json")
PY
