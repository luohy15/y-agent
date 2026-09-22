"""Per-run delivery state for native inputs written into a Claude Code session.

The installed CLI 2.1.259 (`--input-format stream-json --output-format stream-json`)
reports the fate of every stdin user message it reads
as a `command_lifecycle` event whose `command_uuid` echoes the *client-supplied*
`uuid` on that message:

    queued -> started -> exactly one of completed / cancelled / discarded / refused

`queued` is the first point at which the CLI has actually read the input, and
the terminal state is the first point at which the turn that consumed it has
ended. A message written without a `uuid` emits no lifecycle events at all,
which is why every write this package makes carries one.

That distinction is the whole point of this ledger: an SSH append to the stdin
file returning exit 0 only proves the bytes reached the file, and a `result`
event only proves *some* turn ended. Neither is evidence that a particular
input was consumed, so neither may retire it.
"""

import uuid as _uuid
from typing import Dict, Iterable, List, Optional


#: Written to the stdin file; the CLI has not reported reading it.
SUBMITTED = "submitted"
#: The CLI reported `queued` / `started` for it.
ACKNOWLEDGED = "acknowledged"
#: The turn that consumed it ended cleanly.
COMPLETED = "completed"
#: A terminal state that did not answer it (cancelled / discarded / refused).
DROPPED = "dropped"

_OPEN_STATES = (SUBMITTED, ACKNOWLEDGED)
_ACK_STATES = ("queued", "started")
_TERMINAL_STATES = {
    "completed": COMPLETED,
    "cancelled": DROPPED,
    "discarded": DROPPED,
    "refused": DROPPED,
}


def native_input_uuid(chat_id: str, key: str) -> str:
    """Stable native `uuid` for one stdin write.

    Derived rather than random so the same input keeps one identity across a
    Lambda handoff, and a UUID rather than the raw message id so the value is
    well-formed for the CLI's own uuid field.
    """
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"y-agent/chat/{chat_id}/input/{key}"))


class InputLedger:
    """Delivery state for the inputs one detached run has written.

    Keyed by y-agent message id; `groups` maps the native uuid of each write to
    the message ids folded into it (the launch prompt concatenates every pending
    message into a single stdin write, steers are one id each).
    """

    def __init__(self, chat_id: str, states: Optional[Dict[str, str]] = None,
                 groups: Optional[Dict[str, List[str]]] = None,
                 lifecycle_observed: bool = False):
        self.chat_id = chat_id
        self._states: Dict[str, str] = dict(states or {})
        self._groups: Dict[str, List[str]] = {k: list(v) for k, v in (groups or {}).items()}
        self._lifecycle_observed = bool(lifecycle_observed)

    # -- writes ------------------------------------------------------------

    def mark_submitted(self, native_uuid: str, message_ids: Iterable[str]) -> None:
        ids = [mid for mid in message_ids if mid]
        if not ids:
            return
        self._groups[native_uuid] = ids
        for message_id in ids:
            self._states.setdefault(message_id, SUBMITTED)

    def observe_lifecycle(self, event: dict) -> None:
        """Fold one `command_lifecycle` event into the ledger."""
        state = event.get("state")
        command_uuid = event.get("command_uuid")
        if not state or not command_uuid:
            return
        self._lifecycle_observed = True
        message_ids = self._groups.get(command_uuid)
        if not message_ids:
            # A uuid this run never wrote (an internally enqueued command, or a
            # peer's). Nothing of ours to retire.
            return
        if state in _ACK_STATES:
            for message_id in message_ids:
                if self._states.get(message_id) == SUBMITTED:
                    self._states[message_id] = ACKNOWLEDGED
            return
        resolved = _TERMINAL_STATES.get(state)
        if resolved:
            for message_id in message_ids:
                self._states[message_id] = resolved

    # -- reads -------------------------------------------------------------

    @property
    def lifecycle_observed(self) -> bool:
        """True once this run has seen any lifecycle event.

        Absence is not evidence of consumption. Callers must not fall back to
        treating a successful stdin write as a completed input.
        """
        return self._lifecycle_observed

    def outstanding(self) -> bool:
        """True while some written input still owes a native response."""
        return any(state in _OPEN_STATES for state in self._states.values())

    def handled_ids(self) -> set:
        """Ids that need no continuation turn.

        Only an explicit native completion retires an input. A successful file
        write, even when no lifecycle event has arrived, is not consumption.
        """
        return {mid for mid, state in self._states.items() if state == COMPLETED}

    def written_ids(self) -> set:
        """Every id this run has already written; never write one twice."""
        return set(self._states)

    def state_of(self, message_id: str) -> Optional[str]:
        return self._states.get(message_id)

    # -- persistence -------------------------------------------------------

    @property
    def states(self) -> Dict[str, str]:
        return dict(self._states)

    @property
    def groups(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in self._groups.items()}
