"""Backward-compat re-export: all DTOs now live in storage.dto.*"""

from storage.dto import (  # noqa: F401
    BotConfig, DEFAULT_OPENROUTER_CONFIG,
    VmConfig,
    ContentPart, Message, Chat,
    TodoHistoryEntry, Todo,
    CalendarEvent,
    Link, LinkActivity, LinkSummary,
    Note,
    Email,
    TgTopic,
    Reminder,
    RssFeed,
)
