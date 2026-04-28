"""Data Transfer Objects (dataclass DTOs) split by domain."""

from storage.dto.bot import BotConfig, DEFAULT_OPENROUTER_CONFIG
from storage.dto.vm import VmConfig
from storage.dto.chat import ContentPart, Message, Chat
from storage.dto.todo import TodoHistoryEntry, Todo
from storage.dto.calendar_event import CalendarEvent
from storage.dto.link import Link, LinkActivity, LinkSummary
from storage.dto.note import Note
from storage.dto.email import Email
from storage.dto.dev_worktree import DevWorktreeHistoryEntry, DevWorktree
from storage.dto.tg_topic import TgTopic
from storage.dto.reminder import Reminder
from storage.dto.rss_feed import RssFeed
from storage.dto.user_preference import UserPreference

__all__ = [
    "BotConfig", "DEFAULT_OPENROUTER_CONFIG",
    "VmConfig",
    "ContentPart", "Message", "Chat",
    "TodoHistoryEntry", "Todo",
    "CalendarEvent",
    "Link", "LinkActivity", "LinkSummary",
    "Note",
    "Email",
    "DevWorktreeHistoryEntry", "DevWorktree",
    "TgTopic",
    "Reminder",
    "RssFeed",
    "UserPreference",
]
