"""
Embedding engine for semantic code search.
Lazy-loaded: only initialized when user enables embeddings.
"""

import struct
import time
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("embedding_engine")

# Lazy-loaded modules
_fastembed = None
_model = None
_model_name = "BAAI/bge-small-en-v1.5"  # 384 dimensions, fast, good quality
_model_loaded = False

# Status tracking
_embedding_status = {
    "enabled": False,
    "loading": False,
    "total_symbols": 0,
    "embedded_count": 0,
    "current_file": None,
    "error": None,
    "model_name": _model_name,
    "dimensions": 384,
}


def _load_model():
    """Load the embedding model (lazy, one-time)."""
    global _fastembed, _model, _model_loaded, _embedding_status

    if _model_loaded:
        return True

    _embedding_status["loading"] = True
    log.info("[embedding] Loading model %s...", _model_name)

    try:
        from fastembed import TextEmbedding
        _fastembed = TextEmbedding(model_name=_model_name)
        _model = _fastembed
        _model_loaded = True
        _embedding_status["loading"] = False
        log.info("[embedding] Model loaded successfully")
        return True
    except Exception as e:
        _embedding_status["loading"] = False
        _embedding_status["error"] = str(e)
        log.error("[embedding] Failed to load model: %s", e)
        return False


def get_status() -> dict:
    """Get current embedding status."""
    return _embedding_status.copy()


def encode_text(text: str) -> Optional[bytes]:
    """Encode text to vector blob (float32[384])."""
    if not _model_loaded:
        if not _load_model():
            return None

    try:
        # fastembed returns a generator, consume it
        embeddings = list(_model.embed([text]))
        if embeddings and len(embeddings) > 0:
            vec = embeddings[0]
            # Convert to bytes (float32)
            return struct.pack(f'{len(vec)}f', *vec)
    except Exception as e:
        log.error("[embedding] Encode failed: %s", e)
    return None


def encode_batch(texts: list[str]) -> list[Optional[bytes]]:
    """Encode multiple texts to vector blobs."""
    if not _model_loaded:
        if not _load_model():
            return [None] * len(texts)

    try:
        embeddings = list(_model.embed(texts))
        results = []
        for vec in embeddings:
            results.append(struct.pack(f'{len(vec)}f', *vec))
        return results
    except Exception as e:
        log.error("[embedding] Batch encode failed: %s", e)
        return [None] * len(texts)


def decode_vector(blob: bytes) -> list[float]:
    """Decode vector blob to float list."""
    if not blob:
        return []
    n = len(blob) // 4  # float32 = 4 bytes
    return list(struct.unpack(f'{n}f', blob))


def cosine_distance(vec_a: bytes, vec_b: bytes) -> float:
    """Compute cosine distance between two vector blobs."""
    import math

    a = decode_vector(vec_a)
    b = decode_vector(vec_b)

    if len(a) != len(b) or len(a) == 0:
        return float('inf')

    # Cosine similarity
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 1.0

    similarity = dot / (norm_a * norm_b)
    return 1.0 - similarity  # distance = 1 - similarity


def update_status(**kwargs):
    """Update embedding status."""
    _embedding_status.update(kwargs)
