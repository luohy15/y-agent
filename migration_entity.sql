-- Migration: Create entity + entity_note_relation + entity_rss_relation tables
-- Run manually with: psql $DATABASE_URL -f migration_entity.sql

CREATE TABLE entity (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    entity_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    type VARCHAR NOT NULL,
    front_matter JSONB,

    -- base fields
    created_at VARCHAR,
    updated_at VARCHAR,
    created_at_unix BIGINT,
    updated_at_unix BIGINT,

    UNIQUE(user_id, entity_id)
);

CREATE INDEX idx_entity_user_id ON entity(user_id);
CREATE INDEX idx_entity_type ON entity(type);

CREATE TABLE entity_note_relation (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    entity_id VARCHAR NOT NULL,
    note_id VARCHAR NOT NULL,

    created_at VARCHAR,
    updated_at VARCHAR,
    created_at_unix BIGINT,
    updated_at_unix BIGINT,

    UNIQUE(user_id, entity_id, note_id)
);

CREATE INDEX idx_entity_note_relation_user_id ON entity_note_relation(user_id);
CREATE INDEX idx_entity_note_relation_entity_id ON entity_note_relation(entity_id);
CREATE INDEX idx_entity_note_relation_note_id ON entity_note_relation(note_id);

CREATE TABLE entity_rss_relation (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    entity_id VARCHAR NOT NULL,
    rss_feed_id VARCHAR NOT NULL,

    created_at VARCHAR,
    updated_at VARCHAR,
    created_at_unix BIGINT,
    updated_at_unix BIGINT,

    UNIQUE(user_id, entity_id, rss_feed_id)
);

CREATE INDEX idx_entity_rss_relation_user_id ON entity_rss_relation(user_id);
CREATE INDEX idx_entity_rss_relation_entity_id ON entity_rss_relation(entity_id);
CREATE INDEX idx_entity_rss_relation_rss_feed_id ON entity_rss_relation(rss_feed_id);
