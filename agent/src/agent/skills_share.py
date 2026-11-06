"""Verified skill delivery over the launch connection, without touching local skills."""
import hashlib
import json
import re
import posixpath
import shlex
import stat
import uuid

from storage.skill_bundle import MAX_BYTES, validate_manifest, canonical_sha


class SkillShareError(RuntimeError):
    pass


def cleanup_command(chat_id, node=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', chat_id):
        raise SkillShareError('skill_invalid_chat_id')
    name = hashlib.sha256(chat_id.encode()).hexdigest()
    if node is None:
        only = ''
    else:
        from storage.service.vm_config import validate_node_name
        only = validate_node_name(node)
    # POSIX sh, so an unmatched glob is literal and a remote zsh nomatch option
    # cannot see it. macmini is never a shared-skill node.
    script = '''
only=ONLY
root="$HOME/.y-agent/skill-overlay"
[ -d "$root" ] && [ ! -L "$root" ] || exit 0
for node_dir in "$root"/*; do
  [ -d "$node_dir" ] && [ ! -L "$node_dir" ] || continue
  node_name=${node_dir##*/}
  case "$node_name" in macmini|.*|*[!A-Za-z0-9_.-]*) continue ;; esac
  [ -z "$only" ] || [ "$node_name" = "$only" ] || continue
  refs="$node_dir/.refs"
  [ -d "$refs" ] && [ ! -L "$refs" ] || continue
  for generation in "$refs"/*; do
    [ -d "$generation" ] && [ ! -L "$generation" ] || continue
    rm -f -- "$generation/REF"
  done
done
'''.replace('ONLY', shlex.quote(only)).replace('REF', name)
    return 'sh -c ' + shlex.quote(script)


def _safe_tmux(binary):
    return isinstance(binary, str) and re.fullmatch(r'[A-Za-z0-9_./+-]{1,256}', binary) and '..' not in binary.split('/')


def sweep_command(node, ttl_days=7, tmux_binary='tmux'):
    from storage.service.vm_config import validate_node_name
    validate_node_name(node)
    if node == 'macmini' or not _safe_tmux(tmux_binary):
        return 'sh -c ' + shlex.quote('exit 0')
    ttl_days = max(1, min(int(ttl_days), 3650))
    digest = '[0-9a-f]' * 64
    sibling = digest + '-' + ('[0-9a-f]' * 32)
    # No lock: builders publish by atomic rename, and .tmp entries younger than
    # one day are concurrent builds. An unresolvable tmux or ps is unknown:
    # exit 0 before any delete, so the launch is not aborted.
    script = '''
node=NODE
tmux_bin=TMUX
root="$HOME/.y-agent/skill-overlay/$node"
[ -d "$root" ] && [ ! -L "$root" ] || exit 0
ps_bin=$(command -v ps) || exit 0
processes=$("$ps_bin" axeww) || exit 0
case "$tmux_bin" in
  /*) [ -x "$tmux_bin" ] || exit 0 ;;
  *) tmux_bin=$(command -v "$tmux_bin") || exit 0 ;;
esac
sessions=
for socket in dedicated legacy; do
  if [ "$socket" = dedicated ]; then
    result=$("$tmux_bin" -L y-agent list-sessions -F '#S' 2>&1); status=$?
  else
    result=$("$tmux_bin" list-sessions -F '#S' 2>&1); status=$?
  fi
  if [ "$status" != 0 ]; then
    case "$result" in
      *"no server running"*|*"No such file or directory"*) result="" ;;
      *) exit 0 ;;
    esac
  fi
  sessions="$sessions
$result"
done
if [ -d "$root/.tmp" ] && [ ! -L "$root/.tmp" ]; then
  for tmp in "$root/.tmp"/*; do
    [ -d "$tmp" ] && [ ! -L "$tmp" ] || continue
    [ -n "$(find "$tmp" -prune -mtime +1 -print)" ] || continue
    rm -rf -- "$tmp" || exit 0
  done
fi
for generation in "$root"/*; do
  [ -d "$generation" ] && [ ! -L "$generation" ] || continue
  name=${generation##*/}
  case "$name" in
    DIGEST|SIBLING) ;;
    *) continue ;;
  esac
  [ -n "$(find "$generation" -prune -mtime +TTL -print)" ] || continue
  case "$processes" in *"$generation"*) continue ;; esac
  refs="$root/.refs/$name"
  if [ -L "$refs" ]; then
    continue
  fi
  keep=0
  if [ -d "$refs" ]; then
    for ref in "$refs"/*; do
      if [ -L "$ref" ]; then keep=1; break; fi
      [ -f "$ref" ] || continue
      [ -n "$(find "$ref" -prune -mtime +TTL -print)" ] || { keep=1; break; }
      chat=$(cat "$ref") || { keep=1; break; }
      case "$chat" in ''|*[!a-zA-Z0-9_-]*) keep=1; break ;; esac
      case "$sessions" in *"cc-$chat"*) keep=1; break ;; esac
    done
  fi
  [ "$keep" = 0 ] || continue
  rm -rf -- "$generation" || exit 0
  if [ -d "$refs" ] && [ ! -L "$refs" ]; then
    rm -rf -- "$refs" || exit 0
  fi
done
'''.replace('NODE', shlex.quote(node)).replace('TMUX', shlex.quote(tmux_binary)).replace('TTL', str(ttl_days)).replace('DIGEST', digest).replace('SIBLING', sibling)
    return 'sh -c ' + shlex.quote(script)


def generation_digest(pins, config_entries, claude_json, skill_entries):
    return canonical_sha({'v': 1, 'pins': sorted(
        [{'name': pin['name'], 'bundle_sha': pin['bundle_sha']} for pin in pins], key=lambda item: item['name']),
        'config_entries': sorted(config_entries), 'claude_json': claude_json,
        'skill_entries': sorted(skill_entries)})


def _remove_tree(sftp, root):
    for entry in sftp.listdir_attr(root):
        path = f'{root}/{entry.filename}'
        if stat.S_ISDIR(entry.st_mode):
            _remove_tree(sftp, path)
        else:
            sftp.remove(path)
    sftp.rmdir(root)


def _ref(sftp, parent, generation, chat_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', chat_id):
        raise SkillShareError('skill_invalid_chat_id')
    directory = f'{parent}/.refs/{generation}'
    _mkdirs(sftp, directory)
    path = f'{directory}/{hashlib.sha256(chat_id.encode()).hexdigest()}'
    with sftp.open(path, 'w') as stream:
        stream.write(chat_id)
    sftp.chmod(path, 0o600)


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


def _symlink_to(sftp, path, target):
    info = sftp.lstat(path)
    return stat.S_ISLNK(info.st_mode) and sftp.readlink(path) == target


def _generation_valid(sftp, root, digest, pins, config, home, config_entries, claude_json, skill_entries):
    try:
        info = sftp.lstat(root)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return False
        marker = f'{root}/.generation.json'
        if json.loads(_read(sftp, marker)) != {'digest': digest}:
            return False
        names = {pin['name'] for pin in pins}
        expected = set(config_entries) | {'skills', '.generation.json'}
        if claude_json and '.claude.json' not in config_entries:
            expected.add('.claude.json')
        rows = {entry.filename: entry for entry in sftp.listdir_attr(root)}
        if set(rows) != expected or stat.S_ISLNK(rows['.generation.json'].st_mode):
            return False
        for name in config_entries:
            if not _symlink_to(sftp, f'{root}/{name}', f'{config}/{name}'):
                return False
        if '.claude.json' in expected and '.claude.json' not in config_entries:
            if not _symlink_to(sftp, f'{root}/.claude.json', f'{home}/.claude.json'):
                return False
        skills = rows['skills']
        if stat.S_ISLNK(skills.st_mode) or not stat.S_ISDIR(skills.st_mode):
            return False
        skill_rows = {entry.filename: entry for entry in sftp.listdir_attr(f'{root}/skills')}
        if set(skill_rows) != set(skill_entries) | names:
            return False
        for name in skill_entries:
            if name not in names and not _symlink_to(sftp, f'{root}/skills/{name}', f'{config}/skills/{name}'):
                return False
        for pin in pins:
            row = skill_rows[pin['name']]
            if stat.S_ISLNK(row.st_mode) or not stat.S_ISDIR(row.st_mode):
                return False
            if not _matches(sftp, f"{root}/skills/{pin['name']}", pin['manifest']):
                return False
        return True
    except (OSError, ValueError, KeyError):
        return False


def stage_remote(client, chat_id, pins, fetch, node='default'):
    if not pins:
        return None
    from storage.service.vm_config import validate_node_name
    validate_node_name(node)
    sftp = client.open_sftp()
    temporary = None
    try:
        home = sftp.normalize('.')
        config = sftp.normalize(f'{home}/.claude')
        names = {pin['name'] for pin in pins}
        for pin in pins:
            manifest = pin['manifest']
            validate_manifest(pin['name'], manifest)
            if canonical_sha(manifest) != pin['bundle_sha']:
                raise SkillShareError('skill_manifest_hash_mismatch')
            if not set(manifest['requires']['skills']).issubset(names):
                raise SkillShareError('skill_dependency_not_installed')
            for dependency in manifest['requires']['files']:
                if hashlib.sha256(_read(sftp, dependency['path'])).hexdigest() != dependency['sha256']:
                    raise SkillShareError('skill_dependency_mismatch')
        if all(_matches(sftp, f"{config}/skills/{pin['name']}", pin['manifest']) for pin in pins):
            return None
        config_entries = sorted(entry.filename for entry in sftp.listdir_attr(config) if entry.filename != 'skills')
        try:
            skill_entries = sorted(entry.filename for entry in sftp.listdir_attr(f'{config}/skills'))
        except FileNotFoundError:
            skill_entries = []
        try:
            sftp.stat(f'{home}/.claude.json')
            claude_json = True
        except FileNotFoundError:
            claude_json = False
        digest = generation_digest(pins, config_entries, claude_json, skill_entries)
        parent = f'{home}/.y-agent/skill-overlay/{node}'
        _mkdirs(sftp, parent)
        root = f'{parent}/{digest}'
        skeleton = (config, home, config_entries, claude_json, skill_entries)
        _ref(sftp, parent, digest, chat_id)
        if _generation_valid(sftp, root, digest, pins, *skeleton):
            return root
        cache = {pin['name']: _cache(sftp, home, pin, fetch) for pin in pins}
        _mkdirs(sftp, f'{parent}/.tmp')
        temporary = f'{parent}/.tmp/{digest}.{uuid.uuid4().hex}'
        sftp.mkdir(temporary, mode=0o700)
        for entry in config_entries:
            sftp.symlink(f'{config}/{entry}', f'{temporary}/{entry}')
        if claude_json and '.claude.json' not in config_entries:
            sftp.symlink(f'{home}/.claude.json', f'{temporary}/.claude.json')
        sftp.mkdir(f'{temporary}/skills', mode=0o700)
        for entry in skill_entries:
            if entry not in names:
                sftp.symlink(f'{config}/skills/{entry}', f'{temporary}/skills/{entry}')
        for pin in pins:
            target = f"{temporary}/skills/{pin['name']}"
            sftp.mkdir(target, mode=0o700)
            files = {entry['path']: _read(sftp, f"{cache[pin['name']]}/{entry['path']}")
                     for entry in pin['manifest']['files']}
            _write_files(sftp, target, pin['manifest'], files)
        with sftp.open(f'{temporary}/.generation.json', 'wx') as stream:
            stream.write(json.dumps({'digest': digest}).encode())
        if not _generation_valid(sftp, temporary, digest, pins, *skeleton):
            raise SkillShareError('skill_overlay_verification_failed')
        try:
            sftp.rename(temporary, root)
            temporary = None
        except OSError:
            if _generation_valid(sftp, root, digest, pins, *skeleton):
                _remove_tree(sftp, temporary)
                temporary = None
            else:
                generation = digest + '-' + uuid.uuid4().hex
                root = f'{parent}/{generation}'
                _ref(sftp, parent, generation, chat_id)
                sftp.rename(temporary, root)
                temporary = None
        return root
    except Exception as exc:
        if temporary:
            _remove_tree(sftp, temporary)
        if isinstance(exc, SkillShareError):
            raise
        raise SkillShareError('skill_share_staging_failed') from exc
    finally:
        sftp.close()
