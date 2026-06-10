-- Schema Catalog v2: enriched embeddings + MaxSim multi-vectors + value-aware FTS.
--
-- New columns on schema_definitions:
--   embedding_text  - the enriched serialization that was embedded (humanized
--                     name tokens, data type, patterns, FK target, samples)
--   multi_embedding - full ColQwen2 multi-vector, float16 row-major (n_vectors, 128),
--                     same format as document_pages.multi_embedding
--   n_vectors       - number of token vectors in multi_embedding
--
-- search_vector and content_length are GENERATED columns and cannot be altered,
-- so they are dropped and recreated to include embedding_text (weight 'C' lets
-- BM25 match sample values and humanized name tokens too).
--
-- Apply while no schema indexing job is running. Existing connectors keep
-- working (NULL new columns degrade gracefully) but should be re-indexed via
-- POST /api/connectors/{id}/index for full accuracy.

ALTER TABLE schema_definitions
    ADD COLUMN IF NOT EXISTS embedding_text TEXT,
    ADD COLUMN IF NOT EXISTS multi_embedding BYTEA,
    ADD COLUMN IF NOT EXISTS n_vectors INTEGER;

DROP INDEX IF EXISTS idx_schema_definitions_fts;
ALTER TABLE schema_definitions DROP COLUMN IF EXISTS search_vector;
ALTER TABLE schema_definitions ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', COALESCE(table_name, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(column_name, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(semantic_definition, '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(embedding_text, '')), 'C')
) STORED;
CREATE INDEX idx_schema_definitions_fts ON schema_definitions USING GIN(search_vector);

ALTER TABLE schema_definitions DROP COLUMN IF EXISTS content_length;
ALTER TABLE schema_definitions ADD COLUMN content_length INTEGER GENERATED ALWAYS AS (
    length(COALESCE(table_name, '')) +
    length(COALESCE(column_name, '')) +
    length(COALESCE(semantic_definition, '')) +
    length(COALESCE(embedding_text, ''))
) STORED;
