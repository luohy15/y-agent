from fastapi import APIRouter, HTTPException, Query, Request

from storage.repository.chat import find_chats_by_trace_id

router = APIRouter(prefix="/trace")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("/list")
async def list_traces(request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    """List distinct trace_ids from chats, ordered by most recent."""
    user_id = _get_user_id(request)
    from storage.repository.chat import list_trace_ids
    traces = list_trace_ids(user_id, limit=limit, offset=offset)
    return traces


@router.get("/chats")
async def get_trace_chats(request: Request, trace_id: str = Query(...)):
    """Get all chats participating in a trace."""
    user_id = _get_user_id(request)
    chats = find_chats_by_trace_id(user_id, trace_id)
    return [
        {
            "chat_id": c.chat_id,
            "title": c.title,
            "skill": c.skill,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in chats
    ]


@router.get("/by-chat")
async def get_trace_by_chat(request: Request, chat_id: str = Query(...)):
    """Find the active trace for a chat."""
    user_id = _get_user_id(request)
    from storage.repository.chat import get_chat
    chat = await get_chat(user_id, chat_id)
    if not chat or not chat.active_trace_id:
        raise HTTPException(status_code=404, detail="trace not found for chat_id")
    return {"trace_id": chat.active_trace_id, "skill": chat.skill}


@router.get("")
async def get_trace(request: Request, trace_id: str = Query(...)):
    """Get trace details: list of participating chats."""
    user_id = _get_user_id(request)
    chats = find_chats_by_trace_id(user_id, trace_id)
    if not chats:
        raise HTTPException(status_code=404, detail="trace not found")
    return {
        "trace_id": trace_id,
        "participants": [
            {
                "chat_id": c.chat_id,
                "skill": c.skill,
                "title": c.title,
            }
            for c in chats
        ],
    }
