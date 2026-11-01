"""Face gallery: enrolled embeddings and cosine-similarity matching."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GalleryEntry:
    """A single enrolled face embedding."""

    resident_id: uuid.UUID
    embedding: tuple[float, ...]
    embedding_id: uuid.UUID | None = None
    model_name: str = "buffalo_l"
    label: str | None = None


@dataclass(frozen=True, slots=True)
class GalleryMatch:
    resident_id: uuid.UUID
    embedding_id: uuid.UUID | None
    similarity: float
    label: str | None = None


class FaceGallery:
    """Immutable, thread-safe gallery of enrolled face vectors.

    Vectors are L2-normalised once on construction, which turns cosine
    similarity into a single matrix-vector product per query.
    """

    def __init__(self, entries: Sequence[GalleryEntry] = ()) -> None:
        valid: list[GalleryEntry] = []
        vectors: list[NDArray[np.float32]] = []
        for entry in entries:
            vector = np.asarray(entry.embedding, dtype=np.float32)
            if vector.ndim != 1 or vector.size == 0:
                logger.warning("Skipping malformed embedding for resident %s", entry.resident_id)
                continue
            norm = float(np.linalg.norm(vector))
            if norm <= 0:
                continue
            valid.append(entry)
            vectors.append(vector / norm)
        self._entries: tuple[GalleryEntry, ...] = tuple(valid)
        self._matrix: NDArray[np.float32] | None = (
            np.vstack(vectors).astype(np.float32) if vectors else None
        )

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[GalleryEntry, ...]:
        return self._entries

    def match(self, embedding: Sequence[float], threshold: float) -> GalleryMatch | None:
        """Return the best match above ``threshold`` (cosine similarity)."""
        if self._matrix is None or not len(embedding):
            return None
        query = np.asarray(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if norm <= 0 or query.shape[0] != self._matrix.shape[1]:
            return None
        similarities = self._matrix @ (query / norm)
        best_index = int(np.argmax(similarities))
        best_score = float(similarities[best_index])
        if best_score < threshold:
            return None
        entry = self._entries[best_index]
        return GalleryMatch(
            resident_id=entry.resident_id,
            embedding_id=entry.embedding_id,
            similarity=best_score,
            label=entry.label,
        )

    def similarity(self, left: Sequence[float], right: Sequence[float]) -> float:
        """Cosine similarity between two vectors (helper for enrollment checks)."""
        a = np.asarray(left, dtype=np.float32)
        b = np.asarray(right, dtype=np.float32)
        if a.size == 0 or b.size == 0 or a.size != b.size:
            return 0.0
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(np.dot(a, b) / denom) if denom else 0.0

    def stats(self) -> dict[str, Any]:
        """Return gallery counters for the health endpoint."""
        return {
            "entries": len(self._entries),
            "dimension": int(self._matrix.shape[1]) if self._matrix is not None else 0,
            "residents": len({entry.resident_id for entry in self._entries}),
        }


@dataclass(slots=True)
class MutableGallery:
    """Thread-friendly wrapper allowing the manager to hot-swap the gallery."""

    _gallery: FaceGallery = field(default_factory=FaceGallery)

    def replace(self, gallery: FaceGallery) -> None:
        self._gallery = gallery

    def snapshot(self) -> FaceGallery:
        return self._gallery

    def __len__(self) -> int:
        return len(self._gallery)
