from __future__ import annotations

from typing import Sequence

from atlas.types import DocumentId, EmbeddedChunk, Neighbor, ScoredPair


def match_chunks(source: Sequence[EmbeddedChunk], neighbors: Sequence[Neighbor]) -> list[Neighbor]:
    """Fill Neighbor.best_match with the highest-cosine (source chunk, neighbour chunk) pair.
    Neighbours with no chunks keep best_match=None. Order preserved."""
    raise NotImplementedError


def score_links(
    candidates: Sequence[Neighbor],
    threshold: float,
    k: int,
    *,
    source: DocumentId,
) -> list[ScoredPair]:
    """Combined score = 0.5 * doc_score + 0.5 * best_match.score (doc_score alone when
    best_match is None). Keep score >= threshold, sort desc (ties by neighbour id), take k.
    Build DocumentPair.of(source, neighbour) and orient evidence/passages to (a, b).
    Candidates without best_match are dropped (a SemanticLink needs evidence).

    `source` is keyword-only and added to the PRD signature: a ScoredPair needs both ids."""
    raise NotImplementedError
