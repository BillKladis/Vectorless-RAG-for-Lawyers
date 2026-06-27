"""
Citation formatting helpers shared by the UI and the evaluation harness.

Lawyers do not accept "the contract says X" — they accept "§ 8.1(a) says X".
Every answer this system produces is backed by an authority list whose entries
carry a pinpoint citation, the verbatim clause text, and the reason the clause
was pulled (directly responsive vs. reached by following a cross-reference).
"""

from __future__ import annotations


def authority_entry(node: dict, kind: str, reason: str = "") -> dict:
    """Build a serialisable authority record for an answer."""
    from .legal_structure import citation_label, short_citation
    return {
        "number": node["number"],
        "title": node["title"],
        "label": citation_label(node),
        "cite": short_citation(node),
        "text": node["text"],
        "kind": kind,                 # "primary" | "cross-ref"
        "reason": reason,
        "cross_refs": node.get("cross_refs", []),
    }


def format_authorities_markdown(authorities: list[dict]) -> str:
    """Render an authority list as markdown (used in eval reports / CLI)."""
    lines = []
    for a in authorities:
        tag = "↳ cross-reference" if a["kind"] == "cross-ref" else "primary authority"
        lines.append(f"**{a['label']}**  _({tag})_")
        if a["reason"]:
            lines.append(f"> {a['reason']}")
        lines.append("")
        lines.append(a["text"])
        lines.append("")
    return "\n".join(lines)


def definition_entry(glossary_item: dict) -> dict:
    """Build a serialisable defined-term record for an answer."""
    where = f"§ {glossary_item['defined_in']}" if glossary_item.get("defined_in") else glossary_item["source"]
    return {
        "term": glossary_item["term"],
        "definition": glossary_item["definition"],
        "defined_in": glossary_item.get("defined_in"),
        "where": where,
    }
