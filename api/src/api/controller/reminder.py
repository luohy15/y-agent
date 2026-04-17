from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import reminder as reminder_service

router = APIRouter(prefix="/reminder")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class CreateReminderRequest(BaseModel):
    title: str
    remind_at: str
    description: Optional[str] = None
    todo_id: Optional[str] = None
    calendar_event_id: Optional[str] = None


class UpdateReminderRequest(BaseModel):
    reminder_id: str
    title: Optional[str] = None
    remind_at: Optional[str] = None
    description: Optional[str] = None
    todo_id: Optional[str] = None
    calendar_event_id: Optional[str] = None


class ReminderIdRequest(BaseModel):
    reminder_id: str


@router.get("/list")
async def list_reminders(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(50),
):
    user_id = _get_user_id(request)
    reminders = reminder_service.list_reminders(user_id, status=status, limit=limit)
    return [r.to_dict() for r in reminders]


@router.get("/detail")
async def get_reminder(request: Request, reminder_id: str = Query(...)):
    user_id = _get_user_id(request)
    reminder = reminder_service.get_reminder(user_id, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder.to_dict()


@router.post("")
async def create_reminder(req: CreateReminderRequest, request: Request):
    user_id = _get_user_id(request)
    try:
        reminder = reminder_service.add_reminder(
            user_id, req.title, req.remind_at,
            description=req.description,
            todo_id=req.todo_id,
            calendar_event_id=req.calendar_event_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return reminder.to_dict()


@router.post("/update")
async def update_reminder(req: UpdateReminderRequest, request: Request):
    user_id = _get_user_id(request)
    fields = {k: v for k, v in req.model_dump(exclude={"reminder_id"}).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        reminder = reminder_service.update_reminder(user_id, req.reminder_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder.to_dict()


@router.post("/delete")
async def cancel_reminder(req: ReminderIdRequest, request: Request):
    user_id = _get_user_id(request)
    reminder = reminder_service.cancel_reminder(user_id, req.reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found or not pending")
    return reminder.to_dict()
