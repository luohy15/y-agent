"""Phase-2 batch P2: curated carriers (chat, calendar_event, reminder, routine).

Covers: self-registered hydration resolvers, list --tag filter via entity_tag join,
delete cleanup of entity_tag rows. Write path is service.tag (P1 owns the CLI).
"""

import asyncio
import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.calendar_event  # noqa: F401
import storage.entity.chat  # noqa: F401
import storage.entity.entity_tag  # noqa: F401
import storage.entity.reminder  # noqa: F401
import storage.entity.routine  # noqa: F401
import storage.entity.user  # noqa: F401
from storage.entity.chat import ChatEntity
from storage.repository import entity_tag as tag_repo
from storage.service import calendar_event as calendar_service
from storage.service import chat as chat_service
from storage.service import reminder as reminder_service
from storage.service import routine as routine_service
from storage.service import tag as tag_service


class P2CarrierTestCase(unittest.TestCase):
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

    def tearDown(self):
        dbbase._engine = self._orig_engine
        dbbase._SessionLocal = self._orig_session_local

    def _seed_chat(self, user_id: int, chat_id: str, title: str) -> None:
        with dbbase.get_db() as session:
            session.add(ChatEntity(
                user_id=user_id,
                chat_id=chat_id,
                title=title,
                json_content=json.dumps({
                    "id": chat_id,
                    "create_time": "2026-01-01T00:00:00.000Z",
                    "update_time": "2026-01-01T00:00:00.000Z",
                    "messages": [],
                }),
                status="idle",
            ))


class ResolverRegistrationTest(P2CarrierTestCase):
    def test_register_resolver_is_public_extension_point(self):
        seen = {}

        def fake_resolver(user_id, entity_id):
            seen["args"] = (user_id, entity_id)
            return {"id": entity_id, "title": "fake"}

        tag_service.register_resolver("link", fake_resolver)
        tag_repo.add_tag(1, "link", "a-1", "work/y-agent")
        grouped = tag_service.get_by_tag(1, "work/y-agent")
        self.assertEqual(grouped["link"], [{"id": "a-1", "title": "fake"}])
        self.assertEqual(seen["args"], (1, "a-1"))

    def test_chat_calendar_reminder_routine_self_register_and_hydrate(self):
        self._seed_chat(1, "c-1", "Impl P2 tags")
        event = calendar_service.add_event(1, "Standup", "2026-07-21T10:00")
        reminder = reminder_service.add_reminder(1, "Ship tags", "2026-07-21T18:00")
        routine = routine_service.add_routine(
            1, "daily-scan", "0 9 * * *", "run daily scan",
        )

        tag_service.sync_tags(1, "chat", "c-1", ["work/y-agent"])
        tag_service.sync_tags(1, "calendar_event", event.event_id, ["work/y-agent"])
        tag_service.sync_tags(1, "reminder", reminder.reminder_id, ["work/y-agent"])
        tag_service.sync_tags(1, "routine", routine.routine_id, ["work/y-agent"])

        grouped = tag_service.get_by_tag(1, "work/y-agent")

        self.assertEqual(grouped["chat"], [{"id": "c-1", "title": "Impl P2 tags"}])
        self.assertEqual(
            grouped["calendar_event"],
            [{"id": event.event_id, "title": "Standup"}],
        )
        self.assertEqual(
            grouped["reminder"],
            [{"id": reminder.reminder_id, "title": "Ship tags"}],
        )
        self.assertEqual(
            grouped["routine"],
            [{"id": routine.routine_id, "title": "daily-scan"}],
        )


class ListTagFilterTest(P2CarrierTestCase):
    def test_chat_list_filters_by_tag(self):
        self._seed_chat(1, "c-1", "tagged")
        self._seed_chat(1, "c-2", "untagged")
        tag_service.add_tag(1, "chat", "c-1", "work/y-agent")

        results = asyncio.run(chat_service.list_chats(1, limit=50, tag="work/y-agent"))
        self.assertEqual([c.chat_id for c in results], ["c-1"])

    def test_calendar_list_filters_by_tag(self):
        a = calendar_service.add_event(1, "A", "2026-07-21T10:00")
        calendar_service.add_event(1, "B", "2026-07-21T11:00")
        tag_service.add_tag(1, "calendar_event", a.event_id, "life/health")

        results = calendar_service.list_events(1, tag="life/health")
        self.assertEqual([e.event_id for e in results], [a.event_id])

    def test_reminder_list_filters_by_tag(self):
        a = reminder_service.add_reminder(1, "A", "2026-07-21T18:00")
        reminder_service.add_reminder(1, "B", "2026-07-21T19:00")
        tag_service.add_tag(1, "reminder", a.reminder_id, "meta/systems")

        results = reminder_service.list_reminders(1, tag="meta/systems")
        self.assertEqual([r.reminder_id for r in results], [a.reminder_id])

    def test_routine_list_filters_by_tag(self):
        a = routine_service.add_routine(1, "alpha", "0 9 * * *", "msg a")
        routine_service.add_routine(1, "beta", "0 10 * * *", "msg b")
        tag_service.add_tag(1, "routine", a.routine_id, "work/y-agent")

        results = routine_service.list_routines(1, tag="work/y-agent")
        self.assertEqual([r.routine_id for r in results], [a.routine_id])

    def test_tag_filter_is_user_scoped(self):
        a = calendar_service.add_event(1, "Mine", "2026-07-21T10:00")
        other = calendar_service.add_event(2, "Theirs", "2026-07-21T10:00")
        tag_service.add_tag(1, "calendar_event", a.event_id, "work/y-agent")
        tag_service.add_tag(2, "calendar_event", other.event_id, "work/y-agent")

        mine = calendar_service.list_events(1, tag="work/y-agent")
        self.assertEqual([e.event_id for e in mine], [a.event_id])


class DeleteCleanupTest(P2CarrierTestCase):
    def test_delete_chat_clears_entity_tags(self):
        self._seed_chat(1, "c-1", "gone")
        tag_service.sync_tags(1, "chat", "c-1", ["work/y-agent", "life/health"])

        self.assertTrue(asyncio.run(chat_service.delete_chat(1, "c-1")))
        self.assertEqual(tag_repo.list_tags(1, "chat", "c-1"), [])

    def test_delete_calendar_event_clears_entity_tags(self):
        event = calendar_service.add_event(1, "Standup", "2026-07-21T10:00")
        tag_service.sync_tags(1, "calendar_event", event.event_id, ["work/y-agent"])

        deleted = calendar_service.delete_event(1, event.event_id)
        self.assertIsNotNone(deleted)
        self.assertEqual(tag_repo.list_tags(1, "calendar_event", event.event_id), [])

    def test_delete_routine_clears_entity_tags(self):
        routine = routine_service.add_routine(1, "daily", "0 9 * * *", "msg")
        tag_service.sync_tags(1, "routine", routine.routine_id, ["work/y-agent"])

        self.assertTrue(routine_service.delete_routine(1, routine.routine_id))
        self.assertEqual(tag_repo.list_tags(1, "routine", routine.routine_id), [])


if __name__ == "__main__":
    unittest.main()
