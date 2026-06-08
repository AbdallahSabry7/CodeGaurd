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

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body, .stApp { background: radial-gradient(1100px 560px at 72% -12%, #14142433, #0a0a0f 60%); color: #e2e2e2; font-family: 'Syne', sans-serif; }
.block-container { padding: 2rem 3rem !important; max-width: 1500px !important; }

.cg-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid #1e1e2e; }
.cg-brand { display: flex; align-items: center; gap: 0.9rem; }
.cg-mark { font-size: 2rem; filter: drop-shadow(0 0 12px rgba(74,222,128,0.35)); }
.cg-logo { font-weight: 800; font-size: 2rem; color: #fff; letter-spacing: -0.03em; line-height: 1; }
.cg-logo span { color: #4ade80; }
.cg-tagline { font-size: 0.72rem; color: #555570; letter-spacing: 0.16em; text-transform: uppercase; margin-top: 0.35rem; }

.cg-panel-title { font-size: 0.7rem; letter-spacing: 0.15em; text-transform: uppercase; color: #555570; margin-bottom: 0.8rem; display: flex; align-items: center; gap: 0.5rem; }
.cg-panel-title::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: #4ade80; box-shadow: 0 0 8px #4ade80; }

.cg-badge { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.72rem; font-family: 'JetBrains Mono', monospace; padding: 0.3rem 0.8rem; border-radius: 999px; font-weight: 700; letter-spacing: 0.05em; }
.badge-pass { background: #052e16; color: #4ade80; border: 1px solid #166534; }
.badge-fail { background: #2d0a0a; color: #f87171; border: 1px solid #7f1d1d; }
.badge-running { background: #1a1a0a; color: #facc15; border: 1px solid #713f12; }
.badge-idle { background: #111122; color: #555570; border: 1px solid #1e1e2e; }

.cg-code { background: #07070f; border: 1px solid #1e1e2e; border-radius: 10px; padding: 1rem 1.2rem; font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; line-height: 1.7; color: #a0a0c0; white-space: pre-wrap; word-break: break-word; max-height: 560px; overflow-y: auto; }
.cg-code.error-box { border-color: #7f1d1d; color: #f87171; background: #0f0505; }
.cg-code::-webkit-scrollbar { width: 5px; }
.cg-code::-webkit-scrollbar-thumb { background: #1e1e2e; border-radius: 3px; }
.cg-placeholder { color: #2a2a40; }

/* ---- creative loader ---- */
.cg-loader { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 3.6rem 1rem; text-align: center; animation: cgFade 0.4s ease; }
.cg-orbit { position: relative; width: 120px; height: 120px; margin-bottom: 1.8rem; }
.cg-orbit .ring { position: absolute; inset: 0; border-radius: 50%; border: 2px solid transparent; }
.cg-orbit .r1 { border-top-color: #4ade80; animation: cgSpin 1.1s linear infinite; }
.cg-orbit .r2 { inset: 14px; border-right-color: #22d3ee; animation: cgSpin 1.6s linear infinite reverse; }
.cg-orbit .r3 { inset: 28px; border-bottom-color: #a78bfa; animation: cgSpin 2.1s linear infinite; }
.cg-orbit .core { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 2.4rem; animation: cgPulse 1.6s ease-in-out infinite; }
.cg-stage { font-family: 'JetBrains Mono', monospace; font-size: 0.95rem; color: #e2e2e2; font-weight: 700; }
.cg-substage { font-size: 0.72rem; color: #555570; margin-top: 0.4rem; letter-spacing: 0.14em; text-transform: uppercase; }
.cg-bar { position: relative; width: 260px; height: 4px; background: #12121f; border-radius: 999px; margin-top: 1.6rem; overflow: hidden; }
.cg-bar::after { content: ''; position: absolute; left: -40%; top: 0; height: 100%; width: 40%; background: linear-gradient(90deg, transparent, #4ade80, transparent); animation: cgSlide 1.2s ease-in-out infinite; }

@keyframes cgSpin { to { transform: rotate(360deg); } }
@keyframes cgPulse { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.12); opacity: 0.7; } }
@keyframes cgSlide { 0% { left: -40%; } 100% { left: 100%; } }
@keyframes cgFade { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }

/* inputs */
.stTextArea textarea { background: #07070f !important; border: 1px solid #1e1e2e !important; border-radius: 10px !important; color: #a0a0c0 !important; font-family: 'JetBrains Mono', monospace !important; font-size: 0.78rem !important; line-height: 1.7 !important; caret-color: #4ade80; }
.stTextArea textarea:focus { border-color: #4ade80 !important; box-shadow: 0 0 0 2px rgba(74,222,128,0.1) !important; }
.stSelectbox div[data-baseweb="select"] > div { background: #07070f !important; border-color: #1e1e2e !important; color: #a0a0c0 !important; font-family: 'JetBrains Mono', monospace !important; }
.stButton button { background: #4ade80 !important; color: #020f05 !important; border: none !important; border-radius: 10px !important; font-family: 'Syne', sans-serif !important; font-weight: 700 !important; font-size: 0.9rem !important; letter-spacing: 0.05em !important; padding: 0.7rem 2rem !important; width: 100% !important; transition: opacity .15s, transform .15s !important; }
.stButton button:hover { opacity: 0.9 !important; transform: translateY(-1px); }
.stButton button:disabled { background: #1e1e2e !important; color: #3a3a55 !important; }
.stTabs [data-baseweb="tab-list"] { gap: 0.4rem; }
.stTabs [data-baseweb="tab"] { color: #555570; font-family: 'Syne', sans-serif; }
.stTabs [aria-selected="true"] { color: #4ade80 !important; }
hr { border-color: #1e1e2e !important; margin: 1.2rem 0 !important; }
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="cg-header">
  <div class="cg-brand">
    <div class="cg-mark">🛡️</div>
    <div>
      <div class="cg-logo">Code<span>Guard</span></div>
      <div class="cg-tagline">Multi-agent code analysis &amp; refactoring</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

LANG_OPTIONS = {"Python": "python", "C++": "cpp", "Java": "java"}
UPLOAD_TYPES = ["py", "cpp", "cc", "cxx", "hpp", "h", "java"]

DEFAULTS = {
    "running": False,
    "source_language": "python",
    "architect_report": None,   # original (first-pass) report only
    "final_code": "",
    "final_report": "",
    "verdict": "",
    "current_step": "idle",
    "error": "",
    "_shown_step": None,
}
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)

# ---------- helpers ----------
def format_architect_report(report):
    if not report:
        return ""
    if isinstance(report, str):
        return report
    if hasattr(report, "model_dump"):
        report = report.model_dump()
    out = [f"VERDICT: {report.get('global_verdict', '-')}",
           f"LANGUAGE: {report.get('language', '-')}", ""]
    solid = report.get("solid_violations", []) or []
    out.append(f"━━ SOLID VIOLATIONS ({len(solid)}) ━━")
    for v in solid:
        out.append(f"• [{v.get('severity')}] {v.get('principle')} @ {v.get('location')} (conf {v.get('confidence')})")
        out.append(f"    why: {v.get('reasoning')}")
        out.append(f"    fix: {v.get('refactor_directive')}")
    if not solid:
        out.append("    none")
    cc = report.get("clean_code_violations", []) or []
    out += ["", f"━━ CLEAN CODE ({len(cc)}) ━━"]
    for v in cc:
        out.append(f"• [{v.get('severity')}] {v.get('issue_name')} @ {v.get('location')} (conf {v.get('confidence')})")
        out.append(f"    why: {v.get('reasoning')}")
        out.append(f"    fix: {v.get('refactor_directive')}")
    if not cc:
        out.append("    none")
    comp = report.get("complexity_findings", []) or []
    out += ["", f"━━ COMPLEXITY ({len(comp)}) ━━"]
    for c in comp:
        flag = "improvable" if c.get("improvable") else "inherent"
        tgt = f" -> {c.get('target')}" if c.get("target") else ""
        out.append(f"• {c.get('type')} {c.get('current')}{tgt} [{flag}] @ {c.get('location')}")
        out.append(f"    why: {c.get('reasoning')}")
        if c.get("refactor_directive"):
            out.append(f"    fix: {c.get('refactor_directive')}")
    if not comp:
        out.append("    none")
    return "\n".join(out)

def pick_final_code(state):
    """Deliverable: translated-back code for non-python, else final refactored python."""
    refactored = state.get("refactored_code")
    if isinstance(refactored, list):
        refactored = refactored[-1] if refactored else ""
    translated = state.get("translated_code")
    if state.get("source_language", "python") != "python" and translated:
        return translated
    return refactored or ""

def code_block(content, is_error=False):
    cls = "cg-code error-box" if is_error else "cg-code"
    if not content:
        return '<div class="cg-code"><span class="cg-placeholder">Will appear here once the run finishes…</span></div>'
    return f'<div class="{cls}">{html.escape(str(content))}</div>'

STAGES = {
    "analyzer":   ("Scanning structure", "static analysis"),
    "architect":  ("Auditing SOLID & clean code", "architect agent"),
    "refactor":   ("Refactoring code", "refactor agent"),
    "executer":   ("Running in sandbox", "execution"),
    "regression": ("Verifying behavior", "regression check"),
    "translate":  ("Translating back", "translator"),
    "report":     ("Compiling final report", "report agent"),
}

def loader_html(step):
    title, sub = STAGES.get(step, ("Working", "processing"))
    return f"""
<div class="cg-loader">
  <div class="cg-orbit">
    <div class="ring r1"></div><div class="ring r2"></div><div class="ring r3"></div>
    <div class="core">🛡️</div>
  </div>
  <div class="cg-stage">{html.escape(title)}</div>
  <div class="cg-substage">{html.escape(sub)}</div>
  <div class="cg-bar"></div>
</div>
"""

def verdict_badge():
    v = st.session_state.verdict
    if st.session_state.error or (v and "FAIL" in v):
        return '<span class="cg-badge badge-fail">● FAILED</span>'
    if v:
        return f'<span class="cg-badge badge-pass">● {html.escape(v)}</span>'
    if st.session_state.running:
        return '<span class="cg-badge badge-running">● RUNNING</span>'
    return '<span class="cg-badge badge-idle">● IDLE</span>'

# ---------- layout ----------
left_col, right_col = st.columns([1, 1.25], gap="large")

with left_col:
    st.markdown('<div class="cg-panel-title">Input</div>', unsafe_allow_html=True)
    lang_label = st.selectbox("Source language", list(LANG_OPTIONS.keys()), label_visibility="collapsed")
    st.session_state.source_language = LANG_OPTIONS[lang_label]
    uploaded = st.file_uploader("Upload a source file", type=UPLOAD_TYPES, label_visibility="collapsed")
    code_input = uploaded.read().decode("utf-8") if uploaded else st.text_area(
        "Or paste your code", height=300, placeholder="# paste your code here…", label_visibility="collapsed",
    )
    run_btn = st.button("▶  Run Analysis", disabled=st.session_state.running or not (code_input or "").strip())
    st.markdown("---")
    st.markdown('<div class="cg-panel-title">Status</div>', unsafe_allow_html=True)
    badge_slot = st.empty()
    badge_slot.markdown(verdict_badge(), unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="cg-panel-title">Result</div>', unsafe_allow_html=True)
    output_slot = st.empty()

def render_results():
    with output_slot.container():
        tab_report, tab_code, tab_arch = st.tabs(
            ["🛡️ Final Report", "🔧 Final Code", "🧠 Architect Report"]
        )
        with tab_report:
            if st.session_state.final_report:
                st.markdown(st.session_state.final_report)
            else:
                st.markdown(code_block(""), unsafe_allow_html=True)
        with tab_code:
            st.markdown(code_block(st.session_state.final_code), unsafe_allow_html=True)
        with tab_arch:
            st.markdown(
                code_block(format_architect_report(st.session_state.architect_report)),
                unsafe_allow_html=True,
            )

if not st.session_state.running:
    render_results()

# ---------- run ----------
if run_btn and (code_input or "").strip():
    st.session_state.update({
        "running": True, "architect_report": None, "final_code": "",
        "final_report": "", "verdict": "", "current_step": "analyzer",
        "error": "", "_shown_step": None,
    })
    badge_slot.markdown(verdict_badge(), unsafe_allow_html=True)
    output_slot.markdown(loader_html("analyzer"), unsafe_allow_html=True)

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
            "execution_result": "",
            "refactor_syntax_error": None,
            "translator_syntax_error": None,
        }
        for state in app.stream(inputs, stream_mode="values"):
            # capture ORIGINAL architect report only (first occurrence)
            ar = state.get("architect_report")
            if ar and st.session_state.architect_report is None:
                st.session_state.architect_report = ar
                st.session_state.current_step = "refactor"

            fc = pick_final_code(state)
            if fc:
                st.session_state.final_code = fc

            if state.get("execution_result"):
                st.session_state.current_step = "regression"
            if state.get("regression_verdict"):
                st.session_state.current_step = "report"
            if st.session_state.source_language != "python" and state.get("translated_code"):
                st.session_state.current_step = "report"

            fr = state.get("final_report")
            if fr:
                st.session_state.final_report = fr

            step = st.session_state.current_step
            if step != st.session_state._shown_step:
                output_slot.markdown(loader_html(step), unsafe_allow_html=True)
                st.session_state._shown_step = step

        # derive verdict
        fr = st.session_state.final_report
        for kw in ("SOLVED", "PARTIAL", "FAILED"):
            if fr and kw in fr:
                st.session_state.verdict = kw
                break
        if not st.session_state.verdict:
            st.session_state.verdict = "DONE"
        st.session_state.current_step = "done"
    except Exception as exc:
        st.session_state.error = str(exc)
    finally:
        st.session_state.running = False

    badge_slot.markdown(verdict_badge(), unsafe_allow_html=True)
    if st.session_state.error:
        output_slot.markdown(code_block(st.session_state.error, is_error=True), unsafe_allow_html=True)
    else:
        render_results()