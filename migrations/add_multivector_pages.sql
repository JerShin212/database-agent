-- MaxSim late-interaction support for visual page search.
--
-- Stores the full ColQwen2 multi-vector per page (n_vectors x 128, float16,
-- row-major bytes) alongside the existing mean-pooled visual_embedding.
-- Two-stage retrieval: ANN candidate search on visual_embedding (vchordrq
-- cosine index, unchanged), then exact MaxSim rerank over multi_embedding.
--
-- Existing documents have multi_embedding = NULL; re-upload PDFs to backfill.
-- The reranker falls back to the pooled-vector order for NULL rows.

ALTER TABLE document_pages
    ADD COLUMN IF NOT EXISTS multi_embedding BYTEA,
    ADD COLUMN IF NOT EXISTS n_vectors INTEGER;
