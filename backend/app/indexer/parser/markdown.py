"""Markdown document extractor.

Parses .md files into sections based on headings (H1, H2, H3). Each section
becomes a DOC node with its text content as the chunk source. This gives the
retrieval layer section-granularity access to READMEs, docs, and other
Markdown files in the repo.

Design:
- Headings split the document into sections; H1/H2/H3 mark section boundaries.
- Each section is emitted as a RawSymbol (kind=DOC) with a fqname derived from
  the file path and the heading slug.
- Sections form a hierarchy: H3 belongs to the preceding H2, which belongs to
  the preceding H1, via parent_fqname.
- The file itself is a DOC symbol wrapping the whole document.
- Code fences (```) are tracked so ``#`` inside code blocks is not mistaken for
  a heading.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from app.db.enums import NodeKind
from app.indexer.parser.python import module_fqname
from app.indexer.parser.types import FileExtract, RawSymbol


def _slugify(text: str) -> str:
    """Turn a heading into a URL-friendly slug for use in fqnames."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "section"


def extract_markdown(path: str, source: bytes) -> FileExtract:
    """Parse one .md file's bytes into a FileExtract with section symbols.

    Args:
        path: Repo-relative file path (e.g. "README.md", "docs/guide.md").
        source: UTF-8 encoded file contents.

    Returns:
        A FileExtract with one DOC symbol per heading section, plus a file-level
        DOC symbol for the whole document.
    """
    text = source.decode("utf-8", errors="replace")
    lines = text.split("\n")
    num_lines = len(lines)

    # Find heading boundaries, tracking fenced code blocks so we don't treat
    # `#` inside them as headings.
    in_code_block = False
    headings: list[tuple[int, int, str]] = []  # (0-based line, level, text)

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Toggle code fence tracking. Both ``` and ~~~ are common fence markers.
        if re.match(r"^(```|~~~)", stripped):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        # Match ATX headings: `# Title`, `## Title`, `### Title`
        # Also handles closing `#` markers like `## Title ##`.
        m = re.match(r"^(#{1,3})\s+(.+?)(?:\s+#+)?$", stripped)
        if m:
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            headings.append((i, level, heading_text))

    # Build symbols
    module = module_fqname(path)
    file_name = PurePosixPath(path).name

    symbols: list[RawSymbol] = []

    # File-level symbol — wraps the entire document.
    symbols.append(
        RawSymbol(
            kind=NodeKind.DOC,
            fqname=module,
            name=file_name,
            path=path,
            start_line=1,
            end_line=num_lines,
            docstring=_first_paragraph(text),
            source=text,
        )
    )

    # Section symbols — one per heading, with parent_fqname linking to the
    # containing section (or file) for CONTAINS edge creation.
    h1_parent: str = module  # most recent H1's fqname
    h2_parent: str = module  # most recent H2's fqname

    # Track used fqnames to handle duplicate slugs (e.g. two headings that
    # both slugify to "getting-started") — a real possibility in docs.
    used_fqnames: dict[str, int] = defaultdict(int)

    for idx, (line_num, level, heading_text) in enumerate(headings):
        # The section's end_line is the 0-based index of the next heading (or
        # num_lines for the last section). Since lines[line_num:end_line]
        # covers 0-based indices line_num..end_line-1, end_line conveniently
        # equals the last 1-based line of the section. E.g. lines[4:6] covers
        # 0-based indices 4 and 5, which are 1-based lines 5 and 6 — so
        # end_line = 6 is correct for 1-based inclusive.
        if idx + 1 < len(headings):
            end_line = headings[idx + 1][0]
        else:
            end_line = num_lines

        # Section content: heading line + body up to next heading.
        section_lines = lines[line_num:end_line]
        section_source = "\n".join(section_lines)

        slug = _slugify(heading_text)
        # Deduplicate slugs: if this slug has been used before, append a
        # counter suffix so the fqname stays unique (required by the DB's
        # (repo_id, fqname) constraint on the nodes table).
        suffix = used_fqnames[slug]
        used_fqnames[slug] += 1
        if suffix > 0:
            slug = f"{slug}-{suffix}"
        fqname = f"{module}.{slug}"

        # Determine parent based on heading level.
        if level == 1:
            parent: str = module
            h1_parent = fqname
            h2_parent = fqname
        elif level == 2:
            parent = h1_parent
            h2_parent = fqname
        else:  # level 3
            parent = h2_parent

        symbols.append(
            RawSymbol(
                kind=NodeKind.DOC,
                fqname=fqname,
                name=heading_text,
                path=path,
                start_line=line_num + 1,  # convert to 1-based
                end_line=end_line,
                source=section_source,
                parent_fqname=parent,
            )
        )

    return FileExtract(
        path=path,
        language="markdown",
        symbols=symbols,
        had_errors=False,
    )


def _first_paragraph(text: str) -> str | None:
    """Extract the first obvious paragraph from Markdown text for use as docstring.

    Skips leading blank lines and the first heading to get the introductory prose
    block. Returns None if no paragraph is found.
    """
    lines = text.split("\n")
    # Skip leading blank lines and the first heading.
    started = False
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not started and (not stripped or stripped.startswith("#")):
            continue
        started = True
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs[0] if paragraphs else None
