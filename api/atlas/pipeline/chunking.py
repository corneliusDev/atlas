from __future__ import annotations

from atlas.types import Chunk, ParsedNote


def chunk(note: ParsedNote, max_tokens: int = 500, overlap: int = 50) -> list[Chunk]:
    """Split note.body_text along headings into ~max_tokens chunks with ~overlap tokens of
    overlap (IX-2). Token count is approximated as whitespace words * 1.3 (no tokenizer
    dependency). Each chunk keeps its heading_path. Empty notes -> one chunk with the title.
    Deterministic: same note -> same chunks."""
    raise NotImplementedError
