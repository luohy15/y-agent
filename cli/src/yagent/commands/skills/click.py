from pathlib import Path
import subprocess
import tarfile

import click
import httpx

from agent import agents_publish
from yagent.api_client import api_request


def _get(path, **kwargs):
    return api_request('GET', path, **kwargs).json()


def _report(source, namespace, policies, effective=None):
    canonical = agents_publish.normalize_namespace(namespace)
    result = agents_publish.assemble(source, canonical, get=_get, policies=policies)
    click.echo(result['summary'])
    if effective is not None:
        fresh = agents_publish.assess_freshness(source, effective, canonical, get=_get, policies=policies)
        if not fresh['source_fresh'] or not fresh['entrypoint_match'] or not fresh['effective_match']:
            raise ValueError(
                'stale effective tree: source_digest mismatch '
                f"(entrypoint_match={fresh['entrypoint_match']})"
            )
        click.echo('effective=fresh')
    return result


@click.group('skills')
def skills_group():
    """Check, export and publish a composed agents tree.

    Scope default is the unrestricted selection. It is not the node named default.
    personal and work are rejected. An empty stored node namespace publishes as default
    for --node only. --local-target requires an explicit --namespace, and default there
    also requires --full-tree. --host uses one node's stored namespace and refuses an
    unset, default, or non-node-deliverable scope.
    """


@skills_group.command('check')
@click.option('--source', type=click.Path(path_type=Path), default=lambda: Path.home() / '.agents')
@click.option('--namespace', type=str, default='default', show_default=True)
@click.option('--effective', type=click.Path(path_type=Path), default=None,
              help='Compare this effective tree with the source. Stale when the source digest differs.')
def skills_check(source, namespace, effective):
    """Validate one scope against the source and build without writing."""
    try:
        policies = agents_publish.load_registry(get=_get)
        _report(source, namespace, policies, effective)
    except (OSError, ValueError, tarfile.TarError, httpx.HTTPError) as error:
        raise click.ClickException(str(error)) from error


@skills_group.command('export')
@click.option('--namespace', type=str, default=None)
@click.option('--source', type=click.Path(path_type=Path), default=lambda: Path.home() / '.agents')
@click.option('--out', required=True, type=click.Path(path_type=Path))
def skills_export(namespace, source, out):
    """Export a registered namespace. An explicit --namespace is required."""
    if namespace is None:
        raise click.UsageError('export requires an explicit registered --namespace')
    try:
        canonical = agents_publish.normalize_namespace(namespace)
        if canonical == 'default':
            raise click.UsageError('export requires an explicit registered --namespace')
        policies = agents_publish.load_registry(get=_get)
        result = agents_publish.export_scope(source, out, canonical, get=_get, policies=policies)
    except (OSError, ValueError, tarfile.TarError, httpx.HTTPError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(result['summary'])


def _one_delivery(local_target, node, host):
    chosen = [name for name, value in (('--local-target', local_target), ('--node', node), ('--host', host)) if value]
    if len(chosen) > 1:
        raise click.UsageError('choose only one of --node, --host, or --local-target')


@skills_group.command('publish')
@click.option('--run', is_flag=True, help='Upload archives and push selected nodes.')
@click.option('--dry-run', is_flag=True, help='Read API policy and build only (the default).')
@click.option('--source', type=click.Path(path_type=Path), default=lambda: Path.home() / '.agents')
@click.option('--node', multiple=True, help='SSH-config alias registered as a node. Default: mac only.')
@click.option('--host', type=str, default=None,
              help='SSH alias of one tenant-owned node. Uses its stored namespace.')
@click.option('--local-target', type=click.Path(path_type=Path), help='Local effective tree only; no upload or SSH.')
@click.option('--namespace', type=str, default=None,
              help='Required with --local-target. default also requires --full-tree. '
                   'Remote --node and --host reject this flag and use the registry scope. '
                   'Scope default is not the node named default.')
@click.option('--full-tree', is_flag=True,
              help='With --local-target --namespace default, publish the unrestricted selection.')
def skills_publish(run, dry_run, source, node, host, local_target, namespace, full_tree):
    """Publish composed trees only for node-deliverable scopes.

    Dry-run performs read-only API requests, never uploads or writes a target.
    macmini must be selected explicitly. Node SSH keys remain in SSH config.
    """
    if run and dry_run:
        raise click.UsageError('choose --run or --dry-run, not both')
    _one_delivery(local_target, node, host)
    if full_tree and (not local_target or namespace != 'default'):
        raise click.UsageError('--full-tree applies only to --local-target --namespace default')
    if local_target and namespace is None:
        raise click.UsageError('--local-target requires an explicit --namespace')
    if local_target and namespace == 'default' and not full_tree:
        raise click.UsageError('--namespace default requires --full-tree')
    try:
        policies = agents_publish.load_registry(get=_get)
        if local_target:
            canonical = agents_publish.normalize_namespace(namespace)
            if canonical != 'default' and not policies['by_name'].get(canonical, {}).get('node_deliverable', False):
                raise click.UsageError('namespace is not node-deliverable')
            if run:
                result = agents_publish.compose_to(source, local_target, canonical, get=_get, policies=policies)
            else:
                result = agents_publish.assemble(source, canonical, get=_get, policies=policies)
            click.echo(result['summary'])
            if not run:
                click.echo('Dry-run: no upload or target write')
            return
        if namespace is not None:
            raise click.UsageError('--namespace cannot override a remote node scope')
        if host:
            scope = agents_publish.resolve_host_scope(host, _get('/api/vm-config/list'), policies)
            scopes = {host: scope}
        else:
            scopes = agents_publish.node_namespaces(
                list(dict.fromkeys(node or ('mac',))), _get('/api/vm-config/list'), policies)
        for name, scope in scopes.items():
            click.echo(f'{name}: scope={scope}')
        archives = {}
        for scope in sorted(set(scopes.values())):
            result = _report(source, scope, policies)
            archives[scope] = result['archive']
        if not run:
            click.echo('Dry-run: no upload or target write')
        else:
            agents_publish.publish_archives(archives, scopes)
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError, httpx.HTTPError) as error:
        raise click.ClickException(str(error)) from error
