from fastapi import APIRouter, HTTPException, Query, Request

from storage.service import trace as trace_service

router = APIRouter(prefix="/trace")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/list")
async def list_traces(request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    user_id = _get_user_id(request)
    traces = await trace_service.list_traces(user_id, limit=limit, offset=offset)
    return [
        {
            "trace_id": t.trace_id,
            "participants": t.participants,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
        }
        for t in traces
    ]


@router.get("")
async def get_trace(request: Request, trace_id: str = Query(...)):
    user_id = _get_user_id(request)
    trace = trace_service.get_trace(user_id, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace.to_dict()
