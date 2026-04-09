from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import dev_worktree as wt_service

router = APIRouter(prefix="/dev-worktree")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateDevWorktreeRequest(BaseModel):
    name: str
    project_path: str
    worktree_path: str
    branch: str
    todo_id: Optional[str] = None


class UpdateDevWorktreeRequest(BaseModel):
    worktree_id: str
    name: Optional[str] = None
    project_path: Optional[str] = None
    worktree_path: Optional[str] = None
    branch: Optional[str] = None
    status: Optional[str] = None
    todo_id: Optional[str] = None
    server_state: Optional[dict] = None


class WorktreeIdRequest(BaseModel):
    worktree_id: str


@router.get("/list")
async def list_worktrees(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(50),
):
    user_id = _get_user_id(request)
    worktrees = wt_service.list_worktrees(user_id, status=status, limit=limit)
    return [w.to_dict() for w in worktrees]


@router.get("/detail")
async def get_worktree(request: Request, worktree_id: str = Query(...)):
    user_id = _get_user_id(request)
    wt = wt_service.get_worktree(user_id, worktree_id)
    if not wt:
        raise HTTPException(status_code=404, detail="Worktree not found")
    return wt.to_dict()


@router.get("/by-name")
async def get_worktree_by_name(request: Request, name: str = Query(...)):
    user_id = _get_user_id(request)
    wt = wt_service.get_worktree_by_name(user_id, name)
    if not wt:
        raise HTTPException(status_code=404, detail="Worktree not found")
    return wt.to_dict()


@router.post("")
async def create_worktree(req: CreateDevWorktreeRequest, request: Request):
    user_id = _get_user_id(request)
    wt = wt_service.create_worktree(
        user_id, req.name,
        project_path=req.project_path,
        worktree_path=req.worktree_path,
        branch=req.branch,
        todo_id=req.todo_id,
    )
    return wt.to_dict()


@router.post("/update")
async def update_worktree(req: UpdateDevWorktreeRequest, request: Request):
    user_id = _get_user_id(request)
    fields = {k: v for k, v in req.model_dump(exclude={"worktree_id"}).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    wt = wt_service.update_worktree(user_id, req.worktree_id, **fields)
    if not wt:
        raise HTTPException(status_code=404, detail="Worktree not found")
    return wt.to_dict()


@router.post("/remove")
async def remove_worktree(req: WorktreeIdRequest, request: Request):
    user_id = _get_user_id(request)
    wt = wt_service.remove_worktree(user_id, req.worktree_id)
    if not wt:
        raise HTTPException(status_code=404, detail="Worktree not found")
    return wt.to_dict()
