"""Bounded, canonical skill bundles shared by publisher, API and node staging."""
import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath

MAX_BYTES = 4_000_000
MAX_FILES = 256
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')


VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')


def version_key(version):
    if not isinstance(version, str) or len(version) > 64 or not VERSION.fullmatch(version):
        raise ValueError('skill_invalid_version')
    return tuple(int(part) for part in version.split('.'))


def validate_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError('invalid skill name')
    return name


def validate_path(path):
    if (not isinstance(path, str) or not path or len(path) > 512 or '\\' in path
            or any(ord(c) < 32 for c in path) or path.startswith('/')
            or any(part.startswith('.') or not part for part in path.split('/'))
            or str(PurePosixPath(path)) != path):
        raise ValueError('invalid skill file path')
    return path


def scan_references(files):
    skills, absolute = set(), set()
    for path, content in files.items():
        if PurePosixPath(path).suffix in ('.md', '.txt', '.py', '.sh', '.json', '.yaml', '.yml'):
            text = content.decode('utf-8')
            skills.update(re.findall(r'\.\./([a-z0-9][a-z0-9-]*)/', text))
            absolute.update(re.findall(r'/Users/roy/[^\s`\"\'<>()[\]{},;]+', text))
    return skills, absolute


def canonical_sha(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_manifest(name, manifest):
    validate_name(name)
    if not isinstance(manifest, dict) or set(manifest) != {'name', 'files', 'requires'} or manifest['name'] != name:
        raise ValueError('invalid skill manifest')
    files = manifest['files']
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('invalid skill file count')
    paths = []
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'executable'}:
            raise ValueError('invalid file manifest')
        paths.append(validate_path(entry['path']))
        if not isinstance(entry['sha256'], str) or not SHA.fullmatch(entry['sha256']) or type(entry['executable']) is not bool:
            raise ValueError('invalid file hash or mode')
    if paths != sorted(set(paths)) or 'SKILL.md' not in paths:
        raise ValueError('skill requires unique sorted files and SKILL.md')
    requires = manifest['requires']
    if not isinstance(requires, dict) or set(requires) != {'skills', 'files'}:
        raise ValueError('invalid requires')
    if not isinstance(requires['skills'], list) or len(requires['skills']) > MAX_FILES:
        raise ValueError('invalid skill dependencies')
    for dependency in requires['skills']:
        validate_name(dependency)
    if not isinstance(requires['files'], list) or len(requires['files']) > MAX_FILES:
        raise ValueError('invalid file dependencies')
    for entry in requires['files']:
        if (not isinstance(entry, dict) or set(entry) != {'path', 'sha256'}
                or not isinstance(entry['path'], str) or not entry['path'].startswith('/Users/roy/')
                or '..' in entry['path'].split('/') or len(entry['path']) > 512
                or not isinstance(entry['sha256'], str) or not SHA.fullmatch(entry['sha256'])):
            raise ValueError('invalid absolute dependency')


def validate_bundle(name, data, manifest, digest):
    validate_manifest(name, manifest)
    if canonical_sha(manifest) != digest:
        raise ValueError('skill bundle hash mismatch')
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError('skill bundle too large')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            expected = {entry['path']: entry for entry in manifest['files']}
            if len(entries) != len(expected) or {entry.filename for entry in entries} != set(expected):
                raise ValueError('skill archive file mismatch')
            if sum(entry.file_size for entry in entries) > MAX_BYTES:
                raise ValueError('skill expanded bundle too large')
            result = {}
            for entry in entries:
                validate_path(entry.filename)
                mode = entry.external_attr >> 16
                if entry.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or entry.flag_bits & 1:
                    raise ValueError('skill archive must contain regular files')
                content = archive.read(entry)
                if hashlib.sha256(content).hexdigest() != expected[entry.filename]['sha256']:
                    raise ValueError('skill file hash mismatch')
                result[entry.filename] = content
            skills, absolute = scan_references(result)
            if (skills - {name} != set(manifest['requires']['skills'])
                    or absolute != {entry['path'] for entry in manifest['requires']['files']}):
                raise ValueError('skill dependency manifest mismatch')
            return result
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError('invalid skill archive') from exc


def build_bundle(name, files, requires):
    manifest = {'name': name, 'files': [
        {'path': path, 'sha256': hashlib.sha256(content).hexdigest(), 'executable': executable}
        for path, (content, executable) in sorted(files.items())
    ], 'requires': requires}
    validate_manifest(name, manifest)
    if sum(len(content) for content, _ in files.values()) > MAX_BYTES:
        raise ValueError('skill expanded bundle too large')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path, (content, executable) in sorted(files.items()):
            info = zipfile.ZipInfo(path)
            info.external_attr = (stat.S_IFREG | (0o700 if executable else 0o600)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    data = stream.getvalue()
    digest = canonical_sha(manifest)
    validate_bundle(name, data, manifest, digest)
    return data, manifest, digest
