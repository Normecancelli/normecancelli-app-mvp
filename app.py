import streamlit as st
import yaml
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

APP_TITLE = "NormeCancelli – Assistente Normative (MVP)"

# ------------------------------
# Helpers: safe condition engine
# ------------------------------
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

def _safe_num(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")

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
            draw_wrapped("Riferimenti: " + ", ".join(refs))
        y -= 0.3 * line

    c.showPage()
    c.save()
    return buf.getvalue()

# ------------------------------
# App
# ------------------------------
def load_rules(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_node(rules: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    nodes = rules.get("nodes", {})
    if node_id not in nodes:
        raise KeyError(f"Nodo non trovato: {node_id}")
    return nodes[node_id]

def apply_facts(facts: Dict[str, Any], node: Dict[str, Any], choice_key: str, choice_value: Any):
    """
    Node can define:
      set_facts:
        <choice_key>:
          fact1: value
          fact2: value
      or:
      set_on_any:
        fact: value
    """
    set_facts = node.get("set_facts", {})
    if isinstance(set_facts, dict) and choice_key in set_facts:
        mapping = set_facts[choice_key] or {}
        for k, v in mapping.items():
            facts[k] = v

    set_any = node.get("set_on_any", {})
    if isinstance(set_any, dict):
        for k, v in set_any.items():
            facts[k] = v

    # always store raw answer too
    if node.get("store_as"):
        facts[node["store_as"]] = choice_value

def resolve_next(node: Dict[str, Any], choice_key: str) -> Optional[str]:
    nxt = node.get("next")
    if isinstance(nxt, str):
        return nxt
    if isinstance(nxt, dict):
        # mapping by choice key or default
        if choice_key in nxt:
            return nxt[choice_key]
        return nxt.get("default")
    return None

def reset():
    for k in list(st.session_state.keys()):
        if k.startswith("nc_"):
            del st.session_state[k]

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="centered")
    st.title("🧠 " + APP_TITLE)
    st.caption("Un prototipo: fa domande, raccoglie fatti e propone una checklist. Non sostituisce una consulenza tecnica in campo.")

    rules_path = st.sidebar.text_input("Percorso regole (YAML)", value="rules.yaml")
    st.sidebar.button("🔄 Reset sessione", on_click=reset)

    try:
        rules = load_rules(rules_path)
    except Exception as e:
        st.error(f"Non riesco a caricare {rules_path}. Errore: {e}")
        st.stop()

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

    # progress (rough)
    total = max(1, int(rules.get("estimated_questions", 10)))
    st.progress(min(1.0, len(answers) / total))

    node = get_node(rules, node_id)

    # If end node: show results
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
                    refs = block.get("refs", [])
                    if refs:
                        st.caption("Riferimenti: " + ", ".join(refs))

        st.divider()
        st.subheader("📌 Riepilogo risposte")
        for q, a in answers:
            st.write(f"**{q}**: {a}")

        # export
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
            st.caption("Suggerimento: apri rules.yaml e personalizza domande e regole. È pensato per essere estensibile.")

        st.stop()

    # Render question node
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
        # normalize key as the option itself (string)
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
        # go back one answer if possible
        if answers:
            answers.pop()
            # naive backtracking: restart and replay answers
            prev_answers = list(answers)
            reset()
            st.session_state["nc_node"] = start_node
            st.session_state["nc_facts"] = {}
            st.session_state["nc_answers"] = []
            # replay
            for q, a in prev_answers:
                # replay uses stored "node_trace" if present
                pass
            st.rerun()
        else:
            st.warning("Sei già alla prima domanda.")
            st.stop()

    if nxt:
        # basic validation for text
        if ntype == "text" and not str(choice_value).strip():
            st.warning("Scrivi qualcosa (anche solo 'n/d').")
            st.stop()

        apply_facts(facts, node, choice_key, choice_value)
        answers.append((node.get("question","Domanda"), choice_value))

        next_id = resolve_next(node, choice_key)
        if not next_id:
            # fallback to end
            next_id = "end"

        st.session_state["nc_node"] = next_id
        st.session_state["nc_facts"] = facts
        st.session_state["nc_answers"] = answers
        st.rerun()

if __name__ == "__main__":
    main()
