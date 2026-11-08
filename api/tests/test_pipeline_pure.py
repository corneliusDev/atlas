"""Unit tests for the pipeline's pure functions (plain asserts, no mocks)."""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import numpy as np

from atlas.pipeline import chunk, cluster, match_chunks, nearest_cluster, parse_markdown, score_links
from atlas.pipeline.chunking import estimate_tokens
from atlas.pipeline.clustering import CLUSTER_PALETTE
from atlas.testing.fakes import fake_embedding
from atlas.types import (
    CandidateChunk,
    ChunkId,
    ClusterCentroid,
    ClusterId,
    DocumentId,
    DocumentPair,
    DocumentVector,
    EmbeddedChunk,
    Embedding,
    Neighbor,
    VaultPath,
    WikiLinkRef,
)

VAULT = Path(__file__).resolve().parents[2] / "samples" / "vault"


def note_at(rel: str) -> tuple[VaultPath, str]:
    return VaultPath(rel), (VAULT / rel).read_text(encoding="utf-8")


# ---- parse_markdown ----------------------------------------------------------------------
def test_parse_sample_note_with_frontmatter_code_and_tags() -> None:
    path, raw = note_at("papers/ml/transformers/Attention Is All You Need.md")
    n = parse_markdown(path, raw)
    assert n.title == "Attention Is All You Need"
    assert n.frontmatter["year"] == 2017
    assert n.tags == ("attention", "deep-learning", "ml", "paper", "transformers")
    assert [w.target_name for w in n.wikilinks] == ["BERT", "Scaling Laws for Neural Language Models"]
    assert [(h.level, h.text) for h in n.headings] == [
        (1, "Attention Is All You Need"),
        (2, "Key ideas"),
        (2, "Why it matters"),
    ]
    assert "def attention" not in n.body_text  # fenced code stripped
    assert "def attention" in n.body
    assert "[[" not in n.body_text and "Everything in BERT and" in n.body_text
    assert len(n.content_hash) == 64


def test_parse_dates_become_iso_strings_and_frontmatter_is_json() -> None:
    path, raw = note_at("cooking/recipes/Pasteis de Nata.md")
    n = parse_markdown(path, raw)
    assert n.frontmatter["created"] == "2026-10-01"
    json.dumps(n.frontmatter)
    assert n.tags == ("baking", "cooking", "dessert", "portuguese")


def test_parse_alias_and_anchor_wikilinks_from_samples() -> None:
    path, raw = note_at("research/onboarding/Jobs To Be Done.md")
    n = parse_markdown(path, raw)
    assert WikiLinkRef(target_name="Interview Notes - Marcus", alias="Marcus's interview") in n.wikilinks
    assert "Marcus's interview" in n.body_text

    path, raw = note_at("research/onboarding/Interview Notes - Priya.md")
    n = parse_markdown(path, raw)
    assert WikiLinkRef(target_name="Onboarding Friction Themes", anchor="4. No clear next step") in n.wikilinks


def test_parse_ghost_link_targets_are_kept() -> None:
    path, raw = note_at("Welcome.md")
    n = parse_markdown(path, raw)
    assert "Competitor Teardown Q3" in {w.target_name for w in n.wikilinks}
    assert n.title == "Welcome"


def test_parse_every_sample_note_without_error() -> None:
    count = 0
    for f in sorted(VAULT.rglob("*.md")):
        raw = f.read_bytes().decode("utf-8", errors="replace")
        n = parse_markdown(VaultPath(f.relative_to(VAULT).as_posix()), raw)
        assert n.title
        assert list(n.tags) == sorted(set(n.tags))
        count += 1
    assert count == 51  # 50 notes + the latin-1 one


def test_parse_wikilink_variants_embeds_and_code() -> None:
    raw = (
        "Intro [[Target]] and [[Other.md|shown]] and [[Deep#Sec|alias]] and [[Deep#Sec]] again.\n"
        "An embed ![[diagram.png]] and image ![alt](pic.png) and [[#Local heading]].\n"
        "Inline `[[NotALink]] #notatag` code.\n"
        "<!-- [[Hidden]] #hiddentag -->\n"
        "```\n[[InFence]] #fencetag\n```\n"
        "\n    [[Indented]] #indentedtag\n"
        "\nTags: #Alpha #nested/tag #123 http://x.com/#frag a#b #trail-\n"
    )
    n = parse_markdown(VaultPath("x.md"), raw)
    assert n.wikilinks == (
        WikiLinkRef(target_name="Target"),
        WikiLinkRef(target_name="Other", alias="shown"),
        WikiLinkRef(target_name="Deep", anchor="Sec", alias="alias"),
    )
    assert n.tags == ("alpha", "nested/tag", "trail")
    assert "diagram" not in n.body_text and "pic.png" not in n.body_text
    assert "InFence" not in n.body_text and "Indented" not in n.body_text and "Hidden" not in n.body_text
    assert "shown" in n.body_text and "Local heading" in n.body_text
    assert n.title == "x"


def test_parse_malformed_frontmatter_is_lenient() -> None:
    raw = "---\ntitle: [unclosed\n: : :\n---\n# Real Title\n\nBody #tag\n"
    n = parse_markdown(VaultPath("bad.md"), raw)
    assert n.frontmatter == {}
    assert n.title == "Real Title"
    assert n.tags == ("tag",)


def test_parse_frontmatter_string_tags_and_title_precedence() -> None:
    raw = "---\ntitle: From FM\ntags: 'One, #two three'\n---\n# H1 Title\n"
    n = parse_markdown(VaultPath("t.md"), raw)
    assert n.title == "From FM"
    assert n.tags == ("one", "three", "two")


def test_parse_heading_is_not_a_tag_and_empty_file() -> None:
    n = parse_markdown(VaultPath("dir/Empty Note.md"), "")
    assert n.title == "Empty Note" and n.body_text == "" and n.tags == () and n.headings == ()
    n = parse_markdown(VaultPath("h.md"), "# Heading\n## Sub\n")
    assert n.tags == ()


# ---- chunk -------------------------------------------------------------------------------
def test_chunk_small_sample_note_is_one_chunk_with_heading_path() -> None:
    path, raw = note_at("cooking/recipes/Pasteis de Nata.md")
    chunks = chunk(parse_markdown(path, raw))
    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert chunks[0].heading_path == ("Pasteis de Nata",)
    assert "Roll puff pastry" in chunks[0].text


def test_chunk_splits_on_headings_and_keeps_paths() -> None:
    body = (
        "# Doc\n\n## Pricing\n\n" + "price " * 300 + "\n\n### Tiers\n\n" + "tier " * 300
        + "\n\n## Other\n\n" + "other " * 200 + "\n\n## A\n\nsmall a\n\n## B\n\nsmall b\n"
    )
    chunks = chunk(parse_markdown(VaultPath("p.md"), body), max_tokens=500, overlap=50)
    assert [c.heading_path for c in chunks] == [
        ("Doc", "Pricing"),  # the bare "Doc" title line is carried into the first section
        ("Doc", "Pricing", "Tiers"),
        ("Doc",),  # Other + small A + small B packed; heading_path = their common prefix
    ]
    assert chunks[0].text.startswith("Doc\n\nPricing")
    assert "small a" in chunks[2].text and "small b" in chunks[2].text
    assert [c.ordinal for c in chunks] == [0, 1, 2]
    assert all(estimate_tokens(c.text) <= 500 for c in chunks)


def test_chunk_long_section_is_windowed_with_overlap() -> None:
    words = [f"w{i}" for i in range(1000)]
    chunks = chunk(parse_markdown(VaultPath("long.md"), " ".join(words)), max_tokens=500, overlap=50)
    size = math.floor(500 / 1.3)
    shared = math.floor(50 / 1.3)
    assert len(chunks) == math.ceil((1000 - shared) / (size - shared))
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert len(first) == size
    assert first[-shared:] == second[:shared]
    assert chunks[-1].text.split()[-1] == "w999"
    assert all(c.heading_path == () for c in chunks)


def test_chunk_empty_note_yields_title_chunk_and_is_deterministic() -> None:
    n = parse_markdown(VaultPath("Lonely.md"), "---\ntags: [a]\n---\n")
    assert [(c.ordinal, c.heading_path, c.text) for c in chunk(n)] == [(0, (), "Lonely")]
    path, raw = note_at("travel/japan/Tokyo Itinerary.md")
    note = parse_markdown(path, raw)
    assert chunk(note) == chunk(note)


# ---- match_chunks / score_links ------------------------------------------------------------
def _ec(doc: DocumentId, i: int, text: str) -> EmbeddedChunk:
    return EmbeddedChunk(id=ChunkId(uuid.uuid4()), ordinal=i, heading_path=(), text=text, embedding=fake_embedding(text))


def _cand(text: str) -> CandidateChunk:
    return CandidateChunk(id=ChunkId(uuid.uuid4()), heading_path=("H",), text=text, embedding=fake_embedding(text))


def test_match_chunks_picks_best_pair_and_preserves_order() -> None:
    src_doc = DocumentId(uuid.uuid4())
    source = [_ec(src_doc, 0, "alpha"), _ec(src_doc, 1, "shared passage")]
    n1 = Neighbor(document_id=DocumentId(uuid.uuid4()), path=VaultPath("a.md"), title="A", doc_score=0.4,
                  chunks=(_cand("zzz"), _cand("shared passage")))
    n2 = Neighbor(document_id=DocumentId(uuid.uuid4()), path=VaultPath("b.md"), title="B", doc_score=0.9)
    out = match_chunks(source, [n1, n2])
    assert [n.document_id for n in out] == [n1.document_id, n2.document_id]
    m = out[0].best_match
    assert m is not None
    assert m.source_chunk == source[1].id and m.target_chunk == n1.chunks[1].id
    assert abs(m.score - 1.0) < 1e-9 and m.target_text == "shared passage"
    assert out[1].best_match is None


def test_score_links_threshold_topk_order_and_orientation() -> None:
    source = DocumentId(uuid.UUID(int=500))
    src_chunk = _ec(source, 0, "s")

    def neighbor(n: int, doc_score: float, text: str) -> Neighbor:
        return Neighbor(document_id=DocumentId(uuid.UUID(int=n)), path=VaultPath(f"{n}.md"), title=str(n),
                        doc_score=doc_score, chunks=(_cand(text),))

    low = neighbor(100, 0.9, "s")  # a < source
    high = neighbor(900, 0.9, "s")  # source < b
    weak = neighbor(901, 0.2, "other")
    no_chunks = Neighbor(document_id=DocumentId(uuid.UUID(int=902)), path=VaultPath("x.md"), title="x", doc_score=1.0)
    matched = match_chunks([src_chunk], [weak, high, low, no_chunks])
    pairs = score_links(matched, threshold=0.55, k=8, source=source)

    assert [p.neighbor for p in pairs] == [low.document_id, high.document_id]  # equal scores: by id
    assert all(abs(p.score - 0.95) < 1e-9 for p in pairs)
    p_low, p_high = pairs
    assert p_low.pair == DocumentPair.of(source, low.document_id) and p_low.pair.b == source
    assert p_low.evidence == (low.chunks[0].id, src_chunk.id)
    assert p_high.pair.a == source and p_high.evidence == (src_chunk.id, high.chunks[0].id)
    assert score_links(matched, threshold=0.55, k=1, source=source) == pairs[:1]
    assert score_links(matched, threshold=0.99, k=8, source=source) == []


def test_score_links_ignores_self() -> None:
    source = DocumentId(uuid.uuid4())
    me = Neighbor(document_id=source, path=VaultPath("me.md"), title="me", doc_score=1.0, chunks=(_cand("s"),))
    assert score_links(match_chunks([_ec(source, 0, "s")], [me]), threshold=0.0, k=8, source=source) == []


# ---- nearest_cluster / cluster ---------------------------------------------------------------
def _unit(v: list[float]) -> Embedding:
    a = np.asarray(v, dtype=np.float64)
    return tuple(float(x) for x in a / np.linalg.norm(a))


def test_nearest_cluster() -> None:
    c1 = ClusterCentroid(cluster_id=ClusterId(uuid.UUID(int=1)), centroid=_unit([1, 0, 0]), color="#000000")
    c2 = ClusterCentroid(cluster_id=ClusterId(uuid.UUID(int=2)), centroid=_unit([0, 1, 0]), color="#000000")
    assert nearest_cluster(_unit([0.9, 0.1, 0]), [c1, c2]) == c1.cluster_id
    assert nearest_cluster(_unit([0.1, 0.9, 0]), [c2, c1]) == c2.cluster_id
    assert nearest_cluster(_unit([1, 1, 0]), [c2, c1]) == c1.cluster_id  # tie -> lowest id
    assert nearest_cluster(_unit([0, 0, 1]), [c1, c2], min_similarity=0.5) is None
    assert nearest_cluster(_unit([1, 0, 0]), []) is None


def _blobs(groups: int, per: int, dim: int = 32, seed: int = 7) -> list[DocumentVector]:
    rng = np.random.default_rng(seed)
    out: list[DocumentVector] = []
    n = 0
    for g in range(groups):
        base = np.zeros(dim)
        base[g] = 1.0
        for _ in range(per):
            v = base + rng.normal(0, 0.05, dim)
            out.append(DocumentVector(document_id=DocumentId(uuid.UUID(int=n + 1)), path=VaultPath(f"g{g}/{n}.md"),
                                      title=f"g{g}", summary=None, vector=tuple(float(x) for x in v)))
            n += 1
    return out


def _groups_of(assignment_members: object, vectors: list[DocumentVector]) -> dict[str, set[ClusterId | None]]:
    by_doc = {m.document_id: m.cluster_id for m in assignment_members}  # type: ignore[attr-defined]
    out: dict[str, set[ClusterId | None]] = {}
    for v in vectors:
        out.setdefault(v.title, set()).add(by_doc[v.document_id])
    return out


def test_cluster_hdbscan_finds_blobs_deterministically() -> None:
    vectors = _blobs(groups=3, per=10)
    a = cluster(vectors)
    assert len(a.centroids) == 3
    groups = _groups_of(a.members, vectors)
    assert all(len(ids) == 1 and None not in ids for ids in groups.values())
    assert len({next(iter(ids)) for ids in groups.values()}) == 3
    assert [c.color for c in a.centroids] == list(CLUSTER_PALETTE[:3])
    assert cluster(list(reversed(vectors))) == a  # order-independent, stable ids


def test_cluster_tiny_vault_uses_kmeans() -> None:
    vectors = _blobs(groups=2, per=3)
    a = cluster(vectors)
    assert len(a.centroids) == 2
    assert all(len(ids) == 1 for ids in _groups_of(a.members, vectors).values())
    assert all(m.cluster_id is not None for m in a.members)


def test_cluster_fewer_than_three_docs_has_no_clusters() -> None:
    vectors = _blobs(groups=1, per=2)
    a = cluster(vectors)
    assert a.centroids == () and [m.cluster_id for m in a.members] == [None, None]
    assert cluster([]).members == ()


def test_cluster_identical_vectors_do_not_crash() -> None:
    v = _unit([1.0] * 8)
    vectors = [DocumentVector(document_id=DocumentId(uuid.UUID(int=i + 1)), path=VaultPath(f"{i}.md"), title="t",
                              summary=None, vector=v) for i in range(5)]
    a = cluster(vectors)
    assert len(a.centroids) == 1 and all(m.cluster_id == a.centroids[0].cluster_id for m in a.members)
