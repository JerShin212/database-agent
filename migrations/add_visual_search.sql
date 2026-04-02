-- Document pages with ColQwen2 visual embeddings (128-dim, mean-pooled per page)
CREATE TABLE IF NOT EXISTS document_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    collection_id UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    visual_embedding VECTOR(128),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Vector index for visual similarity search (VectorChord, cosine)
CREATE INDEX IF NOT EXISTS document_pages_embedding_idx
    ON document_pages USING vchordrq (visual_embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_document_pages_document_id ON document_pages(document_id);
CREATE INDEX IF NOT EXISTS idx_document_pages_collection_id ON document_pages(collection_id);
