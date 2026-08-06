import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.controller.note import router


class NoteContentKeyValidationTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()

        @app.middleware("http")
        async def set_user_id(request: Request, call_next):
            request.state.user_id = 1
            return await call_next(request)

        app.include_router(router, prefix="/api")
        self.client = TestClient(app)

    def test_import_rejects_home_escaping_content_key(self):
        with patch.dict("os.environ", {"Y_AGENT_HOME": str(Path("/tmp/agent-home"))}, clear=False), \
             patch("api.controller.note.note_service.import_note") as import_note:
            response = self.client.post("/api/note/import", json={"content_key": "../outside.md"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid content key")
        import_note.assert_not_called()

    def test_create_import_and_update_validate_content_keys(self):
        note = SimpleNamespace(to_dict=lambda: {"note_id": "note-1", "content_key": "pages/ok.md"})
        with patch.dict("os.environ", {"Y_AGENT_HOME": str(Path("/tmp/agent-home"))}, clear=False), \
             patch("api.controller.note.note_service.create_note", return_value=note) as create_note, \
             patch("api.controller.note.note_service.import_note", return_value=note) as import_note, \
             patch("api.controller.note.note_service.update_note", return_value=note) as update_note:
            self.assertEqual(self.client.post("/api/note", json={"content_key": "pages/ok.md"}).status_code, 200)
            self.assertEqual(self.client.post("/api/note/import", json={"content_key": "pages/ok.md"}).status_code, 200)
            self.assertEqual(
                self.client.post("/api/note/update", json={"note_id": "note-1", "content_key": "pages/ok.md"}).status_code,
                200,
            )

        create_note.assert_called_once()
        import_note.assert_called_once()
        update_note.assert_called_once()


if __name__ == "__main__":
    unittest.main()
