-- Multi-turn chat via Claude Agent SDK session resume: store the SDK session id
-- of the last completed turn on the conversation, so the next turn passes it as
-- `resume` instead of replaying the whole history as text.
-- Run against existing databases (init.sql already includes the column for new ones):
--   psql $DATABASE_URL -f migrations/add_sdk_session_id.sql

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS sdk_session_id VARCHAR(64);
