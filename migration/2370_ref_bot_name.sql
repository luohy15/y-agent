-- Add ref_bot_name column for pointer bot support
ALTER TABLE bot_config ADD COLUMN ref_bot_name VARCHAR;

-- Set default bot to point to codex (if already seeded, otherwise init.py handles new setups)
UPDATE bot_config SET ref_bot_name = 'codex' WHERE name = 'default' AND ref_bot_name IS NULL;