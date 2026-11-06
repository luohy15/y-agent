"""Verified skill delivery over the launch connection, without touching local skills."""
import hashlib
import posixpath
import shlex
import stat
import uuid

from storage.skill_bundle import MAX_BYTES, validate_manifest, canonical_sha


class SkillShareError(RuntimeError):
    pass


def chat_prefix(chat_id):
    return '/tmp/y-skill-' + hashlib.sha256(chat_id.encode()).hexdigest()[:24] + '-'


def cleanup_command(chat_id):
    name = chat_prefix(chat_id).removeprefix('/tmp/')
    return f"find /tmp/ -maxdepth 1 -name '{name}*' -exec rm -rf -- {{}} +"


def _mkdirs(sftp, path):
    try:
        entry = sftp.lstat(path)
        if not stat.S_ISDIR(entry.st_mode):
            raise SkillShareError('skill_cache_not_directory')
    except FileNotFoundError:
        parent = posixpath.dirname(path)
        if parent != path:
            _mkdirs(sftp, parent)
        try:
            sftp.mkdir(path, mode=0o700)
        except OSError:
            if not stat.S_ISDIR(sftp.lstat(path).st_mode):
                raise


def _read(sftp, path):
    with sftp.open(path, 'rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SkillShareError('skill_file_too_large')
    return data


def _matches(sftp, root, manifest):
    try:
        paths = set()
        pending = [('', root)]
        while pending:
            relative, directory = pending.pop()
            for entry in sftp.listdir_attr(directory):
                path = posixpath.join(relative, entry.filename)
                if stat.S_ISDIR(entry.st_mode):
                    pending.append((path, posixpath.join(root, path)))
                elif stat.S_ISREG(entry.st_mode):
                    paths.add(path)
                else:
                    return False
                if len(paths) + len(pending) > 256:
                    return False
        if paths != {entry['path'] for entry in manifest['files']}:
            return False
        for entry in manifest['files']:
            path = posixpath.join(root, entry['path'])
            if hashlib.sha256(_read(sftp, path)).hexdigest() != entry['sha256']:
                return False
            if bool(sftp.stat(path).st_mode & 0o111) != entry['executable']:
                return False
        return True
    except OSError:
        return False


def _write_files(sftp, root, manifest, files):
    for entry in manifest['files']:
        path = posixpath.join(root, entry['path'])
        _mkdirs(sftp, posixpath.dirname(path))
        with sftp.open(path, 'wx') as stream:
            stream.write(files[entry['path']])
        sftp.chmod(path, 0o700 if entry['executable'] else 0o600)


def _cache(sftp, home, pin, fetch):
    root = f"{home}/.y-agent/skill-cache/{pin['bundle_sha']}"
    _mkdirs(sftp, root)
    # Generations are immutable. A corrupt generation is never overwritten while
    # another launch may still be using it; cache pruning is deliberately separate.
    for entry in sftp.listdir_attr(root):
        if stat.S_ISDIR(entry.st_mode):
            candidate = f'{root}/{entry.filename}'
            if _matches(sftp, candidate, pin['manifest']):
                return candidate
    files = fetch(pin)
    candidate = f'{root}/{uuid.uuid4().hex}'
    sftp.mkdir(candidate, mode=0o700)
    _write_files(sftp, candidate, pin['manifest'], files)
    if not _matches(sftp, candidate, pin['manifest']):
        raise SkillShareError('skill_cache_verification_failed')
    return candidate


def stage_remote(client, chat_id, pins, fetch):
    if not pins:
        return None
    sftp = client.open_sftp()
    root = None
    try:
        home = sftp.normalize('.')
        config = sftp.normalize(f'{home}/.claude')
        names = {pin['name'] for pin in pins}
        cache = {}
        identical = True
        for pin in pins:
            manifest = pin['manifest']
            validate_manifest(pin['name'], manifest)
            if canonical_sha(manifest) != pin['bundle_sha']:
                raise SkillShareError('skill_manifest_hash_mismatch')
            if not set(manifest['requires']['skills']).issubset(names):
                raise SkillShareError(f"skill_dependency_unpinned:{pin['name']}")
            for dependency in manifest['requires']['files']:
                if hashlib.sha256(_read(sftp, dependency['path'])).hexdigest() != dependency['sha256']:
                    raise SkillShareError(f"skill_dependency_mismatch:{pin['name']}")
            cache[pin['name']] = _cache(sftp, home, pin, fetch)
            identical = identical and _matches(sftp, f"{config}/skills/{pin['name']}", manifest)
        if identical:
            return None
        root = f'{chat_prefix(chat_id)}{uuid.uuid4().hex}'
        sftp.mkdir(root, mode=0o700)
        sftp.chmod(root, 0o700)
        config_entries = sftp.listdir_attr(config)
        for entry in config_entries:
            if entry.filename != 'skills':
                sftp.symlink(f'{config}/{entry.filename}', f'{root}/{entry.filename}')
        if '.claude.json' not in {entry.filename for entry in config_entries}:
            try:
                sftp.stat(f'{home}/.claude.json')
            except FileNotFoundError:
                pass
            else:
                sftp.symlink(f'{home}/.claude.json', f'{root}/.claude.json')
        sftp.mkdir(f'{root}/skills', mode=0o700)
        try:
            local_entries = sftp.listdir_attr(f'{config}/skills')
        except FileNotFoundError:
            local_entries = []
        for entry in local_entries:
            if entry.filename not in names:
                sftp.symlink(f'{config}/skills/{entry.filename}', f'{root}/skills/{entry.filename}')
        for pin in pins:
            target = f"{root}/skills/{pin['name']}"
            sftp.mkdir(target, mode=0o700)
            files = {entry['path']: _read(sftp, f"{cache[pin['name']]}/{entry['path']}")
                     for entry in pin['manifest']['files']}
            _write_files(sftp, target, pin['manifest'], files)
            if not _matches(sftp, target, pin['manifest']):
                raise SkillShareError('skill_overlay_verification_failed')
        return root
    except Exception as exc:
        if root:
            client.exec_command(f'rm -rf -- {shlex.quote(root)}')
        if isinstance(exc, SkillShareError):
            raise
        raise SkillShareError('skill_share_staging_failed') from exc
    finally:
        sftp.close()
