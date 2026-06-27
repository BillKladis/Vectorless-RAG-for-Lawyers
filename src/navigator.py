"""
Reasoning-based legal retrieval — no embeddings, no vector similarity.

The navigator answers a question the way a lawyer works through a document:

  1. **Read the index, choose a path.** Starting at the root it reads the
     one-sentence summary of each part and asks the model which sections to
     open — then recurses. This is a greedy best-first search whose scoring
     function is the model's own legal reading, not cosine distance.

  2. **Follow the threads.** Real legal answers are not confined to the clause
     you land on. Once the responsive clauses are collected, the navigator
     automatically pulls in every section they cross-reference ("subject to
     Section 8.4") and resolves the defined terms they rely on. A lawyer does
     this by flipping pages; here it is automatic and recorded.

  3. **Answer on the record.** Synthesis is grounded strictly in the retrieved
     authorities, written with pinpoint citations (§ 8.1(a)), and told to flag
     where the document is silent rather than guess.

Set ``LAW_DEMO=1`` to short-circuit the API with canned answers (used by the
screenshot capture when no key is available).
"""

from __future__ import annotations

import os
import re
import json

import anthropic

from .legal_structure import citation_label, short_citation, index_by_number, iter_nodes
from .cross_reference import terms_used_in
from .citations import authority_entry, definition_entry

MODEL = os.getenv("LAW_MODEL", "claude-haiku-4-5-20251001")

MAX_CROSS_REFS = 8          # cap on auto-followed cross-references per answer
MAX_DEFINITIONS = 10        # cap on resolved defined terms per answer


# ── JSON helper ─────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    m = re.search(r'\{.*\}', text.strip(), re.DOTALL)
    return json.loads(m.group() if m else text)


# ── Greedy tree navigation ──────────────────────────────────────────────────

def _select_children(node: dict, question: str, client: anthropic.Anthropic,
                     precise: bool = True) -> tuple[list[int], str]:
    if not node["children"]:
        return [], ""
    listings = "\n".join(
        f"{i}. {citation_label(c)} — {c['summary']}" for i, c in enumerate(node["children"])
    )
    if precise:
        instruction = (
            "Select the sections that DIRECTLY address the question — a section qualifies if it "
            "states, limits, conditions, or excepts the answer. Also select a limitation or "
            "exception clause when it would change the answer. Do NOT select sections that are only "
            "loosely or topically related, and do not select a section merely because it mentions a "
            "word from the question. Defined terms are resolved separately, so you need not chase "
            "definitions here."
        )
    else:
        instruction = (
            "Select every section that could plausibly bear on the answer — including definitions "
            "and limitation/exception clauses. Be inclusive when unsure; only skip clearly "
            "irrelevant sections."
        )
    prompt = (
        "You are a lawyer locating the clauses needed to answer a question, by reading a "
        f"document's section index. {instruction}\n\n"
        f'Question: "{question}"\n\n'
        f'Currently inside: {citation_label(node)}\n'
        f'Available sections:\n{listings}\n\n'
        'Return JSON: {"indices": [0-based ints], "reasoning": "one sentence"}. '
        'If none apply: {"indices": [], "reasoning": "..."}.'
    )
    msg = client.messages.create(model=MODEL, max_tokens=160,
                                 messages=[{"role": "user", "content": prompt}])
    try:
        result = _extract_json(msg.content[0].text)
    except Exception:
        return list(range(len(node["children"]))), "Could not parse selection; exploring all."
    indices = [i for i in result.get("indices", []) if isinstance(i, int) and 0 <= i < len(node["children"])]
    return indices, result.get("reasoning", "")


def _is_definitions_section(node: dict) -> bool:
    """A section that exists to define terms — navigated around, not through."""
    return node["kind"] == "section" and any(c["kind"] == "definition" for c in node["children"])


def _navigate(node: dict, question: str, client: anthropic.Anthropic,
              depth: int, steps: list, collected: dict, precise: bool = True) -> None:
    step = {"id": node["id"], "number": node["number"], "title": node["title"],
            "label": citation_label(node), "depth": depth, "kind": node["kind"],
            "selected_children": [], "reasoning": ""}
    steps.append(step)

    if not node["children"]:
        if node["text"].strip():
            collected[node["number"]] = node
        return

    indices, reasoning = _select_children(node, question, client, precise=precise)
    step["selected_children"] = [short_citation(node["children"][i]) for i in indices]
    step["reasoning"] = reasoning
    for i in indices:
        _navigate(node["children"][i], question, client, depth + 1, steps, collected, precise=precise)


# ── Cross-reference & definition expansion ──────────────────────────────────

def _expand_cross_references(primary: dict, number_index: dict) -> list[dict]:
    """Pull in sections cross-referenced by the primary clauses (one hop)."""
    authorities = []
    seen = set(primary)
    for num, node in primary.items():
        for target in node["cross_refs"]:
            if target in seen or target not in number_index:
                continue
            tgt = number_index[target]
            if not tgt["text"].strip():        # a bare section header → use its first child instead
                child = next((c for c in tgt["children"] if c["text"].strip()), None)
                tgt = child or tgt
            seen.add(target)
            authorities.append(authority_entry(
                tgt, "cross-ref",
                reason=f"Reached because {short_citation(node)} cross-references {short_citation(number_index[target])}.",
            ))
            if len(authorities) >= MAX_CROSS_REFS:
                return authorities
    return authorities


def _resolve_definitions(primary: dict, index: dict, question: str = "") -> list[dict]:
    """Resolve the defined terms the responsive clauses (and the question) rely on."""
    glossary = index["glossary"]
    seen, defs = set(), []

    def add(term: str) -> bool:
        item = glossary.get(term)
        if not item or term in seen or not item.get("defined_in"):
            return False
        seen.add(term)
        defs.append(definition_entry(item))
        return len(defs) >= MAX_DEFINITIONS

    # Terms named explicitly in the question take priority (supports "what does X mean?").
    if question:
        import re as _re
        for term in sorted(glossary, key=len, reverse=True):
            if glossary[term].get("defined_in") and _re.search(rf'(?<![\w]){_re.escape(term)}(?![\w])', question):
                if add(term):
                    return defs

    for node in primary.values():
        for term in terms_used_in(node, glossary):
            if add(term):
                return defs
    return defs


# ── Synthesis ───────────────────────────────────────────────────────────────

def _synthesise(question: str, authorities: list[dict], definitions: list[dict],
                doc_title: str, client: anthropic.Anthropic, mode: str = "legal") -> str:
    blocks = []
    for a in authorities:
        tag = "DIRECTLY RESPONSIVE" if a["kind"] == "primary" else "CROSS-REFERENCED (may qualify the above)"
        blocks.append(f"[{a['label']}] — {tag}\n{a['text']}")
    context = "\n\n---\n\n".join(blocks)
    if definitions:
        context += "\n\n=== DEFINED TERMS ===\n" + "\n".join(
            f"- \"{d['term']}\" ({d['where']}): {d['definition']}" for d in definitions
        )

    if mode == "generic":
        # A standard RAG synthesis prompt — the baseline the legal mode is measured against.
        prompt = (
            "Answer the question using the document sections below. Cite section names or numbers "
            "where relevant. Be concise.\n\n"
            f"Question: {question}\n\nSections:\n{context}\n\nAnswer:"
        )
    else:
        prompt = (
            f"You are a legal analyst answering a question about \"{doc_title}\" using ONLY the "
            "clauses provided below. Write for a lawyer.\n\n"
            "Rules:\n"
            "• Answer the specific question asked. Use only the clauses that actually bear on it; "
            "if a provided clause is not relevant, ignore it. Do NOT speculate about how tangential "
            "clauses might interact, and do not assert a relationship between clauses unless the text "
            "states it.\n"
            "• Ground every statement in the text. After each point, cite the controlling clause as "
            "§ 8.1 or § 8.1(a).\n"
            "• Apply qualifiers: if a responsive clause is expressly limited by an exception or cap "
            "elsewhere (e.g. \"except as provided in § 8.4\"), state the qualification and cite it.\n"
            "• Use defined terms with their contractual meaning; do not substitute ordinary meaning.\n"
            "• If the clauses do not answer the question, say so plainly — never guess or use outside "
            "knowledge. Do not give legal advice beyond what the text supports.\n\n"
            f"Question: {question}\n\n"
            f"Clauses:\n{context}\n\nAnswer:"
        )
    msg = client.messages.create(model=MODEL, max_tokens=900,
                                 messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()


# ── Public entry point ──────────────────────────────────────────────────────

def answer_question(index: dict, question: str, client: anthropic.Anthropic,
                    follow_cross_refs: bool = True, resolve_definitions: bool = True,
                    synthesis_mode: str = "legal", navigation_mode: str = "precise") -> dict:
    """
    Navigate the document and return a grounded, cited answer plus full provenance.

    Returns a dict: answer, steps (navigation trace), authorities (primary +
    cross-referenced clauses), definitions (resolved terms), retrieved_numbers.

    navigation_mode: "precise" (default) selects directly-responsive sections and
    resolves definitions on demand; "broad" selects inclusively and walks the
    Definitions section too (the higher-recall, lower-precision baseline).
    """
    if os.getenv("LAW_DEMO") == "1":
        return _demo_answer(index, question)

    precise = navigation_mode != "broad"
    tree = index["tree"]
    number_index = index_by_number(tree)
    steps: list[dict] = []
    primary: dict[str, dict] = {}

    # In precise mode, navigate operative clauses only; the Definitions section is
    # resolved on demand (a question rarely needs a definition that none of its
    # operative clauses use). In broad mode, walk everything.
    for child in tree["children"]:
        if precise and _is_definitions_section(child):
            continue
        _navigate(child, question, client, depth=1, steps=steps, collected=primary, precise=precise)

    if not primary:
        return {"answer": "No clause in this document appears to address the question.",
                "steps": steps, "authorities": [], "definitions": [], "retrieved_numbers": []}

    authorities = [authority_entry(n, "primary", reason="Directly responsive to the question.")
                   for n in primary.values()]
    if follow_cross_refs:
        authorities += _expand_cross_references(primary, number_index)
    definitions = _resolve_definitions(primary, index, question) if resolve_definitions else []

    answer = _synthesise(question, authorities, definitions, index["doc_title"], client, mode=synthesis_mode)

    return {
        "answer": answer,
        "steps": steps,
        "authorities": authorities,
        "definitions": definitions,
        "retrieved_numbers": sorted(primary, key=lambda s: [int(p) for p in s.split(".")]),
    }


# ── Demo fallback (no API) ──────────────────────────────────────────────────

def _demo_answer(index: dict, question: str) -> dict:
    number_index = index_by_number(index["tree"])
    q = question.lower()
    if "liab" in q or "cap" in q:
        nums = ["8.1", "8.2", "8.4"]
    elif "terminat" in q or "breach" in q:
        nums = ["5.3", "5.5"]
    elif "indemn" in q:
        nums = ["9.1", "9.2"]
    else:
        nums = [n["number"] for n in list(iter_nodes(index["tree"]))[:2] if n["text"]]
    primary = {n: number_index[n] for n in nums if n in number_index}
    authorities = [authority_entry(n, "primary", "Directly responsive to the question.") for n in primary.values()]
    authorities += _expand_cross_references(primary, number_index)
    answer = ("**Demo mode.** Live answers require an API key. Based on the document structure, the "
              "controlling clauses for this question are "
              + ", ".join(short_citation(n) for n in primary.values()) + ".")
    steps = [{"id": n["id"], "number": n["number"], "title": n["title"], "label": citation_label(n),
              "depth": 1, "kind": n["kind"], "selected_children": [], "reasoning": "Demo selection."}
             for n in primary.values()]
    return {"answer": answer, "steps": steps, "authorities": authorities,
            "definitions": _resolve_definitions(primary, index), "retrieved_numbers": list(primary)}
