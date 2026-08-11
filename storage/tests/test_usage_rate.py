"""Tests for storage.service.usage_rate: the precomputed-on-the-VM run-rate
read path introduced to replace a per-request SSH read (todo 3121).

Runs against an isolated in-memory SQLite DB so unittest discover works
without a DATABASE_URL, mirroring test_english_correction.py's watermark
pattern (user_preference-backed, no agent/SSH involved).

Covers the plan's four API-facing states (fresh, stale-by-age,
stale-by-last_error, never-written) plus the store-side contract that a
failed read never clobbers the last good envelope, plus the review-3121
finding that a corrupted stored row degrades to a closed `bad_payload`
error rather than raising or passing an arbitrary value through.
"""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.user  # noqa: F401
import storage.entity.user_preference  # noqa: F401
from storage.repository.user import get_or_create_user
from storage.service import usage_rate
from storage.service import user_preference as user_pref_service


def _iso(seconds_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def _envelope(*, rpm=2.5, tpm=123456.0, window_minutes=5, is_historical=False, error=None, observed_at=None):
    return {
        "rpm": rpm if error is None else None,
        "tpm": tpm if error is None else None,
        "window_minutes": window_minutes if error is None else None,
        "is_historical": is_historical if error is None else None,
        "observed_at": observed_at or _iso(),
        "error": error,
    }


class UsageRateTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_engine = dbbase._engine
        self._orig_session_local = dbbase._SessionLocal

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        dbbase.Base.metadata.create_all(bind=engine)
        dbbase._engine = engine
        dbbase._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        self.user_id = get_or_create_user("usage-rate-test").id

    def tearDown(self):
        dbbase._engine = self._orig_engine
        dbbase._SessionLocal = self._orig_session_local


class GetReadingTest(UsageRateTestCase):
    def test_never_written_is_vm_unreachable(self):
        result = usage_rate.get_reading(self.user_id)
        self.assertEqual(result["error"], "vm_unreachable")
        self.assertIsNone(result["rpm"])
        self.assertNotIn("stale", result)

    def test_fresh_reading_returned_as_stored_without_stale_marker(self):
        good = _envelope()
        usage_rate.store_reading(self.user_id, good)

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result, good)
        self.assertNotIn("stale", result)

    def test_stale_by_age_marks_last_good_envelope_stale(self):
        aged = _envelope(observed_at=_iso(usage_rate.STALE_AFTER_SECONDS + 1))
        usage_rate.store_reading(self.user_id, aged)

        result = usage_rate.get_reading(self.user_id)

        self.assertTrue(result["stale"])
        self.assertEqual(result["rpm"], aged["rpm"])
        self.assertIsNone(result["error"])

    def test_stale_by_last_error_keeps_last_good_reading_with_new_error_code(self):
        good = _envelope()
        usage_rate.store_reading(self.user_id, good)
        usage_rate.store_reading(self.user_id, _envelope(error="transport_error", observed_at=_iso()))

        result = usage_rate.get_reading(self.user_id)

        self.assertTrue(result["stale"])
        self.assertEqual(result["error"], "transport_error")
        self.assertEqual(result["rpm"], good["rpm"])
        self.assertEqual(result["tpm"], good["tpm"])

    def test_every_attempt_failed_returns_the_specific_error_code(self):
        usage_rate.store_reading(self.user_id, _envelope(error="not_configured"))

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "not_configured")
        self.assertIsNone(result["rpm"])


class MalformedStoredDataTest(UsageRateTestCase):
    """review-3121: the stored row is an API boundary like any other and must
    degrade to the closed `bad_payload` code rather than raising or passing
    an unvalidated value through to a caller-facing field."""

    def _seed(self, value):
        user_pref_service.upsert_preference(self.user_id, usage_rate.USAGE_RATE_KEY, value)

    def test_malformed_top_level_shape_is_bad_payload(self):
        self._seed({"envelope": None})  # missing last_error / last_attempt_at

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "bad_payload")
        self.assertIsNone(result["rpm"])

    def test_non_dict_stored_value_is_bad_payload(self):
        self._seed("not-a-dict")

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "bad_payload")

    def test_envelope_missing_a_field_is_bad_payload_not_a_raise(self):
        good = _envelope()
        del good["window_minutes"]
        self._seed({"envelope": good, "last_error": None, "last_attempt_at": _iso()})

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "bad_payload")

    def test_malformed_observed_at_is_bad_payload_not_a_raise(self):
        bad = _envelope(observed_at="not-a-timestamp")
        self._seed({"envelope": bad, "last_error": None, "last_attempt_at": _iso()})

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "bad_payload")

    def test_timezone_naive_observed_at_is_bad_payload_not_a_raise(self):
        # round-2 finding: syntactically valid ISO, no offset/Z, raises
        # TypeError subtracting from an aware now() if not guarded.
        naive = _envelope(observed_at="2026-08-11T12:00:00")
        self._seed({"envelope": naive, "last_error": None, "last_attempt_at": _iso()})

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "bad_payload")

    def test_unrecognized_last_error_code_is_bad_payload_not_passed_through(self):
        self._seed({"envelope": None, "last_error": "some/private/host/error", "last_attempt_at": _iso()})

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "bad_payload")

    def test_non_string_last_error_is_bad_payload_not_a_raise(self):
        # round-2 finding: `in` on a set with an unhashable value (list/dict)
        # raises TypeError if _valid_last_error doesn't type-check first.
        self._seed({"envelope": None, "last_error": ["not_configured"], "last_attempt_at": _iso()})

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "bad_payload")

    def test_unrecognized_last_error_with_a_good_envelope_is_bad_payload(self):
        good = _envelope()
        self._seed({"envelope": good, "last_error": "unexpected-code", "last_attempt_at": _iso()})

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["error"], "bad_payload")
        self.assertIsNone(result["rpm"])


class StoreReadingTest(UsageRateTestCase):
    def test_successful_read_replaces_the_stored_envelope(self):
        usage_rate.store_reading(self.user_id, _envelope(rpm=1.0))
        usage_rate.store_reading(self.user_id, _envelope(rpm=9.0))

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["rpm"], 9.0)

    def test_failed_read_does_not_clobber_last_good_envelope(self):
        good = _envelope(rpm=4.0)
        usage_rate.store_reading(self.user_id, good)
        usage_rate.store_reading(self.user_id, _envelope(error="parse_failed", observed_at=_iso()))

        result = usage_rate.get_reading(self.user_id)

        self.assertEqual(result["rpm"], 4.0)
        self.assertEqual(result["error"], "parse_failed")

    def test_rejects_an_envelope_with_unexpected_keys(self):
        with self.assertRaises(ValueError):
            usage_rate.store_reading(self.user_id, {"rpm": 1.0})


if __name__ == "__main__":
    unittest.main()
