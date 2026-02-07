#!/bin/bash

# Verification script for hybrid search setup
# Tests that all components are properly installed and configured

set -e

echo "=========================================="
echo "Hybrid Search Verification Script"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if postgres container is running
echo "1. Checking PostgreSQL container..."
if docker ps | grep -q db-agent-postgres; then
    echo -e "${GREEN}✓ PostgreSQL container is running${NC}"
else
    echo -e "${RED}✗ PostgreSQL container is not running${NC}"
    echo "Run: docker-compose up -d postgres"
    exit 1
fi

echo ""

# Check VectorChord extension
echo "2. Checking VectorChord extension..."
if docker exec db-agent-postgres psql -U postgres -d database_agent -c "\dx vchord" | grep -q vchord; then
    echo -e "${GREEN}✓ VectorChord extension installed${NC}"
else
    echo -e "${RED}✗ VectorChord extension not found${NC}"
    exit 1
fi

echo ""

# Check pg_search extension
echo "3. Checking ParadeDB pg_search extension..."
if docker exec db-agent-postgres psql -U postgres -d database_agent -c "\dx pg_search" | grep -q pg_search; then
    echo -e "${GREEN}✓ pg_search extension installed${NC}"
else
    echo -e "${YELLOW}⚠ pg_search extension not found${NC}"
    echo "This is required for BM25 keyword search"
    echo "Run: docker exec -i db-agent-postgres psql -U postgres -d database_agent < migrations/add_bm25_and_cosine.sql"
    exit 1
fi

echo ""

# Check BM25 index
echo "4. Checking BM25 index..."
BM25_INDEX=$(docker exec db-agent-postgres psql -U postgres -d database_agent -t -c "SELECT COUNT(*) FROM paradedb.indexes WHERE index_name = 'document_chunks_bm25_idx';")
if [ "$BM25_INDEX" -gt 0 ]; then
    echo -e "${GREEN}✓ BM25 index exists${NC}"
else
    echo -e "${YELLOW}⚠ BM25 index not found${NC}"
    echo "Run: docker exec -i db-agent-postgres psql -U postgres -d database_agent < migrations/add_bm25_and_cosine.sql"
    exit 1
fi

echo ""

# Check cosine similarity index
echo "5. Checking cosine similarity index..."
COSINE_INDEX=$(docker exec db-agent-postgres psql -U postgres -d database_agent -t -c "SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'document_chunks' AND indexname = 'document_chunks_embedding_cosine_idx';")
if [ "$COSINE_INDEX" -gt 0 ]; then
    echo -e "${GREEN}✓ Cosine similarity index exists${NC}"
else
    echo -e "${YELLOW}⚠ Cosine similarity index not found${NC}"
    echo "Run: docker exec -i db-agent-postgres psql -U postgres -d database_agent < migrations/add_bm25_and_cosine.sql"
    exit 1
fi

echo ""

# Check content_length column
echo "6. Checking content_length column..."
CONTENT_LENGTH=$(docker exec db-agent-postgres psql -U postgres -d database_agent -t -c "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'document_chunks' AND column_name = 'content_length';")
if [ "$CONTENT_LENGTH" -gt 0 ]; then
    echo -e "${GREEN}✓ content_length column exists${NC}"
else
    echo -e "${YELLOW}⚠ content_length column not found${NC}"
    echo "This is optional but recommended for BM25 tuning"
fi

echo ""

# Test BM25 query (if there's data)
echo "7. Testing BM25 query..."
CHUNK_COUNT=$(docker exec db-agent-postgres psql -U postgres -d database_agent -t -c "SELECT COUNT(*) FROM document_chunks;")
if [ "$CHUNK_COUNT" -gt 0 ]; then
    echo "Found $CHUNK_COUNT document chunks"
    BM25_TEST=$(docker exec db-agent-postgres psql -U postgres -d database_agent -t -c "SELECT COUNT(*) FROM document_chunks WHERE document_chunks @@@ paradedb.parse('test');")
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ BM25 search query works${NC}"
    else
        echo -e "${RED}✗ BM25 search query failed${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠ No document chunks found (upload documents to test BM25)${NC}"
fi

echo ""

# Test cosine similarity query (if there's data with embeddings)
echo "8. Testing cosine similarity query..."
EMBEDDING_COUNT=$(docker exec db-agent-postgres psql -U postgres -d database_agent -t -c "SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL;")
if [ "$EMBEDDING_COUNT" -gt 0 ]; then
    echo "Found $EMBEDDING_COUNT chunks with embeddings"
    # Create a dummy embedding vector for testing
    COSINE_TEST=$(docker exec db-agent-postgres psql -U postgres -d database_agent -t -c "SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL ORDER BY embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) LIMIT 1;")
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Cosine similarity query works${NC}"
    else
        echo -e "${RED}✗ Cosine similarity query failed${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠ No embeddings found (upload and process documents to test cosine similarity)${NC}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Hybrid Search Setup Verification Complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Upload documents to a collection"
echo "2. Test hybrid search via API: curl -X POST http://localhost:8001/api/collections/search -H 'Content-Type: application/json' -d '{\"query\": \"test\", \"mode\": \"hybrid\"}'"
echo "3. Test in chat interface"
echo ""
