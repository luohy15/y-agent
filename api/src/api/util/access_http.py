from typing import Optional

from starlette.responses import JSONResponse


def access_json(status: int, detail: str, code: str, state: Optional[str] = None) -> JSONResponse:
    payload = {"detail": detail, "code": code}
    if state is not None:
        payload["state"] = state
    return JSONResponse(status_code=status, content=payload)
