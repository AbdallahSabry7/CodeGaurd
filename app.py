import streamlit as st
import os
from dotenv import load_dotenv

load_dotenv()

os.environ["OPENROUTER_API_KEY"] = os.getenv("OPENROUTER_API_KEY")
os.environ["LANGSMITH_API_KEY"] = os.getenv("LANGSMITH_API_KEY")
os.environ['LANGCHAIN_TRACING_V2'] = 'true'
os.environ['LANGCHAIN_ENDPOINT'] = 'https://api.smith.langchain.com'
os.environ['LANGCHAIN_PROJECT'] = 'learning-langchain'

from graph import build_graph

st.set_page_config(
    page_title="CodeGuard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, .stApp {
    background-color: #0a0a0f;
    color: #e2e2e2;
    font-family: 'Syne', sans-serif;
}

.stApp { padding: 0; }

.block-container {
    padding: 2rem 3rem !important;
    max-width: 1400px !important;
}

.cg-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 2.5rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid #1e1e2e;
}
.cg-logo {
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 2rem;
    color: #ffffff;
    letter-spacing: -0.03em;
}
.cg-logo span { color: #4ade80; }
.cg-tagline {
    font-size: 0.78rem;
    color: #555570;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 0.2rem;
}

.cg-panel-title {
    font-size: 0.7rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #555570;
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.cg-panel-title::before {
    content: '';
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #4ade80;
}

.cg-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.72rem;
    font-family: 'JetBrains Mono', monospace;
    padding: 0.25rem 0.7rem;
    border-radius: 999px;
    font-weight: 700;
    letter-spacing: 0.05em;
}
.badge-pass    { background: #052e16; color: #4ade80; border: 1px solid #166534; }
.badge-fail    { background: #2d0a0a; color: #f87171; border: 1px solid #7f1d1d; }
.badge-error   { background: #2d1a00; color: #fb923c; border: 1px solid #92400e; }
.badge-running { background: #1a1a0a; color: #facc15; border: 1px solid #713f12; }
.badge-idle    { background: #111122; color: #555570; border: 1px solid #1e1e2e; }

.cg-steps {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    margin-bottom: 1.5rem;
}
.cg-step {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 0.9rem;
    border-radius: 8px;
    font-size: 0.8rem;
    border: 1px solid transparent;
}
.step-done   { background: #052e16; border-color: #166534; color: #4ade80; }
.step-active { background: #1a1a0a; border-color: #713f12; color: #facc15; }
.step-error  { background: #2d0a0a; border-color: #7f1d1d; color: #f87171; }
.step-idle   { background: #0f0f1a; border-color: #1e1e2e; color: #3a3a55; }
.step-icon   { font-size: 1rem; width: 1.2rem; text-align: center; }

.cg-code {
    background: #07070f;
    border: 1px solid #1e1e2e;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    line-height: 1.7;
    color: #a0a0c0;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 460px;
    overflow-y: auto;
}
.cg-code.error-box { border-color: #7f1d1d; color: #f87171; background: #0f0505; }
.cg-code::-webkit-scrollbar { width: 4px; }
.cg-code::-webkit-scrollbar-track { background: transparent; }
.cg-code::-webkit-scrollbar-thumb { background: #1e1e2e; border-radius: 2px; }

.cg-placeholder { color: #2a2a40; }

.stTextArea textarea {
    background: #07070f !important;
    border: 1px solid #1e1e2e !important;
    border-radius: 8px !important;
    color: #a0a0c0 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    line-height: 1.7 !important;
    caret-color: #4ade80;
}
.stTextArea textarea:focus {
    border-color: #4ade80 !important;
    box-shadow: 0 0 0 2px rgba(74,222,128,0.1) !important;
}

.stButton button {
    background: #4ade80 !important;
    color: #020f05 !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.05em !important;
    padding: 0.6rem 2rem !important;
    width: 100% !important;
    transition: opacity 0.15s !important;
}
.stButton button:hover { opacity: 0.85 !important; }
.stButton button:disabled { background: #1e1e2e !important; color: #3a3a55 !important; }

hr { border-color: #1e1e2e !important; margin: 1.5rem 0 !important; }

#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }
</style>
""", unsafe_allow_html=True)


st.markdown("""
<div class="cg-header">
  <div>
    <div class="cg-logo">Code<span>Guard</span></div>
    <div class="cg-tagline">Multi-agent Python analysis &amp; refactoring</div>
  </div>
</div>
""", unsafe_allow_html=True)


for key, default in {
    "running": False,
    "analyzer_report": "",
    "refactored_code": "",
    "validator_report": "",
    "final_verdict": "",
    "current_step": "idle",
    "error": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def render_steps():
    order = ["idle", "analyzer", "refactor", "validator", "done"]
    steps = [
        ("analyzer",  "🔍", "Analyzing code"),
        ("refactor",  "🔧", "Refactoring"),
        ("validator", "✅", "Validating"),
    ]
    current = st.session_state.current_step
    has_error = bool(st.session_state.error)

    html = '<div class="cg-steps">'
    for key, icon, label in steps:
        if has_error and current == key:
            cls, extra = "step-error", " ✗"
        elif current == "done":
            cls, extra = "step-done", ""
        else:
            ci = order.index(current) if current in order else 0
            si = order.index(key) if key in order else 0
            if si < ci:
                cls, extra = "step-done", ""
            elif si == ci:
                cls, extra = "step-active", " ⟵"
            else:
                cls, extra = "step-idle", ""
        html += f'<div class="cg-step {cls}"><span class="step-icon">{icon}</span>{label}{extra}</div>'
    html += "</div>"
    return html


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
    placeholder = "cg-placeholder" if not content else ""
    text = content if content else "Will appear here once ready..."
    return f'<div class="{cls} {placeholder}">{text}</div>'


left_col, right_col = st.columns([1, 1], gap="large")

with left_col:
    st.markdown('<div class="cg-panel-title">Input</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader("Upload a .py file", type=["py"], label_visibility="collapsed")
    code_input = uploaded.read().decode("utf-8") if uploaded else st.text_area(
        "Or paste your Python code",
        height=300,
        placeholder="# paste your Python code here...",
        label_visibility="collapsed"
    )

    run_btn = st.button(
        "▶  Run Analysis",
        disabled=st.session_state.running or not (code_input or "").strip()
    )

    st.markdown("---")
    steps_slot = st.empty()
    badge_slot  = st.empty()
    error_slot  = st.empty()

    steps_slot.markdown(render_steps(), unsafe_allow_html=True)
    badge_slot.markdown(render_badge(), unsafe_allow_html=True)

    if st.session_state.error:
        error_slot.markdown(render_code_block(st.session_state.error, is_error=True), unsafe_allow_html=True)

with right_col:
    tab1, tab2, tab3 = st.tabs(["📋 Analysis Report", "🔧 Refactored Code", "✅ Validator Report"])
    with tab1:
        report_slot = st.empty()
        report_slot.markdown(render_code_block(st.session_state.analyzer_report), unsafe_allow_html=True)
    with tab2:
        refactor_slot = st.empty()
        refactor_slot.markdown(render_code_block(st.session_state.refactored_code), unsafe_allow_html=True)
    with tab3:
        validator_slot = st.empty()
        validator_slot.markdown(render_code_block(st.session_state.validator_report), unsafe_allow_html=True)


if run_btn and (code_input or "").strip():
    st.session_state.update({
        "running": True,
        "analyzer_report": "",
        "refactored_code": "",
        "validator_report": "",
        "final_verdict": "",
        "current_step": "analyzer",
        "error": "",
    })

    report_slot.markdown(render_code_block(""), unsafe_allow_html=True)
    refactor_slot.markdown(render_code_block(""), unsafe_allow_html=True)
    validator_slot.markdown(render_code_block(""), unsafe_allow_html=True)
    steps_slot.markdown(render_steps(), unsafe_allow_html=True)
    badge_slot.markdown(render_badge(), unsafe_allow_html=True)
    error_slot.empty()

    try:
        app = build_graph()

        inputs = {
            "messages": [("user", code_input)],
            "original_code": code_input,
            "refactor_iterations": 0,
            "analyzer_report": "",
            "refactored_code": "",
            "validator_report": ""
        }

        for state in app.stream(inputs, stream_mode="values"):
            analyzer_report  = state.get("analyzer_report", "")
            refactored_code  = state.get("refactored_code", "")
            validator_report = state.get("validator_report", "")

            if analyzer_report and analyzer_report != st.session_state.analyzer_report:
                st.session_state.analyzer_report = analyzer_report
                st.session_state.current_step = "refactor"
                report_slot.markdown(render_code_block(analyzer_report), unsafe_allow_html=True)
                steps_slot.markdown(render_steps(), unsafe_allow_html=True)
                badge_slot.markdown(render_badge(), unsafe_allow_html=True)

            if refactored_code and refactored_code != st.session_state.refactored_code:
                st.session_state.refactored_code = refactored_code
                st.session_state.current_step = "validator"
                refactor_slot.markdown(render_code_block(refactored_code), unsafe_allow_html=True)
                steps_slot.markdown(render_steps(), unsafe_allow_html=True)
                badge_slot.markdown(render_badge(), unsafe_allow_html=True)

            if validator_report and validator_report != st.session_state.validator_report:
                st.session_state.validator_report = validator_report
                st.session_state.final_verdict = validator_report
                validator_slot.markdown(render_code_block(validator_report), unsafe_allow_html=True)
                badge_slot.markdown(render_badge(), unsafe_allow_html=True)

        st.session_state.current_step = "done"

    except Exception as e:
        st.session_state.error = str(e)
        error_slot.markdown(render_code_block(str(e), is_error=True), unsafe_allow_html=True)

    finally:
        st.session_state.running = False
        steps_slot.markdown(render_steps(), unsafe_allow_html=True)
        badge_slot.markdown(render_badge(), unsafe_allow_html=True)