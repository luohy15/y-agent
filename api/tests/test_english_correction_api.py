"""Unit tests for api.controller.english_correction (todo 2871, S3).

storage.service.english_correction is mocked; nothing touches a real database.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api.controller import english_correction as ctrl
from storage.dto.english_correction import EnglishCorrection


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def _row(**overrides):
    base = dict(
        correction_id="corr_a1",
        chat_id="chat1",
        message_id="msg1",
        message_at="2026-07-27T03:42:00+00:00",
        message_at_unix=1722051720000,
        original_text="I already finish the draft.",
        corrected_text="I have already finished the draft.",
        error_categories=["tense"],
        explanation="Use present perfect with already.",
        dismissed=False,
        created_at="2026-07-27T04:00:00+00:00",
        created_at_unix=1722052800000,
    )
    base.update(overrides)
    return EnglishCorrection(**base)


class ListDetailTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_happy_path_no_id_key(self):
        with patch.object(ctrl.eng_service, "list_corrections", return_value=[_row()]) as list_fn:
            result = await ctrl.list_corrections(_request(), dismissed=False, limit=10)
        list_fn.assert_called_once()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["correction_id"], "corr_a1")
        self.assertNotIn("id", result[0])

    async def test_detail_happy_path(self):
        with patch.object(ctrl.eng_service, "get_correction", return_value=_row()) as get_fn:
            result = await ctrl.get_correction(_request(), correction_id="corr_a1")
        get_fn.assert_called_once_with(123, "corr_a1")
        self.assertEqual(result["correction_id"], "corr_a1")
        self.assertNotIn("id", result)

    async def test_detail_404(self):
        with patch.object(ctrl.eng_service, "get_correction", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.get_correction(_request(), correction_id="missing")
        self.assertEqual(ctx.exception.status_code, 404)


class AddDismissTest(unittest.IsolatedAsyncioTestCase):
    async def test_add_happy_path(self):
        with patch.object(ctrl.eng_service, "add_correction", return_value=_row()) as add_fn:
            req = ctrl.AddCorrectionRequest(
                chat_id="chat1",
                message_id="msg1",
                message_at="2026-07-27T03:42:00+00:00",
                message_at_unix=1722051720000,
                original_text="I already finish the draft.",
                corrected_text="I have already finished the draft.",
                error_categories=["tense"],
                explanation="Use present perfect with already.",
            )
            result = await ctrl.add_correction(req, _request())
        add_fn.assert_called_once()
        self.assertEqual(result["correction_id"], "corr_a1")
        self.assertNotIn("id", result)

    async def test_dismiss_happy_path(self):
        dismissed = _row(dismissed=True)
        with patch.object(ctrl.eng_service, "dismiss_correction", return_value=dismissed) as d_fn:
            result = await ctrl.dismiss_correction(
                ctrl.DismissRequest(correction_id="corr_a1"), _request()
            )
        d_fn.assert_called_once_with(123, "corr_a1")
        self.assertTrue(result["dismissed"])
        self.assertNotIn("id", result)

    async def test_dismiss_404(self):
        with patch.object(ctrl.eng_service, "dismiss_correction", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.dismiss_correction(
                    ctrl.DismissRequest(correction_id="missing"), _request()
                )
        self.assertEqual(ctx.exception.status_code, 404)


class PendingMarkScannedTest(unittest.IsolatedAsyncioTestCase):
    async def test_pending_happy_path(self):
        payload = {
            "messages": [
                {
                    "chat_id": "c1",
                    "message_id": "m1",
                    "message_at": "2026-07-27T03:42:00+00:00",
                    "message_at_unix": 1722051720000,
                    "text": "I already finish the draft today.",
                }
            ],
            "scan_through_unix": 1722051720000,
            "since_unix": 1722048120000,
        }
        with patch.object(ctrl.eng_service, "list_pending", return_value=payload) as p_fn:
            result = await ctrl.list_pending(_request(), limit=50)
        p_fn.assert_called_once_with(123, since_unix=None, limit=50)
        self.assertEqual(result["scan_through_unix"], 1722051720000)
        self.assertNotIn("id", result)

    async def test_mark_scanned_happy_path(self):
        with patch.object(
            ctrl.eng_service, "set_watermark", return_value={"scanned_through_unix": 99}
        ) as m_fn:
            result = await ctrl.mark_scanned(
                ctrl.MarkScannedRequest(scanned_through_unix=99), _request()
            )
        m_fn.assert_called_once_with(123, 99)
        self.assertEqual(result, {"scanned_through_unix": 99})


if __name__ == "__main__":
    unittest.main()
