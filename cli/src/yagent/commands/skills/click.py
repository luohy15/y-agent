import hashlib
import io
from pathlib import Path
import subprocess
import tarfile

import click
import httpx

from agent import agents_publish
from yagent.api_client import api_request


def _get(path, **kwargs):
    return api_request('GET', path, **kwargs).json()


def _build(source, namespace):
    prefixes, policy_digest = agents_publish.load_policy(namespace, _get)
    agents_publish.check_policy(source, prefixes)
    data = agents_publish.build_archive(source, namespace, prefixes)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        count = sum(member.isfile() and member.name != 'MANIFEST.sha256' for member in archive)
    click.echo(f'{namespace}: policy={policy_digest} sha256={hashlib.sha256(data).hexdigest()} '
               f'files={count} bytes={len(data)}')
    return data


@click.group('skills')
def skills_group():
    """Check and publish the EC2 agents tree to execution nodes."""


@skills_group.command('check')
@click.option('--source', type=click.Path(path_type=Path), default=lambda: Path.home() / '.agents')
@click.option('--namespace', type=click.Choice(['personal', 'work']), default='work', show_default=True)
def skills_check(source, namespace):
    """Validate namespace rules against the source and build without writing."""
    try:
        _build(source, namespace)
    except (OSError, ValueError, tarfile.TarError, httpx.HTTPError) as error:
        raise click.ClickException(str(error)) from error


@skills_group.command('publish')
@click.option('--run', is_flag=True, help='Upload archives and push selected nodes.')
@click.option('--dry-run', is_flag=True, help='Read API policy and build only (the default).')
@click.option('--source', type=click.Path(path_type=Path), default=lambda: Path.home() / '.agents')
@click.option('--node', multiple=True, help='SSH-config alias registered as a node. Default: mac only.')
@click.option('--local-target', type=click.Path(path_type=Path), help='Local receiver only; no upload or SSH.')
@click.option('--namespace', type=click.Choice(['personal', 'work']), default='personal', show_default=True,
              help='Namespace for --local-target; remote delivery always uses registry scope.')
def skills_publish(run, dry_run, source, node, local_target, namespace):
    """Publish selected namespaces. Work requires the namespace module.

    Dry-run performs read-only API requests, never uploads or writes a target.
    macmini must be selected explicitly. Node SSH keys remain in SSH config.
    """
    if run and dry_run:
        raise click.UsageError('choose --run or --dry-run, not both')
    if local_target and node:
        raise click.UsageError('--local-target cannot be combined with --node')
    try:
        scopes = {} if local_target else agents_publish.node_namespaces(
            list(dict.fromkeys(node or ('mac',))), _get('/api/vm-config/list'))
        namespaces = [namespace] if local_target else sorted(set(scopes.values()))
        archives = {scope: _build(source, scope) for scope in namespaces}
        if not run:
            click.echo('Dry-run: no upload or target write')
        elif local_target:
            click.echo(agents_publish.install_archive(archives[namespace], local_target))
        else:
            agents_publish.publish_archives(archives, scopes)
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError, httpx.HTTPError) as error:
        raise click.ClickException(str(error)) from error
