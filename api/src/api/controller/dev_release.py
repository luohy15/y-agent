"""Publication-ownership routes (todo 3493).

One project has at most one active claim. These routes are the only
database-enforced part of the feature: they serialize claim acquisition and
every later transition. They do not fence git, deploy scripts, CI, module
publication or any already-running job, and `/check` is an observation rather
than a lease.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import dev_release as release_service
from storage.service.dev_release import (
    DevReleaseDenied, DevReleaseError, DevReleaseInvalid,
)

router = APIRouter(prefix="/dev-release")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


def _actor(request: Request) -> str:
    return release_service.actor_user_id(_get_user_id(request))


def _http_error(exc: DevReleaseError) -> HTTPException:
    if isinstance(exc, DevReleaseDenied):
        # No evidence or history in a denial: the caller is not the owner.
        return HTTPException(status_code=403, detail={"error": "denied", "reason": exc.reason})
    if isinstance(exc, DevReleaseInvalid):
        return HTTPException(status_code=422, detail={"error": "invalid", "reason": exc.reason})
    current = exc.current.to_dict() if exc.current is not None else None
    return HTTPException(
        status_code=409,
        detail={"error": "conflict", "reason": exc.reason, "current": current},
    )


async def _transition(request: Request, call, *, after=None):
    """Run one ownership transition and project it for the calling account.

    The actor is resolved once and handed to the service, which would otherwise
    look the same account up again for its audit record. `after` runs only once
    the transition has committed -- never while the slot lock is held.
    """
    try:
        actor = _actor(request)
        slot, applied = call(actor)
    except DevReleaseError as exc:
        raise _http_error(exc) from exc
    if after is not None:
        await after(slot)
    return {"status": "applied" if applied else "unchanged",
            "slot": slot.to_dict(actor_user_id=actor)}


class ClaimRequest(BaseModel):
    project: str
    trace_id: str
    chat_id: str
    expected_generation: int
    request_id: str
    target: Optional[str] = None


class ReleaseRequest(BaseModel):
    project: str
    trace_id: str
    chat_id: str
    expected_generation: int
    claim_id: str
    request_id: str
    outcome_reference: str
    quiescence_evidence: str


class HandoffRequest(BaseModel):
    project: str
    trace_id: str
    chat_id: str
    expected_generation: int
    claim_id: str
    request_id: str
    new_owner_chat_id: str


class PublisherRequest(BaseModel):
    project: str
    trace_id: str
    chat_id: str
    expected_generation: int
    claim_id: str
    request_id: str
    publisher_chat_id: Optional[str] = None
    quiescence_evidence: Optional[str] = None


class TakeoverRequest(BaseModel):
    project: str
    new_owner_trace_id: str
    new_owner_chat_id: str
    expected_generation: int
    claim_id: str
    request_id: str
    authorization_reference: str
    quiescence_evidence: str


class EnqueueRequest(BaseModel):
    project: str
    trace_id: str
    chat_id: str
    waiter_id: str
    request_id: str
    authorization_reference: str
    baseline_sha: str
    candidate_sha: str
    todo_ids: list
    target: Optional[str] = None


class CancelWaiterRequest(BaseModel):
    project: str
    trace_id: str
    chat_id: str
    waiter_id: str
    request_id: str


class CheckRequest(BaseModel):
    project: str
    trace_id: str
    chat_id: str
    expected_generation: int
    claim_id: str
    role: str


@router.get("/detail")
async def get_detail(request: Request, project: str = Query(...)):
    try:
        actor = _actor(request)
        slot = release_service.get_slot(project)
        return slot.to_dict(actor_user_id=actor)
    except DevReleaseError as exc:
        raise _http_error(exc) from exc


@router.get("/list")
async def list_active(request: Request, limit: int = Query(50)):
    _get_user_id(request)
    slots = release_service.list_active(limit)
    # Ownership projection only: conflict discovery does not expose other
    # accounts' operation evidence.
    return [slot.to_dict() for slot in slots]


@router.post("/claim")
async def claim(req: ClaimRequest, request: Request):
    user_id = _get_user_id(request)
    return await _transition(request, lambda actor: release_service.claim(
        user_id, project=req.project, trace_id=req.trace_id, chat_id=req.chat_id,
        expected_generation=req.expected_generation, request_id=req.request_id,
        target=req.target, actor=actor,
    ))


@router.post("/release")
async def release(req: ReleaseRequest, request: Request):
    user_id = _get_user_id(request)
    # A release that hands the slot to the waiting head also owes that waiter a
    # wakeup; it is attempted after the commit, and the durable receipt makes a
    # failure here recoverable rather than lost.
    return await _transition(request, lambda actor: release_service.release(
        user_id, project=req.project, trace_id=req.trace_id, chat_id=req.chat_id,
        expected_generation=req.expected_generation, claim_id=req.claim_id,
        request_id=req.request_id, outcome_reference=req.outcome_reference,
        quiescence_evidence=req.quiescence_evidence, actor=actor,
    ), after=release_service.deliver_granted_waiter)


@router.post("/handoff")
async def handoff(req: HandoffRequest, request: Request):
    user_id = _get_user_id(request)
    return await _transition(request, lambda actor: release_service.handoff(
        user_id, project=req.project, trace_id=req.trace_id, chat_id=req.chat_id,
        expected_generation=req.expected_generation, claim_id=req.claim_id,
        request_id=req.request_id, new_owner_chat_id=req.new_owner_chat_id, actor=actor,
    ))


@router.post("/publisher")
async def publisher(req: PublisherRequest, request: Request):
    user_id = _get_user_id(request)
    return await _transition(request, lambda actor: release_service.set_publisher(
        user_id, project=req.project, trace_id=req.trace_id, chat_id=req.chat_id,
        expected_generation=req.expected_generation, claim_id=req.claim_id,
        request_id=req.request_id, publisher_chat_id=req.publisher_chat_id,
        quiescence_evidence=req.quiescence_evidence, actor=actor,
    ))


@router.post("/takeover")
async def takeover(req: TakeoverRequest, request: Request):
    user_id = _get_user_id(request)
    return await _transition(request, lambda actor: release_service.takeover(
        user_id, project=req.project, new_owner_trace_id=req.new_owner_trace_id,
        new_owner_chat_id=req.new_owner_chat_id,
        expected_generation=req.expected_generation, claim_id=req.claim_id,
        request_id=req.request_id, authorization_reference=req.authorization_reference,
        quiescence_evidence=req.quiescence_evidence, actor=actor,
    ))


@router.post("/check")
async def check(req: CheckRequest, request: Request):
    user_id = _get_user_id(request)
    try:
        actor = _actor(request)
        result = release_service.check(
            user_id, project=req.project, trace_id=req.trace_id, chat_id=req.chat_id,
            claim_id=req.claim_id, expected_generation=req.expected_generation,
            role=req.role, actor=actor,
        )
        return {
            "eligible": result["eligible"],
            "reason": result["reason"],
            "role": result["role"],
            "slot": result["slot"].to_dict(actor_user_id=actor),
        }
    except DevReleaseError as exc:
        raise _http_error(exc) from exc


@router.post("/enqueue")
async def enqueue(req: EnqueueRequest, request: Request):
    """Atomic acquire-or-enqueue for an already-authorized coordinator.

    `granted` means this call owns the slot now; `queued` means the caller
    should end its turn and wait to be woken. Contention is never a question
    for the user and never a takeover.
    """
    user_id = _get_user_id(request)
    try:
        actor = _actor(request)
        slot, waiter, outcome = release_service.enqueue(
            user_id, project=req.project, trace_id=req.trace_id, chat_id=req.chat_id,
            waiter_id=req.waiter_id, request_id=req.request_id,
            authorization_reference=req.authorization_reference,
            baseline_sha=req.baseline_sha, candidate_sha=req.candidate_sha,
            todo_ids=req.todo_ids, target=req.target, actor=actor,
        )
    except DevReleaseError as exc:
        raise _http_error(exc) from exc
    # Granting here is an ownership transition like any other, so the waiter it
    # granted is owed the same durable wakeup.
    await release_service.deliver_granted_waiter(slot)
    return {"status": outcome, "slot": slot.to_dict(actor_user_id=actor),
            "waiter": waiter.to_dict()}


@router.post("/cancel-waiter")
async def cancel_waiter(req: CancelWaiterRequest, request: Request):
    """Withdraw a pending registration. An already-granted claim is never released."""
    user_id = _get_user_id(request)
    try:
        actor = _actor(request)
        slot, waiter, outcome = release_service.cancel_waiter(
            user_id, project=req.project, trace_id=req.trace_id, chat_id=req.chat_id,
            waiter_id=req.waiter_id, request_id=req.request_id,
        )
    except DevReleaseError as exc:
        raise _http_error(exc) from exc
    return {"status": outcome, "slot": slot.to_dict(actor_user_id=actor),
            "waiter": waiter.to_dict()}


@router.get("/waiters")
async def list_waiters(request: Request, project: Optional[str] = Query(None),
                       limit: int = Query(50)):
    """This account's own waiter receipts, including the frozen candidate."""
    user_id = _get_user_id(request)
    try:
        waiters = release_service.list_waiters(user_id, project=project, limit=limit)
    except DevReleaseError as exc:
        raise _http_error(exc) from exc
    return [waiter.to_dict() for waiter in waiters]
