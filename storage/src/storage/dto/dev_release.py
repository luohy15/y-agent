from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DevReleaseTransition:
    """One audited state-changing transition of a publication slot.

    ``params`` holds the exact validated request parameters (bounded strings
    only, no arbitrary payload), which is what an idempotent retry is compared
    against. ``generation`` is the generation the slot reached *after* this
    transition.
    """

    timestamp: str
    unix_timestamp: int
    operation: str
    request_id: str
    actor_user_id: str
    generation: int
    params: Dict = field(default_factory=dict)
    # The optimistic preconditions the caller supplied, so an "exact retry"
    # means the same request against the same expected state, not merely the
    # same parameters (review nit, round 1).
    preconditions: Optional[Dict] = None
    previous: Optional[Dict] = None
    # Present on a compound release-and-grant: the waiter that took ownership
    # in this same transition.
    grant: Optional[Dict] = None
    # Waiters this transition resolved as unusable and skipped.
    rejected: Optional[List[Dict]] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'DevReleaseTransition':
        return cls(
            timestamp=data['timestamp'],
            unix_timestamp=int(data['unix_timestamp']),
            operation=data['operation'],
            request_id=data['request_id'],
            actor_user_id=data['actor_user_id'],
            generation=int(data['generation']),
            params=data.get('params') or {},
            preconditions=data.get('preconditions'),
            previous=data.get('previous'),
            grant=data.get('grant'),
            rejected=data.get('rejected'),
        )

    def to_dict(self) -> Dict:
        result = {
            'timestamp': self.timestamp,
            'unix_timestamp': self.unix_timestamp,
            'operation': self.operation,
            'request_id': self.request_id,
            'actor_user_id': self.actor_user_id,
            'generation': self.generation,
            'params': self.params,
        }
        if self.preconditions is not None:
            result['preconditions'] = self.preconditions
        if self.previous is not None:
            result['previous'] = self.previous
        if self.grant is not None:
            result['grant'] = self.grant
        if self.rejected:
            result['rejected'] = self.rejected
        return result


@dataclass
class DevRelease:
    """Public projection of a project's publication slot.

    An absent row is represented as an inactive slot at generation 0, so a
    caller acquiring a never-claimed project uses the same optimistic
    precondition as any other transition.
    """

    project_key: str
    generation: int = 0
    active: bool = False
    claim_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    owner_trace_id: Optional[str] = None
    owner_chat_id: Optional[str] = None
    publisher_chat_id: Optional[str] = None
    target: Optional[str] = None
    # Pending waiter ids in FIFO order. Never projected: another account may
    # learn that a queue exists and how long it is, never who is in it.
    waiters: List[str] = field(default_factory=list)
    history: List[DevReleaseTransition] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    def to_dict(self, *, actor_user_id: Optional[str] = None) -> Dict:
        """Ownership projection every authenticated caller may read.

        Transition history carries operation evidence (authorization and
        quiescence references), so it is filtered to the entries the calling
        account itself wrote; ``actor_user_id=None`` omits history entirely.
        """
        result = {
            'project_key': self.project_key,
            'generation': self.generation,
            'active': self.active,
            'claim_id': self.claim_id,
            'owner_user_id': self.owner_user_id,
            'owner_trace_id': self.owner_trace_id,
            'owner_chat_id': self.owner_chat_id,
            'publisher_chat_id': self.publisher_chat_id,
            'target': self.target,
            'queue_length': len(self.waiters),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'created_at_unix': self.created_at_unix,
            'updated_at_unix': self.updated_at_unix,
        }
        if actor_user_id is not None:
            result['history'] = [
                h.to_dict() for h in self.history if h.actor_user_id == actor_user_id
            ]
        return result


@dataclass
class DevReleaseWaiter:
    """One waiter's durable receipt: registration, queue state and wakeup."""

    project_key: str
    waiter_id: str
    request_id: str
    user_id: str
    trace_id: str
    chat_id: str
    status: str
    authorization_reference: str
    baseline_sha: str
    candidate_sha: str
    todo_ids: List[str] = field(default_factory=list)
    target: Optional[str] = None
    position: Optional[int] = None
    rejected_reason: Optional[str] = None
    granted_claim_id: Optional[str] = None
    granted_generation: Optional[int] = None
    event_id: Optional[str] = None
    delivery_state: Optional[str] = None
    enqueue_needed: Optional[bool] = None
    delivery_attempts: int = 0
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    def to_dict(self) -> Dict:
        """Owner-only projection: the caller is always the registering account,
        so the candidate attestation is included and no integer id ever is."""
        return {
            'project_key': self.project_key,
            'waiter_id': self.waiter_id,
            'request_id': self.request_id,
            'user_id': self.user_id,
            'trace_id': self.trace_id,
            'chat_id': self.chat_id,
            'status': self.status,
            'position': self.position,
            'target': self.target,
            'authorization_reference': self.authorization_reference,
            'baseline_sha': self.baseline_sha,
            'candidate_sha': self.candidate_sha,
            'todo_ids': list(self.todo_ids or []),
            'rejected_reason': self.rejected_reason,
            'granted_claim_id': self.granted_claim_id,
            'granted_generation': self.granted_generation,
            'event_id': self.event_id,
            'delivery_state': self.delivery_state,
            'enqueue_needed': self.enqueue_needed,
            'delivery_attempts': self.delivery_attempts,
            'last_error': self.last_error,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'created_at_unix': self.created_at_unix,
            'updated_at_unix': self.updated_at_unix,
        }
