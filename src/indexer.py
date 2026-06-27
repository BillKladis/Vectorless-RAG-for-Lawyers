"""
Build a navigable, citable index from a legal document.

The index is the vectorless equivalent of an embedding store. It contains:

  * the parsed clause **tree** (every node addressable by its section number),
  * a one-sentence LLM **summary** at every node, generated bottom-up so a
    parent's summary distils its children — this is what the navigator reads
    when it decides which branch to descend,
  * the document **glossary**, term-usage map, and the **cross-reference**
    graph produced by ``cross_reference``.

Indexing cost is paid once and cached to ``data/index/<doc>.json``; thereafter
answering a question costs only the handful of navigation calls plus synthesis.
"""

from __future__ import annotations

import os
import json
from pathlib import Path

import anthropic

from .legal_structure import parse_legal_document, citation_label, iter_nodes
from .cross_reference import build_legal_metadata

MODEL = os.getenv("LAW_MODEL", "claude-haiku-4-5-20251001")


def _summarise(node: dict, content: str, client: anthropic.Anthropic) -> str:
    if not content.strip():
        return f"{citation_label(node)}."
    prompt = (
        "You are a paralegal building a navigation index of a legal agreement. "
        "Write ONE sentence (max 38 words) describing what this clause does, so a "
        "lawyer scanning the index can tell whether it answers a given question. "
        "Name the obligation and the party it binds; mention defined terms or "
        "cross-referenced sections if they are central. Be concrete, not generic.\n\n"
        f"Clause: {citation_label(node)}\n\nText:\n{content[:3000]}\n\nOne-sentence summary:"
    )
    msg = client.messages.create(
        model=MODEL, max_tokens=90,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _build_summaries(node: dict, client: anthropic.Anthropic, depth: int = 0) -> None:
    for child in node["children"]:
        _build_summaries(child, client, depth + 1)

    if node["kind"] == "root":
        children = ", ".join(c["title"] for c in node["children"])
        node["summary"] = f"{node['title']} — top-level parts: {children}."
        return

    if node["children"]:
        content = "\n".join(f"- {citation_label(c)}: {c['summary']}" for c in node["children"])
    else:
        content = node["text"]

    print(f"{'  ' * depth}Summarising {citation_label(node)}")
    node["summary"] = _summarise(node, content, client)


def build_index(doc_path: Path, index_path: Path, client: anthropic.Anthropic, doc_title: str = "") -> dict:
    """Load the index from cache, or build (parse + summarise + analyse) and cache it."""
    if index_path.exists():
        return json.loads(index_path.read_text())

    content = doc_path.read_text(encoding="utf-8")
    tree = parse_legal_document(content, doc_title or doc_path.stem)

    metadata = build_legal_metadata(tree)        # attaches cross_refs, returns glossary/usage/graph
    _build_summaries(tree, client)               # bottom-up LLM summaries

    index = {
        "doc_title": tree["title"],
        "doc_file": doc_path.name,
        "tree": tree,
        "glossary": metadata["glossary"],
        "term_usage": metadata["term_usage"],
        "referenced_by": metadata["referenced_by"],
        "stats": {
            "sections": sum(1 for n in iter_nodes(tree) if n["kind"] == "section"),
            "clauses": sum(1 for n in iter_nodes(tree) if n["kind"] in ("subsection", "definition")),
            "defined_terms": len(metadata["glossary"]),
            "cross_references": sum(len(n["cross_refs"]) for n in iter_nodes(tree)),
        },
    }

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    return index


def build_index_offline(doc_path: Path, doc_title: str = "") -> dict:
    """Parse + analyse without any API calls (summaries fall back to citation labels)."""
    content = doc_path.read_text(encoding="utf-8")
    tree = parse_legal_document(content, doc_title or doc_path.stem)
    metadata = build_legal_metadata(tree)
    for node in iter_nodes(tree):
        node["summary"] = node["summary"] or f"{citation_label(node)}."
    return {
        "doc_title": tree["title"], "doc_file": doc_path.name, "tree": tree,
        "glossary": metadata["glossary"], "term_usage": metadata["term_usage"],
        "referenced_by": metadata["referenced_by"],
    }
