-- External-source tracking for ingest-by-reference (knowledge base integration).
-- Documents pushed by the centralized knowledge base module carry an
-- external_id (idempotency key) and a source_url pointing at the KB's copy.
--
-- Apply manually (only init.sql auto-applies):
--   psql postgresql://postgres:postgres@localhost:5433/database_agent -f migrations/add_external_documents.sql

ALTER TABLE documents ADD COLUMN IF NOT EXISTS external_id VARCHAR(255);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_metadata JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_external_id
    ON documents (external_id)
    WHERE external_id IS NOT NULL;
