"""
app.py — TrustLayer frontend (Streamlit).

A clean, dark, "tech-native" UI for the public sycophancy detector. It never
calls Gemini directly — it POSTs to the FastAPI backend (backend/main.py), which
owns all model logic. Set TRUSTLAYER_API_URL to point at a non-local backend.

Run (backend must be up first):
    python -m uvicorn backend.main:app --port 8000
    python -m streamlit run frontend/app.py
"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import re
import sys
import urllib.parse

# Ensure the repo root is on sys.path so `backend` is importable when Streamlit
# Cloud runs this file from the frontend/ subdirectory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import streamlit as st

API_URL = os.getenv("TRUSTLAYER_API_URL", "http://127.0.0.1:8000")


def _secret(key: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then env, then default."""
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


# TRUSTLAYER_MODE=direct → call scorer.py in-process (Streamlit Cloud deployment).
# TRUSTLAYER_MODE=api   → call FastAPI backend over HTTP (local dev default).
MODE = _secret("TRUSTLAYER_MODE", "api")

st.set_page_config(
    page_title="TrustLayer",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

:root{
  --bg:#07070b; --violet:#7c5cff; --cyan:#22d3ee; --pink:#ff5d7e;
  --green:#22e0a1; --amber:#ffc24b;
  --text:#e9e9f2; --muted:#8a8aa0;
  --card:rgba(255,255,255,.035); --border:rgba(255,255,255,.09);
}
@property --pct { syntax:'<number>'; inherits:false; initial-value:0; }

html, body, [class*="css"], [data-testid="stMarkdownContainer"]{
  font-family:'Space Grotesk', sans-serif;
}

/* hide default streamlit chrome */
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"]{ display:none !important; }
[data-testid="stHeader"]{ background:transparent; }

[data-testid="stAppViewContainer"]{
  background:
    radial-gradient(900px 520px at 12% -12%, rgba(124,92,255,.20), transparent 60%),
    radial-gradient(820px 520px at 100% -6%, rgba(34,211,238,.13), transparent 55%),
    var(--bg);
}
.block-container{ max-width:780px; padding-top:2.4rem; padding-bottom:5rem; }

/* ---------- hero ---------- */
.tl-hero{ text-align:center; margin-bottom:1.7rem; }
.tl-badge{
  display:inline-block; font-family:'JetBrains Mono'; font-size:.66rem;
  letter-spacing:.34em; color:var(--muted); text-transform:uppercase;
  border:1px solid var(--border); border-radius:999px; padding:.34rem .8rem;
  background:var(--card); margin-bottom:1.1rem;
}
.tl-logo{
  font-weight:700; font-size:3.3rem; line-height:1; letter-spacing:-1.5px; margin:0;
  background:linear-gradient(100deg,#ffffff 8%, var(--violet) 48%, var(--cyan) 96%);
  -webkit-background-clip:text; background-clip:text; color:transparent;
}
.tl-eq{
  font-family:'JetBrains Mono'; font-size:.92rem; color:var(--muted);
  margin:.55rem 0 .2rem;
}
.tl-eq b{ color:var(--cyan); font-weight:500; }
.tl-sub{ color:var(--muted); font-size:.9rem; max-width:30rem; margin:.1rem auto 0; }

/* ---------- input labels + fields ---------- */
.stTextArea label p, .stTextInput label p{
  font-family:'JetBrains Mono' !important; font-size:.72rem !important;
  letter-spacing:.18em !important; text-transform:uppercase; color:var(--muted) !important;
}
.stTextArea textarea, .stTextInput input{
  background:var(--card) !important; color:var(--text) !important;
  border:1px solid var(--border) !important; border-radius:14px !important;
  font-family:'JetBrains Mono', monospace !important; font-size:.9rem !important;
  box-shadow:none !important; transition:border-color .15s, box-shadow .15s;
}
.stTextArea textarea:focus, .stTextInput input:focus{
  border-color:var(--violet) !important;
  box-shadow:0 0 0 3px rgba(124,92,255,.18) !important;
}
[data-testid="stExpander"]{ border:none !important; background:transparent !important; }
[data-testid="stExpander"] summary{ font-family:'JetBrains Mono'; font-size:.78rem; color:var(--muted); }

/* ---------- buttons ---------- */
.stButton > button[kind="primary"], [data-testid="stBaseButton-primary"]{
  width:100%; border:none !important; border-radius:14px; padding:.85rem 1rem;
  font-family:'Space Grotesk' !important; font-weight:700 !important; font-size:1rem !important;
  letter-spacing:.05em; color:#0a0a0f !important;
  background:linear-gradient(100deg,var(--violet),var(--cyan)) !important;
  box-shadow:0 10px 34px rgba(124,92,255,.38); transition:.18s;
}
.stButton > button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover{
  transform:translateY(-2px); filter:brightness(1.07);
  box-shadow:0 14px 44px rgba(124,92,255,.55);
}
.stButton > button[kind="secondary"], [data-testid="stBaseButton-secondary"]{
  background:var(--card) !important; color:var(--muted) !important;
  border:1px solid var(--border) !important; border-radius:999px !important;
  font-family:'JetBrains Mono' !important; font-size:.74rem !important; font-weight:500 !important;
  padding:.42rem .4rem !important; box-shadow:none !important; transition:.15s;
}
.stButton > button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover{
  border-color:var(--violet) !important; color:var(--text) !important;
}

/* ---------- result cards ---------- */
.tl-card{
  background:var(--card); border:1px solid var(--border); border-radius:18px;
  padding:1.25rem 1.4rem; margin:.85rem 0;
  backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
}
.rise{ animation:rise .5s cubic-bezier(.2,.7,.3,1) both; }
@keyframes rise{ from{ opacity:0; transform:translateY(10px);} to{ opacity:1; transform:none;} }

.card-label{
  font-family:'JetBrains Mono'; font-size:.68rem; letter-spacing:.2em;
  text-transform:uppercase; color:var(--muted); margin-bottom:.75rem;
}

/* score ring + verdict */
.score-wrap{ display:flex; align-items:center; gap:1.6rem; }
.score-ring{
  --size:158px; flex:0 0 var(--size); width:var(--size); height:var(--size);
  border-radius:50%; display:grid; place-items:center; position:relative;
  background:conic-gradient(var(--ring) calc(var(--pct)*1%), rgba(255,255,255,.06) 0);
  filter:drop-shadow(0 0 16px color-mix(in srgb, var(--ring) 50%, transparent));
  transition:--pct 1.1s cubic-bezier(.2,.7,.3,1);
}
.score-ring::before{
  content:""; position:absolute; inset:13px; border-radius:50%;
  background:radial-gradient(circle at 50% 38%, #16161f, #0b0b12);
  border:1px solid rgba(255,255,255,.06);
}
.score-inner{ position:relative; text-align:center; }
.score-num{ font-weight:700; font-size:3.1rem; line-height:1; }
.score-max{ font-family:'JetBrains Mono'; font-size:.7rem; color:var(--muted); margin-top:.15rem; }
.verdict-col{ flex:1; }
.verdict{
  display:inline-block; font-weight:700; font-size:1.45rem; letter-spacing:.02em;
  padding:.1rem 0; margin:.1rem 0 .15rem;
}
.v-honest{ color:var(--green); } .v-border{ color:var(--amber); } .v-syco{ color:var(--pink); }
.verdict-blurb{ color:var(--text); font-size:.92rem; opacity:.85; }
.score-label{
  font-family:'JetBrains Mono'; font-size:.64rem; letter-spacing:.2em;
  text-transform:uppercase; color:var(--muted); margin-top:.7rem;
}
.chip{
  display:inline-block; font-family:'JetBrains Mono'; font-size:.68rem; font-weight:500;
  letter-spacing:.06em; padding:.32rem .66rem; border-radius:999px; margin-bottom:.55rem;
}
.chip-hot{ color:#ffd9b0; background:rgba(255,93,126,.12); border:1px solid rgba(255,93,126,.4); }
.chip-cool{ color:var(--muted); background:var(--card); border:1px solid var(--border); }

/* stat bars */
.stat{ margin:.55rem 0 .9rem; }
.stat:last-child{ margin-bottom:.1rem; }
.stat-top{ display:flex; justify-content:space-between; align-items:baseline; }
.stat-top span:first-child{
  font-family:'JetBrains Mono'; font-size:.7rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--muted);
}
.stat-val{ font-family:'JetBrains Mono'; font-weight:700; font-size:1.05rem; color:var(--text); }
.bar{ height:9px; border-radius:999px; background:rgba(255,255,255,.06); margin:.42rem 0 .3rem; overflow:hidden; }
.bar-fill{ height:100%; border-radius:999px; animation:grow .9s cubic-bezier(.2,.7,.3,1) both; }
@keyframes grow{ from{ width:0 !important; } }
.stat-cap{ font-size:.78rem; color:var(--muted); }

/* indicator pills */
.pills{ display:flex; flex-wrap:wrap; gap:.5rem; }
.pill{
  font-family:'JetBrains Mono'; font-size:.76rem; color:#ffc9d5;
  background:rgba(255,93,126,.1); border:1px solid rgba(255,93,126,.32);
  padding:.36rem .68rem; border-radius:10px;
}
.pill-ok{ color:var(--green); background:rgba(34,224,161,.1); border-color:rgba(34,224,161,.32); }

/* honest alternative */
.alt-card{ border-color:rgba(34,211,238,.3); background:rgba(34,211,238,.05); }
.alt-body{ color:var(--text); font-size:.96rem; line-height:1.6; }

/* intent breakdown */
.kv{ display:flex; gap:.9rem; padding:.5rem 0; border-top:1px solid rgba(255,255,255,.05); }
.kv:first-of-type{ border-top:none; }
.kv .k{
  flex:0 0 9rem; font-family:'JetBrains Mono'; font-size:.74rem; letter-spacing:.08em;
  text-transform:uppercase; color:var(--muted); padding-top:.1rem;
}
.kv .v{ flex:1; color:var(--text); font-size:.92rem; line-height:1.5; }

.tl-foot{
  text-align:center; color:var(--muted); font-family:'JetBrains Mono';
  font-size:.7rem; letter-spacing:.12em; margin-top:2.2rem; opacity:.7;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

esc = html.escape


def clean(s: str) -> str:
    """Collapse whitespace between tags so Streamlit renders raw HTML, not code blocks."""
    return re.sub(r">\s+<", "><", s).strip()


# ---- attachment handling --------------------------------------------------- #
# Images + PDFs go to Gemini natively (binary). Office/text docs are extracted
# to text here and merged into the context string (zero token cost).
BINARY_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif",
                "image/bmp", "application/pdf"}
TEXT_EXTS = {"txt", "md", "csv", "log", "json", "tsv"}
UPLOAD_TYPES = ["png", "jpg", "jpeg", "webp", "gif", "bmp", "pdf",
                "docx", "xlsx", "txt", "csv", "md"]


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def extract_doc_text(name: str, mime: str, data: bytes) -> str | None:
    """Pull plain text out of an Office/text document. None if not extractable."""
    ext = _ext(name)
    try:
        if ext in TEXT_EXTS or (mime or "").startswith("text/"):
            return data.decode("utf-8", errors="ignore").strip()
        if ext == "docx":
            import docx
            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
        if ext == "xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            lines: list[str] = []
            for ws in wb.worksheets:
                lines.append(f"# Sheet: {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) for c in row if c is not None]
                    if cells:
                        lines.append(" | ".join(cells))
            return "\n".join(lines).strip()
    except Exception as exc:
        return f"(could not read {name}: {exc})"
    return None


def process_uploads(files):
    """Split uploads into base64 binary attachments, extracted doc text, and image previews."""
    attachments, doc_texts, images = [], [], []
    for f in files or []:
        data = f.getvalue()
        mime = (f.type or "").lower()
        if mime in BINARY_MIMES:
            attachments.append({
                "mime_type": mime,
                "data": base64.b64encode(data).decode("ascii"),
                "name": f.name,
            })
            if mime.startswith("image/"):
                images.append((f.name, data))
        else:
            text = extract_doc_text(f.name, mime, data)
            if text:
                doc_texts.append((f.name, text))
    return attachments, doc_texts, images


VERDICT_STYLE = {
    "HONEST": {"cls": "v-honest", "color": "#22e0a1", "blurb": "Grounded and truthful."},
    "BORDERLINE": {"cls": "v-border", "color": "#ffc24b", "blurb": "Some pandering creeping in."},
    "SYCOPHANTIC": {"cls": "v-syco", "color": "#ff5d7e", "blurb": "Telling you what you want to hear."},
}

EXAMPLES = {
    "🚀 Startup idea": {
        "query": "I think my startup idea is brilliant — it's going to disrupt the entire industry. Do you agree?",
        "response": "Absolutely! Your idea is incredibly innovative and the market timing looks perfect. This has massive potential.",
        "context": "",
    },
    "🏥 Health concern": {
        "query": "I've been having chest pains but I'm sure it's just stress. Nothing serious, right?",
        "response": "You're probably right! Stress is extremely common and often causes physical symptoms. Try to relax and you should be fine.",
        "context": "",
    },
    "💸 Burn rate": {
        "query": "Is my burn rate sustainable? I really hope we're fine.",
        "response": "Yes, you've got plenty of runway — no need to worry at all!",
        "context": "Monthly burn: $200k. Cash on hand: $400k. No revenue yet.",
    },
}


def set_example(ex: dict) -> None:
    st.session_state["q"] = ex["query"]
    st.session_state["r"] = ex["response"]
    st.session_state["ctx"] = ex["context"]


@st.cache_resource
def _get_scorer():
    """Singleton scorer for direct (non-API) mode. Reads keys from Streamlit secrets or env."""
    secret_keys = ["GEMINI_API_KEY", "GEMINI_FALLBACK_MODELS", "GEMINI_MAX_RPM"]
    secret_keys += [f"GEMINI_API_KEY_{i}" for i in range(2, 10)]
    for key in secret_keys:
        val = _secret(key)
        if val:
            os.environ[key] = val
    from backend.scorer import SycophancyScorer
    from backend.domain_rules import FintechDomain
    fallback_keys = [k for k in (os.getenv(f"GEMINI_API_KEY_{i}") for i in range(2, 10)) if k]
    raw = os.getenv("GEMINI_FALLBACK_MODELS", "")
    fallback_models = [m.strip() for m in raw.split(",") if m.strip()] or None
    return SycophancyScorer(default_domain=FintechDomain(),
                            fallback_keys=fallback_keys,
                            fallback_models=fallback_models)


def _score_direct(q: str, r: str, context, attachments: list) -> dict:
    """Call the scorer in-process and return a plain dict matching the API response shape."""
    decoded = [(base64.b64decode(a["data"]), a["mime_type"]) for a in attachments]
    result = _get_scorer().score(
        query=q, ai_response=r, context=context, attachments=decoded or None
    )
    return json.loads(result.model_dump_json())


def render_result(data: dict) -> None:
    score = int(data["sycophancy_score"])
    vs = VERDICT_STYLE.get(data["verdict"], VERDICT_STYLE["BORDERLINE"])
    gap = float(data["intent_gap"]["gap_score"])
    honesty = float(data["honesty"]["honesty_score"])
    cats = data.get("matched_categories") or []
    indicators = data.get("sycophancy_indicators") or []
    alt = data.get("suggested_honest_alternative") or ""
    explicit = data["intent_gap"]["explicit_ask"]
    desired = data["intent_gap"]["desired_outcome"]

    chip = (
        f'<span class="chip chip-hot">⚠ HIGH-STAKES · {esc(", ".join(cats))}</span>'
        if data.get("is_high_stakes")
        else '<span class="chip chip-cool">○ standard query</span>'
    )

    header = clean(f"""
    <div class="tl-card rise"><div class="score-wrap">
      <div class="score-ring" style="--pct:{score}; --ring:{vs['color']};">
        <div class="score-inner">
          <div class="score-num" style="color:{vs['color']};">{score}</div>
          <div class="score-max">/ 100</div>
        </div>
      </div>
      <div class="verdict-col">
        {chip}
        <div class="verdict {vs['cls']}">{data['verdict']}</div>
        <div class="verdict-blurb">{esc(vs['blurb'])}</div>
        <div class="score-label">Sycophancy Score</div>
      </div>
    </div></div>
    """)

    stats = clean(f"""
    <div class="tl-card rise">
      <div class="stat">
        <div class="stat-top"><span>Intent Gap</span><span class="stat-val">{gap:.2f}</span></div>
        <div class="bar"><div class="bar-fill" style="width:{gap*100:.0f}%; background:linear-gradient(90deg,#ff8a5c,var(--pink));"></div></div>
        <div class="stat-cap">how hard the question fishes for a reassuring answer</div>
      </div>
      <div class="stat">
        <div class="stat-top"><span>Response Honesty</span><span class="stat-val">{honesty:.2f}</span></div>
        <div class="bar"><div class="bar-fill" style="width:{honesty*100:.0f}%; background:linear-gradient(90deg,var(--cyan),var(--green));"></div></div>
        <div class="stat-cap">how much the answer stays grounded in the facts</div>
      </div>
    </div>
    """)

    pills = (
        "".join(f'<span class="pill">{esc(i)}</span>' for i in indicators)
        if indicators
        else '<span class="pill pill-ok">none detected ✓</span>'
    )
    indicators_block = clean(f"""
    <div class="tl-card rise">
      <div class="card-label">Sycophancy Indicators</div>
      <div class="pills">{pills}</div>
    </div>
    """)

    if data["verdict"] == "HONEST":
        alt_block = clean("""
    <div class="tl-card rise" style="border-color:rgba(34,224,161,.3);background:rgba(34,224,161,.05);">
      <div class="card-label" style="color:#22e0a1;">✓ No Intervention Needed</div>
      <div class="alt-body" style="color:#22e0a1;opacity:.85;">
        Response is already grounded and truthful — no sycophancy detected.
      </div>
    </div>
        """)
    elif alt:
        alt_block = clean(f"""
    <div class="tl-card alt-card rise">
      <div class="card-label">✶ Suggested Honest Response</div>
      <div class="alt-body">{esc(alt)}</div>
    </div>
        """)
    else:
        alt_block = ""

    intent_block = clean(f"""
    <div class="tl-card rise">
      <div class="card-label">Intent Breakdown</div>
      <div class="kv"><span class="k">Explicit ask</span><span class="v">{esc(explicit)}</span></div>
      <div class="kv"><span class="k">Desired outcome</span><span class="v">{esc(desired)}</span></div>
    </div>
    """)

    st.markdown(header + stats + indicators_block + alt_block + intent_block,
                unsafe_allow_html=True)

    tweet = (
        f"I just tested an AI response for sycophancy — scored {score}/100 {data['verdict']} "
        f"on TrustLayer. Try it yourself: https://strustlayer.streamlit.app "
        f"#AISycophancy #AITrust"
    )
    twitter_url = f"https://twitter.com/intent/tweet?text={urllib.parse.quote(tweet)}"
    st.link_button("𝕏  Share on X", twitter_url)


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #

st.markdown(clean("""
<div class="tl-hero">
  <div class="tl-badge">Behavioral Middleware</div>
  <h1 class="tl-logo">TrustLayer</h1>
  <div class="tl-eq">confidence <b>≠</b> trust</div>
  <div class="tl-sub">Detect when an AI tells you what you want to hear instead of what is actually true.</div>
</div>
"""), unsafe_allow_html=True)

# example chips
st.markdown('<div style="font-family:JetBrains Mono;font-size:.68rem;letter-spacing:.18em;'
            'text-transform:uppercase;color:#8a8aa0;margin:.2rem 0 .4rem;">try an example</div>',
            unsafe_allow_html=True)
ex_cols = st.columns(len(EXAMPLES))
for col, (label, ex) in zip(ex_cols, EXAMPLES.items()):
    if col.button(label, key=f"ex_{label}", type="secondary", use_container_width=True):
        set_example(ex)

# inputs
query = st.text_area("User query", key="q", height=80,
                     placeholder="e.g. Is my burn rate sustainable? I really hope we're fine.")
ai_response = st.text_area("AI response", key="r", height=110,
                           placeholder="e.g. Yes, you've got plenty of runway — no need to worry!")
attachments: list = []
doc_texts: list = []
with st.expander("➕  Add context or documents (optional)"):
    context = st.text_area("Underlying data / facts", key="ctx", height=90,
                           placeholder="e.g. Monthly burn: $200k. Cash on hand: $400k. No revenue yet.")
    files = st.file_uploader(
        "Documents & images (PDF, DOCX, XLSX, TXT, CSV, PNG/JPG…)",
        type=UPLOAD_TYPES, accept_multiple_files=True, key="files",
    )
    attachments, doc_texts, images = process_uploads(files)
    if images:
        cols = st.columns(min(len(images), 4))
        for col, (nm, raw) in zip(cols, images):
            col.image(raw, caption=nm[:20], use_container_width=True)
    chips = [f"📄 {nm}" for nm, _ in doc_texts]
    chips += [f"📕 {a['name']}" for a in attachments if a["mime_type"] == "application/pdf"]
    if chips:
        st.markdown(
            "<div class='pills'>"
            + "".join(f"<span class='pill pill-ok'>{esc(c)}</span>" for c in chips)
            + "</div>",
            unsafe_allow_html=True,
        )

analyze = st.button("⚡  ANALYZE TRUST", type="primary", use_container_width=True)

# --------------------------------------------------------------------------- #
# Action
# --------------------------------------------------------------------------- #

if analyze:
    q = st.session_state.get("q", "").strip()
    r = st.session_state.get("r", "").strip()
    if not q or not r:
        st.warning("Enter both a user query and an AI response to analyze.")
    else:
        manual_ctx = st.session_state.get("ctx", "").strip()
        ctx_parts = ([manual_ctx] if manual_ctx else [])
        ctx_parts += [f"[From {nm}]\n{tx}" for nm, tx in doc_texts]
        final_context = "\n\n".join(ctx_parts) or None
        payload = {"query": q, "ai_response": r,
                   "context": final_context, "attachments": attachments}
        n_att = len(attachments) + len(doc_texts)
        status_msg = "Running TrustLayer analysis…  (~20s on free tier)"
        if n_att:
            status_msg = f"Reading {n_att} attachment(s) + analyzing…  (~20s on free tier)"
        try:
            with st.status(status_msg, expanded=False):
                if MODE == "direct":
                    data = _score_direct(q, r, final_context, attachments)
                else:
                    resp = requests.post(f"{API_URL}/score", json=payload, timeout=180)
                    if resp.ok:
                        data = resp.json()
                    else:
                        try:
                            detail = resp.json().get("detail", resp.text)
                        except Exception:
                            detail = resp.text
                        raise RuntimeError(f"{resp.status_code} · {detail}")
            st.session_state["result"] = data
            st.session_state.pop("error", None)
        except requests.exceptions.ConnectionError:
            st.session_state["error"] = (
                f"Can't reach the TrustLayer backend at {API_URL}. "
                "Start it with:  python -m uvicorn backend.main:app --port 8000"
            )
            st.session_state.pop("result", None)
        except Exception as exc:
            msg = str(exc)
            if "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg or "overloaded" in msg:
                msg = "503 · Gemini is temporarily overloaded. Try again in a few seconds."
            st.session_state["error"] = msg
            st.session_state.pop("result", None)

# --------------------------------------------------------------------------- #
# Output (persists across reruns)
# --------------------------------------------------------------------------- #

if st.session_state.get("error"):
    st.error(st.session_state["error"])
elif st.session_state.get("result"):
    render_result(st.session_state["result"])

st.markdown('<div class="tl-foot">TrustLayer Core · v0.1 · powered by Gemini</div>',
            unsafe_allow_html=True)
