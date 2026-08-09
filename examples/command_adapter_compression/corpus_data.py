"""Identity-bound access to the committed compression corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path

CORPUS_PATH = Path(__file__).with_name("corpus.txt")
CORPUS_BYTE_COUNT = 145_258
CORPUS_SHA256 = "b23ded0b042d8ccf288f3b4a255becec15c78f039b360d6a4529af24815d65ca"
CORPUS_PROVENANCE = "project-authored structured RDE Core workload text; no third-party data"


def load_corpus() -> bytes:
    """Return the exact committed corpus after verifying its identity."""

    payload = CORPUS_PATH.read_bytes()
    if len(payload) != CORPUS_BYTE_COUNT:
        raise RuntimeError("Committed compression corpus byte count changed.")
    if hashlib.sha256(payload).hexdigest() != CORPUS_SHA256:
        raise RuntimeError("Committed compression corpus SHA-256 changed.")
    return payload
