-- Migration: Add Connectors and Schema Catalog
-- Description: Implements semantic schema catalog for text-to-SQL generation
-- Tables: users, connectors, schema_definitions, schema_relationships

-- ============================================================================
-- Table: users
-- Purpose: Basic user management (placeholder for future auth system)
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create default user for single-user mode
INSERT INTO users (username, email) VALUES ('default', 'user@localhost')
ON CONFLICT (username) DO NOTHING;

-- ============================================================================
-- Table: connectors
-- Purpose: Store external database connection configurations
-- ============================================================================
CREATE TABLE IF NOT EXISTS connectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    db_type VARCHAR(50) NOT NULL, -- 'sqlite', 'postgresql', 'mysql'
    connection_string TEXT NOT NULL, -- Encrypted with Fernet
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- 'pending', 'indexing', 'ready', 'failed'
    indexing_progress JSONB, -- {"stage": "...", "current": X, "total": Y, "table": "..."}
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_connectors_user_id ON connectors(user_id);
CREATE INDEX idx_connectors_status ON connectors(status);

-- ============================================================================
-- Table: schema_definitions
-- Purpose: Semantic catalog of tables and columns with LLM-generated definitions
-- ============================================================================
CREATE TABLE IF NOT EXISTS schema_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    definition_type VARCHAR(20) NOT NULL, -- 'table' or 'column'
    table_name VARCHAR(255) NOT NULL,
    column_name VARCHAR(255), -- NULL for table-level definitions
    data_type VARCHAR(100), -- e.g., 'VARCHAR(255)', 'INTEGER', 'TIMESTAMP'
    semantic_definition TEXT NOT NULL, -- LLM-generated human-readable description
    sample_values JSONB, -- Sample data values for context
    embedding vector(1536), -- OpenAI text-embedding-3-small
    search_vector tsvector GENERATED ALWAYS AS (
        -- Boost table/column names with weight 'A', definition with weight 'B'
        setweight(to_tsvector('english', COALESCE(table_name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(column_name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(semantic_definition, '')), 'B')
    ) STORED,
    content_length INTEGER GENERATED ALWAYS AS (
        length(COALESCE(table_name, '')) +
        length(COALESCE(column_name, '')) +
        length(COALESCE(semantic_definition, ''))
    ) STORED,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_schema_definitions_connector_id ON schema_definitions(connector_id);
CREATE INDEX idx_schema_definitions_table_name ON schema_definitions(connector_id, table_name);
CREATE INDEX idx_schema_definitions_type ON schema_definitions(definition_type);
CREATE INDEX idx_schema_definitions_fts ON schema_definitions USING GIN(search_vector);
CREATE INDEX idx_schema_definitions_vector ON schema_definitions USING vchordrq (embedding vector_cosine_ops);

-- ============================================================================
-- Table: schema_relationships
-- Purpose: Store foreign key relationships between tables
-- ============================================================================
CREATE TABLE IF NOT EXISTS schema_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    from_table VARCHAR(255) NOT NULL,
    from_column VARCHAR(255) NOT NULL,
    to_table VARCHAR(255) NOT NULL,
    to_column VARCHAR(255) NOT NULL,
    relationship_type VARCHAR(50) DEFAULT 'foreign_key', -- 'foreign_key', 'one_to_many', etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_schema_relationships_connector_id ON schema_relationships(connector_id);
CREATE INDEX idx_schema_relationships_from_table ON schema_relationships(connector_id, from_table);
CREATE INDEX idx_schema_relationships_to_table ON schema_relationships(connector_id, to_table);

-- ============================================================================
-- Custom BM25 Ranking Function (Reuse from existing system)
-- ============================================================================
-- Note: This assumes the bm25_rank function already exists from document_chunks migration
-- If not, create it:

CREATE OR REPLACE FUNCTION bm25_rank(
    search_vector tsvector,
    query tsquery,
    content_length integer,
    avgdl float DEFAULT 500.0,
    k1 float DEFAULT 1.2,
    b float DEFAULT 0.75
) RETURNS float AS $$
DECLARE
    score float;
    tf float;
    idf float;
    norm_length float;
BEGIN
    -- Simple BM25 approximation using PostgreSQL FTS
    -- Get base ts_rank score
    score := ts_rank(search_vector, query);

    -- Apply length normalization
    norm_length := 1.0 - b + b * (content_length / avgdl);

    -- Apply BM25-like scaling
    RETURN score * (k1 + 1.0) / (score + k1 * norm_length);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- Update Timestamp Trigger
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_connectors_updated_at
    BEFORE UPDATE ON connectors
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_schema_definitions_updated_at
    BEFORE UPDATE ON schema_definitions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Verification Queries
-- ============================================================================
-- Run these after migration to verify:
-- SELECT tablename, indexname FROM pg_indexes WHERE tablename IN ('connectors', 'schema_definitions', 'schema_relationships');
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'schema_definitions';
