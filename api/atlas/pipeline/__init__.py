"""IngestPipeline + its pure functions (no I/O, no clock, no unseeded randomness).

Pure-function contracts (PRD Output 2), one module each:
    markdown.parse_markdown(path, raw) -> ParsedNote
    chunking.chunk(note, max_tokens=500, overlap=50) -> list[Chunk]
    scoring.match_chunks(source, neighbors) -> list[Neighbor]          (Wave 0 addition)
    scoring.score_links(candidates, threshold, k, source=...) -> list[ScoredPair]
    clustering.nearest_cluster(vector, centroids, min_similarity=...) -> ClusterId | None
    clustering.cluster(vectors) -> ClusterAssignment

The concrete IngestPipeline (implements atlas.ports.IngestPipeline) lives in
atlas/pipeline/ingest.py (track B).
"""

from atlas.pipeline.chunking import chunk
from atlas.pipeline.clustering import cluster, nearest_cluster
from atlas.pipeline.markdown import parse_markdown
from atlas.pipeline.scoring import match_chunks, score_links

__all__ = ["chunk", "cluster", "match_chunks", "nearest_cluster", "parse_markdown", "score_links"]
