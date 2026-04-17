-- Migration: Create reminder table
-- Run manually with: psql $DATABASE_URL -f migration_reminder.sql

CREATE TABLE reminder (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    reminder_id VARCHAR NOT NULL,

    -- content
    title VARCHAR NOT NULL,
    description TEXT,

    -- optional associations
    todo_id VARCHAR,
    calendar_event_id VARCHAR,

    -- scheduling
    remind_at VARCHAR NOT NULL,

    -- status
    status VARCHAR NOT NULL DEFAULT 'pending',
    sent_at VARCHAR,

    -- base fields
    created_at VARCHAR,
    updated_at VARCHAR,
    created_at_unix BIGINT,
    updated_at_unix BIGINT,

    UNIQUE(user_id, reminder_id)
);

CREATE INDEX idx_reminder_user_id ON reminder(user_id);
CREATE INDEX idx_reminder_pending ON reminder(status, remind_at) WHERE status = 'pending';
