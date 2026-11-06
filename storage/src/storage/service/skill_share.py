"""Owner-scoped pins and private immutable skill bundle storage."""
import os
from pathlib import Path
from urllib.parse import quote

from storage.repository import skill_share as repo
from storage.service import user, vm_config
from storage.skill_bundle import MAX_BYTES, validate_bundle, validate_name


def _key(user_id, name, digest):
    public = user.get_live_public_user_id(user_id)
    if not public:
        raise ValueError('skill owner not found')
    if public in ('.', '..'):
        raise ValueError('invalid skill owner')
    from storage.skill_bundle import SHA
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError('invalid skill bundle hash')
    return f'skill/{quote(public, safe="")}/{validate_name(name)}/{digest}.zip'


def _local_path(key):
    return Path(os.environ.get('Y_AGENT_SKILL_BUNDLE_DIR', '~/.y-agent/skill-bundles')).expanduser() / key


def _s3():
    import boto3
    client = boto3.client('s3')
    bucket = os.environ['Y_AGENT_S3_BUCKET']
    block = client.get_public_access_block(Bucket=bucket).get('PublicAccessBlockConfiguration', {})
    if not all(block.get(key) is True for key in ('BlockPublicAcls', 'BlockPublicPolicy', 'IgnorePublicAcls', 'RestrictPublicBuckets')):
        raise RuntimeError('skill_store_not_private')
    return client, bucket


def publish(user_id, name, data, manifest, bundle_sha, nodes, version=None):
    validate_bundle(name, data, manifest, bundle_sha)
    if not nodes or len(nodes) > 64 or len(set(nodes)) != len(nodes):
        raise ValueError('select at least one distinct node')
    for node in nodes:
        config = vm_config.get_config(user_id, node)
        if node == 'macmini' or not config or not config.enabled or (config.auth_mode or 'relay') != 'relay':
            raise ValueError(f'skill node unavailable or not relay: {node}')
    key = _key(user_id, name, bundle_sha)
    if os.environ.get('Y_AGENT_S3_BUCKET'):
        client, bucket = _s3()
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType='application/zip', ServerSideEncryption='AES256')
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with path.open('xb') as stream:
                os.chmod(path, 0o600)
                stream.write(data)
        except FileExistsError:
            validate_bundle(name, path.read_bytes(), manifest, bundle_sha)
    repo.publish(user_id, name, bundle_sha, manifest, version, nodes)
    return {'name': name, 'bundle_sha': bundle_sha, 'nodes': nodes, 'version': version}


def read_bundle(user_id, pin):
    key = _key(user_id, pin['name'], pin['bundle_sha'])
    if os.environ.get('Y_AGENT_S3_BUCKET'):
        client, bucket = _s3()
        body = client.get_object(Bucket=bucket, Key=key)['Body']
        try:
            data = body.read(MAX_BYTES + 1)
        finally:
            body.close()
    else:
        with _local_path(key).open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
    return validate_bundle(pin['name'], data, pin['manifest'], pin['bundle_sha'])


def list_pins(user_id, node=None):
    return repo.list_pins(user_id, node)


def unshare(user_id, name):
    validate_name(name)
    repo.unshare(user_id, name)
    return {'ok': True, 'name': name}
