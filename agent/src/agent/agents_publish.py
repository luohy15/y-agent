#!/usr/bin/env python3
"""Publish one composed agents tree. Dry-run by default; never called by bisync.

Selection and composition match the 4235 reference contract: additive overlay,
verbatim core bytes, and a source digest of the selected inputs.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import uuid


MARKER = "<!-- deployment overlay: {scope}; core rules follow verbatim -->"
DENYLIST = "local/private-denylist.txt"
BASELINE = "local/reference-baseline.tsv"
ROOTS = "local/approved-roots.tsv"
ALIASES = {"personal": "default", "work": "alphavantage"}
SCOPE_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}")
CANONICAL_ROOTS = {"skills", "references", "hooks", "commands", "synced", "local"}
DENY_CATEGORIES = {"personal", "organization", "credential"}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+?\.md)(?:#[^)]*)?\)")
TOK_RE = re.compile(r"`([^`]+)`")
CFG_PREFIXES = ("~/.agents/", ".agents/", "$Y_AGENTS_ROOT/", "references/", "skills/")
EXPORT_KEEP = {"README.md", "cli-contract.md", "GENERATED.sha256"}


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or name == "." or path.is_absolute() or str(path) != name
            or any(part in (".", "..") for part in path.parts)
            or any(c in name for c in "\n\r\\*?[]\x00")):
        raise ValueError("Unsafe relative path: " + repr(name))
    return path


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalize_namespace(namespace):
    """Return (canonical, legacy). Unknown names fail before any caller reads or writes."""
    if not isinstance(namespace, str) or not SCOPE_RE.fullmatch(namespace):
        raise ValueError("Invalid namespace")
    return ALIASES.get(namespace, namespace), namespace in ALIASES


def load_registry(get=None, policies=None):
    """Load one owner-scoped registry snapshot, including retained exclusions."""
    if policies is None:
        if get is None:
            raise ValueError("namespace registry required")
        policies = get("/api/module/namespace/scopes")
    if not isinstance(policies, dict) or not isinstance(policies.get("scopes"), list):
        raise ValueError("Invalid namespace registry")
    rows = {}
    for row in policies["scopes"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid namespace scope")
        name = row.get("name")
        canonical, legacy = normalize_namespace(name)
        if legacy or canonical == "default" or name in rows:
            raise ValueError("Invalid namespace registration")
        overlay, allowlist = row.get("overlay"), row.get("allowlist")
        if overlay is not None:
            if not isinstance(overlay, str) or not SCOPE_RE.fullmatch(overlay) or overlay in CANONICAL_ROOTS:
                raise ValueError("Invalid overlay directory")
        if allowlist is not None:
            safe_name(allowlist)
            if not allowlist.startswith("local/") or allowlist == DENYLIST or not overlay:
                raise ValueError("Invalid scope allowlist")
        markers = row.get("markers", [])
        if (not isinstance(markers, list) or any(not isinstance(item, str) for item in markers)
                or (markers and not allowlist) or (overlay and not allowlist)):
            raise ValueError("Invalid scope markers or overlay")
        if not isinstance(row.get("node_deliverable", False), bool):
            raise ValueError("Invalid node capability")
        rows[name] = {**row, "markers": sorted(set(markers))}
    overlays = [row["overlay"] for row in rows.values() if row.get("overlay")]
    if len(overlays) != len(set(overlays)):
        raise ValueError("Duplicate overlay directory")
    for name in rows:
        policy_chain(name, rows)
    exclusions = policies.get("exclusions")
    if (not isinstance(exclusions, dict) or not isinstance(exclusions.get("overlays"), list)
            or not isinstance(exclusions.get("allowlists"), list)):
        raise ValueError("Missing namespace exclusion metadata")
    for overlay in exclusions["overlays"]:
        if not isinstance(overlay, str) or not SCOPE_RE.fullmatch(overlay) or overlay in CANONICAL_ROOTS:
            raise ValueError("Invalid excluded overlay")
    for path in exclusions["allowlists"]:
        safe_name(path)
        if not path.startswith("local/"):
            raise ValueError("Invalid excluded allowlist")
    if (not set(overlays).issubset(exclusions["overlays"])
            or not {row["allowlist"] for row in rows.values() if row.get("allowlist")}.issubset(exclusions["allowlists"])):
        raise ValueError("Incomplete namespace exclusions")
    return {**policies, "by_name": rows}


def policy_chain(name, rows):
    chain = []
    while name is not None:
        if name == "default" or name not in rows or name in chain or len(chain) >= 16:
            raise ValueError("Unregistered or cyclic namespace: " + name)
        chain.append(name)
        name = rows[name].get("parent")
    return list(reversed(chain))


def _text(data, rel):
    if b"\x00" in data:
        raise ValueError("non-text file: " + rel)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("non-text file: " + rel) from None


def iter_files(root, restricted=()):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        kept = []
        for name in dirnames:
            path = Path(dirpath) / name
            if path.is_symlink():
                raise ValueError("refusing symlink directory: " + path.relative_to(root).as_posix())
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            safe_name(rel)
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                if _matches(rel, restricted):
                    raise ValueError("cache file in selection: " + rel)
                continue
            if path.is_symlink():
                raise ValueError("refusing symlink: " + rel)
            if not path.is_file():
                raise ValueError("refusing non-regular file: " + rel)
            mode = path.stat().st_mode
            yield rel, path.read_bytes(), mode


def load_denylist(path):
    found = []
    for index, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 3 or parts[1] not in DENY_CATEGORIES:
            raise ValueError(f"bad denylist row: line={index}")
        try:
            compiled = re.compile(parts[2])
        except re.error:
            raise ValueError(f"bad denylist pattern: line={index}") from None
        found.append((parts[0], parts[1], parts[2], compiled))
    return found


def load_allowlist(path, overlay):
    entries = []
    seen = set()
    for index, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        rel = parts[0].strip()
        rationale = parts[1].strip() if len(parts) > 1 else ""
        if (not rel or rel in seen or not rel.startswith(overlay + "/")
                or any(char in rel for char in "*?[]{}<>")):
            raise ValueError(f"invalid allowlist entry: line={index}")
        if not rationale:
            raise ValueError(f"allowlist entry missing rationale: line={index}")
        safe_name(rel)
        seen.add(rel)
        entries.append(rel)
    return entries


def _fetch_rules(get, namespace):
    payload = get("/api/module/namespace/rules", params={"namespace": namespace})
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
        raise ValueError("Invalid namespace rules response")
    selected = set()
    for row in payload["rules"]:
        if not isinstance(row, dict) or row.get("namespace") != namespace:
            raise ValueError("Invalid namespace rule")
        kind, value = row.get("kind"), row.get("value")
        if not isinstance(value, str):
            raise ValueError("Invalid namespace rule value")
        if kind == "skill":
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
                raise ValueError("Invalid skill name")
            value = "skills/" + value
        elif kind != "path":
            raise ValueError("Invalid namespace rule kind")
        safe_name(value)
        if value == "local" or value.startswith("local/"):
            raise ValueError("local/ in selection: " + value)
        selected.add(value)
    return tuple(sorted(selected))


def load_policy(namespace, registry, get=None):
    canonical, legacy = normalize_namespace(namespace)
    rows = registry["by_name"]
    chain = policy_chain(canonical, rows) if canonical != "default" else []
    policy = rows[canonical] if chain else {"overlay": "local", "markers": [], "node_deliverable": True}
    rules = {}
    # Default also validates active membership before excluding private sources.
    for name in (chain if chain else sorted(rows)):
        rules[name] = _fetch_rules(get, name) if get else tuple(rows[name].get("rules", ()))
        for value in rules[name]:
            safe_name(value)
    return canonical, legacy, chain, policy, rules


def check_policy(source, prefixes):
    source = Path(source).resolve(strict=True)
    for prefix in prefixes:
        path = source / safe_name(prefix)
        if path.is_symlink() or not path.exists() or not path.resolve().is_relative_to(source):
            raise ValueError("Missing or escaping policy path: " + prefix)
        if prefix.startswith("skills/") and len(PurePosixPath(prefix).parts) == 2:
            if not path.is_dir() or not (path / "SKILL.md").is_file():
                raise ValueError("Skill requires SKILL.md: " + prefix)


def _matches(rel, prefixes):
    return any(rel == prefix or rel.startswith(prefix + "/") for prefix in prefixes)


def classify(entries, scope, allowlist, prefixes, policy, controls, excluded):
    base, overlay = {}, {}
    for rel, data, mode in entries:
        if rel in controls:
            continue
        if rel in allowlist:
            overlay[rel[len(policy["overlay"]) + 1:]] = (rel, data, mode)
        elif rel.startswith("local/"):
            if scope == "default":
                overlay[rel[len("local/"):]] = (rel, data, mode)
        elif _matches(rel, excluded):
            continue
        elif scope == "default" or _matches(rel, prefixes):
            base[rel] = (data, mode)
    if set(allowlist) - {src for src, _data, _mode in overlay.values()}:
        raise ValueError("Missing allowlist source")
    if not base:
        raise ValueError("empty selection")
    return base, overlay


def split_skill(core):
    if not core.startswith("---\n"):
        raise ValueError("SKILL.md is missing YAML front matter")
    end = core.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md front matter is unclosed")
    front = core[: end + 5]
    body = core[end + 5 :]
    if not body.startswith("\n"):
        body = "\n" + body
    return front, body


def compose_bytes(overlay, core, scope, skill):
    marker = MARKER.format(scope=scope)
    try:
        ov = overlay.decode("utf-8")
        co = core.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("non-text composed file") from None
    if skill:
        front, body = split_skill(co)
        text = front + "\n" + marker + "\n" + ov.rstrip("\n") + "\n" + body
        if not text.startswith("---\n"):
            raise ValueError("composed SKILL.md front matter is not first")
        if marker not in text or body not in text.split(marker, 1)[1]:
            raise ValueError("composed SKILL.md dropped the core body")
    else:
        text = ov.rstrip("\n") + "\n\n" + marker + "\n" + co
        if text.split(marker, 1)[1] != "\n" + co:
            raise ValueError("composed file dropped the verbatim core block")
    return text.encode("utf-8")


def build_files(base, overlay, scope):
    files, modes, rows = {}, {}, []
    for rel in sorted(set(base) | set(overlay)):
        in_base = rel in base
        in_overlay = rel in overlay
        skill = rel.endswith("/SKILL.md") or rel == "SKILL.md"
        if in_base and in_overlay:
            src_rel, ov, mode = overlay[rel]
            data = compose_bytes(ov, base[rel][0], scope, skill)
            kind = "composed"
            sources = f"{src_rel}+{rel}"
            source_hash = sha256(ov + b"\n" + base[rel][0])
            file_mode = base[rel][1]
        elif in_overlay:
            src_rel, data, file_mode = overlay[rel]
            kind = "overlay"
            sources = src_rel
            source_hash = sha256(data)
        else:
            data, file_mode = base[rel]
            kind = "core"
            sources = rel
            source_hash = sha256(data)
        files[rel] = data
        modes[rel] = file_mode
        rows.append((rel, kind, sources, source_hash, sha256(data)))
    return files, modes, rows


def source_digest(base, overlay):
    lines = [f"{rel}\t{sha256(data)}" for rel, (data, _mode) in sorted(base.items())]
    lines += [f"{src}\t{sha256(data)}" for _rel, (src, data, _mode) in sorted(overlay.items())]
    return sha256(("\n".join(lines) + "\n").encode("utf-8"))


def manifest_text(scope, digest, rows):
    lines = [f"scope\t{scope}", f"source_digest\t{digest}"]
    for rel, kind, sources, source_hash, effective_hash in rows:
        lines.append("\t".join(["file", rel, kind, sources, source_hash, effective_hash]))
    try:
        entry = next(row for row in rows if row[0] == "global-instructions.md")
    except StopIteration:
        raise ValueError("selection is missing global-instructions.md") from None
    lines.append(f"effective\tglobal-instructions.md\t{entry[4]}")
    return "\n".join(lines) + "\n"



def _blocked(category, pattern, markers, source_rel, allowset):
    if category in ("personal", "credential"):
        return True
    if category != "organization":
        raise ValueError("unknown denylist category")
    if pattern in markers and source_rel in allowset:
        return False
    return True


def scan_sources(sources, patterns, scope, allowset, markers):
    """sources: (display rel, source rel, bytes). Errors name ids and hashes, never text."""
    if scope == "default":
        return
    errors = []
    for rel, source_rel, data in sources:
        try:
            text = _text(data, rel)
        except ValueError:
            raise
        for pid, category, pattern, compiled in patterns:
            if compiled.search(rel) and _blocked(category, pattern, markers, source_rel, allowset):
                errors.append(f"marker: {rel} id={pid} line=0 sha256={sha256(rel.encode())}")
            for index, line in enumerate(text.splitlines(), 1):
                if compiled.search(line) and _blocked(category, pattern, markers, source_rel, allowset):
                    errors.append(
                        f"marker: {rel} id={pid} line={index} sha256={sha256(line.encode())}")
    if errors:
        raise ValueError("scan blocked " + " ".join(errors))


def assert_no_pointers(files):
    for rel, data in files.items():
        if b"$Y_AGENTS_ROOT/local/" in data or b"<overlay>" in data:
            raise ValueError("overlay pointer: " + rel)


def ref_candidates(token, file):
    target = token.strip().split("#")[0]
    if target.startswith(("http://", "https://")):
        return None
    if any(char in target for char in "<>*{}"):
        return None
    if target.startswith(("$Y_AGENT_WORKSPACE", "pages/", "code/", "assets/", "/")):
        return None
    if "$" in target and not target.startswith("$Y_AGENTS_ROOT/"):
        return None
    if target.startswith(("~/.agents/", ".agents/")):
        target = target.split(".agents/", 1)[1]
    elif target.startswith("$Y_AGENTS_ROOT/"):
        target = target[len("$Y_AGENTS_ROOT/"):]
    found = []
    parts = file.split("/")
    if parts[0] == "skills" and len(parts) > 2:
        found.append(str(PurePosixPath("skills", parts[1], target)))
        found.append(str(PurePosixPath("local", "skills", parts[1], target)))
    if len(parts) > 3 and parts[0] == "local" and parts[1] == "skills":
        found.append(str(PurePosixPath("local", "skills", parts[2], target)))
        found.append(str(PurePosixPath("skills", parts[2], target)))
    found.append(str(PurePosixPath(file).parent / target))
    found.append(target)
    return [posixpath.normpath(item) for item in found]


def unresolved_refs(files, names):
    selected = set(files)
    found = []
    for rel in names:
        data = files.get(rel)
        if data is None:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        tokens = [match.group(1) for match in LINK_RE.finditer(text)]
        tokens += [match.group(1) for match in TOK_RE.finditer(text)
                   if match.group(1).endswith(".md") and match.group(1).startswith(CFG_PREFIXES)]
        for token in tokens:
            candidates = ref_candidates(token, rel)
            if candidates is None:
                continue
            if not any(item in selected for item in candidates):
                found.append((rel, sha256(token.encode("utf-8"))))
    return found



def load_reference_baseline(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) != 4 or not cols[3].strip() or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in cols[1:3]):
            raise ValueError("Malformed reference baseline")
        safe_name(cols[0])
        rows.append(tuple(cols[:3]))
    return rows


def check_reference_baseline(files, baseline, owned=()):
    remaining = list(baseline)
    count = 0
    for rel, token in unresolved_refs(files, files):
        row = (rel, sha256(files[rel]), token)
        if rel in owned or row not in remaining:
            raise ValueError(f"unresolved ref {rel} sha256={token}")
        remaining.remove(row)
        count += 1
    if remaining:
        rel, content, token = remaining[0]
        raise ValueError(f"stale reference baseline {rel} content={content} sha256={token}")
    return count


def approved_roots(source, registry):
    bindings = {}
    for line in (source / ROOTS).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if (len(cols) != 3 or not cols[2].strip() or not SCOPE_RE.fullmatch(cols[0])
                or cols[0] in CANONICAL_ROOTS or cols[0] in bindings):
            raise ValueError("Invalid approved root binding")
        name, legacy = normalize_namespace(cols[1])
        if legacy or name == "default":
            raise ValueError("Invalid approved root namespace")
        bindings[cols[0]] = name
    for name, row in registry["by_name"].items():
        if row.get("overlay") and bindings.get(row["overlay"]) != name:
            raise ValueError("Missing or mismatched root approval: " + name)
    return set(bindings)


def previous_file_rows(path, scope):
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or non-regular composition manifest")
    found = set()
    scope_rows = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if cols[0] == "scope" and len(cols) == 2 and cols[1] == scope:
            scope_rows += 1
        elif cols[0] == "file" and len(cols) == 6:
            safe_name(cols[1])
            if cols[1] in found or cols[2] not in {"core", "overlay", "composed"} or any(
                    not re.fullmatch(r"[0-9a-f]{64}", value) for value in cols[4:]):
                raise ValueError("Malformed composition file row")
            found.add(cols[1])
        elif cols[0] == "source_digest" and len(cols) == 2 and re.fullmatch(r"[0-9a-f]{64}", cols[1]):
            continue
        elif cols[0] == "effective" and len(cols) == 3 and cols[1] == "global-instructions.md" and re.fullmatch(r"[0-9a-f]{64}", cols[2]):
            continue
        else:
            raise ValueError("Malformed or cross-scope composition manifest")
    if scope_rows != 1:
        raise ValueError("Invalid composition scope")
    return found


def inventory_output(out, allowed):
    directories = {str(parent) for rel in allowed for parent in PurePosixPath(rel).parents if str(parent) != "."}
    for path in out.rglob("*"):
        rel = path.relative_to(out).as_posix()
        if path.is_symlink():
            raise ValueError("symlink output: " + rel)
        if path.is_dir():
            if rel not in directories:
                raise ValueError("unexpected output directory: " + rel)
        elif not path.is_file() or rel not in allowed:
            raise ValueError("unexpected output path: " + rel)


def write_tree(out, files, manifest):
    previous = set()
    if out.exists():
        if out.is_symlink() or not out.is_dir():
            raise ValueError("refusing non-directory output")
        scope = manifest.splitlines()[0].split("\t")[1]
        previous = previous_file_rows(out / "COMPOSITION.sha256", scope)
        inventory_output(out, previous | set(files) | {"COMPOSITION.sha256"})
        for rel in files:
            dest = out / rel
            if dest.is_dir() or any(parent.is_file() for parent in dest.parents if parent != out):
                raise ValueError("output path type conflict: " + rel)
        for rel in previous:
            if not (out / rel).is_file():
                raise ValueError("missing prior output: " + rel)
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    for rel, data in files.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        os.chmod(dest, 0o600)
    for rel in sorted(previous - set(files)):
        (out / rel).unlink()
    for path in sorted(out.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    man = out / "COMPOSITION.sha256"
    man.write_text(manifest, encoding="utf-8")
    os.chmod(man, 0o600)


def _refuse_inside(source, out):
    source = Path(source).resolve(strict=True)
    out = Path(out).expanduser().absolute()
    if any(path.is_symlink() for path in (out, *out.parents)):
        raise ValueError("refusing symlink output ancestry")
    if out == source or source in out.parents or out in source.parents:
        raise ValueError("refusing an output inside or above the source")
    return source, out


def _regular_source(source, rel):
    path = source / safe_name(rel)
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != source):
        raise ValueError("symlink source: " + rel)
    if not path.is_file() or not path.resolve().is_relative_to(source):
        raise ValueError("missing source file: " + rel)
    return path


def _controls(source, registry):
    controls = {DENYLIST, BASELINE, ROOTS, *registry["exclusions"]["allowlists"]}
    required = controls
    return controls, {rel: _regular_source(source, rel).read_bytes() for rel in sorted(required)}


def _pack(files, modes, manifest):
    bodies = {rel: (data, 0o755 if modes[rel] & 0o111 else 0o644) for rel, data in files.items()}
    bodies["COMPOSITION.sha256"] = (manifest.encode("utf-8"), 0o644)
    directories = set()
    for name in bodies:
        directories.update(str(parent) for parent in PurePosixPath(name).parents if str(parent) != ".")
    if directories.intersection(bodies):
        raise ValueError("Required directory conflicts with file")
    file_manifest = "".join(
        sha256(body) + "  " + name + "\n" for name, (body, _mode) in sorted(bodies.items())).encode()
    bodies["MANIFEST.sha256"] = (file_manifest, 0o644)
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            names = sorted(directories | bodies.keys())
            for name in names:
                member = tarfile.TarInfo(name)
                if name in directories:
                    member.type = tarfile.DIRTYPE
                    member.mode = 0o755
                    archive.addfile(member)
                else:
                    body, member.mode = bodies[name]
                    member.size = len(body)
                    archive.addfile(member, io.BytesIO(body))
    return output.getvalue()


def assemble(source, namespace, get=None, policies=None, out=None):
    """Build from one registry snapshot. Baseline exceptions require exact bytes."""
    normalize_namespace(namespace)
    registry = load_registry(get, policies)
    canonical, legacy, chain, policy, rules = load_policy(namespace, registry, get)
    source = Path(source).resolve(strict=True)
    controls, control_bytes = _controls(source, registry)
    patterns = load_denylist(source / DENYLIST)
    organization = {pattern for _pid, category, pattern, _compiled in patterns if category == "organization"}
    excluded = tuple(sorted(set(registry["exclusions"]["overlays"]) | approved_roots(source, registry)))
    allowlists = {}
    for name, row in registry["by_name"].items():
        if not set(row["markers"]).issubset(organization):
            raise ValueError("Unapproved organization marker: " + name)
        allowlists[name] = load_allowlist(source / row["allowlist"], row["overlay"]) if row.get("allowlist") else []
    prefixes = set()
    for name, values in rules.items():
        row = registry["by_name"][name]
        for value in values:
            if row.get("allowlist"):
                if value not in allowlists[name]:
                    raise ValueError("unapproved namespace rule: " + value)
                continue
            if value.startswith("local/") or value == "local" or _matches(value, excluded):
                raise ValueError("private path in selection: " + value)
            if any(_matches(path, (value,)) for path in excluded + tuple(controls)):
                raise ValueError("private prefix overlap: " + value)
            if name in chain:
                prefixes.add(value)
    prefixes = tuple(sorted(prefixes))
    if canonical != "default":
        if not prefixes:
            raise ValueError("empty selection")
        check_policy(source, prefixes)
    allowlist = allowlists.get(canonical, [])
    entries = list(iter_files(source, prefixes + tuple(allowlist) if canonical != "default" else ()))
    base, overlay = classify(entries, canonical, allowlist, prefixes, policy, controls, excluded)
    if "global-instructions.md" not in base:
        raise ValueError("selection is missing global-instructions.md")
    sources = [(rel, rel, data) for rel, (data, _mode) in base.items()]
    sources += [(rel, src, data) for rel, (src, data, _mode) in overlay.items()]
    scan_sources(sources, patterns, canonical, set(allowlist), policy["markers"])
    files, modes, rows = build_files(base, overlay, canonical)
    assert_no_pointers(files)
    owned_prefixes = tuple(value for values in rules.values() for value in values)
    owned = {rel for rel, kind, _sources, _src, _effective in rows
             if kind != "core" or _matches(rel, owned_prefixes)}
    baseline = load_reference_baseline(source / BASELINE) if canonical == "default" else []
    count = check_reference_baseline(files, baseline, owned)
    baseline_open = unresolved_refs(files, files) if count else []
    source_hash = source_digest(base, overlay)
    policy_data = {"scope": canonical, "chain": chain, "rules": rules,
                   "scopes": registry["scopes"], "exclusions": registry["exclusions"],
                   "controls": {key: sha256(data) for key, data in control_bytes.items()}}
    policy_hash = sha256(json.dumps(policy_data, sort_keys=True, separators=(",", ":")).encode())
    digest = sha256((source_hash + policy_hash).encode())
    manifest = manifest_text(canonical, digest, rows)
    archive = _pack(files, modes, manifest)
    summary = (f"{canonical}: policy={policy_hash} sha256={sha256(archive)} "
               f"files={len(files)} bytes={len(archive)} scan=clean refs=closed composed=clean "
               f"source_digest={digest} baseline_open={len(baseline_open)}")
    if out is not None:
        source, out = _refuse_inside(source, out)
        write_tree(out, files, manifest)
    return {"namespace": canonical, "legacy": legacy, "files": files, "modes": modes,
            "rows": rows, "manifest": manifest, "source_digest": digest,
            "archive": archive, "summary": summary, "baseline_open": baseline_open}


def build_archive(source, namespace, **kwargs):
    return assemble(source, namespace, **kwargs)["archive"]


def compose_to(source, out, namespace, **kwargs):
    return assemble(source, namespace, out=out, **kwargs)


def parse_composition(text):
    digest = effective = None
    for line in text.splitlines():
        cols = line.split("\t")
        if cols[0] == "source_digest" and len(cols) == 2:
            digest = cols[1]
        elif cols[0] == "effective" and len(cols) >= 3 and cols[1] == "global-instructions.md":
            effective = cols[2]
    if digest is None:
        raise ValueError("Malformed composition manifest")
    return digest, effective


def assess_freshness(source, effective, namespace, **kwargs):
    """True freshness is the selected-source digest. The entrypoint hash is narrower."""
    current = assemble(source, namespace, **kwargs)
    manifest = Path(effective) / "COMPOSITION.sha256"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("missing composition manifest")
    recorded_digest, recorded_effective = parse_composition(manifest.read_text(encoding="utf-8"))
    entry = Path(effective) / "global-instructions.md"
    if entry.is_symlink() or not entry.is_file():
        raise ValueError("missing effective entrypoint")
    actual = sha256(entry.read_bytes())
    return {
        "source_fresh": recorded_digest == current["source_digest"],
        "entrypoint_match": recorded_effective == actual,
        "effective_match": all((Path(effective) / rel).is_file() and not (Path(effective) / rel).is_symlink()
                               and sha256((Path(effective) / rel).read_bytes()) == sha256(data)
                               for rel, data in current["files"].items()),
        "recorded_source_digest": recorded_digest,
        "current_source_digest": current["source_digest"],
    }


def _generated(files):
    return "".join(sha256(files[name]) + "  " + name + "\n" for name in sorted(files))


def _previous_generated(path):
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("Malformed generated manifest")
        safe_name(match.group(2))
        if match.group(2) in found or match.group(2) in EXPORT_KEEP:
            raise ValueError("Duplicate or reserved generated row")
        found.add(match.group(2))
    return found


def export_scope(source, out, namespace, **kwargs):
    """Write a registered composed selection without node manifests."""
    if normalize_namespace(namespace)[0] == "default":
        raise ValueError("export requires a registered namespace")
    result = assemble(source, namespace, **kwargs)
    source = Path(source).resolve(strict=True)
    out = Path(out).expanduser().absolute()
    _refuse_inside(source, out)
    if out.exists():
        if out.is_symlink() or not out.is_dir():
            raise ValueError("refusing non-directory export: " + str(out))
        previous_path = out / "GENERATED.sha256"
        previous = _previous_generated(previous_path) if previous_path.is_file() else set()
        for path in out.rglob("*"):
            if path.is_symlink():
                raise ValueError("refusing export symlink: " + str(path))
            if not path.is_file():
                continue
            rel = path.relative_to(out).as_posix()
            if rel not in previous and rel not in EXPORT_KEEP:
                raise ValueError("refusing unexpected export path: " + rel)
        inventory_output(out, previous | EXPORT_KEEP)
        for rel in previous:
            if not (out / rel).is_file():
                raise ValueError("missing generated output: " + rel)
        for rel in result["files"]:
            dest = out / rel
            if dest.is_dir() or any(parent.is_file() for parent in dest.parents if parent != out):
                raise ValueError("output path type conflict: " + rel)
        for rel in sorted(previous - set(result["files"])):
            (out / rel).unlink()
    else:
        if not out.parent.is_dir():
            raise ValueError("export parent does not exist: " + str(out.parent))
        out.mkdir()
    for rel, data in result["files"].items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            raise ValueError("refusing to replace symlink: " + rel)
        dest.write_bytes(data)
        os.chmod(dest, 0o755 if result["modes"][rel] & 0o111 else 0o644)
    generated = out / "GENERATED.sha256"
    generated.write_text(_generated(result["files"]), encoding="utf-8")
    os.chmod(generated, 0o644)
    for banned in ("MANIFEST.sha256", "COMPOSITION.sha256", ".agents-sync"):
        if (out / banned).exists():
            raise ValueError("export wrote a node manifest: " + banned)
    return result


def extract_verified(data, stage):
    files = set()
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            safe_name(member.name)
            if member.name in seen or not (member.isfile() or member.isdir()):
                raise ValueError("Duplicate or special archive entry: " + member.name)
            if member.name == ".synced-sha256":
                raise ValueError("Archive contains a sync stamp")
            seen.add(member.name)
            target = stage / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    shutil.copyfileobj(archive.extractfile(member), output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
                files.add(member.name)
    manifest = stage / "MANIFEST.sha256"
    expected = set()
    for line in manifest.read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("Malformed manifest")
        digest, name = match.groups()
        safe_name(name)
        if name in expected or name == "MANIFEST.sha256" or name not in files:
            raise ValueError("Invalid manifest entry: " + name)
        expected.add(name)
        if sha256((stage / name).read_bytes()) != digest:
            raise ValueError("Manifest mismatch: " + name)
    if files != expected | {"MANIFEST.sha256"}:
        raise ValueError("Manifest does not cover every file")


def install_archive(data, target, expected_digest=None, source=None):
    digest = sha256(data)
    if expected_digest is not None and digest != expected_digest:
        raise ValueError("Archive digest mismatch")
    target = Path(target).expanduser().absolute()
    if source is not None:
        _refuse_inside(source, target)
    metadata = target.parent / ".agents-sync"
    real = target.resolve()
    real.parent.mkdir(parents=True, exist_ok=True)
    lock = real.with_name(real.name + ".publish-lock")
    lock.mkdir()  # Fail closed if another publisher or an interrupted swap owns it.
    stage = real.with_name(real.name + ".staging." + uuid.uuid4().hex)
    previous = real.with_name(real.name + ".prev." + uuid.uuid4().hex)
    try:
        if real.exists() and not real.is_dir():
            raise ValueError("Target is not a directory")
        stamp = metadata / "synced-sha256"
        manifest = metadata / "MANIFEST.sha256"
        if real.is_dir() and manifest.is_file() and stamp.is_file() and stamp.read_text().strip() == digest:
            return "unchanged"
        stage.mkdir()
        extract_verified(data, stage)
        metadata.mkdir(parents=True, exist_ok=True)
        saved_metadata = {path: path.read_bytes() if path.exists() else None
                          for path in (manifest, stamp)}
        had_previous = real.exists()
        moved_previous = False
        try:
            shutil.move(str(stage / "MANIFEST.sha256"), str(manifest))
            stamp.write_text(digest + "\n")
            if had_previous:
                os.rename(real, previous)
                moved_previous = True
            os.rename(stage, real)
        except BaseException:
            # A failed swap must not leave a stamp that makes its retry a no-op.
            for path, content in saved_metadata.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            if moved_previous:
                os.rename(previous, real)
            raise
        if had_previous:
            shutil.rmtree(previous)
        # Under the exclusive lock, only remove siblings from our UUID naming scheme.
        for sibling in real.parent.iterdir():
            suffix = sibling.name.removeprefix(real.name)
            if re.fullmatch(r"\.(staging|prev)\.[0-9a-f]{32}", suffix):
                if sibling.is_dir() and not sibling.is_symlink():
                    shutil.rmtree(sibling)
        return "installed"
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        lock.rmdir()


def remote_command(namespace, digest, receiver):
    canonical, _legacy = normalize_namespace(namespace)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid remote archive identity")
    prefix = "s3:luohy15/.agents-archive/" + canonical
    precheck = '''import pathlib, sys
checksum, digest = sys.argv[1:]
if checksum != digest + "  tree.tar.gz":
    sys.exit("Remote checksum does not match published candidate")
home = pathlib.Path.home()
real = (home / ".agents").resolve()
if real.with_name(real.name + ".publish-lock").exists():
    sys.exit("Publisher lock exists; inspect interrupted or concurrent publication")
metadata = home / ".agents-sync"
stamp = metadata / "synced-sha256"
if real.is_dir() and (metadata / "MANIFEST.sha256").is_file() and stamp.is_file() and stamp.read_text().strip() == digest:
    print("unchanged")
    sys.exit(0)
sys.exit(3)
'''
    script = f'''set -euo pipefail
if rclone=$(command -v rclone); then
    :
elif [ "$(uname -s)" = Darwin ] && [ -x /opt/homebrew/bin/rclone ]; then
    rclone=/opt/homebrew/bin/rclone
else
    printf '%s\\n' 'rclone unavailable' >&2
    exit 1
fi
checksum=$("$rclone" cat {shlex.quote(prefix + '/sha256')})
if python3 -I -c {shlex.quote(precheck)} "$checksum" {digest}; then
    exit 0
else
    status=$?
    [ "$status" = 3 ] || exit "$status"
fi
"$rclone" cat {shlex.quote(prefix + '/tree.tar.gz')} | python3 -I -c {shlex.quote(receiver)} --receive {digest}
'''
    return "bash -c " + shlex.quote(script)


def receiver_source():
    """Send this stdlib-only module, not CLI dependencies, to the receiver."""
    return Path(__file__).read_text() + '\nimport sys\nprint(install_archive(sys.stdin.buffer.read(), Path.home() / ".agents", sys.argv[2]))\n'


def node_namespaces(nodes, records, policies):
    registry = load_registry(policies=policies)
    if not isinstance(records, list):
        raise ValueError("Invalid node registry response")
    scopes = {}
    for node in nodes:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", node) or node in ("default", "ec2"):
            raise ValueError("Invalid publishing node: " + node)
        matches = [row for row in records if isinstance(row, dict) and row.get("name") == node]
        if len(matches) != 1 or not matches[0].get("data_scope"):
            raise ValueError("Unknown or invalid node scope: " + node)
        if matches[0].get("enabled") is not True:
            raise ValueError("Disabled publishing node: " + node)
        scope, _legacy = normalize_namespace(matches[0]["data_scope"])
        if scope != "default":
            if scope not in registry["by_name"] or not registry["by_name"][scope].get("node_deliverable", False):
                raise ValueError("Namespace is not node-deliverable: " + scope)
        scopes[node] = scope
    return scopes


def publish_archives(archives, scopes):
    # All policies, archives and registry scopes are validated before any write.
    with tempfile.TemporaryDirectory(prefix="publish-agents-") as temporary:
        for scope, data in archives.items():
            archive = Path(temporary) / "tree.tar.gz"
            checksum = Path(temporary) / "sha256"
            archive.write_bytes(data)
            checksum.write_text(sha256(data) + "  tree.tar.gz\n")
            for path in (archive, checksum):
                subprocess.run(["rclone", "copyto", str(path), f"s3:luohy15/.agents-archive/{scope}/{path.name}"], check=True)
    receiver = receiver_source()
    for node, scope in scopes.items():
        digest = sha256(archives[scope])
        command = remote_command(scope, digest, receiver)
        subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", node, command], stdin=subprocess.DEVNULL, check=True)
