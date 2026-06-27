"""
Cross-reference and defined-term analysis for legal instruments.

Two things separate legal reading from ordinary document Q&A:

  1. **Cross-references.** A clause is rarely self-contained. "Each party's
     liability ... will not be more than the General Cap Amount" only means
     something once you also read Section 8.4 (Exceptions) and the definition
     of "Increased Claims". Lawyers trace these threads by hand. This module
     builds the directed graph of every "Section X.Y" pointer in the document
     so the navigator (and the UI) can follow them automatically.

  2. **Defined terms.** Capitalised terms ("Confidential Information",
     "Provider Covered Claim") have precise, document-controlled meanings.
     This module extracts the glossary — what each term means, where it is
     defined, and everywhere it is used — so an answer can resolve a term to
     its actual contractual definition instead of its dictionary meaning.
"""

from __future__ import annotations

import re

from .legal_structure import iter_nodes, index_by_number

# "Section 8.1", "Sections 8.1 ... and 8.2", "Section 8.1(a)", "§ 8.4"
_RE_SECTION_REF = re.compile(r'(?:Sections?|§)\s+(\d+(?:\.\d+)?)')
# A bare "N.M (" — catches the second member of "Sections 8.1 (..) and 8.2 (..)".
_RE_TITLED_REF = re.compile(r'(?<!\d)(\d+\.\d+)\s*[(（]')
# Inline bold-quoted defined terms, e.g. ("**Receiving Party**") in an NDA recital.
_RE_INLINE_TERM = re.compile(r'[“"(]\s*\*\*(.+?)\*\*\s*[”")]')


# ── Cross-reference graph ───────────────────────────────────────────────────

def attach_cross_references(tree: dict) -> dict[str, list[str]]:
    """
    Populate ``node['cross_refs']`` for every node and return the inverse
    ('referenced_by') map: section number -> list of section numbers citing it.
    """
    numbers = index_by_number(tree)
    referenced_by: dict[str, set] = {num: set() for num in numbers}

    for node in iter_nodes(tree):
        if not node["text"]:
            continue
        found = set(_RE_SECTION_REF.findall(node["text"])) | set(_RE_TITLED_REF.findall(node["text"]))
        # A pointer resolves to the deepest section number that actually exists.
        targets = sorted(
            (t for t in found if t in numbers and t != node["number"]),
            key=lambda s: [int(p) for p in s.split(".")],
        )
        node["cross_refs"] = targets
        for t in targets:
            referenced_by[t].add(node["number"])

    return {k: sorted(v, key=lambda s: [int(p) for p in s.split(".")]) for k, v in referenced_by.items()}


# ── Defined-term glossary ───────────────────────────────────────────────────

def build_glossary(tree: dict) -> dict[str, dict]:
    """
    Build the document glossary: term -> {term, definition, defined_in, node_id, source}.

    Sources, in priority order:
      * an explicit Definitions section (``kind == 'definition'``)
      * inline bold-quoted terms introduced in a recital (NDA style)
      * Cover Page / Order Form Variables used but not otherwise defined
    """
    glossary: dict[str, dict] = {}

    # 1. Explicit definition clauses.
    for node in iter_nodes(tree):
        if node["kind"] == "definition" and node["title"]:
            glossary[node["title"]] = {
                "term": node["title"],
                "definition": node["text"],
                "defined_in": node["number"],
                "node_id": node["id"],
                "source": "Definitions section",
            }

    # 2. Inline bold-quoted terms (recital-defined).
    for node in iter_nodes(tree):
        for m in _RE_INLINE_TERM.finditer(node["raw"]):
            term = m.group(1).strip()
            if term and term not in glossary:
                glossary[term] = {
                    "term": term,
                    "definition": node["text"],
                    "defined_in": node["number"],
                    "node_id": node["id"],
                    "source": "Defined in-line",
                }

    # 3. Cover Page / Order Form Variables not captured above.
    for node in iter_nodes(tree):
        for term in node["variables_used"]:
            if term not in glossary:
                glossary[term] = {
                    "term": term,
                    "definition": "A Variable whose value is set on the Cover Page / Order Form.",
                    "defined_in": None,
                    "node_id": None,
                    "source": "Cover Page Variable",
                }

    return glossary


def compute_term_usage(tree: dict, glossary: dict[str, dict]) -> dict[str, list[str]]:
    """For each glossary term, list the section numbers whose text uses it."""
    usage: dict[str, list[str]] = {}
    for term in glossary:
        pattern = re.compile(rf'(?<![\w]){re.escape(term)}(?![\w])')
        hits = [
            n["number"] for n in iter_nodes(tree)
            if n["number"] and n["kind"] != "definition" and pattern.search(n["text"])
        ]
        usage[term] = sorted(set(hits), key=lambda s: [int(p) for p in s.split(".")])
    return usage


def terms_used_in(node: dict, glossary: dict[str, dict]) -> list[str]:
    """Which glossary terms appear in this node's text (longest-match first)."""
    found = []
    for term in sorted(glossary, key=len, reverse=True):
        if re.search(rf'(?<![\w]){re.escape(term)}(?![\w])', node["text"]):
            found.append(term)
    return found


def build_legal_metadata(tree: dict) -> dict:
    """One-shot: attach cross-refs and return glossary, usage, and inverse graph."""
    referenced_by = attach_cross_references(tree)
    glossary = build_glossary(tree)
    term_usage = compute_term_usage(tree, glossary)
    return {
        "referenced_by": referenced_by,
        "glossary": glossary,
        "term_usage": term_usage,
    }
