"""Host-internal VM command execution shared by API controllers and module_host."""

from __future__ import annotations

from typing import Optional


async def execute_vm_command(
    vm_config,
    argv: list[str],
    *,
    stdin: Optional[str] = None,
    timeout: float = 30,
    work_dir: Optional[str] = None,
    check: bool = False,
    wake: bool = True,
) -> str:
    """Execute argv using a resolved VM config.

    `work_dir` overrides the config only when supplied. Callers resolve the VM
    according to their own ownership rules before reaching this primitive.
    `wake=False` skips `ensure_and_touch_vm` so a caller that already refused a
    stopped VM does not pay the unbounded cold-boot prelude.
    """
    effective_work_dir = work_dir if work_dir is not None else vm_config.work_dir
    if not vm_config.api_token:
        from agent.tools.local_exec import local_exec

        return await local_exec(
            argv,
            stdin,
            timeout=timeout,
            cwd=effective_work_dir or None,
            check=check,
        )

    from agent.tools.ssh_exec import ssh_exec

    return await ssh_exec(
        vm_config,
        argv,
        stdin,
        dir=effective_work_dir or None,
        timeout=timeout,
        check=check,
        wake=wake,
    )


async def run_vm_command(
    user_id: int,
    argv: list[str],
    timeout: float = 10,
    vm_name: Optional[str] = None,
    work_dir: Optional[str] = None,
    stdin: Optional[str] = None,
    check: bool = False,
    wake: bool = True,
) -> str:
    """Resolve a user's VM then execute an argv command on it.

    API controllers use this legacy host path. Backend modules use the stricter
    request-bound wrapper in ``agent.module_host`` instead.
    """
    from agent.config import resolve_vm_config

    vm_config = resolve_vm_config(user_id, vm_name)
    return await execute_vm_command(
        vm_config,
        argv,
        stdin=stdin,
        timeout=timeout,
        work_dir=work_dir,
        check=check,
        wake=wake,
    )
