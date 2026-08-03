"""Routine pre-fire guard resolution (todo 2871) and the vm_command action (todo 3020, phase 6)."""

import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from storage.dto.routine import Routine
from storage.service import routine as routine_svc


_calls = []


def guard_true(user_id):
    _calls.append(user_id)
    return True


def guard_false(user_id):
    _calls.append(user_id)
    return False


def guard_truthy_non_bool(user_id):
    return [1]


def guard_falsy_non_bool(user_id):
    return []


def guard_raises(user_id):
    raise RuntimeError("guard exploded")


# Whatever name this module actually registered under in sys.modules, so the
# dotted-path lookup resolves the same way regardless of how pytest roots it.
_THIS = __name__


class EvaluateGuardTest(unittest.TestCase):
    def setUp(self):
        _calls.clear()

    def test_guard_returning_true_fires(self):
        self.assertTrue(routine_svc.evaluate_guard(7, f"{_THIS}:guard_true"))
        self.assertEqual(_calls, [7])

    def test_guard_returning_false_blocks(self):
        self.assertFalse(routine_svc.evaluate_guard(7, f"{_THIS}:guard_false"))
        self.assertEqual(_calls, [7])

    def test_non_bool_return_is_coerced(self):
        self.assertTrue(routine_svc.evaluate_guard(1, f"{_THIS}:guard_truthy_non_bool"))
        self.assertFalse(routine_svc.evaluate_guard(1, f"{_THIS}:guard_falsy_non_bool"))

    def test_missing_function_separator_is_rejected(self):
        with self.assertRaises(ValueError):
            routine_svc.evaluate_guard(1, "storage.service.routine")

    def test_unknown_module_raises(self):
        with self.assertRaises(ModuleNotFoundError):
            routine_svc.evaluate_guard(1, "storage.service.no_such_module:f")

    def test_unknown_function_raises(self):
        with self.assertRaises(AttributeError):
            routine_svc.evaluate_guard(1, f"{_THIS}:no_such_function")

    def test_guard_exception_propagates_to_caller(self):
        # The admin tick catches this and fails open; the service must not swallow it.
        with self.assertRaises(RuntimeError):
            routine_svc.evaluate_guard(1, f"{_THIS}:guard_raises")


def _fake_module_host(run_vm_command_mock):
    """Build a fake `agent`/`agent.module_host` pair for sys.modules injection.

    storage's own dependency closure does not include the `agent` package
    (agent depends on storage, not the reverse — D9), so these tests inject
    a fake module rather than require `agent` to be installed. They exercise
    fire_routine's vm_command wiring (argv/vm_name/timeout passed through,
    status stamped, no chat created); run_vm_command's own behavior is covered
    by agent/tests/test_module_host.py.
    """
    agent_pkg = types.ModuleType("agent")
    module_host = types.ModuleType("agent.module_host")

    @contextmanager
    def request_owner(user_id):
        yield

    module_host.request_owner = request_owner
    module_host.run_vm_command = run_vm_command_mock
    agent_pkg.module_host = module_host
    return agent_pkg, module_host


def _vm_command_routine(**overrides):
    fields = dict(
        routine_id="r1",
        name="test-vm-routine",
        schedule="* * * * *",
        action="vm_command",
        command=["y", "todo", "list"],
        vm_name=None,
    )
    fields.update(overrides)
    return Routine(**fields)


class FireRoutineVmCommandTest(unittest.TestCase):
    def _patched(self, run_vm_command_mock, routine, saved):
        agent_pkg, module_host = _fake_module_host(run_vm_command_mock)

        def fake_save(user_id, r):
            saved["routine"] = r
            return r

        return (
            patch.dict(sys.modules, {"agent": agent_pkg, "agent.module_host": module_host}),
            patch("storage.repository.routine.get_routine", return_value=routine),
            patch("storage.repository.routine.save_routine", side_effect=fake_save),
        )

    def test_success_stamps_ok_passes_argv_and_creates_no_chat(self):
        routine = _vm_command_routine(vm_name="prod")
        run_vm_command_mock = AsyncMock(return_value="did the thing")
        saved = {}

        p1, p2, p3 = self._patched(run_vm_command_mock, routine, saved)
        with p1, p2, p3:
            chat_id = routine_svc.fire_routine(7, "r1")

        self.assertEqual(chat_id, "")
        run_vm_command_mock.assert_awaited_once_with(
            7, "prod", ["y", "todo", "list"], timeout=routine_svc.VM_COMMAND_TIMEOUT
        )
        self.assertEqual(saved["routine"].last_run_status, "ok")
        self.assertIsNone(saved["routine"].last_chat_id)

    def test_failure_stamps_truncated_error_without_raising(self):
        routine = _vm_command_routine()
        run_vm_command_mock = AsyncMock(side_effect=RuntimeError("boom first line\nboom second line"))
        saved = {}

        p1, p2, p3 = self._patched(run_vm_command_mock, routine, saved)
        with p1, p2, p3:
            chat_id = routine_svc.fire_routine(7, "r1")  # must not raise past the caller

        self.assertEqual(chat_id, "")
        self.assertEqual(saved["routine"].last_run_status, "error: boom first line")
        self.assertIsNone(saved["routine"].last_chat_id)

    def test_runs_correctly_when_called_from_an_already_running_event_loop(self):
        # Regression: fire_routine is also called synchronously from the
        # FastAPI `/routine/run` endpoint, an `async def` handler with an
        # event loop already running on this thread. asyncio.run() would
        # raise there; _run_coro_sync must fall back to a worker thread.
        import asyncio

        routine = _vm_command_routine()
        run_vm_command_mock = AsyncMock(return_value="ok")
        saved = {}
        p1, p2, p3 = self._patched(run_vm_command_mock, routine, saved)

        async def _call_from_running_loop():
            with p1, p2, p3:
                return routine_svc.fire_routine(7, "r1")

        chat_id = asyncio.run(_call_from_running_loop())
        self.assertEqual(chat_id, "")
        run_vm_command_mock.assert_awaited_once()
        self.assertEqual(saved["routine"].last_run_status, "ok")


class RoutinePayloadValidationTest(unittest.TestCase):
    def test_chat_action_requires_message(self):
        with self.assertRaises(ValueError):
            routine_svc._validate_routine_payload("chat", None, None)
        with self.assertRaises(ValueError):
            routine_svc._validate_routine_payload("chat", "", None)
        routine_svc._validate_routine_payload("chat", "hello", None)  # does not raise

    def test_vm_command_action_requires_argv_list(self):
        with self.assertRaises(ValueError):
            routine_svc._validate_routine_payload("vm_command", None, None)
        with self.assertRaises(ValueError):
            routine_svc._validate_routine_payload("vm_command", None, [])
        with self.assertRaises(ValueError):
            routine_svc._validate_routine_payload("vm_command", None, "y finance sync")  # a shell string, not argv
        with self.assertRaises(ValueError):
            routine_svc._validate_routine_payload("vm_command", None, ["y", 1])
        routine_svc._validate_routine_payload("vm_command", None, ["y", "finance", "sync"])  # does not raise

    def test_unknown_action_is_rejected(self):
        with self.assertRaises(ValueError):
            routine_svc._validate_routine_payload("delete_prod", None, None)


if __name__ == "__main__":
    unittest.main()
