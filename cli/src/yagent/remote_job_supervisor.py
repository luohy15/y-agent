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


def main():
    root = Path.cwd()
    config = json.loads((root / 'input.json').read_text())
    (root / 'prompt.txt').write_text(config['prompt'])
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
