"""
CaseLens — Vectorless RAG for legal documents.

A reasoning-based research assistant for contracts, statutes, and other legal
instruments. It answers questions by *navigating* a document's clause structure
(no embeddings), returns answers with pinpoint citations, automatically follows
cross-references, and resolves defined terms — with a Cross-Reference Map and
Defined-Terms glossary built for how lawyers actually read.

Run:  streamlit run app.py
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
import anthropic

from src.indexer import build_index
from src.navigator import answer_question
from src.legal_structure import iter_nodes, index_by_number, citation_label, short_citation

load_dotenv()

# ── Document catalogue ──────────────────────────────────────────────────────
DATA = Path("data")
DOCUMENTS = {
    "Cloud Service Agreement": {
        "doc": DATA / "cloud_service_agreement.md",
        "index": DATA / "index" / "cloud_service_agreement.json",
        "blurb": "Common Paper standard SaaS agreement — 13 sections, 33 defined terms.",
        "examples": [
            "What is each party's cap on liability, and what claims are excluded from it?",
            "If the customer stops paying, what can the provider do and how fast?",
            "Which obligations survive termination of the agreement?",
            "Who indemnifies whom, and what must the protected party do to get that protection?",
        ],
    },
    "Mutual Non-Disclosure Agreement": {
        "doc": DATA / "mutual_nda.md",
        "index": DATA / "index" / "mutual_nda.json",
        "blurb": "Common Paper mutual NDA — confidentiality obligations and carve-outs.",
        "examples": [
            "How long do confidentiality obligations last after the NDA ends?",
            "When may the receiving party disclose confidential information if compelled by law?",
            "What information is carved out of the confidentiality obligations?",
        ],
    },
}

st.set_page_config(page_title="CaseLens — Legal Document Intelligence", page_icon="§", layout="wide")

# ── Styling ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      :root { --ink:#16233b; --accent:#9a7b34; --rule:#d8dde6; }
      html, body, [class*="css"] { font-family: 'Georgia', 'Iowan Old Style', serif; }
      h1, h2, h3 { color: var(--ink); letter-spacing:.2px; }
      .stApp { background:#fbfaf7; }
      .cl-brand { font-size:2.1rem; font-weight:700; color:var(--ink); margin-bottom:0; }
      .cl-sub { color:#5b6678; font-style:italic; margin-top:.1rem; }
      .cl-rule { border:none; border-top:2px solid var(--accent); width:64px; margin:.4rem 0 1rem 0; }
      .cl-cite { font-variant:small-caps; font-weight:700; color:var(--accent); }
      .cl-pill { display:inline-block; background:#eef1f6; color:var(--ink); border:1px solid var(--rule);
                 border-radius:10px; padding:1px 8px; margin:2px; font-size:.8rem; font-family:ui-monospace,monospace; }
      .cl-pill-x { background:#f6efe1; border-color:#e3d4ac; }
      .cl-card { background:#fff; border:1px solid var(--rule); border-left:3px solid var(--accent);
                 border-radius:6px; padding:.7rem .9rem; margin:.4rem 0; }
      .cl-note { color:#6b7588; font-size:.85rem; }
      [data-testid="stSidebar"] { background:#f3f1ea; border-right:1px solid var(--rule); }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Anthropic client ────────────────────────────────────────────────────────
api_key = os.getenv("ANTHROPIC_API_KEY", "")
# In the user's deployment this is api.anthropic.com; an explicit override allows
# routing through a corporate gateway without touching code.
base_url = os.getenv("LAW_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
client = anthropic.Anthropic(api_key=api_key, base_url=base_url) if api_key else None

# ── Session state ───────────────────────────────────────────────────────────
ss = st.session_state
ss.setdefault("doc_name", list(DOCUMENTS)[0])
ss.setdefault("indices", {})
ss.setdefault("messages", {})
ss.setdefault("pending", None)
ss.setdefault("settings", {"cross_refs": True, "definitions": True})


def load_index(name: str) -> dict:
    if name not in ss.indices:
        meta = DOCUMENTS[name]
        if not meta["index"].exists() and client is None:
            st.error("This document has no pre-built index and no ANTHROPIC_API_KEY is set to build one.")
            st.stop()
        ss.indices[name] = build_index(meta["doc"], meta["index"], client, name)
    return ss.indices[name]


# ── Sidebar: matter selection + outline ─────────────────────────────────────
with st.sidebar:
    st.markdown("### CaseLens")
    st.caption("Reasoning-based legal research — no vector search.")
    st.divider()
    ss.doc_name = st.selectbox("Document on the desk", list(DOCUMENTS), index=list(DOCUMENTS).index(ss.doc_name))
    st.caption(DOCUMENTS[ss.doc_name]["blurb"])

    st.markdown("**Research options**")
    ss.settings["cross_refs"] = st.checkbox("Auto-follow cross-references", value=ss.settings["cross_refs"])
    ss.settings["definitions"] = st.checkbox("Resolve defined terms", value=ss.settings["definitions"])

    index = load_index(ss.doc_name)
    st.divider()
    st.markdown("**Document outline**")
    for sec in index["tree"]["children"]:
        st.markdown(f"<span class='cl-cite'>§ {sec['number']}</span> {sec['title']}", unsafe_allow_html=True)
        st.caption(sec["summary"])

    if "stats" in index:
        s = index["stats"]
        st.divider()
        st.caption(f"{s['sections']} sections · {s['clauses']} clauses · "
                   f"{s['defined_terms']} defined terms · {s['cross_references']} cross-references")
    if api_key:
        st.caption("API key: loaded")
    else:
        st.caption("API key: not set — answering disabled")


# ── Header ──────────────────────────────────────────────────────────────────
st.markdown("<p class='cl-brand'>CaseLens</p>", unsafe_allow_html=True)
st.markdown(f"<p class='cl-sub'>{index['doc_title']}</p>", unsafe_allow_html=True)
st.markdown("<hr class='cl-rule'>", unsafe_allow_html=True)

tab_ask, tab_xref, tab_terms, tab_about = st.tabs(
    ["Research", "Cross-Reference Map", "Defined Terms", "About"]
)


# ── Rendering helpers ───────────────────────────────────────────────────────
def render_answer(result: dict) -> None:
    st.markdown(result["answer"])

    primary = [a for a in result["authorities"] if a["kind"] == "primary"]
    xrefs = [a for a in result["authorities"] if a["kind"] == "cross-ref"]

    cites = " ".join(f"<span class='cl-pill'>{a['cite']}</span>" for a in primary)
    if cites:
        st.markdown("**Authorities relied on:** " + cites, unsafe_allow_html=True)
    if xrefs:
        xcites = " ".join(f"<span class='cl-pill cl-pill-x'>{a['cite']}</span>" for a in xrefs)
        st.markdown("**Cross-references followed:** " + xcites, unsafe_allow_html=True)

    with st.expander(f"Authorities — full clause text ({len(result['authorities'])})", expanded=False):
        for a in result["authorities"]:
            tag = "↳ cross-reference" if a["kind"] == "cross-ref" else "primary authority"
            st.markdown(f"<div class='cl-card'><span class='cl-cite'>{a['label']}</span> "
                        f"<span class='cl-note'>· {tag}</span><br>"
                        f"<span class='cl-note'>{a['reason']}</span></div>", unsafe_allow_html=True)
            st.markdown(a["text"])
            st.markdown("---")

    if result["definitions"]:
        with st.expander(f"Defined terms in play ({len(result['definitions'])})", expanded=False):
            for d in result["definitions"]:
                st.markdown(f"**{d['term']}** <span class='cl-note'>({d['where']})</span>", unsafe_allow_html=True)
                st.markdown(f"> {d['definition']}")

    with st.expander("Reasoning path — how the answer was located", expanded=False):
        st.caption("The model read each section's summary and chose which branches to open. "
                   "No embeddings or vector search were used.")
        for stp in result["steps"]:
            pad = "&nbsp;" * 4 * max(0, stp["depth"] - 1)
            st.markdown(f"{pad}**{stp['label']}**", unsafe_allow_html=True)
            if stp["reasoning"]:
                st.markdown(f"{pad}<span class='cl-note'><i>{stp['reasoning']}</i></span>", unsafe_allow_html=True)
            if stp["selected_children"]:
                st.markdown(f"{pad}<span class='cl-note'>→ opened {', '.join(stp['selected_children'])}</span>",
                            unsafe_allow_html=True)


# ── Research tab ────────────────────────────────────────────────────────────
with tab_ask:
    ss.messages.setdefault(ss.doc_name, [])
    history = ss.messages[ss.doc_name]

    st.markdown("Ask a question about this document. Answers are grounded in the clauses, "
                "cite section numbers, and follow cross-references automatically.")

    if not history:
        st.markdown("**Sample questions:**")
        cols = st.columns(2)
        for i, q in enumerate(DOCUMENTS[ss.doc_name]["examples"]):
            if cols[i % 2].button(q, use_container_width=True, key=f"ex_{i}"):
                ss.pending = q
                st.rerun()

    for msg in history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_answer(msg["result"])
            else:
                st.markdown(msg["content"])

    question = ss.pending or st.chat_input("Ask about this document…")
    ss.pending = None
    if question:
        if client is None:
            st.error("Set ANTHROPIC_API_KEY in your .env to ask questions.")
        else:
            history.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Reading the document and following cross-references…"):
                    result = answer_question(index, question, client,
                                             follow_cross_refs=ss.settings["cross_refs"],
                                             resolve_definitions=ss.settings["definitions"])
                render_answer(result)
            history.append({"role": "assistant", "result": result})
            st.caption("Informational research aid, not legal advice.")


# ── Cross-Reference Map tab ─────────────────────────────────────────────────
with tab_xref:
    st.markdown("### Cross-Reference Map")
    st.markdown("Every internal pointer in the document — which clause **relies on** which, and which "
                "clauses **depend on** it. This is the web a lawyer traces by hand when reading a "
                "limitation, exception, or survival clause.")

    number_index = index_by_number(index["tree"])
    referenced_by = index.get("referenced_by", {})
    rows = [n for n in iter_nodes(index["tree"]) if n["cross_refs"] or referenced_by.get(n["number"])]

    focus = st.selectbox(
        "Focus on a clause",
        ["(show all)"] + [citation_label(n) for n in rows],
    )

    def xref_row(n: dict) -> None:
        outs = " ".join(f"<span class='cl-pill cl-pill-x'>§ {t}</span>" for t in n["cross_refs"])
        ins = " ".join(f"<span class='cl-pill'>§ {t}</span>" for t in referenced_by.get(n["number"], []))
        st.markdown(f"<div class='cl-card'><span class='cl-cite'>{citation_label(n)}</span></div>",
                    unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.markdown(f"<span class='cl-note'>refers out to →</span><br>{outs or '<span class=cl-note>—</span>'}",
                    unsafe_allow_html=True)
        c2.markdown(f"<span class='cl-note'>← referenced by</span><br>{ins or '<span class=cl-note>—</span>'}",
                    unsafe_allow_html=True)
        st.markdown("")

    if focus == "(show all)":
        st.caption(f"{len(rows)} clauses participate in the cross-reference network.")
        for n in rows:
            xref_row(n)
    else:
        node = next(n for n in rows if citation_label(n) == focus)
        xref_row(node)
        st.markdown("**Clause text**")
        st.markdown(node["text"])


# ── Defined Terms tab ───────────────────────────────────────────────────────
with tab_terms:
    st.markdown("### Defined Terms")
    st.markdown("The document's controlled vocabulary. In a contract, a capitalised term means exactly "
                "what the definitions say — no more, no less. Each entry shows where it is **defined** "
                "and everywhere it is **used**.")

    glossary = index["glossary"]
    usage = index.get("term_usage", {})
    query = st.text_input("Filter terms", "")
    terms = sorted(t for t in glossary if query.lower() in t.lower())
    st.caption(f"{len(terms)} of {len(glossary)} terms")

    for t in terms:
        g = glossary[t]
        where = f"§ {g['defined_in']}" if g.get("defined_in") else g["source"]
        used = usage.get(t, [])
        with st.expander(f"{t}  ·  {where}"):
            st.markdown(g["definition"])
            if used:
                pills = " ".join(f"<span class='cl-pill'>§ {u}</span>" for u in used)
                st.markdown(f"<span class='cl-note'>Used in:</span> {pills}", unsafe_allow_html=True)


# ── About tab ───────────────────────────────────────────────────────────────
with tab_about:
    st.markdown(
        """
### How CaseLens works

CaseLens replaces the embedding store of a classic RAG system with the document's
own structure. Legal instruments are written to be navigated — every obligation
sits at a numbered, citable address — so navigation, not vector similarity, is the
right retrieval primitive.

1. **Index** — the document is parsed into a clause tree; every node gets a
   one-sentence summary (generated bottom-up) plus its defined terms and
   cross-references.
2. **Navigate** — to answer a question, the model reads section summaries and
   chooses which branches to open, recursively. This is a greedy best-first
   search whose scoring function is legal reading, not cosine distance.
3. **Follow the threads** — the responsive clauses' cross-references are pulled
   in automatically (e.g. a liability cap that is *"subject to § 8.4"*), and the
   defined terms they use are resolved to their contractual meaning.
4. **Answer on the record** — synthesis is grounded strictly in the retrieved
   clauses, with pinpoint citations, and is told to flag silence rather than guess.

**Why a lawyer cares:** answers are auditable. Every statement carries a § cite,
the full clause text is one click away, the cross-reference web is explicit, and
the reasoning path shows exactly how each authority was reached.

_CaseLens is an informational research aid, not legal advice, and does not create
an attorney–client relationship._

---
Documents in this demo are the Common Paper Cloud Service Agreement and Mutual NDA,
used under CC BY 4.0.
        """
    )
