import asyncio
import os


async def local_exec(cmd: list[str], stdin: str | None = None, timeout: float = 30, cwd: str | None = None) -> str:
    if cwd:
        cwd = os.path.expanduser(cwd)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd or None,
    )
    stdout, _ = await asyncio.wait_for(
        proc.communicate(input=stdin.encode() if stdin else None),
        timeout=timeout,
    )
    return stdout.decode() if stdout else ""
