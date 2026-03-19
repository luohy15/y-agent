from fastapi import APIRouter, HTTPException, Query, Request

from storage.service import trace as trace_service

router = APIRouter(prefix="/trace")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("")
async def get_trace(request: Request, trace_id: str = Query(...)):
    user_id = _get_user_id(request)
    trace = trace_service.get_trace(user_id, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace.to_dict()
