"""Track E pure read-side helpers: wikilink resolution, RRF fusion, snippets, graph assembly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from atlas.read.documents import FileRoots, strip_frontmatter
from atlas.read.graph import DocRow, GraphData, SemanticRow, WikiRow, build_graph, center_key, local_view
from atlas.read.search import _Ranked, collapse_to_documents, fuse, render_snippet
from atlas.read.wikilinks import DocKey, WikiResolver, normalize_name
from atlas.types import (
    DEFAULT_VAULT_ID,
    ChunkId,
    DocumentId,
    DocumentPair,
    GhostNode,
    GraphFilters,
    LinkVerdict,
    NodeKind,
    VaultPath,
)

A, B, C = sorted(DocumentId(uuid.uuid4()) for _ in range(3))
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def test_normalize_name() -> None:
    assert normalize_name("  Kyoto   Ryokan List ") == "kyoto ryokan list"
    assert normalize_name("Note.md") == "note"
    assert normalize_name(".md") == ".md"


def test_resolver_priority_path_then_stem_then_title() -> None:
    docs = [
        DocKey(id=A, path="projects/alpha.md", title="Roadmap"),
        DocKey(id=B, path="archive/alpha.md", title="Alpha (old)"),
        DocKey(id=C, path="roadmap.md", title="Something else"),
    ]
    r = WikiResolver(docs)
    assert r.resolve("projects/alpha") == docs[0]  # full path
    hit = r.resolve("Alpha")  # stem tie -> smallest path wins
    assert hit is not None and hit.id == B
    stem = r.resolve("roadmap")  # stem beats A's title "Roadmap"
    assert stem is not None and stem.id == C
    title = r.resolve("alpha (OLD)")
    assert title is not None and title.id == B
    assert r.resolve("Nope") is None and r.resolve("  ") is None


def test_rrf_fusion() -> None:
    c = [ChunkId(uuid.uuid4()) for _ in range(4)]
    kw = collapse_to_documents([(A, c[0]), (A, c[1]), (B, c[2])])
    assert kw[A].rank == 1 and kw[A].chunk == c[0] and kw[B].rank == 2
    sem = collapse_to_documents([(B, c[2]), (C, c[3])])
    fused = fuse(kw, sem, limit=10)
    assert [d for d, *_ in fused] == [B, A, C]  # B in both lists wins
    assert fused[0][1] == 1 / 62 + 1 / 61
    assert len(fuse(kw, sem, limit=1)) == 1
    assert fuse({}, {}, 5) == []
    assert isinstance(fused[0][2], _Ranked)


def test_render_snippet_escapes_then_marks() -> None:
    assert render_snippet("a <b> \x02churn\x03  &\n c") == "a &lt;b&gt; <mark>churn</mark> &amp; c"


def test_strip_frontmatter() -> None:
    assert strip_frontmatter("---\ntitle: x\n---\n\n# H\nbody") == "# H\nbody"
    assert strip_frontmatter("﻿---\na: 1\n...\nbody") == "body"
    assert strip_frontmatter("---\nunclosed\n# H") == "---\nunclosed\n# H"
    assert strip_frontmatter("# No fm\n---\n") == "# No fm\n---\n"


def test_file_roots_contain_paths(tmp_path: object) -> None:
    from pathlib import Path

    root = Path(str(tmp_path))
    roots = FileRoots.from_settings(vault_root=root / "vault", uploads_root=root / "up")
    assert roots.file_for(DEFAULT_VAULT_ID, "/elsewhere", "vault", "a/b.md") == (root / "vault" / "a" / "b.md").resolve()
    assert roots.file_for(DEFAULT_VAULT_ID, None, "upload", "a.md") == (root / "up" / str(DEFAULT_VAULT_ID) / "a.md").resolve()
    assert roots.file_for(DEFAULT_VAULT_ID, None, "vault", "../../etc/passwd") is None


def _doc(d: DocumentId, path: str, **kw: object) -> DocRow:
    base: dict[str, object] = dict(id=d, path=VaultPath(path), title=path.removesuffix(".md").title(), summary=None,
                                   tags=(), cluster_id=None, origin="vault", indexed_at=NOW)
    base.update(kw)
    return DocRow(**base)  # type: ignore[arg-type]


def test_confirmed_link_bypasses_min_score_and_ghost_layer_toggle() -> None:
    data = GraphData(
        docs=[_doc(A, "a.md"), _doc(B, "b.md"), _doc(C, "c.md")],
        semantic=[SemanticRow(pair=DocumentPair.of(A, B), score=0.3, reason=None),
                  SemanticRow(pair=DocumentPair.of(B, C), score=0.3, reason=None)],
        feedback={DocumentPair.of(A, B): LinkVerdict.CONFIRMED},
        wiki=[WikiRow(source=A, target_name="Missing Note", anchor=None), WikiRow(source=A, target_name="c", anchor="H")],
    )
    g = build_graph(data, GraphFilters(min_score=0.5))
    keys = {e.key for e in g.edges}
    assert f"semantic:{A}:{B}" in keys and f"semantic:{B}:{C}" not in keys
    assert "ghost:missing note" in {n.key for n in g.nodes}
    no_ghost = build_graph(data, GraphFilters(layers=frozenset({NodeKind.DOCUMENT})))
    assert not any(n.key.startswith("ghost:") for n in no_ghost.nodes)
    assert f"wiki:{A}:doc:{C}" in {e.key for e in no_ghost.edges}


def test_local_view_unknown_centre_and_ghost_key() -> None:
    data = GraphData(docs=[_doc(A, "a.md")])
    full = build_graph(data, GraphFilters())
    v = local_view(full, "doc:" + str(B), 2)
    assert v.nodes == () and v.center == f"doc:{B}"
    assert center_key(GhostNode(name="  Big Idea ")) == "ghost:big idea"
    v = local_view(full, f"doc:{A}", 1)
    assert [n.key for n in v.nodes] == [f"doc:{A}"] and v.nodes[0].degree == 0


def test_build_read_services_wires_every_read_port(tmp_path: object) -> None:
    from pathlib import Path

    from atlas.config import Settings
    from atlas.http.app import AppServices
    from atlas.read.db import connect_factory
    from atlas.read.wiring import build_read_services
    from atlas.testing.fakes import FakeEmbeddingModel

    root = Path(str(tmp_path))
    s = Settings(vault_root=root / "v", uploads_root=root / "u", ATLAS_EMBEDDINGS_ONLY=True)  # type: ignore[call-arg]
    read = build_read_services(s, connect_factory("postgresql://x@127.0.0.1:1/x"), FakeEmbeddingModel(), lambda: True)
    services = AppServices(**read.as_kwargs())
    assert services.search is read.search and services.uploads is not None
    assert services.uploads.root == root / "u" and read.health.llm_model is None
