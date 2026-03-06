import streamlit as st
import yaml
from typing import Any, Dict, List, Optional, Tuple
import io
import os
import re
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

APP_TITLE = "NormeCancelli – Assistente Normative (MVP)"

LOGO_PATH = "assets/logo_normecancelli.png"
DEFAULT_RULES_PATH = "rules.yaml"
DEFAULT_REFS_PATH = "norme_refs.yaml"

# ------------------------------
# Helpers: safe condition engine
# ------------------------------
def _safe_num(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")

OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "in": lambda a, b: a in b if isinstance(b, (list, tuple, set)) else False,
    "not_in": lambda a, b: a not in b if isinstance(b, (list, tuple, set)) else True,
    ">": lambda a, b: _safe_num(a) > _safe_num(b),
    ">=": lambda a, b: _safe_num(a) >= _safe_num(b),
    "<": lambda a, b: _safe_num(a) < _safe_num(b),
    "<=": lambda a, b: _safe_num(a) <= _safe_num(b),
    "exists": lambda a, b: a is not None,
    "missing": lambda a, b: a is None,
}

def check_clause(facts: Dict[str, Any], clause: Dict[str, Any]) -> bool:
    fact = clause.get("fact")
    op = clause.get("op", "==")
    val = clause.get("value")

    a = facts.get(fact, None)
    fn = OPS.get(op)
    if not fn:
        return False
    return bool(fn(a, val))

def check_when(facts: Dict[str, Any], when: Dict[str, Any]) -> bool:
    """
    when can be:
      - {"all": [clause, clause, ...]}
      - {"any": [clause, clause, ...]}
      - {"clause": clause}
      - {}  -> always true
    """
    if not when:
        return True
    if "clause" in when:
        return check_clause(facts, when["clause"])
    if "all" in when:
        return all(check_clause(facts, c) for c in when["all"])
    if "any" in when:
        return any(check_clause(facts, c) for c in when["any"])
    return True

# ------------------------------
# Reference library
# ------------------------------
def load_yaml_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_refs(path: str) -> Dict[str, Dict[str, Any]]:
    """
    Expected YAML:
      meta: ...
      items:
        - id: EN12453_5_1_3
          norm: UNI EN 12453:2022
          clause: 5.1.3
          title: ...
          note: ...
    Returns dict by id.
    """
    if not os.path.exists(path):
        return {}
    doc = load_yaml_file(path)
    items = doc.get("items", [])
    idx: Dict[str, Dict[str, Any]] = {}
    for it in items:
        rid = str(it.get("id", "")).strip()
        if rid:
            idx[rid] = it
    return idx

def resolve_ref(ref: str, ref_index: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # 1) direct id
    if ref in ref_index:
        return ref_index[ref]

    # 2) try to parse text like: "UNI EN 12453:2022 §5.1.3" or "EN 12453 5.1.3" or "Appendice A"
    txt = str(ref)
    code = None
    if "12453" in txt:
        code = "EN12453"
    elif "12978" in txt:
        code = "EN12978"
    elif "12604" in txt:
        code = "EN12604"
    elif "11894" in txt:
        code = "UNI11894_1"

    if not code:
        return None

    m = re.search(r"(Appendice\s+[A-Z]|\d+(?:\.\d+){0,4})", txt, re.IGNORECASE)
    if not m:
        return None
    clause = m.group(1).strip()
    if clause.lower().startswith("appendice"):
        letter = clause.split()[-1].upper()
        rid = f"{code}_APP_{letter}"
    else:
        rid = f"{code}_{clause.replace('.', '_')}"
    return ref_index.get(rid)

# ------------------------------
# PDF export
# ------------------------------
def build_pdf_bytes(title: str, facts: Dict[str, Any], answers: List[Tuple[str, Any]], result_blocks: List[Dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    x = 18 * mm
    y = height - 18 * mm
    line = 6.0 * mm

    def draw_wrapped(text: str, max_chars: int = 95):
        nonlocal y
        for paragraph in str(text).split("\n"):
            if not paragraph.strip():
                y -= line
                continue
            words = paragraph.split(" ")
            cur = ""
            for w in words:
                nxt = (cur + " " + w).strip()
                if len(nxt) <= max_chars:
                    cur = nxt
                else:
                    c.drawString(x, y, cur)
                    y -= line
                    cur = w
                    if y < 25 * mm:
                        c.showPage()
                        y = height - 18 * mm
            if cur:
                c.drawString(x, y, cur)
                y -= line
                if y < 25 * mm:
                    c.showPage()
                    y = height - 18 * mm

    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, title)
    y -= 2 * line

    c.setFont("Helvetica", 9)
    c.drawString(x, y, f"Generato: {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}")
    y -= 2 * line

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Risposte inserite")
    y -= 1.5 * line

    c.setFont("Helvetica", 10)
    for q, a in answers:
        draw_wrapped(f"- {q}: {a}")

    y -= 0.5 * line
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Indicazioni e checklist (MVP)")
    y -= 1.5 * line

    c.setFont("Helvetica", 10)
    for block in result_blocks:
        draw_wrapped(f"• {block.get('title','')}")
        body = block.get("body","").strip()
        if body:
            draw_wrapped(body)
        refs = block.get("refs", [])
        if refs:
            draw_wrapped("Riferimenti: " + ", ".join([str(r) for r in refs]))
        y -= 0.3 * line

    c.showPage()
    c.save()
    return buf.getvalue()

# ------------------------------
# App core
# ------------------------------
def get_node(rules: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    nodes = rules.get("nodes", {})
    if node_id not in nodes:
        raise KeyError(f"Nodo non trovato: {node_id}")
    return nodes[node_id]

def apply_facts(facts: Dict[str, Any], node: Dict[str, Any], choice_key: str, choice_value: Any):
    set_facts = node.get("set_facts", {})
    if isinstance(set_facts, dict) and choice_key in set_facts:
        mapping = set_facts[choice_key] or {}
        for k, v in mapping.items():
            facts[k] = v

    set_any = node.get("set_on_any", {})
    if isinstance(set_any, dict):
        for k, v in set_any.items():
            facts[k] = v

    if node.get("store_as"):
        facts[node["store_as"]] = choice_value

def resolve_next(node: Dict[str, Any], choice_key: str) -> Optional[str]:
    nxt = node.get("next")
    if isinstance(nxt, str):
        return nxt
    if isinstance(nxt, dict):
        if choice_key in nxt:
            return nxt[choice_key]
        return nxt.get("default")
    return None

def reset():
    for k in list(st.session_state.keys()):
        if k.startswith("nc_"):
            del st.session_state[k]

def header():
    col1, col2 = st.columns([1, 4])
    with col1:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
        else:
            st.write("🟦🟧")
    with col2:
        st.title(APP_TITLE)
        st.caption("Wizard operativo: fa domande, raccoglie fatti e propone checklist + riferimenti. Non sostituisce una consulenza in campo.")

def sidebar_refs(ref_index: Dict[str, Dict[str, Any]]):
    with st.sidebar.expander("📚 Libreria riferimenti", expanded=False):
        st.caption("Cerca per ID, norma, clausola o parole chiave. (Titoli brevi: niente testo integrale delle norme.)")
        q = st.text_input("Cerca", value="", placeholder="es. 12453 5.1.3, 'fotocellule', 'modifica sostanziale'...")
        if not ref_index:
            st.info("Nessuna libreria caricata.")
            return
        items = list(ref_index.values())
        if q.strip():
            ql = q.lower().strip()
            def hit(it):
                blob = " ".join([
                    str(it.get("id","")),
                    str(it.get("norm","")),
                    str(it.get("clause","")),
                    str(it.get("title","")),
                    " ".join(it.get("keywords", []) or []),
                ]).lower()
                return ql in blob
            items = [it for it in items if hit(it)]
        st.write(f"Trovati: **{len(items)}**")
        for it in items[:25]:
            with st.expander(f"{it['id']}  —  {it.get('clause','')}", expanded=False):
                st.write(f"**{it.get('norm','')}**")
                st.write(f"**{it.get('clause','')}** — {it.get('title','')}")
                note = (it.get("note") or "").strip()
                if note:
                    st.caption(note)
                st.code(it.get("id",""))
        if len(items) > 25:
            st.caption("…mostro solo i primi 25 risultati (per non impallare la pagina).")

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🟦", layout="centered")
    header()

    rules_path = st.sidebar.text_input("Percorso regole (YAML)", value=DEFAULT_RULES_PATH)
    refs_path = st.sidebar.text_input("Percorso libreria riferimenti (YAML)", value=DEFAULT_REFS_PATH)
    st.sidebar.button("🔄 Reset sessione", on_click=reset)

    try:
        rules = load_yaml_file(rules_path)
    except Exception as e:
        st.error(f"Non riesco a caricare {rules_path}. Errore: {e}")
        st.stop()

    ref_index = {}
    try:
        ref_index = load_refs(refs_path)
    except Exception:
        ref_index = {}

    sidebar_refs(ref_index)

    start_node = rules.get("start_node", "start")

    if "nc_node" not in st.session_state:
        st.session_state["nc_node"] = start_node
    if "nc_facts" not in st.session_state:
        st.session_state["nc_facts"] = {}
    if "nc_answers" not in st.session_state:
        st.session_state["nc_answers"] = []

    node_id = st.session_state["nc_node"]
    facts: Dict[str, Any] = st.session_state["nc_facts"]
    answers: List[Tuple[str, Any]] = st.session_state["nc_answers"]

    total = max(1, int(rules.get("estimated_questions", 10)))
    st.progress(min(1.0, len(answers) / total))

    node = get_node(rules, node_id)

    if node.get("type") == "end":
        st.subheader("✅ Risultato (MVP)")
        st.write(node.get("intro", "Ecco cosa emerge dalle risposte:"))

        results = rules.get("results", [])
        matched = []
        for block in results:
            when = block.get("when", {})
            if check_when(facts, when):
                matched.append(block)

        if not matched:
            st.info("Nessuna regola ha fatto match. (MVP) – puoi aggiungere più regole nel file rules.yaml.")
        else:
            for block in matched:
                with st.expander(block.get("title", "Indicazione"), expanded=True):
                    st.write(block.get("body", ""))

                    refs = block.get("refs", []) or []
                    if refs:
                        st.caption("Riferimenti: " + ", ".join([str(r) for r in refs]))

                        with st.expander("📌 Dettagli riferimenti", expanded=False):
                            for r in refs:
                                info = resolve_ref(str(r), ref_index)
                                if info:
                                    st.write(f"**{info.get('norm','')} – {info.get('clause','')}**")
                                    st.write(info.get("title",""))
                                    note = (info.get("note") or "").strip()
                                    if note:
                                        st.caption(note)
                                    st.code(info.get("id",""))
                                else:
                                    st.write(f"- {r}")

        st.divider()
        st.subheader("📌 Riepilogo risposte")
        for q, a in answers:
            st.write(f"**{q}**: {a}")

        pdf_bytes = build_pdf_bytes("NormeCancelli – Report (MVP)", facts, answers, matched)
        st.download_button(
            "⬇️ Scarica report PDF",
            data=pdf_bytes,
            file_name="normecancelli_report_mvp.pdf",
            mime="application/pdf",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("↩️ Ricomincia"):
                reset()
                st.rerun()
        with col2:
            st.caption("Suggerimento: per riferimenti puntuali usa ID tipo EN12453_5_1_3 dentro rules.yaml → refs: []")

        st.stop()

    st.subheader(node.get("title", "Domanda"))
    st.write(node.get("question", ""))

    ntype = node.get("type", "choice")
    choice_key = None
    choice_value = None

    if ntype == "yesno":
        choice_value = st.radio("Seleziona:", ["Sì", "No"], horizontal=True)
        choice_key = "yes" if choice_value == "Sì" else "no"

    elif ntype == "choice":
        options = node.get("options", [])
        if not options:
            st.error("Nodo 'choice' senza 'options' (rules.yaml).")
            st.stop()
        choice_value = st.selectbox("Seleziona:", options)
        choice_key = str(choice_value)

    elif ntype == "number":
        mn = node.get("min", 0)
        mx = node.get("max", 9999)
        step = node.get("step", 1)
        choice_value = st.number_input("Inserisci un numero:", min_value=mn, max_value=mx, step=step)
        choice_key = "number"

    elif ntype == "text":
        choice_value = st.text_input("Scrivi qui:")
        choice_key = "text"

    else:
        st.error(f"Tipo nodo sconosciuto: {ntype}")
        st.stop()

    colA, colB = st.columns([1, 1])
    with colA:
        back = st.button("⬅️ Indietro", use_container_width=True)
    with colB:
        nxt = st.button("Avanti ➡️", type="primary", use_container_width=True)

    if back:
        if answers:
            answers.pop()
            reset()
            st.session_state["nc_node"] = start_node
            st.session_state["nc_facts"] = {}
            st.session_state["nc_answers"] = answers
            st.rerun()
        else:
            st.warning("Sei già alla prima domanda.")
            st.stop()

    if nxt:
        if ntype == "text" and not str(choice_value).strip():
            st.warning("Scrivi qualcosa (anche solo 'n/d').")
            st.stop()

        apply_facts(facts, node, choice_key, choice_value)
        answers.append((node.get("question","Domanda"), choice_value))

        next_id = resolve_next(node, choice_key) or "end"
        st.session_state["nc_node"] = next_id
        st.session_state["nc_facts"] = facts
        st.session_state["nc_answers"] = answers
        st.rerun()

if __name__ == "__main__":
    main()
