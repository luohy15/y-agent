-- Migration: Add optional password protection to chat and trace shares
-- Run manually with: psql $DATABASE_URL -f migration_share_password.sql

ALTER TABLE chat ADD COLUMN share_password_hash VARCHAR;
ALTER TABLE trace_share ADD COLUMN password_hash VARCHAR;
