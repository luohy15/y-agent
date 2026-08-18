"""Markdown front-matter tag surgery for coordinated retags (todo 3219).

Ported from the one-off `migration/3159_tag_merge.py` helpers. The CLI owns the
on-disk half of `y tag rename` (same split as `y note import`): rewrite the
`tags` value in place, preserve quoting/body bytes, and fail closed on any
shape that cannot be rewritten safely.
"""

from __future__ import annotations

import re

import yaml


class FrontMatterError(Exception):
    """Raised when a file's front matter cannot be rewritten safely."""


FM_RE = re.compile(r"\A---\n(?P<fm>.*?)\n---(?=\n|\Z)", re.DOTALL)
TAGS_LINE_RE = re.compile(r"^(?P<key>tags[ \t]*:)(?P<value>.*)$")
BLOCK_ITEM_RE = re.compile(r"^(?P<indent>[ \t]+)-[ \t]*(?P<token>.*)$")


def apply_mapping(tags, mapping):
    """Expand mapped values in `tags` into their targets, dedupe, preserve order.

    Returns (new_tags, replaced, dropped) where `dropped` counts target values
    removed because they were already present on the carrier.
    """
    out, seen = [], set()
    replaced, dropped = [], []
    for tag in tags:
        if not isinstance(tag, str):
            out.append(tag)
            continue
        targets = mapping.get(tag)
        if targets is None:
            targets = [tag]
        else:
            replaced.append({"from": tag, "to": list(targets)})
        for new in targets:
            if new in seen:
                dropped.append({"from": tag, "to": new})
                continue
            seen.add(new)
            out.append(new)
    return out, replaced, dropped


def tags_of(value):
    """Normalize a raw tags payload (list or scalar) to a list for comparison."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def _substitute_token(raw, old_value, new_value):
    """Replace a scalar tag token's value, preserving its original quoting."""
    token = raw.strip()
    if token == old_value:
        return new_value
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        try:
            if yaml.safe_load(token) == old_value:
                return f"{token[0]}{new_value}{token[0]}"
        except yaml.YAMLError:
            pass
    raise FrontMatterError(f"cannot rewrite tag token {raw!r} (value {old_value!r})")


def _split_flow_items(inner):
    """Split a single-line YAML flow sequence body on top-level commas."""
    if any(ch in inner for ch in "[]{}"):
        raise FrontMatterError("nested flow structure in tags")
    if "#" in inner:
        raise FrontMatterError("comment inside tags value")
    items, buf, quote = [], "", None
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf += ch
            continue
        if ch == ",":
            items.append(buf)
            buf = ""
            continue
        buf += ch
    if quote:
        raise FrontMatterError("unterminated quote in tags value")
    if buf.strip() or items:
        items.append(buf)
    return items


def _verify_rewrite(text, new_text, new_fm, fm_end, parsed, new_tags, rendered_sequence):
    """Fail-closed check: front matter must round-trip; body bytes must survive."""
    try:
        reparsed = yaml.safe_load(new_fm)
    except yaml.YAMLError as exc:
        raise FrontMatterError(f"rewritten front matter does not parse: {exc}") from exc
    expected = dict(parsed)
    expected["tags"] = new_tags if rendered_sequence else new_tags[0]
    if reparsed != expected:
        raise FrontMatterError("rewritten front matter does not match the expected value")
    new_match = FM_RE.match(new_text)
    if not new_match or new_text[new_match.end("fm"):] != text[fm_end:]:
        raise FrontMatterError("body bytes would change")


def rewrite_front_matter_tags(text, mapping):
    """Rewrite only the `tags` value inside a markdown file's front matter.

    Returns None when nothing changes. Otherwise returns a dict with the new
    text plus before/after tag lists. Raises FrontMatterError when the file
    cannot be edited safely (the caller turns that into a blocker).
    """
    match = FM_RE.match(text)
    if not match:
        return None
    fm_start, fm_end = match.start("fm"), match.end("fm")
    fm_text = match.group("fm")
    if "\r" in fm_text:
        raise FrontMatterError("CRLF front matter is not supported")
    lines = fm_text.split("\n")
    hits = [i for i, line in enumerate(lines) if TAGS_LINE_RE.match(line)]
    # Fail closed on duplicate top-level `tags:` keys before consulting the
    # YAML-selected value: YAML keeps one of them, so an unmapped winner would
    # otherwise make an in-scope duplicate-key file look untouched.
    if len(hits) > 1:
        raise FrontMatterError(
            f"expected exactly one top-level `tags:` line, found {len(hits)}"
        )

    try:
        parsed = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise FrontMatterError(f"unparseable front matter: {exc}") from exc
    if not isinstance(parsed, dict) or "tags" not in parsed:
        return None

    old_raw = parsed["tags"]
    old_tags = tags_of(old_raw)
    if not any(isinstance(t, str) and t in mapping for t in old_tags):
        return None
    new_tags, replaced, dropped = apply_mapping(old_tags, mapping)
    if new_tags == old_tags:
        return None

    if len(hits) != 1:
        raise FrontMatterError(f"expected exactly one top-level `tags:` line, found {len(hits)}")
    idx = hits[0]
    m = TAGS_LINE_RE.match(lines[idx])
    key_part, value_part = m.group("key"), m.group("value")
    stripped = value_part.strip()

    if stripped.startswith("["):
        if not stripped.endswith("]"):
            raise FrontMatterError("multi-line flow sequence in tags")
        inner = stripped[1:-1]
        raw_items = _split_flow_items(inner)
        values = [yaml.safe_load(item.strip()) if item.strip() else None for item in raw_items]
        if values != old_tags:
            raise FrontMatterError("tags flow items do not round-trip to the parsed value")
        kept, seen = [], set()
        for raw_item, value in zip(raw_items, values):
            if not isinstance(value, str):
                kept.append(raw_item.strip())
                continue
            for new_value in mapping.get(value, [value]):
                if new_value in seen:
                    continue
                seen.add(new_value)
                kept.append(
                    _substitute_token(raw_item, value, new_value)
                    if new_value != value
                    else raw_item.strip()
                )
        new_line = f"{key_part} [{', '.join(kept)}]"
        new_lines = lines[:idx] + [new_line] + lines[idx + 1:]
        rendered_sequence = True

    elif stripped == "":
        end = idx + 1
        item_lines = []
        while end < len(lines):
            item = BLOCK_ITEM_RE.match(lines[end])
            if not item:
                break
            item_lines.append((end, item))
            end += 1
        if not item_lines:
            raise FrontMatterError("empty `tags:` key with no block items")
        values = []
        for _, item in item_lines:
            token = item.group("token")
            if "#" in token:
                raise FrontMatterError("comment inside tags block item")
            values.append(yaml.safe_load(token) if token.strip() else None)
        if values != old_tags:
            raise FrontMatterError("tags block items do not round-trip to the parsed value")
        kept_lines, seen = [], set()
        for (_, item), value in zip(item_lines, values):
            if not isinstance(value, str):
                kept_lines.append(f"{item.group('indent')}- {item.group('token')}")
                continue
            for new_value in mapping.get(value, [value]):
                if new_value in seen:
                    continue
                seen.add(new_value)
                token = (
                    _substitute_token(item.group("token"), value, new_value)
                    if new_value != value
                    else item.group("token")
                )
                kept_lines.append(f"{item.group('indent')}- {token}")
        new_lines = lines[:idx + 1] + kept_lines + lines[end:]
        rendered_sequence = True

    else:
        value = yaml.safe_load(stripped)
        if [value] != old_tags:
            raise FrontMatterError("tags scalar does not round-trip to the parsed value")
        new_values = mapping.get(value, [value]) if isinstance(value, str) else [value]
        tokens = [_substitute_token(value_part, value, new_value) for new_value in new_values]
        rendered_sequence = len(tokens) > 1
        if rendered_sequence:
            new_lines = lines[:idx] + [f"{key_part} [{', '.join(tokens)}]"] + lines[idx + 1:]
        else:
            lead = value_part[: len(value_part) - len(value_part.lstrip())] or " "
            new_lines = lines[:idx] + [f"{key_part}{lead}{tokens[0]}"] + lines[idx + 1:]

    new_fm = "\n".join(new_lines)
    new_text = text[:fm_start] + new_fm + text[fm_end:]
    _verify_rewrite(text, new_text, new_fm, fm_end, parsed, new_tags, rendered_sequence)

    return {
        "text": new_text,
        "tags_before": old_tags,
        "tags_after": new_tags,
        "replaced": replaced,
        "dropped": dropped,
    }


def raw_tags_region(text):
    """Best-effort raw text of a file's `tags:` value for unparseable files."""
    match = FM_RE.match(text)
    if not match:
        return ""
    lines = match.group("fm").split("\n")
    hits = [i for i, line in enumerate(lines) if TAGS_LINE_RE.match(line)]
    region = []
    for idx in hits:
        region.append(lines[idx])
        end = idx + 1
        while end < len(lines) and BLOCK_ITEM_RE.match(lines[end]):
            region.append(lines[end])
            end += 1
    return "\n".join(region)


def sources_in_region(region, sources):
    """Source spellings that appear as whole tokens inside a raw tags region."""
    found = []
    for source in sources:
        pattern = rf"(?<![A-Za-z0-9_/\-.]){re.escape(source)}(?![A-Za-z0-9_/\-.])"
        if re.search(pattern, region):
            found.append(source)
    return sorted(found)
