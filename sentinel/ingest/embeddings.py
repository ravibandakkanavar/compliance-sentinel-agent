"""Text embedders. Both produce vectors of `Settings.embedding_dim` length."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from sentinel.config import Settings


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Local ONNX embedding model. Downloads the model on first use."""

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


class HashEmbedder:
    """Feature-hashed bag of words. No model download; used in tests and offline runs.

    Retrieval quality is far below a real embedding model, so the hybrid
    search's keyword half carries most of the weight when this is selected.
    """

    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "hash":
        return HashEmbedder(settings.embedding_dim)
    if settings.embedder == "fastembed":
        return FastEmbedEmbedder(settings.embedding_model)
    raise ValueError(f"Unknown embedder: {settings.embedder!r}")
