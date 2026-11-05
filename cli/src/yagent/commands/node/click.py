import json
from pathlib import Path

import click

from yagent.api_client import api_request


def _nodes():
    return api_request('GET', '/api/vm-config/list').json()


def _print_node(node: dict) -> None:
    click.echo(json.dumps(node, ensure_ascii=False, indent=2))


@click.group('node')
def node_group():
    """Manage execution nodes (vm_config rows).

    `default` is the orchestrator and SSH jump anchor. Other rows are chat-only
    targets reached through it; `y chat --on <name>` picks one.
    """


@node_group.command('list')
def node_list():
    """List nodes, default first."""
    nodes = _nodes()
    if not nodes:
        click.echo('no nodes configured')
        return
    headers = ('NAME', 'PLATFORM', 'SCOPE', 'ENABLED', 'ADDRESS', 'WORK_DIR')
    rows = [
        (
            node.get('name', ''),
            node.get('platform') or 'linux',
            node.get('data_scope') or 'personal',
            'yes' if node.get('enabled', True) else 'no',
            node.get('vm_name', ''),
            node.get('work_dir', ''),
        )
        for node in nodes
    ]
    widths = [max(len(str(row[i])) for row in (headers, *rows)) for i in range(len(headers))]
    for row in (headers, *rows):
        click.echo('  '.join(str(value).ljust(widths[i]) for i, value in enumerate(row)).rstrip())


@node_group.command('show')
@click.argument('name')
def node_show(name):
    """Show one node as JSON. SSH keys are never printed."""
    for node in _nodes():
        if node.get('name') == name:
            _print_node(node)
            return
    raise click.ClickException(f'unknown node: {name}')


@node_group.command('add')
@click.argument('name')
@click.option('--host', required=True, help='SSH host (tailnet IP or DNS name).')
@click.option('--user', required=True, help='SSH user on the node.')
@click.option('--port', default=22, type=click.IntRange(1, 65535), show_default=True)
@click.option('--platform', type=click.Choice(['linux', 'darwin']), default='linux', show_default=True,
              help='Derives binaries and PATH on the node.')
@click.option('--data-scope', type=click.Choice(['personal', 'work']), required=True,
              help='Visible metadata only: what kind of data this node carries.')
@click.option('--key-file', type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Private key for this node. Omit to inherit the default node key.')
@click.option('--inherit-key', is_flag=True, help='Explicitly inherit the default node key.')
@click.option('--work-dir', default='', help='Default workspace on the node.')
def node_add(name, host, user, port, platform, data_scope, key_file, inherit_key, work_dir):
    """Create or update a non-default node. No deploy is needed."""
    if key_file and inherit_key:
        raise click.UsageError('choose --key-file or --inherit-key, not both')
    payload = {
        'name': name,
        'vm_name': f'ssh:{user}@{host}:{port}',
        'platform': platform,
        'data_scope': data_scope,
        'work_dir': work_dir,
    }
    if key_file:
        payload['api_token'] = key_file.read_text()
    node = api_request('POST', '/api/vm-config', json=payload).json()
    _print_node(node)


def _set_enabled(name: str, enabled: bool) -> None:
    verb = 'enable' if enabled else 'disable'
    _print_node(api_request('POST', f'/api/vm-config/{name}/{verb}').json())


@node_group.command('enable')
@click.argument('name')
def node_enable(name):
    """Allow new chats on this node."""
    _set_enabled(name, True)


@node_group.command('disable')
@click.argument('name')
def node_disable(name):
    """Stop new chats on this node; existing chats still stop and monitor."""
    _set_enabled(name, False)
