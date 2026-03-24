from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import todo as todo_service

router = APIRouter(prefix="/todo")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateTodoRequest(BaseModel):
    name: str
    desc: Optional[str] = None
    tags: Optional[List[str]] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None


class UpdateTodoRequest(BaseModel):
    todo_id: str
    name: Optional[str] = None
    desc: Optional[str] = None
    tags: Optional[List[str]] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    progress: Optional[str] = None


class TodoIdRequest(BaseModel):
    todo_id: str


@router.get("/list")
async def list_todos(
    request: Request,
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    limit: int = Query(50),
):
    user_id = _get_user_id(request)
    todos = todo_service.list_todos(user_id, status=status, priority=priority, limit=limit)
    return [t.to_dict() for t in todos]


@router.get("/detail")
async def get_todo(request: Request, todo_id: str = Query(...)):
    user_id = _get_user_id(request)
    todo = todo_service.get_todo(user_id, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()


@router.post("")
async def create_todo(req: CreateTodoRequest, request: Request):
    user_id = _get_user_id(request)
    todo = todo_service.create_todo(
        user_id, req.name, desc=req.desc, tags=req.tags,
        due_date=req.due_date, priority=req.priority,
    )
    return todo.to_dict()


@router.post("/update")
async def update_todo(req: UpdateTodoRequest, request: Request):
    user_id = _get_user_id(request)
    fields = {k: v for k, v in req.model_dump(exclude={"todo_id"}).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    todo = todo_service.update_todo(user_id, req.todo_id, **fields)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()


@router.post("/finish")
async def finish_todo(req: TodoIdRequest, request: Request):
    user_id = _get_user_id(request)
    todo = todo_service.finish_todo(user_id, req.todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()


@router.post("/delete")
async def delete_todo(req: TodoIdRequest, request: Request):
    user_id = _get_user_id(request)
    todo = todo_service.delete_todo(user_id, req.todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()


@router.post("/activate")
async def activate_todo(req: TodoIdRequest, request: Request):
    user_id = _get_user_id(request)
    todo = todo_service.activate_todo(user_id, req.todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()


@router.post("/deactivate")
async def deactivate_todo(req: TodoIdRequest, request: Request):
    user_id = _get_user_id(request)
    todo = todo_service.deactivate_todo(user_id, req.todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo.to_dict()
