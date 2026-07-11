from __future__ import annotations

import hashlib
import math
import re

from langchain_openai import OpenAIEmbeddings

from app.cache.service import cache
from app.core.config import get_settings

settings = get_settings()


class EmbeddingService:
    def __init__(self):
        self.dimensions = settings.embedding_dimensions
        self._remote = (
            OpenAIEmbeddings(
                model=settings.zhipu_embedding_model,
                api_key=settings.zhipu_api_key,
                base_url=settings.zhipu_base_url,
                dimensions=self.dimensions,
                chunk_size=64,
            )
            if settings.zhipu_api_key
            else None
        )

    def _cache_key(self, text: str) -> str:
        digest = cache.digest(settings.zhipu_embedding_model, self.dimensions, text)
        return f"embedding:{digest}"

    def _hash_embedding(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower()) or [text]
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        missing_indices: list[int] = []
        missing_texts: list[str] = []

        for index, text in enumerate(texts):
            cached = cache.get_json(self._cache_key(text))
            if cached is None:
                missing_indices.append(index)
                missing_texts.append(text)
            else:
                results[index] = cached

        if missing_texts:
            generated = (
                self._remote.embed_documents(missing_texts)
                if self._remote
                else [self._hash_embedding(text) for text in missing_texts]
            )
            for index, text, vector in zip(
                missing_indices, missing_texts, generated, strict=True
            ):
                results[index] = vector
                cache.set_json(
                    self._cache_key(text), vector, settings.cache_embedding_ttl
                )

        return [vector for vector in results if vector is not None]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
