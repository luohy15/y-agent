import threading
from typing import Callable, List, Optional, Tuple

from loguru import logger


class PollLoop:
    """Unified 2-second polling loop for interrupt checking and steer message forwarding.

    Runs a single daemon thread that every 2 seconds:
    1. Checks for interrupt → calls on_interrupt() and stops
    2. Checks for steer messages → calls on_steer(text, msg_id) for each

    Usage:
        loop = PollLoop(
            check_interrupted_fn=lambda: check_interrupted(chat_id),
            on_interrupt=lambda: kill_and_close(),
            check_steer_fn=lambda: get_new_messages(),
            on_steer=lambda text, msg_id: write_to_stdin(text, msg_id),
        )
        loop.start()
        # ... do work ...
        loop.stop()  # signals thread to exit and waits
    """

    def __init__(
        self,
        check_interrupted_fn: Optional[Callable[[], bool]] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
        check_steer_fn: Optional[Callable[[], List[Tuple[str, str]]]] = None,
        on_steer: Optional[Callable[[str, str], None]] = None,
    ):
        self._check_interrupted_fn = check_interrupted_fn
        self._on_interrupt = on_interrupt
        self._check_steer_fn = check_steer_fn
        self._on_steer = on_steer
        self._done = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the polling thread. No-op if nothing to poll."""
        if not self._check_interrupted_fn and not self._check_steer_fn:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        """Signal the loop to stop and wait for thread exit."""
        self._done.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    @property
    def done_event(self) -> threading.Event:
        """Expose done_event so _read_lines can set it on completion."""
        return self._done

    def _loop(self) -> None:
        while not self._done.is_set():
            # Check interrupt first — takes priority
            if self._check_interrupted_fn:
                try:
                    if self._check_interrupted_fn():
                        if self._on_interrupt:
                            self._on_interrupt()
                        break
                except Exception as e:
                    logger.warning("poll_loop interrupt check failed: {}", e)

            # Check steer
            if self._check_steer_fn and self._on_steer:
                try:
                    msgs = self._check_steer_fn()
                    for text, msg_id in msgs:
                        self._on_steer(text, msg_id)
                except Exception as e:
                    logger.warning("poll_loop steer failed: {}", e)
                    break

            self._done.wait(1)
