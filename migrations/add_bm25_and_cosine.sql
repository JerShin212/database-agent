-- ==============================================================================
-- Migration: Add BM25-like Keyword Search and Cosine Similarity Support
-- ==============================================================================
-- This migration adds hybrid search capabilities combining BM25-like keyword
-- search (using PostgreSQL FTS) and cosine similarity semantic search with
-- Reciprocal Rank Fusion (RRF).
--
-- Note: Using PostgreSQL's built-in Full-Text Search with custom BM25-like
-- scoring function as a fallback (no additional extensions required).
-- ==============================================================================

-- ==============================================================================
-- Part 1: Create Full-Text Search Column and Index
-- ==============================================================================

-- Add tsvector column for full-text search
-- Generated column automatically updates when content changes
ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS search_vector tsvector
GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(content, '')), 'A')
) STORED;

-- Create GIN index for fast full-text search
-- GIN (Generalized Inverted Index) is optimized for FTS queries
CREATE INDEX IF NOT EXISTS document_chunks_search_idx
ON document_chunks USING GIN (search_vector);

-- ==============================================================================
-- Part 2: Create Custom BM25-like Scoring Function
-- ==============================================================================

-- Custom BM25-like ranking function using PostgreSQL FTS
-- This approximates BM25 algorithm using ts_rank_cd as base with
-- length normalization parameters
CREATE OR REPLACE FUNCTION bm25_rank(
    search_vector tsvector,
    query tsquery,
    doc_length integer,
    avg_length float DEFAULT 500.0,
    k1 float DEFAULT 1.2,
    b float DEFAULT 0.75
) RETURNS float AS $$
    -- BM25-like scoring using ts_rank_cd with length normalization
    -- k1 controls term saturation (higher = less saturation)
    -- b controls length normalization (0 = no norm, 1 = full norm)
    SELECT ts_rank_cd(search_vector, query, 32) *
           (k1 + 1.0) /
           (1.0 + (k1 * ((1.0 - b) + b * (doc_length::float / avg_length))))::float;
$$ LANGUAGE SQL IMMUTABLE PARALLEL SAFE;

-- ==============================================================================
-- Part 3: Migrate Vector Index from L2 to Cosine Similarity
-- ==============================================================================

-- Drop existing L2 distance index
DROP INDEX IF EXISTS document_chunks_embedding_idx;

-- Create new cosine similarity index
-- VectorChord uses 'vchordrq' index with vector_cosine_ops for cosine distance
-- Cosine distance operator: <=> (range 0-2 for normalized vectors)
-- Cosine similarity = 1 - cosine_distance (range -1 to 1, typically 0-1)
CREATE INDEX IF NOT EXISTS document_chunks_embedding_cosine_idx
ON document_chunks USING vchordrq (embedding vector_cosine_ops);

-- ==============================================================================
-- Part 4: Add Metadata Column for BM25 Scores
-- ==============================================================================

-- Store document length for BM25 parameter tuning and analysis
ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS content_length INTEGER
GENERATED ALWAYS AS (length(content)) STORED;

CREATE INDEX IF NOT EXISTS document_chunks_content_length_idx
ON document_chunks(content_length);

-- ==============================================================================
-- Part 5: Calculate Average Document Length (for BM25 normalization)
-- ==============================================================================

-- Create a simple view to track average document length
-- This can be used by applications for BM25 parameter tuning
CREATE OR REPLACE VIEW document_chunks_stats AS
SELECT
    COUNT(*) as total_chunks,
    AVG(content_length) as avg_content_length,
    MIN(content_length) as min_content_length,
    MAX(content_length) as max_content_length,
    STDDEV(content_length) as stddev_content_length
FROM document_chunks
WHERE content_length IS NOT NULL;

-- ==============================================================================
-- Verification Queries (for manual testing after migration)
-- ==============================================================================

-- Test FTS index exists
-- SELECT indexname, indexdef FROM pg_indexes
-- WHERE tablename = 'document_chunks' AND indexname = 'document_chunks_search_idx';

-- Test cosine similarity index exists
-- SELECT indexname, indexdef FROM pg_indexes
-- WHERE tablename = 'document_chunks' AND indexname LIKE '%cosine%';

-- Test BM25-like query (example)
-- SELECT content,
--        bm25_rank(search_vector, websearch_to_tsquery('english', 'test query'),
--                  content_length, 500.0, 1.2, 0.75) as score
-- FROM document_chunks
-- WHERE search_vector @@ websearch_to_tsquery('english', 'test query')
-- ORDER BY score DESC
-- LIMIT 5;

-- Test cosine similarity query (example with placeholder embedding)
-- SELECT content, 1.0 - (embedding <=> ARRAY[0.1, 0.2, ...]::vector) as similarity
-- FROM document_chunks
-- WHERE embedding IS NOT NULL
-- ORDER BY embedding <=> ARRAY[0.1, 0.2, ...]::vector
-- LIMIT 5;

-- View document statistics
-- SELECT * FROM document_chunks_stats;
