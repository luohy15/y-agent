"""Classified columns. Metadata, ids, enums, times and counters stay plaintext."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    table: str
    owner_attr: str | None
    public_attr: str | None
    fields: tuple[str, ...]
    bidx: tuple[tuple[str, str, str], ...] = ()
    clear: tuple[str, ...] = ()
    credential_owner: bool = False

    def public_id(self, obj, bidx_values: dict[str, str]) -> str:
        if self.table == "entity_tag":
            return f"{obj.entity_type}:{obj.entity_id}:{bidx_values['tag']}"
        if self.table == "tag_vocabulary":
            return bidx_values["tag"]
        if self.table == "email_account":
            return bidx_values["address"]
        if self.table == "mcp_credential":
            return f"{obj.connector_pk}:{obj.kind}"
        if self.table == "chat_context_session":
            return f"{obj.chat_id}:{obj.session_id}"
        if self.table == "chat_context_request":
            return f"{obj.chat_id}:{obj.request_id}"
        if self.table == "chat_context_contributor":
            return f"{obj.chat_id}:{obj.session_id}:{obj.occurrence_id}"
        if self.table == "wechat_inbound":
            return f"{obj.account}:{obj.message_id}"
        value = getattr(obj, self.public_attr)
        if value is None or value == "":
            raise RuntimeError("missing public id")
        return str(value)


def _spec(table: str, public: str, fields: tuple[str, ...], bidx=(), clear=(), owner="user_id", credential=False):
    return TableSpec(table, owner, public, fields, bidx, clear, credential)


SPECS = {
    "WechatAccountEntity": _spec("wechat_account", "account", ("bot_token",)),
    "WechatContextEntity": _spec("wechat_context", "key", ("context_token",)),
    "WechatOutboxEntity": _spec("wechat_outbox", "outbox_id", ("text",)),
    "WechatInboundEntity": _spec("wechat_inbound", "message_id", ("quote_text", "media_name")),
    "ChatEntity": _spec("chat", "chat_id", ("title", "json_content"), clear=("search_text",)),
    "ChatWakeupEntity": _spec("chat_wakeup", "wakeup_id", ("message",)),
    "TodoEntity": _spec("todo", "todo_id", ("name", "desc", "progress", "tags", "history")),
    "EntityTagEntity": _spec(
        "entity_tag", "tag", ("tag",), bidx=(("tag", "tag_bidx", "tag"),),
    ),
    "TagVocabularyEntity": _spec(
        "tag_vocabulary", "tag", ("tag",), bidx=(("tag", "tag_bidx", "tag"),),
    ),
    "CalendarEventEntity": _spec("calendar_event", "event_id", ("summary", "description", "source_id")),
    "ReminderEntity": _spec("reminder", "reminder_id", ("title", "description")),
    "RoutineEntity": _spec(
        "routine", "routine_id", ("name", "description", "message", "work_dir", "command", "guard"),
    ),
    "EmailEntity": _spec(
        "email", "email_id",
        ("subject", "content", "from_addr", "to_addrs", "cc_addrs", "bcc_addrs"),
        bidx=(("from_addr", "from_addr_bidx", "from_addr"), ("account", "account_bidx", "account")),
    ),
    "EmailAccountEntity": _spec(
        "email_account", "address", ("address", "app_password"),
        bidx=(("address", "address_bidx", "address"),),
    ),
    "EnglishCorrectionEntity": _spec(
        "english_correction", "correction_id", ("original_text", "corrected_text", "explanation"),
    ),
    "EntityEntity": _spec("entity", "entity_id", ("name", "front_matter")),
    "NoteEntity": _spec("note", "note_id", ("front_matter",)),
    "LinkEntity": _spec("link", "link_id", ("base_url", "title"), bidx=(("base_url", "base_url_bidx", "base_url"),)),
    "LinkActivityEntity": _spec(
        "link_activity", "activity_id", ("url", "title"), bidx=(("url", "url_bidx", "url"),),
    ),
    "RssFeedEntity": _spec(
        "rss_feed", "rss_feed_id", ("url", "title", "scrape_config"), bidx=(("url", "url_bidx", "url"),),
    ),
    "BotConfigEntity": _spec(
        "bot_config", "name",
        ("api_key", "backends", "openrouter_config", "prompts", "description", "effort_evidence"),
    ),
    "VmConfigEntity": _spec("vm_config", "name", ("api_token", "vm_name", "work_dir")),
    "UserCookiesEntity": _spec(
        "user_cookies", "domain", ("cookies_txt",), bidx=(("domain", "domain_bidx", "domain"),),
    ),
    "UserPreferenceEntity": _spec("user_preference", "key", ("value",)),
    "UploadJobEntity": _spec("upload_job", "upload_id", ("filename", "dest_dir", "work_dir")),
    "ChatContextSessionEntity": _spec(
        "chat_context_session", "session_id", ("gaps", "events", "suggestions"),
    ),
    "ChatContextRequestEntity": _spec("chat_context_request", "request_id", ("gaps",)),
    "ChatContextContributorEntity": _spec("chat_context_contributor", "occurrence_id", ("label",)),
    "McpConnectorEntity": _spec("mcp_connector", "connector_id", ("catalog",)),
    "McpCredentialEntity": _spec(
        "mcp_credential", "kind", ("secret_json",), credential=True,
    ),
    "McpOAuthTransactionEntity": _spec("mcp_oauth_transaction", "transaction_id", ("secret_json",)),
    "RelayCredentialEntity": _spec("relay_credential", "credential_id", ("api_key",)),
}
