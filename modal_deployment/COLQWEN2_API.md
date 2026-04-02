# ColQwen2 Embedding Service API

This document describes how to call the deployed Modal endpoints in `modal_deployment/modal_colqwen2.py`.

## Base Endpoints

- Image: `https://jershin212--daikin-test-colqwen2-embedder-model-embed-image.modal.run`
- Text: `https://jershin212--daikin-test-colqwen2-embedder-model-embed-text.modal.run`
- PDF: `https://jershin212--daikin-test-colqwen2-embedder-model-embed-pdf.modal.run`

All endpoints use `POST` and return JSON.

## 1) Embed Text

### Request

- URL: `...-embed-text.modal.run`
- Method: `POST`
- Content-Type: `application/json`
- Body:

```json
{
  "text": "your query text"
}
```

### cURL

```bash
curl -X POST "https://jershin212--daikin-test-colqwen2-embedder-model-embed-text.modal.run" \
  -H "Content-Type: application/json" \
  -d '{"text":"What is preventive maintenance for HVAC?"}'
```

### Response Structure (200)

```json
{
  "embeddings": [[0.123, -0.456, "..."]],
  "total_vectors": 1,
  "vector_dim": 128,
  "text": "What is preventive maintenance for HVAC?",
  "message": "Successfully processed text query"
}
```

- `embeddings`: multi-vector representation for the input text
- `total_vectors`: number of vectors returned
- `vector_dim`: vector dimension (or `null` if unavailable)

## 2) Embed Image

### Request

- URL: `...-embed-image.modal.run`
- Method: `POST`
- Content-Type: `multipart/form-data`
- Form field: `file` (image file)
- Supported extensions: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.webp`

### cURL

```bash
curl -X POST "https://jershin212--daikin-test-colqwen2-embedder-model-embed-image.modal.run" \
  -F "file=@/absolute/path/to/image.jpg"
```

### Response Structure (200)

```json
{
  "embeddings": [[0.123, -0.456, "..."]],
  "total_vectors": 1,
  "vector_dim": 128,
  "filename": "image.jpg",
  "image_size": [1920, 1080],
  "message": "Successfully processed image image.jpg"
}
```

- `image_size`: `[width, height]`

## 3) Embed PDF

### Request

- URL: `...-embed-pdf.modal.run`
- Method: `POST`
- Content-Type: `multipart/form-data`
- Form field: `file` (PDF file, `.pdf`)

### cURL

```bash
curl -X POST "https://jershin212--daikin-test-colqwen2-embedder-model-embed-pdf.modal.run" \
  -F "file=@/absolute/path/to/document.pdf"
```

### Response Structure (200)

```json
{
  "embeddings": [[0.123, -0.456, "..."]],
  "document_paths": ["document.pdf", "document.pdf"],
  "page_counts": [2],
  "total_embeddings": 2,
  "embedding_dim": 128,
  "filename": "document.pdf",
  "message": "Successfully processed 2 pages from document.pdf"
}
```

- `document_paths`: repeated original filename for each processed page
- `page_counts`: currently a single-item list with the number of pages
- `total_embeddings`: number of page-level embeddings returned

## Error Behavior

Current implementation raises generic exceptions; failed requests return HTTP 500.

Common validation failures:

- Text endpoint: empty/blank `text`
- Image endpoint: unsupported extension or invalid image file
- PDF endpoint: non-PDF upload or unreadable PDF

## Notes for Consumers

- Large PDFs/images may take longer due to GPU inference and PDF-to-image conversion.
- This API currently has no auth at endpoint level; if needed, add a gateway/auth layer before broader sharing.
