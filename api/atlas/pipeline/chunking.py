from __future__ import annotations

import math
import re
from dataclasses import dataclass

from atlas.types import Chunk, ParsedNote

TOKENS_PER_WORD = 1.3
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class _Section:
    heading_path: tuple[str, ...]
    text: str  # heading line (as plain text) + content, stripped

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def estimate_tokens(text: str) -> int:
    """Token approximation used everywhere in the pipeline: whitespace words * 1.3."""
    return math.ceil(len(_WORD_RE.findall(text)) * TOKENS_PER_WORD)


def chunk(note: ParsedNote, max_tokens: int = 500, overlap: int = 50) -> list[Chunk]:
    """Split note.body_text along headings into ~max_tokens chunks with ~overlap tokens of
    overlap (IX-2). Token count is approximated as whitespace words * 1.3 (no tokenizer
    dependency). Each chunk keeps its heading_path. Empty notes -> one chunk with the title.
    Deterministic: same note -> same chunks.

    Algorithm: (1) split body_text into sections at ATX headings, each with its heading path;
    (2) greedily pack consecutive small sections into one chunk while it stays <= max_tokens
    (the chunk's heading_path is the common prefix of the packed sections' paths);
    (3) a section larger than max_tokens is windowed by words with ``overlap`` tokens shared
    between consecutive windows, keeping the original whitespace of each window."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    overlap = max(0, min(overlap, max_tokens // 2))
    sections = _carry_bare_headings([s for s in _sections(note.body_text) if s.text])
    if not sections:
        return [Chunk(ordinal=0, heading_path=(), text=note.title)]

    pieces: list[tuple[tuple[str, ...], str]] = []
    pack: list[_Section] = []
    pack_tokens = 0

    def flush() -> None:
        nonlocal pack, pack_tokens
        if pack:
            pieces.append((_common_prefix([s.heading_path for s in pack]), "\n\n".join(s.text for s in pack)))
        pack, pack_tokens = [], 0

    for section in sections:
        t = section.tokens
        if t > max_tokens:
            flush()
            pieces.extend((section.heading_path, w) for w in _windows(section.text, max_tokens, overlap))
            continue
        if pack and pack_tokens + t > max_tokens:
            flush()
        pack.append(section)
        pack_tokens += t
    flush()

    return [Chunk(ordinal=i, heading_path=path, text=text) for i, (path, text) in enumerate(pieces)]


def _sections(body_text: str) -> list[_Section]:
    out: list[_Section] = []
    stack: list[tuple[int, str]] = []  # (level, text)
    current: list[str] = []

    def emit() -> None:
        text = "\n".join(current).strip()
        out.append(_Section(heading_path=tuple(t for _, t in stack), text=text))

    for line in body_text.split("\n"):
        m = _ATX_RE.match(line)
        if m is None:
            current.append(line)
            continue
        emit()
        level, heading = len(m.group(1)), m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        if heading:
            stack.append((level, heading))
        current = [heading] if heading else []
    emit()
    return out


def _carry_bare_headings(sections: list[_Section]) -> list[_Section]:
    """A section that is only its heading line (e.g. an H1 title directly followed by an H2)
    is prepended to the next section instead of widening the packed chunk's heading_path."""
    out: list[_Section] = []
    carry: list[str] = []
    for s in sections:
        bare = bool(s.heading_path) and s.text == s.heading_path[-1]
        if bare:
            carry.append(s.text)
            continue
        if carry:
            s = _Section(heading_path=s.heading_path, text="\n\n".join([*carry, s.text]))
            carry = []
        out.append(s)
    if carry:  # trailing bare headings: keep them as their own (tiny) section
        out.append(_Section(heading_path=sections[-1].heading_path, text="\n\n".join(carry)))
    return out


def _common_prefix(paths: list[tuple[str, ...]]) -> tuple[str, ...]:
    prefix = paths[0]
    for p in paths[1:]:
        n = 0
        while n < len(prefix) and n < len(p) and prefix[n] == p[n]:
            n += 1
        prefix = prefix[:n]
    return prefix


def _windows(text: str, max_tokens: int, overlap: int) -> list[str]:
    spans = [m.span() for m in _WORD_RE.finditer(text)]
    size = max(1, math.floor(max_tokens / TOKENS_PER_WORD))
    shared = min(size - 1, math.floor(overlap / TOKENS_PER_WORD))
    step = max(1, size - shared)
    out: list[str] = []
    start = 0
    while start < len(spans):
        end = min(start + size, len(spans))
        out.append(text[spans[start][0] : spans[end - 1][1]])
        if end == len(spans):
            break
        start += step
    return out
