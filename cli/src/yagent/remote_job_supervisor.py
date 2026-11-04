"""Standalone stdlib supervisor staged on the Mac; no host credentials/imports."""

import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


def capture(stream, path):
    remaining = 65536
    with path.open('wb') as output:
        while chunk := stream.read(4096):
            output.write(chunk[:remaining])
            remaining = max(0, remaining - len(chunk))


def terminate(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            continue
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
    return False


def version_key(name):
    parts = []
    for part in name.split('.'):
        if not part.isdigit():
            return (0, name)
        parts.append(int(part))
    return (1, tuple(parts))


def browser_client(root=None):
    base = Path(root) if root is not None else Path.home() / '.codex/plugins/cache/openai-bundled'
    found = []
    for family in ('browser', 'chrome'):
        family_dir = base / family
        if not family_dir.is_dir():
            continue
        for version_dir in family_dir.iterdir():
            script = version_dir / 'scripts' / 'browser-client.mjs'
            if script.is_file():
                found.append((version_key(version_dir.name), family, str(script)))
    if not found:
        return 'BROWSER_CLIENT_NOT_FOUND'
    found.sort()
    return found[-1][2]


def render_prompt(text, client_path):
    marker = 'BROWSER_CLIENT_PATH'
    if marker not in text:
        return text
    # Once: a later copy inside the server-validated URL must not rewrite the setup line.
    return text.replace(marker, client_path, 1)


def main():
    root = Path.cwd()
    config = json.loads((root / 'input.json').read_text())
    (root / 'prompt.txt').write_text(render_prompt(config['prompt'], browser_client()))
    with (root / 'prompt.txt').open('rb') as prompt_input:
        process = subprocess.Popen(
            ['codex', 'exec', '--ephemeral', '--skip-git-repo-check', '--approve-for-me',
             '-C', str(root), '--json', '-'],
            stdin=prompt_input, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    (root / 'pid').write_text(str(process.pid))
    threads = [threading.Thread(target=capture, args=(stream, root / name), daemon=True)
               for stream, name in [(process.stdout, 'stdout.jsonl'), (process.stderr, 'stderr.txt')]]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + config['timeout_seconds']
    state = None
    while process.poll() is None:
        if (root / 'cancel').exists():
            state = 'cancelled'
            break
        if time.monotonic() >= deadline:
            state = 'timeout'
            break
        time.sleep(0.2)
    confirmed = terminate(process)
    if not confirmed:
        state = 'host_offline'
    elif state is None:
        state = 'completed' if process.returncode == 0 else 'failed'
    for thread in threads:
        thread.join(timeout=2)
    result = {'state': state, 'exit_code': process.returncode,
              'termination_confirmed': confirmed}
    (root / 'exit.tmp').write_text(json.dumps(result))
    (root / 'exit.tmp').replace(root / 'exit')


if __name__ == '__main__':
    main()
