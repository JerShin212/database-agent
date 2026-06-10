-- Fix bm25_rank returning NULL (which crashed search code calling float(score))
-- and guard against division by zero.
--
-- NULL paths in the old version:
--   - content_length NULL -> norm_length NULL -> NULL return
--   - score + k1 * norm_length = 0 -> division by zero
-- Same signature as the existing function so all call sites pick it up
-- (schema_definitions and document_chunks searches). DROP first because the
-- deployed version may use a different parameter name (doc_length), which
-- CREATE OR REPLACE cannot rename.

DROP FUNCTION IF EXISTS bm25_rank(tsvector, tsquery, integer, double precision, double precision, double precision);

CREATE FUNCTION bm25_rank(
    search_vector tsvector,
    query tsquery,
    content_length integer,
    avgdl float DEFAULT 500.0,
    k1 float DEFAULT 1.2,
    b float DEFAULT 0.75
) RETURNS float AS $$
DECLARE
    score float;
    norm_length float;
BEGIN
    score := COALESCE(ts_rank(search_vector, query), 0.0);
    norm_length := 1.0 - b + b * (COALESCE(content_length, avgdl::integer)::float / NULLIF(avgdl, 0.0));
    RETURN COALESCE(score * (k1 + 1.0) / NULLIF(score + k1 * norm_length, 0.0), 0.0);
END;
$$ LANGUAGE plpgsql IMMUTABLE;
