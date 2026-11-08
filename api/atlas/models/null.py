"""Null-object LanguageModel for ATLAS_EMBEDDINGS_ONLY mode: no network, nothing leaves the
machine. Returns exactly the 'enrichment failed' values the pipeline already handles, so
summaries / topics / link reasons / cluster labels simply stay empty."""

from __future__ import annotations

from typing import Sequence

from atlas.models.prompts import empty_summary
from atlas.types import (
    ClusterLabel,
    ClusterSample,
    LinkEvidence,
    LinkReason,
    NoteSummary,
    ParsedNote,
    TopicMention,
)


class EmbeddingsOnlyLanguageModel:
    """Implements atlas.ports.LanguageModel without calling any model."""

    def summarize(self, note: ParsedNote) -> NoteSummary:
        return empty_summary(note)

    def extract_topics(self, note: ParsedNote) -> list[TopicMention]:
        return []

    def explain_links(self, pairs: Sequence[LinkEvidence]) -> list[LinkReason]:
        return []

    def label_clusters(self, samples: Sequence[ClusterSample]) -> list[ClusterLabel]:
        return []
