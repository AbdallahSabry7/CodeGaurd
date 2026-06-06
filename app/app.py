import os
import html

import streamlit as st

from helpers.config import get_settings

settings = get_settings()
os.environ["OPENROUTER_API_KEY"] = settings.OPENROUTER_API_KEY
os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT

from graph import build_graph

st.set_page_config(
    page_title="CodeGuard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body, .stApp { background-color: #0a0a0f; color: #e2e2e2; font-family: 'Syne', sans-serif; }
.block-container { padding: 2rem 3rem !important; max-width: 1500px !important; }
.cg-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid #1e1e2e; }
.cg-logo { font-family: 'Syne', sans-serif; font-weight: 800; font-size: 2rem; color: #ffffff; letter-spacing: -0.03em; }
.cg-logo span { color: #4ade80; }
.cg-tagline { font-size: 0.78rem; color: #555570; letter-spacing: 0.12em; text-transform: uppercase; margin-top: 0.2rem; }
.cg-panel-title { font-size: 0.7rem; letter-spacing: 0.15em; text-transform: uppercase; color: #555570; margin-bottom: 0.8rem; display: flex; align-items: center; gap: 0.5rem; }
.cg-panel-title::before { content: ''; display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #4ade80; }
.cg-badge { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.72rem; font-family: 'JetBrains Mono', monospace; padding: 0.25rem 0.7rem; border-radius: 999px; font-weight: 700; letter-spacing: 0.05em; }
.badge-pass { background: #052e16; color: #4ade80; border: 1px solid #166534; }
.badge-fail { background: #2d0a0a; color: #f87171; border: 1px solid #7f1d1d; }
.badge-error { background: #2d1a00; color: #fb923c; border: 1px solid #92400e; }
.badge-running { background: #1a1a0a; color: #facc15; border: 1px solid #713f12; }
.badge-idle { background: #111122; color: #555570; border: 1px solid #1e1e2e; }
.cg-steps { display: flex; flex-direction: column; gap: 0.6rem; margin: 1rem 0 1.5rem; }
.cg-step { display: flex; align-items: center; gap: 0.75rem; padding: 0.6rem 0.9rem; border-radius: 8px; font-size: 0.8rem; border: 1px solid transparent; transition: all 0.2s; }
.step-done { background: #052e16; border-color: #166534; color: #4ade80; }
.step-active { background: #1a1a0a; border-color: #713f12; color: #facc15; }
.step-error { background: #2d0a0a; border-color: #7f1d1d; color: #f87171; }
.step-idle { background: #0f0f1a; border-color: #1e1e2e; color: #3a3a55; }
.step-icon { font-size: 1rem; width: 1.2rem; text-align: center; }
.cg-verdict { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; padding: 0.6rem 1rem; border-radius: 8px; margin-bottom: 1rem; font-weight: 700; }
.verdict-pass { background: #052e16; color: #4ade80; border: 1px solid #166534; }
.verdict-fail { background: #2d0a0a; color: #f87171; border: 1px solid #7f1d1d; }
.cg-code { background: #07070f; border: 1px solid #1e1e2e; border-radius: 8px; padding: 1rem 1.2rem; font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; line-height: 1.7; color: #a0a0c0; white-space: pre-wrap; word-break: break-word; max-height: 520px; overflow-y: auto; }
.cg-code.error-box { border-color: #7f1d1d; color: #f87171; background: #0f0505; }
.cg-code::-webkit-scrollbar { width: 4px; }
.cg-code::-webkit-scrollbar-track { background: transparent; }
.cg-code::-webkit-scrollbar-thumb { background: #1e1e2e; border-radius: 2px; }
.cg-placeholder { color: #2a2a40; }
.stTextArea textarea { background: #07070f !important; border: 1px solid #1e1e2e !important; border-radius: 8px !important; color: #a0a0c0 !important; font-family: 'JetBrains Mono', monospace !important; font-size: 0.78rem !important; line-height: 1.7 !important; caret-color: #4ade80; }
.stTextArea textarea:focus { border-color: #4ade80 !important; box-shadow: 0 0 0 2px rgba(74,222,128,0.1) !important; }
.stSelectbox div[data-baseweb="select"] > div { background: #07070f !important; border-color: #1e1e2e !important; color: #a0a0c0 !important; font-family: 'JetBrains Mono', monospace !important; }
.stButton button { background: #4ade80 !important; color: #020f05 !important; border: none !important; border-radius: 8px !important; font-family: 'Syne', sans-serif !important; font-weight: 700 !important; font-size: 0.85rem !important; letter-spacing: 0.05em !important; padding: 0.6rem 2rem !important; width: 100% !important; transition: opacity 0.15s !important; }
.stButton button:hover { opacity: 0.85 !important; }
.stButton button:disabled { background: #1e1e2e !important; color: #3a3a55 !important; }
.stTabs [data-baseweb="tab-list"] { gap: 0.25rem; }
.stTabs [data-baseweb="tab"] { color: #555570; font-family: 'Syne', sans-serif; }
.stTabs [aria-selected="true"] { color: #4ade80 !important; }
hr { border-color: #1e1e2e !important; margin: 1.2rem 0 !important; }
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }
</style>""", unsafe_allow_html=True)

st.markdown("""<div class="cg-header">
  <div>
    <div class="cg-logo">Code<span>Guard</span></div>
    <div class="cg-tagline">Multi-agent code analysis &amp; refactoring</div>
  </div>
</div>""", unsafe_allow_html=True)

LANG_OPTIONS = {"Python": "python", "C++": "cpp", "Java": "java"}
UPLOAD_TYPES = ["py", "cpp", "cc", "cxx", "hpp", "h", "java"]

DEFAULTS = {
    "running": False,
    "source_language": "python",
    "architect_report": None,
    "analyzer_report": "",
    "refactored_code": "",
    "comparator_report": "",
    "execution_result": "",
    "translated_code": "",
    "final_verdict": "",
    "current_step": "idle",
    "error": "",
}
for _key, _default in DEFAULTS.items():
    st.session_state.setdefault(_key, _default)


def format_architect_report(report):
    """Render the architect's JSON report as readable text."""
    if not report:
        return ""
    if isinstance(report, str):
        return report
    out = [f"VERDICT:  {report.get('global_verdict', '-')}",
           f"LANGUAGE: {report.get('language', '-')}", ""]

    solid = report.get("solid_violations", []) or []
    out.append(f"━━ SOLID VIOLATIONS ({len(solid)}) ━━")
    for v in solid:
        out.append(f"• [{v.get('severity')}] {v.get('principle')} @ {v.get('location')} (conf {v.get('confidence')})")
        out.append(f"    why: {v.get('reasoning')}")
        out.append(f"    fix: {v.get('refactor_directive')}")
    if not solid:
        out.append("  none")

    cc = report.get("clean_code_violations", []) or []
    out.append("")
    out.append(f"━━ CLEAN CODE ({len(cc)}) ━━")
    for v in cc:
        out.append(f"• [{v.get('severity')}] {v.get('issue_name')} @ {v.get('location')} (conf {v.get('confidence')})")
        out.append(f"    why: {v.get('reasoning')}")
        out.append(f"    fix: {v.get('refactor_directive')}")
    if not cc:
        out.append("  none")

    comp = report.get("complexity_findings", []) or []
    out.append("")
    out.append(f"━━ COMPLEXITY ({len(comp)}) ━━")
    for c in comp:
        flag = "improvable" if c.get("improvable") else "inherent"
        tgt = f" -> {c.get('target')}" if c.get("target") else ""
        out.append(f"• {c.get('type')} {c.get('current')}{tgt} [{flag}] @ {c.get('location')}")
        out.append(f"    why: {c.get('reasoning')}")
        if c.get("refactor_directive"):
            out.append(f"    fix: {c.get('refactor_directive')}")
    if not comp:
        out.append("  none")

    rej = report.get("rejected_issues", []) or []
    if rej:
        out.append("")
        out.append(f"━━ REJECTED FALSE POSITIVES ({len(rej)}) ━━")
        for r in rej:
            out.append(f"• ({r.get('category')}) {r.get('issue_name')}: {r.get('rejection_reason')}")
    return "\n".join(out)


def render_steps():
    steps = [
        ("analyzer", "🔍", "Analyzing"),
        ("architect", "🧠", "Architecting"),
        ("refactor", "🔧", "Refactoring"),
        ("comparator", "📊", "Comparing"),
        ("executer", "▶️", "Executing"),
    ]
    if st.session_state.source_language != "python":
        steps.append(("translate", "🌐", "Translating back"))
    order = ["idle"] + [k for k, _, _ in steps] + ["done"]
    current = st.session_state.current_step
    has_error = bool(st.session_state.error)
    ci = order.index(current) if current in order else 0
    out = '<div class="cg-steps">'
    for key, icon, label in steps:
        si = order.index(key)
        if has_error and current == key:
            cls, extra = "step-error", " ✗"
        elif current == "done":
            cls, extra = "step-done", ""
        elif si < ci:
            cls, extra = "step-done", ""
        elif si == ci:
            cls, extra = "step-active", " ⟵"
        else:
            cls, extra = "step-idle", ""
        out += f'<div class="cg-step {cls}"><span class="step-icon">{icon}</span>{label}{extra}</div>'
    return out + "</div>"


def render_badge():
    if st.session_state.error:
        return '<span class="cg-badge badge-error">● ERROR</span>'
    if st.session_state.final_verdict:
        if "PASS" in st.session_state.final_verdict:
            return '<span class="cg-badge badge-pass">● PASS</span>'
        return '<span class="cg-badge badge-fail">● FAIL</span>'
    if st.session_state.running:
        return '<span class="cg-badge badge-running">● RUNNING</span>'
    return '<span class="cg-badge badge-idle">● IDLE</span>'


def render_code_block(content, is_error=False):
    cls = "cg-code error-box" if is_error else "cg-code"
    if not content:
        return f'<div class="{cls} cg-placeholder">Will appear here once ready…</div>'
    return f'<div class="{cls}">{html.escape(str(content))}</div>'


left_col, right_col = st.columns([1, 1.2], gap="large")

with left_col:
    st.markdown('<div class="cg-panel-title">Input</div>', unsafe_allow_html=True)
    lang_label = st.selectbox("Source language", list(LANG_OPTIONS.keys()), label_visibility="collapsed")
    st.session_state.source_language = LANG_OPTIONS[lang_label]

    uploaded = st.file_uploader("Upload a source file", type=UPLOAD_TYPES, label_visibility="collapsed")
    code_input = uploaded.read().decode("utf-8") if uploaded else st.text_area(
        "Or paste your code",
        height=280,
        placeholder="# paste your code here...",
        label_visibility="collapsed",
    )
    run_btn = st.button(
        "▶  Run Analysis",
        disabled=st.session_state.running or not (code_input or "").strip(),
    )

    st.markdown("---")
    badge_slot = st.empty()
    steps_slot = st.empty()
    error_slot = st.empty()
    badge_slot.markdown(render_badge(), unsafe_allow_html=True)
    steps_slot.markdown(render_steps(), unsafe_allow_html=True)
    if st.session_state.error:
        error_slot.markdown(render_code_block(st.session_state.error, is_error=True), unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="cg-panel-title">Output</div>', unsafe_allow_html=True)
    tab_arch, tab_ref, tab_cmp, tab_exec, tab_tr = st.tabs([
        "🧠 Architect Report",
        "🔧 Refactored Code",
        "📊 Comparator",
        "▶️ Execution",
        "🌐 Translated",
    ])
    with tab_arch:
        arch_slot = st.empty()
        arch_slot.markdown(render_code_block(format_architect_report(st.session_state.architect_report)), unsafe_allow_html=True)
    with tab_ref:
        refactor_slot = st.empty()
        refactor_slot.markdown(render_code_block(st.session_state.refactored_code), unsafe_allow_html=True)
    with tab_cmp:
        comparator_slot = st.empty()
        comparator_slot.markdown(render_code_block(st.session_state.comparator_report), unsafe_allow_html=True)
    with tab_exec:
        executer_slot = st.empty()
        executer_slot.markdown(render_code_block(st.session_state.execution_result), unsafe_allow_html=True)
    with tab_tr:
        translated_slot = st.empty()
        if st.session_state.source_language == "python":
            translated_slot.markdown(render_code_block("Source language is Python — no back-translation needed."), unsafe_allow_html=True)
        else:
            translated_slot.markdown(render_code_block(st.session_state.translated_code), unsafe_allow_html=True)


if run_btn and (code_input or "").strip():
    st.session_state.update({
        "running": True,
        "architect_report": None,
        "analyzer_report": "",
        "refactored_code": "",
        "comparator_report": "",
        "execution_result": "",
        "translated_code": "",
        "final_verdict": "",
        "current_step": "analyzer",
        "error": "",
    })
    for slot in (arch_slot, refactor_slot, comparator_slot, executer_slot, translated_slot):
        slot.markdown(render_code_block(""), unsafe_allow_html=True)
    badge_slot.markdown(render_badge(), unsafe_allow_html=True)
    steps_slot.markdown(render_steps(), unsafe_allow_html=True)
    error_slot.empty()

    def _refresh():
        steps_slot.markdown(render_steps(), unsafe_allow_html=True)
        badge_slot.markdown(render_badge(), unsafe_allow_html=True)

    try:
        app = build_graph()
        inputs = {
            "messages": [("user", code_input)],
            "original_code": code_input,
            "source_language": st.session_state.source_language,
            "destination_language": "python",
            "language": "python",
            "refactor_iterations": 0,
            "analyzer_report": "",
            "original_analyzer_report": "",
            "refactored_code": "",
            "comparator_report": "",
            "execution_result": "",
            "refactor_syntax_error": None,
            "translator_syntax_error": None,
        }
        for state in app.stream(inputs, stream_mode="values"):
            analyzer_report = state.get("analyzer_report", "")
            architect_report = state.get("architect_report")
            refactored_code = state.get("refactored_code", "")
            comparator_report = state.get("comparator_report", "")
            execution_result = state.get("execution_result", "")
            translated_code = state.get("translated_code", "")

            if analyzer_report and analyzer_report != st.session_state.analyzer_report:
                st.session_state.analyzer_report = analyzer_report
                st.session_state.current_step = "architect"
                _refresh()

            if architect_report and architect_report != st.session_state.architect_report:
                st.session_state.architect_report = architect_report
                st.session_state.current_step = "refactor"
                arch_slot.markdown(render_code_block(format_architect_report(architect_report)), unsafe_allow_html=True)
                _refresh()

            if refactored_code and refactored_code != st.session_state.refactored_code:
                st.session_state.refactored_code = refactored_code
                st.session_state.current_step = "comparator"
                refactor_slot.markdown(render_code_block(refactored_code), unsafe_allow_html=True)
                _refresh()

            if comparator_report and comparator_report != st.session_state.comparator_report:
                st.session_state.comparator_report = comparator_report
                st.session_state.current_step = "executer"
                comparator_slot.markdown(render_code_block(comparator_report), unsafe_allow_html=True)
                _refresh()

            if execution_result and execution_result != st.session_state.execution_result:
                st.session_state.execution_result = execution_result
                st.session_state.final_verdict = execution_result
                st.session_state.current_step = (
                    "translate" if st.session_state.source_language != "python" else "done"
                )
                executer_slot.markdown(render_code_block(execution_result), unsafe_allow_html=True)
                _refresh()

            if translated_code and translated_code != st.session_state.translated_code:
                st.session_state.translated_code = translated_code
                translated_slot.markdown(render_code_block(translated_code), unsafe_allow_html=True)
                _refresh()

        st.session_state.current_step = "done"
    except Exception as exc:
        st.session_state.error = str(exc)
        error_slot.markdown(render_code_block(str(exc), is_error=True), unsafe_allow_html=True)
    finally:
        st.session_state.running = False
        _refresh()