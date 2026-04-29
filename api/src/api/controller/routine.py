from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import routine as routine_service

router = APIRouter(prefix="/routine")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateRoutineRequest(BaseModel):
    name: str
    schedule: str
    message: str
    description: Optional[str] = None
    target_topic: Optional[str] = None
    target_skill: Optional[str] = None
    work_dir: Optional[str] = None
    backend: Optional[str] = None
    enabled: bool = True


class UpdateRoutineRequest(BaseModel):
    routine_id: str
    name: Optional[str] = None
    schedule: Optional[str] = None
    message: Optional[str] = None
    description: Optional[str] = None
    target_topic: Optional[str] = None
    target_skill: Optional[str] = None
    work_dir: Optional[str] = None
    backend: Optional[str] = None


class RoutineIdRequest(BaseModel):
    routine_id: str


@router.get("/list")
async def list_routines(
    request: Request,
    enabled: Optional[bool] = Query(None),
    limit: int = Query(50),
):
    user_id = _get_user_id(request)
    routines = routine_service.list_routines(user_id, enabled=enabled, limit=limit)
    return [r.to_dict() for r in routines]


@router.get("/detail")
async def get_routine(request: Request, routine_id: str = Query(...)):
    user_id = _get_user_id(request)
    routine = routine_service.get_routine(user_id, routine_id)
    if not routine:
        raise HTTPException(status_code=404, detail="Routine not found")
    return routine.to_dict()


@router.post("")
async def create_routine(req: CreateRoutineRequest, request: Request):
    user_id = _get_user_id(request)
    try:
        routine = routine_service.add_routine(
            user_id,
            req.name,
            req.schedule,
            req.message,
            description=req.description,
            target_topic=req.target_topic,
            target_skill=req.target_skill,
            work_dir=req.work_dir,
            backend=req.backend,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return routine.to_dict()


@router.post("/update")
async def update_routine(req: UpdateRoutineRequest, request: Request):
    user_id = _get_user_id(request)
    fields = {k: v for k, v in req.model_dump(exclude={"routine_id"}).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        routine = routine_service.update_routine(user_id, req.routine_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not routine:
        raise HTTPException(status_code=404, detail="Routine not found")
    return routine.to_dict()


@router.post("/enable")
async def enable_routine(req: RoutineIdRequest, request: Request):
    user_id = _get_user_id(request)
    routine = routine_service.enable_routine(user_id, req.routine_id)
    if not routine:
        raise HTTPException(status_code=404, detail="Routine not found")
    return routine.to_dict()


@router.post("/disable")
async def disable_routine(req: RoutineIdRequest, request: Request):
    user_id = _get_user_id(request)
    routine = routine_service.disable_routine(user_id, req.routine_id)
    if not routine:
        raise HTTPException(status_code=404, detail="Routine not found")
    return routine.to_dict()


@router.post("/delete")
async def delete_routine(req: RoutineIdRequest, request: Request):
    user_id = _get_user_id(request)
    ok = routine_service.delete_routine(user_id, req.routine_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Routine not found")
    return {"ok": True}


@router.post("/run")
async def run_routine(req: RoutineIdRequest, request: Request):
    user_id = _get_user_id(request)
    try:
        chat_id = routine_service.fire_routine(user_id, req.routine_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fire_routine failed: {e}")
    return {"ok": True, "chat_id": chat_id}
