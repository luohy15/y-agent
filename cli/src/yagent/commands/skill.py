import base64
import hashlib
import json
from pathlib import Path
import subprocess

import click

from storage.project_key import normalize_project_key
from storage.skill_bundle import MAX_BYTES, MAX_FILES, build_bundle, scan_references, validate_name, version_key
from yagent.api_client import api_request


def parse_spec(spec, required=False):
    parts = spec.split('@')
    if len(parts) > 2 or (required and len(parts) != 2):
        raise click.BadParameter('expected name@MAJOR.MINOR.PATCH')
    try:
        validate_name(parts[0])
        version = parts[1] if len(parts) == 2 else None
        if version is not None:
            version_key(version)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    return parts[0], version


def collect_bundle(name, source, sha='HEAD'):
    validate_name(name)

    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], stderr=subprocess.PIPE)

    commit = git('rev-parse', '--verify', '--end-of-options', sha + '^{commit}').decode().strip()
    repo = normalize_project_key(git('remote', 'get-url', 'origin').decode().strip())
    prefix = f'skills/{name}/'
    entries = git('ls-tree', '-rz', commit, '--', prefix).split(b'\0')
    files, total = {}, 0
    for entry in filter(None, entries):
        meta, path = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        path = path.decode()
        if not path.startswith(prefix) or mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('skill_source_not_regular_blob')
        size = int(git('cat-file', '-s', oid))
        total += size
        if total > MAX_BYTES or len(files) >= MAX_FILES:
            raise ValueError('skill bundle exceeds limits')
        files[path[len(prefix):]] = (git('cat-file', 'blob', oid), mode == '100755')
    skills, absolute = scan_references({path: content for path, (content, _) in files.items()})
    references = []
    for value in sorted(absolute):
        path = Path(value)
        if not path.is_file():
            raise ValueError(f'absolute dependency is not a concrete file: {value}')
        references.append({'path': value, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    data, manifest, digest = build_bundle(name, files, {'skills': sorted(skills - {name}), 'files': references})
    return data, manifest, digest, commit, repo


def _print(response):
    click.echo(json.dumps(response.json(), ensure_ascii=False, indent=2))


@click.group('skill')
def skill_group():
    """Publish immutable skill versions and manage node installs."""


@skill_group.command('publish')
@click.argument('spec')
@click.option('--source', default='/Users/roy/luohy15/.agents', type=click.Path(path_type=Path))
@click.option('--sha', default='HEAD')
def publish(spec, source, sha):
    """Publish NAME@MAJOR.MINOR.PATCH from committed skills/NAME bytes."""
    name, version = parse_spec(spec, required=True)
    try:
        data, manifest, digest, commit, repo = collect_bundle(name, source, sha)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException('skill committed-source packaging failed: ' + str(exc)) from exc
    _print(api_request('POST', '/api/skill/publish', json={
        'name': name, 'bundle': base64.b64encode(data).decode(), 'manifest': manifest,
        'bundle_sha': digest, 'version': version, 'source_commit': commit, 'source_repo': repo,
    }))


@skill_group.command('list')
def list_skills():
    _print(api_request('GET', '/api/skill/list'))


@skill_group.command('show')
@click.argument('spec')
def show(spec):
    name, version = parse_spec(spec)
    _print(api_request('GET', '/api/skill/show', params={'name': name, **({'version': version} if version else {})}))


@skill_group.command('status')
@click.option('--node', default=None)
def status(node):
    _print(api_request('GET', '/api/skill/status', params={'node': node} if node else {}))


def _node_command(operation):
    @click.command(operation)
    @click.argument('spec')
    @click.option('--node', required=True)
    def command(spec, node):
        name, version = parse_spec(spec, required=operation == 'install')
        if version and operation in ('rollback', 'uninstall'):
            raise click.BadParameter('version is not allowed for ' + operation)
        _print(api_request('POST', '/api/skill/' + operation,
                           json={'name': name, 'version': version, 'node': node}))
    return command


for _operation in ('install', 'upgrade', 'rollback', 'uninstall'):
    skill_group.add_command(_node_command(_operation))
