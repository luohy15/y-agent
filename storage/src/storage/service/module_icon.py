"""Normalize a module sidebar icon: a registry key, or inline SVG markup.

Stored on the existing module_version.icon column (todo 3861). A value that
matches the key shape is returned unchanged. Anything else must be an SVG
document, and the return value is the normalized markup (it starts with
``<svg``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
KEY_RE = re.compile(r"^[a-z0-9-]{1,32}$")
ALLOWED = {"svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon"}
MAX_BYTES = 4096
_STRIP_ATTRS = {"width", "height"}
_FORBIDDEN_ATTRS = {"href", "style"}
_DECL_RE = re.compile(r"<!doctype|<!entity|<!\[", re.IGNORECASE)


def normalize_module_icon(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("module icon must be a string")
    if KEY_RE.fullmatch(value):
        return value
    if not value.lstrip().startswith("<"):
        raise ValueError(
            "module icon must be a registry key ([a-z0-9-]{1,32}) or an <svg> document, "
            f"got {value!r}"
        )
    collapsed = re.sub(r"\s+", " ", value).strip()
    if len(collapsed.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"module icon SVG exceeds {MAX_BYTES} bytes after whitespace collapse")
    if _DECL_RE.search(value):
        raise ValueError("module icon SVG must not contain a doctype, entity, or CDATA section")
    try:
        root = ET.fromstring(value)
    except ET.ParseError as exc:
        raise ValueError(f"module icon SVG is not valid XML: {exc}") from exc
    _validate(root, root=True)
    return _serialize(root)


def _ns_local(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        ns, local = tag[1:].split("}", 1)
        return ns, local
    return "", tag


def _validate(el: ET.Element, *, root: bool) -> None:
    if not isinstance(el.tag, str):
        raise ValueError("module icon SVG contains a non-element node")
    ns, local = _ns_local(el.tag)
    if ns != SVG_NS or local not in ALLOWED or (root and local != "svg"):
        raise ValueError(f"module icon SVG element <{local}> is not allowed")
    if (el.text and el.text.strip()) or (el.tail and el.tail.strip()):
        raise ValueError("module icon SVG must not contain text")
    if root and "viewBox" not in el.attrib:
        raise ValueError("module icon SVG requires a viewBox")
    for key in el.attrib:
        attr_ns, attr = _ns_local(key)
        name = attr.lower()
        if name.startswith("on") or name in _FORBIDDEN_ATTRS:
            raise ValueError(f"module icon SVG attribute {attr!r} is not allowed")
        if attr_ns and attr_ns != "http://www.w3.org/2000/xmlns/":
            raise ValueError(f"module icon SVG attribute {attr!r} is not allowed")
    for child in list(el):
        _validate(child, root=False)


def _serialize(el: ET.Element) -> str:
    _ns, local = _ns_local(el.tag)
    attrs: list[str] = []
    if local == "svg":
        attrs.append(f'xmlns="{SVG_NS}"')
    for key, val in el.attrib.items():
        attr_ns, attr = _ns_local(key)
        if attr_ns or attr.lower() in _STRIP_ATTRS:
            continue
        attrs.append(f'{attr}="{_esc(val)}"')
    body = "".join(_serialize(child) for child in list(el))
    rendered = " ".join(attrs)
    if not body:
        return f"<{local} {rendered}/>" if rendered else f"<{local}/>"
    open_tag = f"<{local} {rendered}>" if rendered else f"<{local}>"
    return f"{open_tag}{body}</{local}>"


def _esc(val: str) -> str:
    return (
        val.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
