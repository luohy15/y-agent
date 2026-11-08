#!/usr/bin/env python3
"""Publish the EC2 agents tree. Dry-run by default; never called by bisync."""
import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or name == "." or path.is_absolute() or str(path) != name
            or any(part in (".", "..") for part in path.parts)
            or any(c in name for c in "\n\r\\*?[]\x00")):
        raise ValueError("Unsafe relative path: " + repr(name))
    return path


def build_archive(source, namespace, prefixes=()):
    if namespace not in ("personal", "work"):
        raise ValueError("Unknown namespace")
    source = source.resolve(strict=True)
    entries = {}
    for root, dirs, files in os.walk(source, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(root) / name
            relative = path.relative_to(source).as_posix()
            safe_name(relative)
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError("Symlink or special source entry: " + relative)
            entries[relative] = path
    selected = set(entries)
    if namespace == "work":
        selected = set()
        for entry in prefixes:
            safe_name(entry)
            selected.update(name for name in entries if name == entry or name.startswith(entry + "/"))
        selected.discard("work-allowlist.txt")
    directories = {"skills", "references", "hooks"} if namespace == "work" else set()
    bodies = {}
    for name in selected:
        path = entries[name]
        if path.is_dir():
            directories.add(name)
        else:
            # O_NOFOLLOW also rejects a link substituted after the initial scan.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                mode = os.fstat(stream.fileno()).st_mode
                if not stat.S_ISREG(mode):
                    raise ValueError("Source changed type: " + name)
                bodies[name] = (stream.read(), 0o755 if mode & 0o111 else 0o644)
        directories.update(str(parent) for parent in PurePosixPath(name).parents if str(parent) != ".")
    if directories.intersection(bodies):
        raise ValueError("Required directory conflicts with file")
    manifest = "".join(hashlib.sha256(body).hexdigest() + "  " + name + "\n"
                       for name, (body, _) in sorted(bodies.items())).encode()
    bodies["MANIFEST.sha256"] = (manifest, 0o644)
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name in sorted(directories | bodies.keys()):
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
        if hashlib.sha256((stage / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Manifest mismatch: " + name)
    if files != expected | {"MANIFEST.sha256"}:
        raise ValueError("Manifest does not cover every file")


def install_archive(data, target, expected_digest=None):
    digest = hashlib.sha256(data).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ValueError("Archive digest mismatch")
    target = target.expanduser().absolute()
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
    if namespace not in ("personal", "work") or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid remote archive identity")
    prefix = "s3:luohy15/.agents-archive/" + namespace
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


def load_policy(namespace, get):
    if namespace == "personal":
        prefixes = ()
    elif namespace == "work":
        payload = get("/api/module/namespace/rules", params={"namespace": namespace})
        if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
            raise ValueError("Invalid namespace rules response")
        rows = payload["rules"]
        selected = set()
        for row in rows:
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
            selected.add(value)
        prefixes = tuple(sorted(selected))
    else:
        raise ValueError("Unknown namespace")
    digest = hashlib.sha256((namespace + "\n" + "".join(p + "\n" for p in prefixes)).encode()).hexdigest()
    return prefixes, digest


def check_policy(source, prefixes):
    source = source.resolve(strict=True)
    for prefix in prefixes:
        path = source / safe_name(prefix)
        if not path.exists() or not path.resolve().is_relative_to(source):
            raise ValueError("Missing or escaping policy path: " + prefix)
        if prefix.startswith("skills/") and len(PurePosixPath(prefix).parts) == 2:
            if not path.is_dir() or not (path / "SKILL.md").is_file():
                raise ValueError("Skill requires SKILL.md: " + prefix)


def node_namespaces(nodes, records):
    if not isinstance(records, list):
        raise ValueError("Invalid node registry response")
    scopes = {}
    for node in nodes:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", node) or node in ("default", "ec2"):
            raise ValueError("Invalid publishing node: " + node)
        matches = [row for row in records if isinstance(row, dict) and row.get("name") == node]
        if len(matches) != 1 or matches[0].get("data_scope") not in ("personal", "work"):
            raise ValueError("Unknown or invalid node scope: " + node)
        if matches[0].get("enabled") is not True:
            raise ValueError("Disabled publishing node: " + node)
        scopes[node] = matches[0]["data_scope"]
    return scopes


def publish_archives(archives, scopes):
    # All policies, archives and registry scopes are validated before any write.
    with tempfile.TemporaryDirectory(prefix="publish-agents-") as temporary:
        for scope, data in archives.items():
            archive = Path(temporary) / "tree.tar.gz"
            checksum = Path(temporary) / "sha256"
            archive.write_bytes(data)
            checksum.write_text(hashlib.sha256(data).hexdigest() + "  tree.tar.gz\n")
            for path in (archive, checksum):
                subprocess.run(["rclone", "copyto", str(path), f"s3:luohy15/.agents-archive/{scope}/{path.name}"], check=True)
    receiver = receiver_source()
    for node, scope in scopes.items():
        digest = hashlib.sha256(archives[scope]).hexdigest()
        command = remote_command(scope, digest, receiver)
        subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", node, command], stdin=subprocess.DEVNULL, check=True)
