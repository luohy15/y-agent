"""Routine pre-fire guard resolution (todo 2871)."""

import unittest

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


if __name__ == "__main__":
    unittest.main()
