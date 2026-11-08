from __future__ import annotations

from atlas.types import ParsedNote, VaultPath


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
    raise NotImplementedError
