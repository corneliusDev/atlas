"""Read-time [[wikilink]] resolution (PRD Output 1 rule: links are stored by target name).

A target resolves to a document of the same vault when its normalised name equals, in order
of priority: the document path without its .md/.markdown suffix ("folder/note"), the file stem
("note"), or the document title. Ties break on the lexicographically smallest path, so the
answer is deterministic. Anything else is a ghost node keyed by its normalised name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

from atlas.types import MARKDOWN_SUFFIXES, DocumentId


def normalize_name(name: str) -> str:
    """lower(trim(name)) with internal whitespace collapsed and a trailing .md dropped."""
    s = " ".join(name.strip().lower().split())
    p = PurePosixPath(s)
    if p.suffix in MARKDOWN_SUFFIXES and p.stem:
        s = s[: -len(p.suffix)]
    return s


@dataclass(frozen=True)
class DocKey:
    id: DocumentId
    path: str
    title: str


class WikiResolver:
    def __init__(self, docs: Iterable[DocKey]) -> None:
        self._by_path: dict[str, DocKey] = {}
        self._by_stem: dict[str, DocKey] = {}
        self._by_title: dict[str, DocKey] = {}
        for d in sorted(docs, key=lambda d: d.path):  # first (smallest path) wins ties
            p = PurePosixPath(d.path)
            no_suffix = str(p.with_suffix("")) if p.suffix.lower() in MARKDOWN_SUFFIXES else d.path
            self._by_path.setdefault(normalize_name(no_suffix), d)
            self._by_stem.setdefault(normalize_name(p.stem), d)
            if d.title.strip():
                self._by_title.setdefault(normalize_name(d.title), d)

    def resolve(self, target_name: str) -> DocKey | None:
        key = normalize_name(target_name)
        if not key:
            return None
        return self._by_path.get(key) or self._by_stem.get(key) or self._by_title.get(key)
