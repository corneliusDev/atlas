from __future__ import annotations

from typing import Sequence

import numpy as np
import numpy.typing as npt

from atlas.types import ChunkMatch, DocumentId, DocumentPair, EmbeddedChunk, Embedding, Neighbor, ScoredPair

DOC_WEIGHT = 0.5
CHUNK_WEIGHT = 0.5


def _unit_rows(vectors: Sequence[Embedding]) -> npt.NDArray[np.float64]:
    m = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: npt.NDArray[np.float64] = m / norms
    return out


def match_chunks(source: Sequence[EmbeddedChunk], neighbors: Sequence[Neighbor]) -> list[Neighbor]:
    """Fill Neighbor.best_match with the highest-cosine (source chunk, neighbour chunk) pair.
    Neighbours with no chunks keep best_match=None. Order preserved.
    Ties go to the earliest source chunk, then the earliest neighbour chunk (deterministic)."""
    if not source:
        return [n.model_copy(update={"best_match": None}) for n in neighbors]
    src = _unit_rows([c.embedding for c in source])
    out: list[Neighbor] = []
    for n in neighbors:
        if not n.chunks:
            out.append(n.model_copy(update={"best_match": None}))
            continue
        tgt = _unit_rows([c.embedding for c in n.chunks])
        sims = src @ tgt.T
        i, j = np.unravel_index(int(np.argmax(sims)), sims.shape)
        s, t = source[int(i)], n.chunks[int(j)]
        match = ChunkMatch(
            source_chunk=s.id,
            target_chunk=t.id,
            score=float(sims[i, j]),
            source_text=s.text,
            target_text=t.text,
        )
        out.append(n.model_copy(update={"best_match": match}))
    return out


def combined_score(n: Neighbor) -> float:
    """0.5 * doc_score + 0.5 * best chunk score (doc_score alone without a match), in [0, 1]."""
    raw = n.doc_score if n.best_match is None else DOC_WEIGHT * n.doc_score + CHUNK_WEIGHT * n.best_match.score
    return max(0.0, min(1.0, raw))


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
    if k <= 0:
        return []
    best: dict[DocumentId, tuple[float, Neighbor]] = {}
    for n in candidates:
        if n.best_match is None or n.document_id == source:
            continue
        score = combined_score(n)
        if score < threshold:
            continue
        prev = best.get(n.document_id)
        if prev is None or score > prev[0]:
            best[n.document_id] = (score, n)
    ranked = sorted(best.values(), key=lambda sn: (-sn[0], str(sn[1].document_id)))[:k]
    out: list[ScoredPair] = []
    for score, n in ranked:
        m = n.best_match
        assert m is not None
        pair = DocumentPair.of(source, n.document_id)
        if pair.a == source:
            evidence, a_text, b_text = (m.source_chunk, m.target_chunk), m.source_text, m.target_text
        else:
            evidence, a_text, b_text = (m.target_chunk, m.source_chunk), m.target_text, m.source_text
        out.append(
            ScoredPair(
                pair=pair,
                neighbor=n.document_id,
                score=score,
                evidence=evidence,
                a_passage=a_text,
                b_passage=b_text,
            )
        )
    return out
