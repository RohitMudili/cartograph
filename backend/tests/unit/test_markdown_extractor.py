"""Tests for the Markdown document extractor.

These assert exact extraction output against known source — the contract the
graph builder depends on. Line numbers are 1-based inclusive.
"""

from __future__ import annotations

from app.db.enums import NodeKind
from app.indexer.parser.markdown import extract_markdown

README = b"""# Cartograph

Turn a GitHub repo into a knowledge graph and answer questions about it.

## Installation

### Prerequisites

You need Python 3.12 and Node 20.

### Quick start

Run the following:

```
pip install cartograph
```

## Usage

Import the library and create a graph.
"""

NO_HEADINGS = b"""Just a plain text file with no markdown headings.

Some content here.
And more content.
"""


def _by_fqname(extract, fqname):
    return next(s for s in extract.symbols if s.fqname == fqname)


def test_file_symbol() -> None:
    ex = extract_markdown("README.md", README)
    file_sym = _by_fqname(ex, "README")
    assert file_sym.kind == NodeKind.DOC
    assert file_sym.name == "README.md"
    assert file_sym.path == "README.md"
    assert file_sym.start_line == 1
    assert file_sym.end_line == 22
    assert file_sym.parent_fqname is None
    # docstring should be the first paragraph
    assert "Turn a GitHub repo into a knowledge graph" in (file_sym.docstring or "")


def test_h1_section() -> None:
    ex = extract_markdown("README.md", README)
    h1 = _by_fqname(ex, "README.cartograph")
    assert h1.kind == NodeKind.DOC
    assert h1.name == "Cartograph"
    assert h1.start_line == 1
    assert h1.end_line == 4  # next heading at line 4 (0-based), section covers 1-based lines 1-4
    assert h1.parent_fqname == "README"


def test_h2_section() -> None:
    ex = extract_markdown("README.md", README)
    h2 = _by_fqname(ex, "README.installation")
    assert h2.kind == NodeKind.DOC
    assert h2.name == "Installation"
    assert h2.start_line == 5
    assert h2.parent_fqname == "README.cartograph"  # child of H1


def test_h3_section_under_h2() -> None:
    ex = extract_markdown("README.md", README)
    h3 = _by_fqname(ex, "README.prerequisites")
    assert h3.kind == NodeKind.DOC
    assert h3.name == "Prerequisites"
    assert h3.start_line == 7
    assert h3.parent_fqname == "README.installation"  # child of H2


def test_h3_section_content() -> None:
    ex = extract_markdown("README.md", README)
    h3 = _by_fqname(ex, "README.prerequisites")
    assert "You need Python 3.12" in h3.source
    assert "### Quick start" not in h3.source  # next H3, not in this section


def test_heading_text_normalized() -> None:
    ex = extract_markdown("README.md", README)
    # "Quick start" should slugify to "quick-start"
    expected = next(s for s in ex.symbols if "quick-start" in s.fqname)
    assert expected.name == "Quick start"


def test_no_headings() -> None:
    ex = extract_markdown("plain.txt", NO_HEADINGS)
    assert len(ex.symbols) == 1  # just the file-level symbol
    file_sym = ex.symbols[0]
    assert file_sym.kind == NodeKind.DOC
    assert file_sym.name == "plain.txt"
    assert file_sym.source == NO_HEADINGS.decode("utf-8")


def test_code_block_content_not_mistaken_for_heading() -> None:
    source = b"""# Title

```
# This is code, not a heading
def foo():
    pass
```

## Real heading

Text here.
"""
    ex = extract_markdown("test.md", source)
    fqnames = {s.fqname for s in ex.symbols}
    # Should NOT have a symbol for "# This is code" — only the file, H1, and H2
    assert "test.title" in fqnames
    assert "test.real-heading" in fqnames
    # Should not have any symbols for the code block content
    code_like = [s for s in fqnames if "code" in s]
    assert len(code_like) == 0, f"Unexpected symbols from code block: {code_like}"


def test_slugify_special_characters() -> None:
    source = b"# Hello, World! (2024)\n\nContent.\n## FAQ: How do I?\n"
    ex = extract_markdown("test.md", source)
    fqnames = {s.fqname for s in ex.symbols}
    assert "test.hello-world-2024" in fqnames
    assert "test.faq-how-do-i" in fqnames


def test_duplicate_headings_slug_unique() -> None:
    """Two headings that slug to the same thing get unique fqnames."""
    source = b"# Getting Started\n\nContent.\n\n## Getting started\n\nMore content.\n"
    ex = extract_markdown("test.md", source)
    fqnames = {s.fqname for s in ex.symbols}
    assert "test.getting-started" in fqnames
    assert "test.getting-started-1" in fqnames


def test_multiple_files_extraction() -> None:
    """Verify the extractor works the same for different .md file paths."""
    ex = extract_markdown("docs/guide.md", README)
    file_sym = _by_fqname(ex, "docs.guide")
    assert file_sym.path == "docs/guide.md"
    h1 = _by_fqname(ex, "docs.guide.cartograph")
    assert h1 is not None
