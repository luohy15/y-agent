import asyncio


async def local_exec(cmd: list[str], stdin: str | None = None, timeout: float = 30) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(
        proc.communicate(input=stdin.encode() if stdin else None),
        timeout=timeout,
    )
    return stdout.decode() if stdout else ""
