"""
ui_components.py
----------------
Premium UI theme and reusable render helpers for the Streamlit app.

Everything visual lives here so app.py stays about behavior. The palette
matches the brief exactly:

    Primary   #2563EB    Secondary #7C3AED    Accent  #06B6D4
    Background#0F172A    Surface   #1E293B     Text    #F8FAFC / #CBD5E1
    Success   #22C55E    Warning   #F59E0B     Error   #EF4444

No business logic here; no filesystem access beyond reading image bytes
for inline previews.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import streamlit as st
import re


def _c(html: str) -> str:
    """Compact HTML to one line so Streamlit never renders it as a code block."""
    return re.sub(r"\n\s*", "", html).strip()


# --------------------------------------------------------------------------- #
# Palette (single source of truth, also injected as CSS variables)
# --------------------------------------------------------------------------- #

PALETTE = {
    "primary": "#2563EB",
    "secondary": "#7C3AED",
    "accent": "#06B6D4",
    "bg": "#0F172A",
    "surface": "#1E293B",
    "surface_2": "#233046",
    "text": "#F8FAFC",
    "text_muted": "#CBD5E1",
    "text_faint": "#94A3B8",
    "border": "#334155",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "error": "#EF4444",
}

_EXT_COLORS = {
    "jpg": "#2563EB",
    "jpeg": "#2563EB",
    "png": "#7C3AED",
    "webp": "#06B6D4",
    "gif": "#F59E0B",
}


THEME_CSS = """
<style>
:root {
  --primary:#2563EB; --secondary:#7C3AED; --accent:#06B6D4;
  --bg:#0F172A; --surface:#1E293B; --surface2:#233046;
  --text:#F8FAFC; --muted:#CBD5E1; --faint:#94A3B8; --border:#334155;
  --success:#22C55E; --warning:#F59E0B; --error:#EF4444;
  --radius:18px; --radius-sm:12px;
  --shadow:0 10px 30px rgba(2,6,23,.45);
  --shadow-lg:0 24px 60px rgba(2,6,23,.55);
  --ease:cubic-bezier(.16,1,.3,1);
}

/* ---- base ---- */
.stApp { background:
    radial-gradient(1200px 600px at 12% -10%, rgba(37,99,235,.18), transparent 60%),
    radial-gradient(1000px 620px at 100% 0%, rgba(124,58,237,.16), transparent 55%),
    var(--bg);
}
.block-container { padding-top:1.6rem; padding-bottom:4rem; max-width:1320px; }
html, body, [class*="css"] { font-family:'Inter','Segoe UI',system-ui,-apple-system,sans-serif; }
#MainMenu, footer, header [data-testid="stStatusWidget"] { visibility:hidden; }
::-webkit-scrollbar { width:10px; height:10px; }
::-webkit-scrollbar-thumb { background:var(--border); border-radius:10px; }
::-webkit-scrollbar-thumb:hover { background:#41506b; }

/* ---- sidebar ---- */
section[data-testid="stSidebar"] {
  background:linear-gradient(180deg,#0d1526,#0f172a);
  border-right:1px solid var(--border);
}
section[data-testid="stSidebar"] .stButton>button { width:100%; }

/* ---- headings & text ---- */
h1,h2,h3,h4 { color:var(--text); letter-spacing:-.02em; }
p, span, label, .stMarkdown { color:var(--muted); }

/* ---- buttons ---- */
.stButton>button {
  border-radius:var(--radius-sm); border:1px solid var(--border);
  background:var(--surface); color:var(--text); font-weight:600;
  padding:.5rem .9rem; transition:transform .18s var(--ease), box-shadow .18s var(--ease), background .18s var(--ease), border-color .18s var(--ease);
}
.stButton>button:hover { transform:translateY(-2px); border-color:var(--primary); box-shadow:0 8px 22px rgba(37,99,235,.25); }
.stButton>button:active { transform:translateY(0); }
.stButton>button[kind="primary"] {
  background:linear-gradient(135deg,var(--primary),var(--secondary));
  border:none; color:#fff; box-shadow:0 10px 26px rgba(37,99,235,.4);
}
.stButton>button[kind="primary"]:hover { box-shadow:0 16px 34px rgba(124,58,237,.5); }

/* ---- inputs ---- */
.stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"]>div,
.stMultiSelect div[data-baseweb="select"]>div {
  background:var(--surface)!important; color:var(--text)!important;
  border-radius:var(--radius-sm)!important; border:1px solid var(--border)!important;
}
.stTextInput input:focus { border-color:var(--primary)!important; box-shadow:0 0 0 3px rgba(37,99,235,.25)!important; }
div[data-baseweb="tag"] { background:linear-gradient(135deg,var(--primary),var(--secondary))!important; border:none!important; }

/* ---- tabs ---- */
.stTabs [data-baseweb="tab-list"] { gap:.4rem; border-bottom:1px solid var(--border); }
.stTabs [data-baseweb="tab"] {
  background:transparent; color:var(--faint); border-radius:10px 10px 0 0;
  padding:.5rem 1rem; font-weight:600; transition:color .2s var(--ease);
}
.stTabs [aria-selected="true"] { color:var(--text)!important; background:rgba(37,99,235,.12); }

/* ============ custom components ============ */

/* hero */
.hero {
  position:relative; overflow:hidden; border-radius:26px; padding:2.2rem 2.4rem;
  background:linear-gradient(120deg,#111c33 0%,#15213b 45%,#1b1638 100%);
  border:1px solid var(--border); box-shadow:var(--shadow-lg); margin-bottom:1.6rem;
  animation:rise .6s var(--ease) both;
}
.hero::after {
  content:""; position:absolute; inset:0;
  background:radial-gradient(600px 200px at 85% -40%, rgba(6,182,212,.35), transparent 60%);
  pointer-events:none;
}
.hero .eyebrow {
  display:inline-flex; align-items:center; gap:.5rem; font-size:.72rem; font-weight:700;
  letter-spacing:.18em; text-transform:uppercase; color:var(--accent);
  background:rgba(6,182,212,.1); border:1px solid rgba(6,182,212,.3);
  padding:.3rem .7rem; border-radius:999px;
}
.hero h1 { margin:.7rem 0 .3rem; font-size:2.4rem; font-weight:800;
  background:linear-gradient(90deg,#fff,#c7d2fe); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
.hero p { margin:0; color:var(--muted); max-width:60ch; }

/* stat cards */
.stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:1rem; margin:.4rem 0 1.4rem; }
.stat {
  position:relative; overflow:hidden; padding:1.15rem 1.25rem; border-radius:var(--radius);
  background:linear-gradient(180deg,var(--surface),#182236); border:1px solid var(--border);
  box-shadow:var(--shadow); transition:transform .22s var(--ease), border-color .22s var(--ease);
  animation:rise .5s var(--ease) both;
}
.stat:hover { transform:translateY(-4px); border-color:var(--primary); }
.stat .ic { width:42px; height:42px; border-radius:12px; display:grid; place-items:center; font-size:1.2rem; margin-bottom:.7rem; }
.stat .val { font-size:1.9rem; font-weight:800; color:var(--text); line-height:1; }
.stat .lbl { font-size:.8rem; color:var(--faint); margin-top:.35rem; text-transform:uppercase; letter-spacing:.08em; }
.stat .bar { position:absolute; left:0; top:0; height:100%; width:4px; }

/* section header */
.section-h { display:flex; align-items:center; justify-content:space-between; margin:.4rem 0 .8rem; }
.section-h h2 { font-size:1.25rem; margin:0; }
.section-h .hint { color:var(--faint); font-size:.85rem; }

/* image card */
.img-card {
  border-radius:var(--radius); overflow:hidden; background:var(--surface);
  border:1px solid var(--border); box-shadow:var(--shadow);
  transition:transform .25s var(--ease), box-shadow .25s var(--ease), border-color .25s var(--ease);
  animation:fade .45s var(--ease) both;
}
.img-card:hover { transform:translateY(-6px); box-shadow:var(--shadow-lg); border-color:var(--primary); }
.img-frame { position:relative; aspect-ratio:1/1; background:#0b1220; overflow:hidden; }
.img-frame img { width:100%; height:100%; object-fit:cover; display:block; transition:transform .5s var(--ease); }
.img-card:hover .img-frame img { transform:scale(1.06); }
.img-badge {
  position:absolute; top:.55rem; left:.55rem; font-size:.62rem; font-weight:800; letter-spacing:.06em;
  text-transform:uppercase; color:#fff; padding:.2rem .5rem; border-radius:7px;
  backdrop-filter:blur(6px); background:rgba(15,23,42,.6); border:1px solid rgba(255,255,255,.12);
}
.img-meta { padding:.7rem .8rem .4rem; }
.img-meta .nm { font-size:.8rem; color:var(--text); font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.img-meta .sub { display:flex; justify-content:space-between; font-size:.72rem; color:var(--faint); margin-top:.25rem; }

/* skeleton */
.skeleton { aspect-ratio:1/1; border-radius:var(--radius); border:1px solid var(--border);
  background:linear-gradient(100deg,#131d31 30%,#1c2942 50%,#131d31 70%); background-size:200% 100%;
  animation:shimmer 1.3s infinite linear; }

/* category chip */
.cat-row { display:flex; flex-wrap:wrap; gap:.55rem; margin:.2rem 0 1rem; }
.cat-chip {
  display:inline-flex; align-items:center; gap:.5rem; padding:.45rem .8rem; border-radius:999px;
  background:var(--surface); border:1px solid var(--border); color:var(--muted); font-size:.82rem; font-weight:600;
  transition:border-color .2s var(--ease), color .2s var(--ease), transform .2s var(--ease);
}
.cat-chip:hover { border-color:var(--accent); color:var(--text); transform:translateY(-2px); }
.cat-chip .dot { width:8px; height:8px; border-radius:50%; background:var(--accent); }
.cat-chip .n { color:var(--faint); font-weight:700; }

/* empty state */
.empty {
  text-align:center; padding:3.2rem 1.5rem; border-radius:var(--radius);
  border:1px dashed var(--border); background:rgba(30,41,59,.4);
}
.empty .em { font-size:2.4rem; }
.empty h3 { margin:.6rem 0 .3rem; color:var(--text); }
.empty p { color:var(--faint); margin:0; }

/* pill / status */
.pill { display:inline-flex; align-items:center; gap:.4rem; padding:.3rem .7rem; border-radius:999px;
  font-size:.78rem; font-weight:700; }
.pill.ok { background:rgba(34,197,94,.14); color:#4ade80; border:1px solid rgba(34,197,94,.3); }
.pill.warn { background:rgba(245,158,11,.14); color:#fbbf24; border:1px solid rgba(245,158,11,.3); }

/* animations */
@keyframes rise { from{opacity:0; transform:translateY(14px);} to{opacity:1; transform:none;} }
@keyframes fade { from{opacity:0;} to{opacity:1;} }
@keyframes shimmer { from{background-position:200% 0;} to{background-position:-200% 0;} }
@media (prefers-reduced-motion: reduce){ *{animation:none!important; transition:none!important;} }

/* responsive */
@media (max-width: 640px){
  .hero{ padding:1.5rem 1.3rem; } .hero h1{ font-size:1.7rem; }
  .block-container{ padding-left:.6rem; padding-right:.6rem; }
}
</style>
"""


# --------------------------------------------------------------------------- #
# Injection
# --------------------------------------------------------------------------- #


def inject_theme() -> None:
    """Inject the global theme CSS once per page render."""
    st.markdown(THEME_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Small render helpers (return HTML strings or render directly)
# --------------------------------------------------------------------------- #


def hero(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    """Big centered page title. Subtitle/eyebrow intentionally not rendered."""
    st.markdown(
        _c(f"""
        <div style="text-align:center; padding:.6rem 0 1.4rem;">
          <h1 style="margin:0; font-size:2.6rem; font-weight:800; letter-spacing:-.02em;
              background:linear-gradient(90deg,#fff,#c7d2fe);
              -webkit-background-clip:text; background-clip:text;
              -webkit-text-fill-color:transparent;">{title}</h1>
        </div>
        """),
        unsafe_allow_html=True,
    )


def _stat_card(icon: str, value: str, label: str, tint: str) -> str:
    return _c(f"""
    <div class="stat">
      <div class="bar" style="background:{tint}"></div>
      <div class="ic" style="background:{tint}22; color:{tint}">{icon}</div>
      <div class="val">{value}</div>
      <div class="lbl">{label}</div>
    </div>
    """)


def stat_row(cards: list[tuple[str, str, str, str]]) -> None:
    """cards: list of (icon, value, label, tint_hex)."""
    inner = "".join(_stat_card(*c) for c in cards)
    st.markdown(_c(f'<div class="stat-grid">{inner}</div>'), unsafe_allow_html=True)


def section_header(title: str, hint: str = "") -> None:
    st.markdown(
        _c(f'<div class="section-h"><h2>{title}</h2><span class="hint">{hint}</span></div>'),
        unsafe_allow_html=True,
    )


def category_chips(categories) -> None:
    chips = "".join(
        f'<span class="cat-chip"><span class="dot"></span>{c.name}<span class="n">{c.count}</span></span>'
        for c in categories
    )
    st.markdown(_c(f'<div class="cat-row">{chips}</div>'), unsafe_allow_html=True)


def empty_state(emoji: str, title: str, message: str) -> None:
    st.markdown(
        _c(f'<div class="empty"><div class="em">{emoji}</div><h3>{title}</h3><p>{message}</p></div>'),
        unsafe_allow_html=True,
    )


def skeleton_grid(n: int = 8) -> None:
    cells = "".join('<div class="skeleton"></div>' for _ in range(n))
    st.markdown(
        _c(f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:1rem">{cells}</div>'),
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Image encoding (inline data URIs so cards render without a static server)
# --------------------------------------------------------------------------- #


def img_data_uri(path: Path) -> str:
    """Return a base64 data URI for an image path (cached by caller)."""
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def ext_color(ext: str) -> str:
    return _EXT_COLORS.get(ext.lower(), PALETTE["primary"])


def image_card_html(data_uri: str, name: str, ext: str, size_label: str, date_label: str) -> str:
    tint = ext_color(ext)
    return _c(f"""
    <div class="img-card">
      <div class="img-frame">
        <img loading="lazy" src="{data_uri}" alt="{name}"/>
        <span class="img-badge" style="background:{tint}cc">{ext}</span>
      </div>
      <div class="img-meta">
        <div class="nm" title="{name}">{name}</div>
        <div class="sub"><span>{size_label}</span><span>{date_label}</span></div>
      </div>
    </div>
    """)
