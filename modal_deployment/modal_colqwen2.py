"""
Modal deployment script for ColQwen2 embedding service.

This script defines a Modal application that provides PDF embedding services
using the ColQwen2 model for multimodal document understanding.
"""

import os
import tempfile
from pathlib import Path
from typing import List

import modal
import numpy as np
from fastapi import File, UploadFile
from pydantic import BaseModel

# Configuration constants
MODEL_ID = "vidore/colqwen2-v1.0-hf"
GPU_CONFIG = "A10G"
CACHE_DIR = "/cache"
PDF_DPI = 150
BATCH_SIZE = 8

# Persistent volume for Hugging Face model cache
cache_vol = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)


def download_model():
    """Download model weights during image build."""
    from transformers import ColQwen2ForRetrieval, ColQwen2Processor

    print(f"Downloading {MODEL_ID} to {CACHE_DIR}")
    ColQwen2ForRetrieval.from_pretrained(
        MODEL_ID,
        cache_dir=CACHE_DIR,
        trust_remote_code=True,
    )
    ColQwen2Processor.from_pretrained(
        MODEL_ID,
        cache_dir=CACHE_DIR,
    )
    print("Model downloaded successfully")


# Modal image configuration with required dependencies
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch>=2.8.0",
        "torchvision>=0.23.0",
        "transformers>=4.57",
        "accelerate>=1.10.1",
        "pdf2image>=1.17.0",
        "fastapi>=0.120.0",
        "python-multipart>=0.0.20",
        "Pillow>=12.0.0", 
    )
    .apt_install("poppler-utils")  # Required by pdf2image
    .run_function(download_model, volumes={CACHE_DIR: cache_vol})  # Download at build time
)

# Pydantic model for text embedding request
class TextInput(BaseModel):
    text: str

# Main Modal application
app = modal.App("daikin-test-colqwen2-embedder", image=image)


def process_pdf_to_images(pdf_path: str, dpi: int = PDF_DPI) -> List:
    """
    Convert PDF to list of PIL Images.

    Args:
        pdf_path: Path to PDF file
        dpi: DPI for PDF conversion

    Returns:
        List of PIL Images (one per page)

    Raises:
        Exception: If PDF processing fails
    """
    try:
        from pdf2image import convert_from_path

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise Exception(f"PDF file not found: {pdf_path}")

        if pdf_path.suffix.lower() != ".pdf":
            raise Exception(f"File is not a PDF: {pdf_path}")

        pages = convert_from_path(str(pdf_path), dpi=dpi)

        # Convert to RGB if necessary
        rgb_pages = []
        for page in pages:
            if page.mode != "RGB":
                page = page.convert("RGB")
            rgb_pages.append(page)

        return rgb_pages

    except Exception as e:
        raise Exception(f"Failed to process PDF {pdf_path}: {str(e)}")


def batch_process_images(images: List, batch_size: int, process_func):
    """
    Process images in batches to manage memory usage.

    Args:
        images: List of PIL Images
        batch_size: Size of each batch
        process_func: Function to process each batch

    Returns:
        Concatenated results from all batches
    """
    results = []

    for i in range(0, len(images), batch_size):
        batch = images[i : i + batch_size]
        batch_result = process_func(batch)
        results.append(batch_result)

    return np.concatenate(results, axis=0)


@app.cls(
    gpu=GPU_CONFIG,
    volumes={CACHE_DIR: cache_vol},
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True}  # Enable GPU snapshots
)
class Model:
    """ColQwen2 model class for PDF embedding generation."""

    @modal.enter(snap=True)
    def load(self):
        """Load the ColQwen2 model and processor."""
        import torch
        from transformers import ColQwen2ForRetrieval, ColQwen2Processor

        self.model = ColQwen2ForRetrieval.from_pretrained(
            MODEL_ID,
            device_map="cuda",
            dtype=torch.bfloat16,
            cache_dir=CACHE_DIR,
            trust_remote_code=True,
        ).eval()

        self.processor = ColQwen2Processor.from_pretrained(
            MODEL_ID,
            cache_dir=CACHE_DIR,
            use_fast=True  # Use fast processor to avoid warnings
        )

        # Set the target device for encoding
        self.target_device = "cuda"


    def embed_images_batch(self, images: List, batch_size: int = BATCH_SIZE):
        """
        Generate embeddings for multiple images in batches.

        Args:
            images: List of PIL Images
            batch_size: Size of each batch

        Returns:
            Matrix of image embeddings (n_images × embedding_dim)
        """
        import torch

        def process_batch(batch_images):
            # Simplified - processor handles dtype conversion
            inputs = self.processor(
                images=batch_images,
                return_tensors="pt"
            ).to(self.target_device)

            with torch.no_grad():
                outputs = self.model(**inputs)
                embeddings = outputs.embeddings.float().cpu().numpy()

            return embeddings

        # Process in batches
        embeddings = batch_process_images(images, batch_size, process_batch)
        return embeddings

    def embed_text(self, text: str):
        """
        Generate multi-vector embeddings for text query using ColQwen2.

        Args:
            text: Text string to embed

        Returns:
            Multi-vector text embedding as numpy array
        """
        import torch

        # Process text using the processor (similar to the official example)
        inputs_text = self.processor(
            text=[text]  # Processor expects a list of texts
        ).to(self.target_device)

        with torch.no_grad():
            query_embeddings = self.model(**inputs_text).embeddings
            # Return the first (and only) query embedding
            return query_embeddings.float().cpu().numpy()[0]

    @modal.fastapi_endpoint(
        method="POST",
        label="daikin-test-colqwen2-embedder-model-embed-pdf"
    )
    async def embed_pdf_endpoint(self, file: UploadFile = File(...)) -> dict:
        """
        Generate embeddings for uploaded PDF file.

        Args:
            file: PDF file uploaded via multipart form data

        Returns:
            Dictionary containing embeddings, document paths, and page counts
        """
        try:
            # Validate file type
            if not file.filename.lower().endswith('.pdf'):
                raise Exception("Only PDF files are supported")

            # Read file content asynchronously
            file_content = await file.read()

            # Create temporary file to store uploaded PDF
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
                temp_file.write(file_content)
                temp_path = temp_file.name

            try:
                # Process the uploaded PDF
                print(f"DEBUG: Processing PDF at {temp_path}")
                pages = process_pdf_to_images(temp_path)
                print(f"DEBUG: Converted PDF to {len(pages)} pages")

                if not pages:
                    raise Exception("No valid PDF pages found to process")

                # Generate embeddings
                print(f"DEBUG: Starting embedding generation for {len(pages)} pages")
                embeddings = self.embed_images_batch(pages)
                print(f"DEBUG: Generated embeddings with shape: {embeddings.shape}")

                # Convert numpy array to list for JSON serialization
                embeddings_list = embeddings.tolist()
                print(f"DEBUG: Converted embeddings to list with {len(embeddings_list)} items")

                return {
                    "embeddings": embeddings_list,
                    "document_paths": [file.filename] * len(pages),
                    "page_counts": [len(pages)],
                    "total_embeddings": len(embeddings_list),
                    "embedding_dim": embeddings.shape[1]
                    if len(embeddings.shape) > 1
                    else None,
                    "filename": file.filename,
                    "message": f"Successfully processed {len(pages)} pages from {file.filename}"
                }

            finally:
                # Clean up temporary file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except Exception as e:
            raise Exception(f"Failed to process uploaded PDF: {str(e)}")

    @modal.fastapi_endpoint(
        method="POST",
        label="daikin-test-colqwen2-embedder-model-embed-text"
    )
    async def embed_text_endpoint(self, request: TextInput) -> dict:
        """
        Generate embeddings for text query.

        Args:
            request: TextInput object containing the text to embed

        Returns:
            Dictionary containing the text embedding and metadata
        """
        try:
            # Validate input
            if not request.text or not request.text.strip():
                raise Exception("Text cannot be empty")

            print(f"DEBUG: Processing text: {request.text[:100]}...")

            # Generate embeddings
            embeddings = self.embed_text(request.text.strip())
            print(f"DEBUG: Generated text embeddings with shape: {embeddings.shape}")

            # Convert numpy array to list for JSON serialization
            embeddings_list = embeddings.tolist()
            print(f"DEBUG: Converted embeddings to list with {len(embeddings_list)} vectors")

            return {
                "embeddings": embeddings_list,
                "total_vectors": len(embeddings_list),
                "vector_dim": embeddings.shape[1] if len(embeddings.shape) > 1 else None,
                "text": request.text,
                "message": "Successfully processed text query"
            }

        except Exception as e:
            raise Exception(f"Failed to process text query: {str(e)}")

    @modal.fastapi_endpoint(
        method="POST",
        label="daikin-test-colqwen2-embedder-model-embed-image"
    )
    async def embed_image_endpoint(self, file: UploadFile = File(...)) -> dict:
        """
        Generate embeddings for uploaded image file.

        Args:
            file: Image file uploaded via multipart form data

        Returns:
            Dictionary containing embeddings and metadata
        """
        try:
            # Validate file type
            valid_image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp')
            if not file.filename.lower().endswith(valid_image_extensions):
                raise Exception(f"Only image files are supported. Valid extensions: {', '.join(valid_image_extensions)}")

            # Read file content asynchronously
            file_content = await file.read()

            # Create temporary file to store uploaded image
            file_extension = os.path.splitext(file.filename)[1].lower()
            with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as temp_file:
                temp_file.write(file_content)
                temp_path = temp_file.name

            try:
                # Load the image using PIL
                from PIL import Image
                image = Image.open(temp_path)
                
                # Convert to RGB if necessary
                if image.mode != "RGB":
                    image = image.convert("RGB")

                print(f"DEBUG: Processing image at {temp_path}, size: {image.size}")

                # Generate embeddings
                print(f"DEBUG: Starting embedding generation for image")
                embeddings = self.embed_images_batch([image])
                print(f"DEBUG: Generated embeddings with shape: {embeddings.shape}")

                # Convert numpy array to list for JSON serialization
                embeddings_list = embeddings.tolist()
                print(f"DEBUG: Converted embeddings to list with {len(embeddings_list)} items")

                return {
                    "embeddings": embeddings_list,
                    "total_vectors": len(embeddings_list),
                    "vector_dim": embeddings.shape[1] if len(embeddings.shape) > 1 else None,
                    "filename": file.filename,
                    "image_size": image.size,
                    "message": f"Successfully processed image {file.filename}"
                }

            finally:
                # Clean up temporary file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except Exception as e:
            raise Exception(f"Failed to process uploaded image: {str(e)}")
