"""Carrier integration tests for entity_tag-backed link, email, and RSS filters."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.email  # noqa: F401 - registers EmailEntity with Base.metadata
import storage.entity.entity_tag  # noqa: F401 - registers EntityTagEntity with Base.metadata
import storage.entity.link  # noqa: F401 - registers LinkEntity and LinkActivityEntity
import storage.entity.rss_feed  # noqa: F401 - registers RssFeedEntity with Base.metadata
import storage.entity.user  # noqa: F401 - carrier and entity_tag user_id FKs
from storage.repository import email as email_repo
from storage.service import email as email_service
from storage.service import link as link_service
from storage.service import rss_feed as rss_feed_service
from storage.service import tag as tag_service


class TagCarrierTestCase(unittest.TestCase):
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

    def test_filters_and_hydrates_ingested_carriers(self):
        link = link_service.add_link(
            1, "https://example.com/link", title="Tagged link", timestamp=1,
        )
        link_service.add_link(1, "https://example.com/other", title="Other link", timestamp=2)
        email_repo.save_emails_batch(1, [{
            "external_id": "email-1",
            "subject": "Tagged email",
            "from_addr": "sender@example.com",
            "to_addrs": ["user@example.com"],
            "date": 3,
        }])
        email_repo.save_emails_batch(1, [{
            "external_id": "email-2",
            "subject": "Other email",
            "from_addr": "sender@example.com",
            "to_addrs": ["user@example.com"],
            "date": 4,
        }])
        tagged_email = email_service.list_emails(1, query="Tagged")[0]
        feed = rss_feed_service.add_feed(1, "https://example.com/feed", title="Tagged feed")
        rss_feed_service.add_feed(1, "https://example.com/other-feed", title="Other feed")

        for entity_type, entity_id in [
            ("link", link.activity_id),
            ("email", tagged_email.email_id),
            ("rss_feed", feed.rss_feed_id),
        ]:
            self.assertTrue(tag_service.add_tag(1, entity_type, entity_id, "inbox/read"))

        self.assertEqual(
            [item.activity_id for item in link_service.list_links(1, tag="inbox/read")],
            [link.activity_id],
        )
        self.assertEqual(
            [item.email_id for item in email_service.list_emails(1, tag="inbox/read")],
            [tagged_email.email_id],
        )
        self.assertEqual(
            [item.rss_feed_id for item in rss_feed_service.list_feeds(1, tag="inbox/read")],
            [feed.rss_feed_id],
        )

        hydrated = tag_service.get_by_tag(1, "inbox/read")
        self.assertEqual(hydrated["link"], [{"id": link.activity_id, "title": "Tagged link"}])
        self.assertEqual(hydrated["email"], [{"id": tagged_email.email_id, "title": "Tagged email"}])
        self.assertEqual(hydrated["rss_feed"], [{"id": feed.rss_feed_id, "title": "Tagged feed"}])

    def test_link_and_feed_delete_clean_up_tags(self):
        link = link_service.add_link(1, "https://example.com/link", title="Link", timestamp=1)
        feed = rss_feed_service.add_feed(1, "https://example.com/feed", title="Feed")
        tag_service.add_tag(1, "link", link.activity_id, "cleanup")
        tag_service.add_tag(1, "rss_feed", feed.rss_feed_id, "cleanup")

        self.assertTrue(link_service.delete_link(1, link.activity_id))
        self.assertTrue(rss_feed_service.delete_feed(1, feed.rss_feed_id))

        self.assertEqual(tag_service.list_tags(1, "link", link.activity_id), [])
        self.assertEqual(tag_service.list_tags(1, "rss_feed", feed.rss_feed_id), [])


if __name__ == "__main__":
    unittest.main()
