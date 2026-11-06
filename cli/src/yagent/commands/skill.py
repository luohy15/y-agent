import base64
import hashlib
import json
from pathlib import Path

import click

from storage.skill_bundle import MAX_BYTES, MAX_FILES, build_bundle, scan_references, validate_name
from yagent.api_client import api_request


def collect_bundle(name, root):
    validate_name(name)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('skill source must be a real directory')
    files = {}
    total = 0
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if path.is_symlink() or any(part.startswith('.') for part in relative.parts):
            raise ValueError(f'symlink or dotfile in skill: {relative}')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f'not a regular skill file: {relative}')
        total += path.stat().st_size
        if total > MAX_BYTES or len(files) >= MAX_FILES:
            raise ValueError('skill bundle exceeds limits')
        content = path.read_bytes()
        files[relative.as_posix()] = (content, bool(path.stat().st_mode & 0o111))
    skills, absolute = scan_references({path: content for path, (content, _) in files.items()})
    references = []
    for value in sorted(absolute):
        path = Path(value)
        if not path.is_file():
            raise ValueError(f'absolute dependency is not a concrete file: {value}')
        references.append({'path': value, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return build_bundle(name, files, {'skills': sorted(skills - {name}), 'files': references})


@click.group('skill')
def skill_group():
    """Publish selected private skills and pin them to relay nodes."""


@skill_group.command('publish')
@click.argument('name')
@click.option('--node', 'nodes', multiple=True, required=True, help='Target node; repeat for each target.')
@click.option('--version', default=None)
def publish(name, nodes, version):
    """Publish ~/.agents/skills/NAME; replace its complete node pin set."""
    try:
        data, manifest, digest = collect_bundle(name, Path.home() / '.agents' / 'skills' / name)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    result = api_request('POST', '/api/skill/publish', json={
        'name': name, 'bundle': base64.b64encode(data).decode(), 'manifest': manifest,
        'bundle_sha': digest, 'nodes': list(nodes), 'version': version,
    }).json()
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@skill_group.command('list')
def list_pins():
    """List this owner's active node pins."""
    click.echo(json.dumps(api_request('GET', '/api/skill/list').json(), ensure_ascii=False, indent=2))


@skill_group.command('unshare')
@click.argument('name')
def unshare(name):
    """Remove all this skill's pins; next launches use their local skills again."""
    click.echo(json.dumps(api_request('POST', '/api/skill/unshare', json={'name': name}).json()))
