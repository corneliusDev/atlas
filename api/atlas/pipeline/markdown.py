from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime, time
from pathlib import PurePosixPath
from typing import Any

import frontmatter
from markdown_it import MarkdownIt

from atlas.types import ContentHash, Heading, ParsedNote, VaultPath, WikiLinkRef

_MD = MarkdownIt("commonmark")

# A frontmatter block must start on the very first line.
_FM_RE = re.compile(r"\A---[ \t]*\r?\n")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1", re.DOTALL)
_WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
_IMAGE_RE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")
_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]+)\]\([^)\n]*\)")
# Obsidian-style tag: '#' not preceded by a word char, '/', '#', '&' or a quote-ish char, then
# letters/digits/_/-/'/'. Must contain at least one non-digit (so "#123" is not a tag).
_TAG_RE = re.compile(r"(?<![\w/#&'\"`\]])#([\w][\w/-]*)")
_MD_SUFFIX_RE = re.compile(r"\.(md|markdown)$", re.IGNORECASE)


def parse_markdown(path: VaultPath, raw: str) -> ParsedNote:
    """Lenient Markdown parse (IX-1, SL-4, SL-5).

    - Split YAML frontmatter (python-frontmatter); malformed YAML -> {} and the whole file is body.
      Frontmatter values made JSON-compatible (dates -> ISO strings).
    - title: frontmatter `title` > first H1 > file stem.
    - tags: frontmatter `tags` (list or comma/space string) + inline `#tags` outside code;
      lowercased, '#' stripped, deduped, sorted. `#` headings are not tags.
    - wikilinks: [[Target]], [[Target|alias]], [[Target#Heading]], [[Target#Heading|alias]],
      ignoring ![[embeds]] and links inside code. target_name drops a trailing .md.
    - headings: ATX headings outside code blocks.
    - body_text: body with fenced/indented code blocks, images (![...](...), ![[...]]) and HTML
      comments removed; wikilinks replaced by their alias or target name.
    - content_hash: sha256 hex of raw.encode("utf-8"). NOTE: callers that have the file bytes
      should prefer hashing bytes; for UTF-8 input these are identical.
    """
    content_hash = ContentHash(hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest())
    text = raw.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    meta, body = _split_frontmatter(text)

    tokens = _MD.parse(body)
    lines = body.split("\n")
    code_lines: set[int] = set()
    headings: list[Heading] = []
    for i, tok in enumerate(tokens):
        if tok.type in ("fence", "code_block") and tok.map is not None:
            code_lines.update(range(tok.map[0], tok.map[1]))
        elif tok.type == "heading_open" and tok.map is not None and i + 1 < len(tokens):
            level = int(tok.tag[1:])
            heading_text = _plain_inline(tokens[i + 1].content)
            if heading_text:
                headings.append(Heading(level=level, text=heading_text, line=tok.map[0]))

    # Code blocks removed (kept as blank lines so line numbers stay put), comments removed.
    prose_lines = ["" if n in code_lines else line for n, line in enumerate(lines)]
    prose = _HTML_COMMENT_RE.sub("", "\n".join(prose_lines))
    no_inline_code = _INLINE_CODE_RE.sub(" ", prose)

    wikilinks = _extract_wikilinks(no_inline_code)
    tags = _frontmatter_tags(meta) | _inline_tags(_WIKILINK_RE.sub(" ", no_inline_code))

    title = _title(meta, headings, path)
    body_text = _body_text(prose)

    return ParsedNote(
        path=path,
        title=title,
        frontmatter=meta,
        tags=tuple(sorted(tags)),
        wikilinks=tuple(wikilinks),
        headings=tuple(headings),
        body=body,
        body_text=body_text,
        content_hash=content_hash,
    )


# ---- frontmatter -----------------------------------------------------------------------
def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not _FM_RE.match(text):
        return {}, text
    try:
        post = frontmatter.loads(text)
    except Exception:  # malformed YAML of any kind: lenient
        return {}, text
    meta = post.metadata
    if not isinstance(meta, dict):
        return {}, text
    clean = _jsonable(meta)
    assert isinstance(clean, dict)
    return clean, str(post.content)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [_jsonable(v) for v in items]
    return str(value)


def _frontmatter_tags(meta: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("tags", "tag"):
        raw = meta.get(key)
        if raw is None:
            continue
        items: list[Any]
        if isinstance(raw, str):
            items = re.split(r"[,\s]+", raw)
        elif isinstance(raw, list):
            items = raw
        else:
            items = [raw]
        for item in items:
            if item is None or isinstance(item, (dict, list)):
                continue
            tag = _normalise_tag(str(item))
            if tag:
                out.add(tag)
    return out


def _normalise_tag(raw: str) -> str:
    return raw.strip().lstrip("#").strip().lower()


# ---- inline syntax ----------------------------------------------------------------------
def _inline_tags(prose: str) -> set[str]:
    out: set[str] = set()
    for m in _TAG_RE.finditer(prose):
        tag = m.group(1).rstrip("/-")
        if tag and not tag.isdigit():
            out.add(tag.lower())
    return out


def _split_wikilink(inner: str) -> WikiLinkRef | None:
    inner = inner.replace("\\|", "|")
    target_part, _, alias = inner.partition("|")
    target_part, _, anchor = target_part.partition("#")
    target = _MD_SUFFIX_RE.sub("", target_part.strip()).strip()
    if not target:  # [[#Heading]] = link into the same note; not a graph edge
        return None
    return WikiLinkRef(
        target_name=target,
        anchor=anchor.strip() or None,
        alias=alias.strip() or None,
    )


def _extract_wikilinks(prose: str) -> list[WikiLinkRef]:
    seen: set[tuple[str, str | None]] = set()
    out: list[WikiLinkRef] = []
    for m in _WIKILINK_RE.finditer(prose):
        if m.group(1):  # ![[embed]]
            continue
        ref = _split_wikilink(m.group(2))
        if ref is None or (ref.target_name, ref.anchor) in seen:
            continue
        seen.add((ref.target_name, ref.anchor))
        out.append(ref)
    return out


def _wikilink_display(m: re.Match[str]) -> str:
    if m.group(1):
        return ""
    ref = _split_wikilink(m.group(2))
    if ref is None:
        inner = m.group(2).replace("\\|", "|")
        return (inner.partition("|")[2] or inner.lstrip("#")).strip()
    return ref.alias or ref.target_name


def _plain_inline(content: str) -> str:
    s = _IMAGE_RE.sub("", content)
    s = _WIKILINK_RE.sub(_wikilink_display, s)
    s = _MD_LINK_RE.sub(r"\1", s)
    s = _INLINE_CODE_RE.sub(r"\2", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    return " ".join(s.split())


def _title(meta: dict[str, Any], headings: list[Heading], path: VaultPath) -> str:
    fm_title = meta.get("title")
    if isinstance(fm_title, (str, int, float)) and str(fm_title).strip():
        return str(fm_title).strip()
    for h in headings:
        if h.level == 1:
            return h.text
    return PurePosixPath(path).stem


def _body_text(prose: str) -> str:
    s = _IMAGE_RE.sub("", prose)
    s = _WIKILINK_RE.sub(_wikilink_display, s)
    s = _MD_LINK_RE.sub(r"\1", s)
    s = _INLINE_CODE_RE.sub(r"\2", s)
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
