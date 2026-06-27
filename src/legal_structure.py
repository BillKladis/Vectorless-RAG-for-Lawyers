"""
Legal-aware document parsing.

Unlike free-form prose, legal instruments are *built to be navigated*: every
obligation lives at a numbered, citable address (Section 8.1(a), Article III,
§ 107). This module turns a legal markdown document into a hierarchical tree
where every node carries its own pinpoint citation anchor — the same address a
lawyer would write in a brief.

Two real-world contract layouts are supported out of the box:

  * Common Paper "Standard Terms" style — ordered lists whose headings are
    tagged ``<span class="header_2" id="8">`` / ``<span class="header_3"
    id="8.1">``, with a dedicated Definitions section. Section numbers come
    straight from the ``id`` attribute, so citations are exact.
  * Flat numbered style — ``1. **Introduction**. ...`` with inline (a)/(b)
    sub-clauses (e.g. the Mutual NDA). Each top-level number becomes a node.

The parser is deliberately tolerant: anything it cannot classify as a new
numbered clause is folded into the body of the clause currently open, so no
contract text is ever dropped.
"""

from __future__ import annotations

import re

# ── Line patterns ───────────────────────────────────────────────────────────
# A titled subsection/section: ``N. <span class="header_2" id="8.1">Title.</span> body``
_RE_HEADER = re.compile(
    r'^\s*\d+\.\s+<span class="header_[234]" id="(?P<id>[\d.]+)">(?P<title>.*?)</span>(?P<body>.*)$'
)
# A definition entry: ``N. <span id="13.8">**"Confidential Information"**</span> means ...``
_RE_DEFINITION = re.compile(
    r'^\s*\d+\.\s+<span[^>]*id="(?P<id>1?\d\.\d+)"[^>]*>\s*\*\*[“"](?P<title>.+?)[”"]\*\*\s*</span>(?P<body>.*)$'
)
# An untitled subsection whose id rides on an inline span: ``1. <span class="coverpage_link" id="7.1">Provider</span> makes ...``
_RE_INLINE_ID = re.compile(
    r'^\s*\d+\.\s+.*?id="(?P<id>\d+\.\d+)".*$'
)
# A flat bold-titled top-level clause (NDA style): ``2. **Use and Protection**. body``
_RE_BOLD_TOP = re.compile(
    r'^(?P<indent>\s*)(?P<num>\d+)\.\s+\*\*(?P<title>.+?)\*\*\.?\s*(?P<body>.*)$'
)
# Document title (single leading ``# ...``)
_RE_DOC_TITLE = re.compile(r'^#\s+(.+)$')
# A leading ordered-list marker (``  2. ``) to strip from folded clause bodies.
_RE_MARKER = re.compile(r'^\s*\d+\.\s+')

# Spans that mark a contract Variable / defined term used in the body text.
_RE_TERM_SPAN = re.compile(r'<span class="(?:keyterms_link|coverpage_link|orderform_link)"[^>]*>(.+?)</span>')


def _clean(text: str) -> str:
    """Strip HTML span tags and markdown emphasis, leaving readable legal prose."""
    text = re.sub(r'</?span[^>]*>', '', text)
    text = text.replace('**', '').replace('__', '')
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def _node(node_id: str, number: str, title: str, kind: str) -> dict:
    return {
        "id": node_id,
        "number": number,        # citation number, e.g. "8.1" ("" for the root)
        "title": title,          # heading text, e.g. "Liability Caps"
        "kind": kind,            # "root" | "section" | "subsection" | "definition"
        "raw": "",               # original markup (kept for term/cross-ref extraction)
        "text": "",              # cleaned body prose
        "summary": "",           # filled in by the indexer
        "variables_used": [],    # defined-term Variables appearing in this node
        "cross_refs": [],        # section numbers this node points to
        "children": [],
    }


def _append_body(node: dict, raw_line: str) -> None:
    cleaned = _clean(raw_line)
    if cleaned:
        node["text"] = (node["text"] + "\n" + cleaned).strip() if node["text"] else cleaned
        node["raw"] = (node["raw"] + "\n" + raw_line).strip() if node["raw"] else raw_line.strip()


def parse_legal_document(content: str, doc_title: str = "Document") -> dict:
    """Parse a legal markdown document into a citable hierarchical tree."""
    title_match = next((_RE_DOC_TITLE.match(l) for l in content.splitlines() if _RE_DOC_TITLE.match(l)), None)
    if title_match:
        doc_title = title_match.group(1).strip()

    root = _node("root", "", doc_title, "root")
    by_id: dict[str, dict] = {}
    order: list[dict] = []
    current: dict = root          # node currently accumulating body text
    top_counter = 0

    for raw_line in content.splitlines():
        if not raw_line.strip() or _RE_DOC_TITLE.match(raw_line):
            continue

        header = _RE_HEADER.match(raw_line)
        definition = None if header else _RE_DEFINITION.match(raw_line)
        bold_top = None if (header or definition) else _RE_BOLD_TOP.match(raw_line)
        inline = None if (header or definition or bold_top) else _RE_INLINE_ID.match(raw_line)

        if header:
            num = header.group("id")
            kind = "section" if "." not in num else "subsection"
            node = _node(f"n{num}", num, _clean(header.group("title")).rstrip(". "), kind)
            _append_body(node, header.group("body"))
        elif definition:
            num = definition.group("id")
            node = _node(f"n{num}", num, _clean(definition.group("title")), "definition")
            _append_body(node, _RE_MARKER.sub("", raw_line))  # keep the full "X means ..." sentence
        elif inline:
            num = inline.group("id")
            node = _node(f"n{num}", num, "", "subsection")
            _append_body(node, _RE_MARKER.sub("", raw_line))
        elif bold_top:
            top_counter += 1
            num = str(top_counter)
            node = _node(f"n{num}", num, _clean(bold_top.group("title")).rstrip(". "), "section")
            _append_body(node, bold_top.group("body"))
        else:
            # Continuation line, lettered sub-clause, or stray prose → fold into the open clause.
            _append_body(current, raw_line)
            continue

        by_id[num] = node
        order.append(node)
        current = node

    # Link nodes into the tree using their dotted-number parentage.
    for node in order:
        parent_num = node["number"].rpartition(".")[0]
        parent = by_id.get(parent_num, root)
        parent["children"].append(node)

    _extract_variables(root)
    return root


def _extract_variables(node: dict) -> None:
    """Record the contract Variables (defined-term spans) used in each node's text."""
    if node["raw"]:
        terms = sorted({re.sub(r"[’']s$", "", m.group(1).strip()).strip() for m in _RE_TERM_SPAN.finditer(node["raw"])})
        node["variables_used"] = [t for t in terms if t]
    for child in node["children"]:
        _extract_variables(child)


# ── Citation helpers ────────────────────────────────────────────────────────

def citation_label(node: dict) -> str:
    """Render a pinpoint citation label, e.g. '§ 8.1 (Liability Caps)'."""
    if node["kind"] == "root" or not node["number"]:
        return node["title"]
    if node["title"]:
        return f"§ {node['number']} ({node['title']})"
    return f"§ {node['number']}"


def short_citation(node: dict) -> str:
    """Render a bare pinpoint cite, e.g. '§ 8.1'."""
    return f"§ {node['number']}" if node["number"] else node["title"]


def iter_nodes(node: dict):
    """Depth-first iteration over every node in the tree (excluding the root)."""
    for child in node["children"]:
        yield child
        yield from iter_nodes(child)


def index_by_number(tree: dict) -> dict[str, dict]:
    """Map every section number (e.g. '8.1') to its node."""
    return {n["number"]: n for n in iter_nodes(tree) if n["number"]}
