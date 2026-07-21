from fastapi import APIRouter, Query, Request

from storage.service import tag as tag_service

router = APIRouter(prefix="/tag")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


@router.get("")
async def get_by_tag(request: Request, tag: str = Query(...), prefix: bool = Query(False)):
    user_id = _get_user_id(request)
    return tag_service.get_by_tag(user_id, tag, prefix=prefix)


@router.get("/list")
async def list_tags(request: Request):
    user_id = _get_user_id(request)
    vocabulary = tag_service.list_vocabulary(user_id)
    return [{"tag": t, "count": c} for t, c in vocabulary]
