import httpx

from storage.entity.dto import VmConfig

SPRITES_API = "https://api.sprites.dev"


async def sprites_exec(vm_config: VmConfig, cmd: list[str], stdin: str | None = None, dir: str | None = None, timeout: float = 30) -> str:
    api_url = SPRITES_API
    params = [("cmd", c) for c in cmd]
    if dir:
        params.append(("dir", dir))
    if stdin is not None:
        params.append(("stdin", "true"))
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{api_url}/v1/sprites/{vm_config.vm_name}/exec",
            params=params,
            headers={"Authorization": f"Bearer {vm_config.api_token}"},
            content=stdin.encode() if stdin else None,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.text
