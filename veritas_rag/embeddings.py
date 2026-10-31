import os
import math
import hashlib
import re
from typing import List

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from veritas_rag.config import config


class EmbeddingService:
    """Keeps document and query vectors in one explicit embedding space."""

    def __init__(self):
        self._client = None
        self._api_key = config.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.vector_dim = config.gemini_embedding_dimensions
        self.current_model_name = "local-hash-projection"
        if self._api_key:
            self.configure_key(self._api_key)

    def configure_key(self, api_key: str):
        self._api_key = api_key
        if not self._api_key:
            self._client = None
            self.vector_dim = 128
            self.current_model_name = "local-hash-projection"
            return
        try:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
            self.vector_dim = config.gemini_embedding_dimensions
            self.current_model_name = config.embedding_model
        except Exception as exc:
            self._client = None
            raise RuntimeError(f"Could not initialize Gemini embedding client: {exc}") from exc

    def _provider_contents(self, texts: List[str], task_type: str) -> List[str]:
        # Gemini Embedding 2 has no task_type parameter; its task instruction belongs
        # in the text. gemini-embedding-001 uses the structured task_type configuration.
        if "embedding-2" in config.embedding_model:
            instruction = "task: search query" if task_type == "RETRIEVAL_QUERY" else "task: search document"
            return [f"{instruction} | text: {text}" for text in texts]
        return texts

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _gemini_embed_batch(self, texts: List[str], task_type: str) -> List[List[float]]:
        if not self._client:
            raise RuntimeError("Gemini embedding client is not configured.")
        from google.genai import types

        kwargs = {"output_dimensionality": config.gemini_embedding_dimensions}
        if "embedding-2" not in config.embedding_model:
            kwargs["task_type"] = task_type
        response = self._client.models.embed_content(
            model=config.embedding_model,
            contents=self._provider_contents(texts, task_type),
            config=types.EmbedContentConfig(**kwargs),
        )
        if not response.embeddings or len(response.embeddings) != len(texts):
            raise RuntimeError(
                f"Embedding provider returned {len(response.embeddings or [])} vectors for {len(texts)} inputs."
            )
        vectors = [self._normalize(list(item.values)) for item in response.embeddings]
        dimensions = {len(vector) for vector in vectors}
        if dimensions != {config.gemini_embedding_dimensions}:
            raise RuntimeError(f"Embedding provider returned inconsistent dimensions: {sorted(dimensions)}")
        return vectors

    def get_embedding(self, text: str) -> List[float]:
        if self._api_key:
            if not self._client:
                self.configure_key(self._api_key)
            # Do not fall back to a different vector space after a transient API error.
            vectors = self._gemini_embed_batch([text], "RETRIEVAL_QUERY")
            self.vector_dim = len(vectors[0])
            self.current_model_name = config.embedding_model
            return vectors[0]

        self.vector_dim = 128
        self.current_model_name = "local-hash-projection"
        return self._local_semantic_embedding(text)

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if not self._api_key:
            self.vector_dim = 128
            self.current_model_name = "local-hash-projection"
            return [self._local_semantic_embedding(text) for text in texts]

        if not self._client:
            self.configure_key(self._api_key)

        vectors: List[List[float]] = []
        # Online embedContent calls are intentionally kept below the 100-item batch size.
        for offset in range(0, len(texts), 100):
            batch = texts[offset:offset + 100]
            vectors.extend(self._gemini_embed_batch(batch, "RETRIEVAL_DOCUMENT"))

        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1 or len(vectors) != len(texts):
            raise RuntimeError("Embedding batch is incomplete or contains mixed dimensions.")
        self.vector_dim = len(vectors[0])
        self.current_model_name = config.embedding_model
        return vectors

    def _normalize(self, vec: List[float]) -> List[float]:
        norm = math.sqrt(sum(x * x for x in vec))
        if norm < 1e-9:
            return vec
        return [x / norm for x in vec]

    def _local_semantic_embedding(self, text: str, dim: int = 128) -> List[float]:
        """Deterministic local hash encoder for offline development only."""
        clean_text = text.lower().strip()
        words = re.findall(r"\b[a-z0-9_-]+\b", clean_text)
        vec = [0.0] * dim
        if not words:
            return vec

        for word in words:
            hashed = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx1 = hashed % dim
            idx2 = (hashed >> 16) % dim
            weight = math.log(1.0 + len(word))
            vec[idx1] += weight
            vec[idx2] += weight * 0.5

        for index in range(len(clean_text) - 2):
            shingle = clean_text[index:index + 3]
            hashed = int(hashlib.sha256(shingle.encode("utf-8")).hexdigest(), 16)
            vec[hashed % dim] += 0.25

        return self._normalize(vec)


embedding_service = EmbeddingService()
