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
    personal and work are rejected. An empty stored node namespace publishes as default.
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


@skills_group.command('publish')
@click.option('--run', is_flag=True, help='Upload archives and push selected nodes.')
@click.option('--dry-run', is_flag=True, help='Read API policy and build only (the default).')
@click.option('--source', type=click.Path(path_type=Path), default=lambda: Path.home() / '.agents')
@click.option('--node', multiple=True, help='SSH-config alias registered as a node. Default: mac only.')
@click.option('--local-target', type=click.Path(path_type=Path), help='Local effective tree only; no upload or SSH.')
@click.option('--namespace', type=str, default=None,
              help='Local scope when --local-target is set. Omitted means default. '
                   'Remote delivery rejects this flag and uses the registry scope. '
                   'Scope default is not the node named default.')
def skills_publish(run, dry_run, source, node, local_target, namespace):
    """Publish composed trees only for node-deliverable scopes.

    Dry-run performs read-only API requests, never uploads or writes a target.
    macmini must be selected explicitly. Node SSH keys remain in SSH config.
    """
    if run and dry_run:
        raise click.UsageError('choose --run or --dry-run, not both')
    if local_target and node:
        raise click.UsageError('--local-target cannot be combined with --node')
    try:
        policies = agents_publish.load_registry(get=_get)
        if local_target:
            chosen = namespace or 'default'
            canonical = agents_publish.normalize_namespace(chosen)
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
