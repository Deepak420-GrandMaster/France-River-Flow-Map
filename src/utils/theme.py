"""Design system for the dashboard: tokens, component styling and motion.

All CSS lives here rather than being scattered through ``app.py``, so the look
of the product can be changed in one place. Selectors use Streamlit's stable
``data-testid`` hooks instead of generated class names, which change between
releases.
"""

from __future__ import annotations

import streamlit as st

from src.config import (
    FLOW_CLASSES,
    NO_DATA_COLOR,
    NORMAL_CLASSES,
    NORMAL_UNKNOWN_COLOR,
)

# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------
INK = "#0d2438"
INK_SOFT = "#476175"
INK_MUTED = "#7b8fa1"
ACCENT = "#1c6fa8"
ACCENT_SOFT = "#e6f1f8"
SURFACE = "#ffffff"
CANVAS = "#f4f7fa"
HAIRLINE = "#dfe6ec"

CSS = f"""
<style>
/* ---------------------------------------------------------------- tokens */
:root {{
  --ink: {INK};
  --ink-soft: {INK_SOFT};
  --ink-muted: {INK_MUTED};
  --accent: {ACCENT};
  --accent-soft: {ACCENT_SOFT};
  --surface: {SURFACE};
  --canvas: {CANVAS};
  --hairline: {HAIRLINE};
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: 0 1px 2px rgba(13,36,56,.05), 0 6px 16px rgba(13,36,56,.05);
  --shadow-lift: 0 2px 4px rgba(13,36,56,.07), 0 12px 28px rgba(13,36,56,.09);
  --ease: cubic-bezier(.22,.61,.36,1);
}}

/* ------------------------------------------------------------- app shell */
[data-testid="stAppViewContainer"] {{ background: var(--canvas); }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{
  padding-top: .9rem; padding-bottom: 1rem; max-width: 1720px;
}}
/* Streamlit's default block gap is generous; the dashboard reads better
   tighter, and every pixel saved goes to the map. */
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {{ gap: .55rem; }}
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:empty {{ display: none; }}

h1, h2, h3, h4 {{ color: var(--ink); letter-spacing: -.015em; }}

/* ------------------------------------------------------------------ hero */
.hero {{
  background: linear-gradient(118deg, #1f5f8b 0%, #2b83bd 45%, #4aa6d8 100%);
  background-size: 160% 160%;
  animation: rise .55s var(--ease) both, heroDrift 18s ease-in-out infinite;
  border-radius: var(--radius);
  padding: 16px 22px 15px;
  padding-right: 150px;   /* room for the floating language switch */
  margin-bottom: 8px;
  position: relative;
  overflow: hidden;
  box-shadow: 0 2px 6px rgba(13,36,56,.10), 0 14px 34px rgba(28,111,168,.16);
}}
@keyframes heroDrift {{
  0%, 100% {{ background-position: 0% 50%; }}
  50%      {{ background-position: 100% 50%; }}
}}
/* Slow-moving wave band along the bottom edge: the hero reads as water. */
.hero::before {{
  content: "";
  position: absolute; left: 0; right: 0; bottom: -2px; height: 46px;
  background-repeat: repeat-x; background-size: 240px 46px; opacity: .28;
  background-image: url("data:image/svg+xml;utf8,\
<svg xmlns='http://www.w3.org/2000/svg' width='240' height='46' viewBox='0 0 240 46'>\
<path d='M0 30 C 30 14 60 46 90 30 S 150 14 180 30 S 240 46 240 30 L240 46 L0 46 Z' fill='%23ffffff'/>\
</svg>");
  animation: waveShift 14s linear infinite;
  pointer-events: none;
}}
@keyframes waveShift {{ from {{ background-position-x: 0; }} to {{ background-position-x: 240px; }} }}
/* Slow diagonal sheen: suggests moving water without distracting. */
.hero::after {{
  content: "";
  position: absolute; inset: -60% -20%;
  background: linear-gradient(115deg, transparent 42%, rgba(255,255,255,.10) 50%, transparent 58%);
  animation: sheen 9s linear infinite;
  pointer-events: none;
}}
.hero-title, .hero-sub, .hero-pills {{ position: relative; z-index: 1; }}
.hero-pills .pill {{ animation: rise .5s var(--ease) both; }}
.hero-pills .pill:nth-child(2) {{ animation-delay: .07s; }}
.hero-pills .pill:nth-child(3) {{ animation-delay: .13s; }}
@keyframes sheen {{ from {{ transform: translateX(-45%); }} to {{ transform: translateX(45%); }} }}

.hero-title {{
  font-size: 1.6rem; font-weight: 700; color: #fff;
  letter-spacing: -.03em; line-height: 1.15; margin: 0;
}}
.hero-sub {{
  color: rgba(255,255,255,.72); font-size: .85rem;
  margin: 4px 0 0; max-width: 760px; line-height: 1.45;
}}
.hero-pills {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }}
.pill {{
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.18);
  color: #eaf3f9; font-size: .73rem; font-weight: 500;
  padding: 4px 10px; border-radius: 999px; backdrop-filter: blur(4px);
}}
.pill-dot {{ width: 7px; height: 7px; border-radius: 50%; background: #6ee7a8; }}
.pill-dot.live {{ animation: pulse 2.2s ease-in-out infinite; }}
.pill-dot.stale {{ background: #f0a202; }}
.pill-dot.down {{ background: #ef6461; }}
@keyframes pulse {{
  0%, 100% {{ box-shadow: 0 0 0 0 rgba(110,231,168,.55); }}
  70%      {{ box-shadow: 0 0 0 7px rgba(110,231,168,0); }}
}}

/* --------------------------------------------------------------- metrics */
[data-testid="stMetric"] {{
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  padding: 10px 14px 9px;
  box-shadow: var(--shadow);
  transition: transform .22s var(--ease), box-shadow .22s var(--ease);
  animation: rise .5s var(--ease) both;
  position: relative; overflow: hidden;
}}
[data-testid="stMetric"]::before {{
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: linear-gradient(180deg, var(--accent), #6ab8e0);
  opacity: .85;
}}
[data-testid="stMetric"]:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-lift); }}
[data-testid="stMetricLabel"] p {{
  font-size: .715rem !important; font-weight: 600 !important;
  text-transform: uppercase; letter-spacing: .07em; color: var(--ink-muted) !important;
}}
[data-testid="stMetricValue"] {{
  font-size: 1.5rem !important; font-weight: 650 !important;
  color: var(--ink) !important; letter-spacing: -.025em;
}}
/* Stagger the KPI row so it assembles rather than snapping in. */
[data-testid="stHorizontalBlock"] > div:nth-child(1) [data-testid="stMetric"] {{ animation-delay: .02s; }}
[data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stMetric"] {{ animation-delay: .08s; }}
[data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stMetric"] {{ animation-delay: .14s; }}
[data-testid="stHorizontalBlock"] > div:nth-child(4) [data-testid="stMetric"] {{ animation-delay: .20s; }}

@keyframes rise {{ from {{ opacity: 0; transform: translateY(9px); }} to {{ opacity: 1; transform: none; }} }}

/* --------------------------------------------------------------- sidebar */
[data-testid="stSidebar"] {{
  background: var(--surface);
  border-right: 1px solid var(--hairline);
}}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: .62rem; }}
.side-brand {{ display: flex; align-items: center; gap: 9px;
  margin: -6px 0 4px; }}
.side-mark {{ width: 46px; height: 46px; flex: none; display: block;
  margin: -4px -2px -4px -3px; }}
.side-mark .mark-current {{
  stroke-dasharray: 3 5;
  animation: markflow 1.5s linear infinite;
}}
@keyframes markflow {{ from {{ stroke-dashoffset: 16; }} to {{ stroke-dashoffset: 0; }} }}
.side-name {{ font-weight: 680; font-size: 1.06rem; color: var(--ink); letter-spacing: -.02em; }}
.side-tag {{ font-size: .74rem; color: var(--ink-muted); margin: -2px 0 0; }}

.side-section {{
  font-size: .68rem; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-muted);
  margin: 14px 0 2px;
}}

/* ------------------------------------------------------- generic widgets */
[data-testid="stExpander"] {{
  border: 1px solid var(--hairline) !important;
  border-radius: var(--radius) !important;
  background: var(--surface);
  box-shadow: var(--shadow);
  overflow: hidden;
}}
[data-testid="stExpander"] summary {{ font-weight: 600; font-size: .88rem; color: var(--ink); }}
[data-testid="stExpander"] summary:hover {{ color: var(--accent); }}

[data-testid="stSidebar"] [data-testid="stExpander"] {{ box-shadow: none; }}

button[kind="secondary"], [data-testid="stBaseButton-secondary"] {{
  border-radius: var(--radius-sm) !important;
  border: 1px solid var(--hairline) !important;
  font-weight: 600 !important;
  transition: background .18s var(--ease), border-color .18s var(--ease), transform .18s var(--ease);
}}
button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover {{
  border-color: var(--accent) !important; color: var(--accent) !important; transform: translateY(-1px);
}}

[data-testid="stDataFrame"] {{ border-radius: var(--radius-sm); overflow: hidden; }}

/* The Folium iframe should read as a card, not a raw embed. */
[data-testid="stIFrame"] {{
  border-radius: var(--radius);
  border: 1px solid var(--hairline);
  box-shadow: var(--shadow);
  overflow: hidden;
  /* Streamlit swaps the iframe document when the map changes. Painting the
     element itself in the map's own background colour means the swap reads as
     a soft crossfade instead of a white flash. */
  background: #eef3f7;
  animation: fadeIn .3s var(--ease) both;
}}
@keyframes fadeIn {{ from {{ opacity: .55; }} to {{ opacity: 1; }} }}

/* Charts and panels settle in rather than snapping. */
[data-testid="stPlotlyChart"] {{ animation: fadeIn .32s var(--ease) both; }}
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{
  transition: color .2s var(--ease);
}}
[data-testid="stToggle"] label, [data-testid="stCheckbox"] label {{
  transition: color .16s var(--ease);
}}

/* --------------------------------------------------- station detail panel */
.panel {{
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: var(--radius); padding: 15px 17px; box-shadow: var(--shadow);
  animation: rise .4s var(--ease) both;
}}
.panel-empty {{
  border-style: dashed; color: var(--ink-muted); font-size: .86rem;
  text-align: center; padding: 26px 18px; background: transparent; box-shadow: none;
}}
.panel-title {{ font-size: 1.02rem; font-weight: 660; color: var(--ink); line-height: 1.25; }}
.panel-sub {{ font-size: .78rem; color: var(--ink-muted); margin-top: 2px; }}

.state-row {{ display: flex; align-items: center; gap: 8px; font-size: .8rem; color: var(--ink-soft); }}
.state-dot {{ width: 9px; height: 9px; border-radius: 50%; flex: none; }}

.chip {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: .74rem; font-weight: 600; padding: 4px 10px;
  border-radius: 999px; border: 1px solid var(--hairline); background: var(--canvas);
  color: var(--ink-soft);
}}

/* ------------------------------------------------------ language switch */
/* Anchored top-right, above the hero, so it reads as a page-level control
   rather than one more filter in the sidebar. */
.lang-anchor {{ height: 0; }}

/* Language switch: flags read better with a touch more air and a subtle
   lift on the active option. */
.st-key-langbar [data-testid="stButtonGroup"] {{ display: flex; justify-content: flex-end; }}
/* The switch is rendered just before the hero and pulled down over it, so it
   costs no vertical space of its own. */
/* The language switch is rendered immediately before the hero and then taken
   out of flow, so it costs no vertical space and lands at a known offset
   inside the hero's top-right corner. Streamlit's button-group block is 68 px
   tall (it reserves room for a hidden label), which is why relying on a
   negative margin alone pushed it above the hero. */
.st-key-langbar {{
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  position: relative;
  z-index: 6;
  overflow: visible;
}}
.st-key-langbar [data-testid="stElementContainer"] {{
  position: absolute;
  top: 12px;
  right: 16px;
  width: auto !important;
  margin: 0 !important;
}}
.st-key-langbar [data-testid="stWidgetLabel"] {{ display: none !important; }}

/* High contrast against the hero: a solid track, a solid white active pill. */
.st-key-langbar [data-testid="stButtonGroup"] > div:last-child {{
  background: rgba(9, 34, 54, .38) !important;
  border: 1px solid rgba(255,255,255,.55) !important;
  border-radius: 999px !important;
  padding: 3px !important;
  backdrop-filter: blur(8px);
  box-shadow: 0 2px 8px rgba(9,34,54,.22);
}}
.st-key-langbar [data-testid="stButtonGroup"] button {{
  border: 0 !important;
  border-radius: 999px !important;
  background: transparent !important;
  color: #ffffff !important;
  font-size: .78rem !important;
  font-weight: 650 !important;
  padding: 3px 13px !important;
  letter-spacing: .02em;
  transition: background .18s var(--ease), color .18s var(--ease);
}}
.st-key-langbar [data-testid="stButtonGroup"] button p {{
  color: inherit !important;
  font-size: .78rem !important;
  font-weight: 650 !important;
}}
.st-key-langbar [data-testid="stButtonGroup"] button:hover {{ background: rgba(255,255,255,.16) !important; }}
.st-key-langbar [data-testid="stButtonGroup"] button[aria-checked="true"],
.st-key-langbar [data-testid="stButtonGroup"] button[data-selected="true"] {{
  background: #ffffff !important;
  box-shadow: 0 1px 4px rgba(9,34,54,.28);
}}
.st-key-langbar [data-testid="stButtonGroup"] button[aria-checked="true"],
.st-key-langbar [data-testid="stButtonGroup"] button[aria-checked="true"] p,
.st-key-langbar [data-testid="stButtonGroup"] button[data-selected="true"],
.st-key-langbar [data-testid="stButtonGroup"] button[data-selected="true"] p {{
  color: var(--ink) !important;
}}

[data-testid="stMetric"] {{
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  padding: 10px 14px 9px;
  box-shadow: var(--shadow);
  transition: transform .22s var(--ease), box-shadow .22s var(--ease);
  animation: rise .5s var(--ease) both;
  position: relative; overflow: hidden;
}}
[data-testid="stMetric"]::before {{
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: linear-gradient(180deg, var(--accent), #6ab8e0);
  opacity: .85;
}}
[data-testid="stMetric"]:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-lift); }}
[data-testid="stMetricLabel"] p {{
  font-size: .715rem !important; font-weight: 600 !important;
  text-transform: uppercase; letter-spacing: .07em; color: var(--ink-muted) !important;
}}
[data-testid="stMetricValue"] {{
  font-size: 1.5rem !important; font-weight: 650 !important;
  color: var(--ink) !important; letter-spacing: -.025em;
}}
/* Stagger the KPI row so it assembles rather than snapping in. */
[data-testid="stHorizontalBlock"] > div:nth-child(1) [data-testid="stMetric"] {{ animation-delay: .02s; }}
[data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stMetric"] {{ animation-delay: .08s; }}
[data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stMetric"] {{ animation-delay: .14s; }}
[data-testid="stHorizontalBlock"] > div:nth-child(4) [data-testid="stMetric"] {{ animation-delay: .20s; }}

@keyframes rise {{ from {{ opacity: 0; transform: translateY(9px); }} to {{ opacity: 1; transform: none; }} }}

/* --------------------------------------------------------------- sidebar */
[data-testid="stSidebar"] {{
  background: var(--surface);
  border-right: 1px solid var(--hairline);
}}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: .62rem; }}
.side-brand {{ display: flex; align-items: center; gap: 9px;
  margin: -6px 0 4px; }}
.side-mark {{ width: 46px; height: 46px; flex: none; display: block;
  margin: -4px -2px -4px -3px; }}
.side-mark .mark-current {{
  stroke-dasharray: 3 5;
  animation: markflow 1.5s linear infinite;
}}
@keyframes markflow {{ from {{ stroke-dashoffset: 16; }} to {{ stroke-dashoffset: 0; }} }}
.side-name {{ font-weight: 680; font-size: 1.06rem; color: var(--ink); letter-spacing: -.02em; }}
.side-tag {{ font-size: .74rem; color: var(--ink-muted); margin: -2px 0 0; }}

.side-section {{
  font-size: .68rem; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-muted);
  margin: 14px 0 2px;
}}

/* ------------------------------------------------------- generic widgets */
[data-testid="stExpander"] {{
  border: 1px solid var(--hairline) !important;
  border-radius: var(--radius) !important;
  background: var(--surface);
  box-shadow: var(--shadow);
  overflow: hidden;
}}
[data-testid="stExpander"] summary {{ font-weight: 600; font-size: .88rem; color: var(--ink); }}
[data-testid="stExpander"] summary:hover {{ color: var(--accent); }}

[data-testid="stSidebar"] [data-testid="stExpander"] {{ box-shadow: none; }}

button[kind="secondary"], [data-testid="stBaseButton-secondary"] {{
  border-radius: var(--radius-sm) !important;
  border: 1px solid var(--hairline) !important;
  font-weight: 600 !important;
  transition: background .18s var(--ease), border-color .18s var(--ease), transform .18s var(--ease);
}}
button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover {{
  border-color: var(--accent) !important; color: var(--accent) !important; transform: translateY(-1px);
}}

[data-testid="stDataFrame"] {{ border-radius: var(--radius-sm); overflow: hidden; }}

/* The Folium iframe should read as a card, not a raw embed. */
[data-testid="stIFrame"] {{
  border-radius: var(--radius);
  border: 1px solid var(--hairline);
  box-shadow: var(--shadow);
  overflow: hidden;
  /* Streamlit swaps the iframe document when the map changes. Painting the
     element itself in the map's own background colour means the swap reads as
     a soft crossfade instead of a white flash. */
  background: #eef3f7;
  animation: fadeIn .3s var(--ease) both;
}}
@keyframes fadeIn {{ from {{ opacity: .55; }} to {{ opacity: 1; }} }}

/* Charts and panels settle in rather than snapping. */
[data-testid="stPlotlyChart"] {{ animation: fadeIn .32s var(--ease) both; }}
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{
  transition: color .2s var(--ease);
}}
[data-testid="stToggle"] label, [data-testid="stCheckbox"] label {{
  transition: color .16s var(--ease);
}}

/* --------------------------------------------------- station detail panel */
.panel {{
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: var(--radius); padding: 15px 17px; box-shadow: var(--shadow);
  animation: rise .4s var(--ease) both;
}}
.panel-empty {{
  border-style: dashed; color: var(--ink-muted); font-size: .86rem;
  text-align: center; padding: 26px 18px; background: transparent; box-shadow: none;
}}
.panel-title {{ font-size: 1.02rem; font-weight: 660; color: var(--ink); line-height: 1.25; }}
.panel-sub {{ font-size: .78rem; color: var(--ink-muted); margin-top: 2px; }}

.state-row {{ display: flex; align-items: center; gap: 8px; font-size: .8rem; color: var(--ink-soft); }}
.state-dot {{ width: 9px; height: 9px; border-radius: 50%; flex: none; }}

.chip {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: .74rem; font-weight: 600; padding: 4px 10px;
  border-radius: 999px; border: 1px solid var(--hairline); background: var(--canvas);
  color: var(--ink-soft);
}}

/* ------------------------------------------------------ language switch */
/* Anchored top-right, above the hero, so it reads as a page-level control
   rather than one more filter in the sidebar. */
.lang-anchor {{ height: 0; }}

/* Language switch: flags read better with a touch more air and a subtle
   lift on the active option. */
.st-key-langbar [data-testid="stButtonGroup"] {{ display: flex; justify-content: flex-end; }}
/* The switch is rendered just before the hero and pulled down over it, so it
   costs no vertical space of its own. */
/* Streamlit's vertical block is a *column* flex container, so the horizontal
   axis is the cross axis: align-items, not justify-content, is what moves the
   switch to the right. */
.st-key-langbar {{
  position: relative; z-index: 4;
  margin: 0 16px -46px 0 !important;
  /* Streamlit's own emotion rule sets align-items on stVerticalBlock with
     higher specificity, so this one has to win explicitly. */
  display: flex !important;
  flex-direction: column !important;
  align-items: flex-end !important;
  width: 100%;
  pointer-events: none;
}}
.st-key-langbar [data-testid="stElementContainer"] {{ width: auto !important; }}
.st-key-langbar [data-testid="stButtonGroup"] {{ pointer-events: auto; }}
.st-key-langbar [data-testid="stButtonGroup"] {{ pointer-events: auto; margin-right: 6px; }}
.st-key-langbar [data-testid="stButtonGroup"] > div:last-child {{
  background: rgba(255,255,255,.14) !important;
  border: 1px solid rgba(255,255,255,.26) !important;
  border-radius: 999px !important; padding: 2px !important;
  backdrop-filter: blur(6px);
}}
.st-key-langbar [data-testid="stButtonGroup"] button {{
  border: 0 !important; border-radius: 999px !important; background: transparent !important;
  color: rgba(255,255,255,.8) !important;
}}
.st-key-langbar [data-testid="stButtonGroup"] button p {{ color: inherit !important; }}
.st-key-langbar [data-testid="stButtonGroup"] button[aria-checked="true"],
.st-key-langbar [data-testid="stButtonGroup"] button[data-selected="true"] {{
  background: #ffffff !important; color: var(--ink) !important;
  box-shadow: 0 1px 3px rgba(0,0,0,.18);
}}
.st-key-langbar [data-testid="stButtonGroup"] button {{
  font-size: .8rem !important; font-weight: 600 !important;
  padding: 3px 12px !important; letter-spacing: .01em;
  transition: background .18s var(--ease), color .18s var(--ease);
}}
.st-key-langbar [data-testid="stButtonGroup"] button p {{ font-size: .8rem !important; }}

/* --------------------------------------------------------------- footer */
.site-foot {{
  margin-top: 18px; padding: 13px 2px 6px;
  border-top: 1px solid var(--hairline);
  display: flex; justify-content: center;
  color: var(--ink-muted); font-size: .76rem;
}}
.site-foot strong {{ color: var(--ink-soft); font-weight: 650; }}

/* --------------------------------------------------------------- caption */
.foot {{ color: var(--ink-muted); font-size: .68rem; line-height: 1.55; }}

/* Respect a reader's motion preference -- all decorative motion stops. */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation: none !important; transition: none !important; }}
}}
</style>
"""


def inject_theme() -> None:
    """Apply the design system. Call once, immediately after set_page_config."""
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, pills: list[tuple[str, str]]) -> None:
    """Page header. ``pills`` is a list of (state, text) where state is one of
    ``live``, ``stale``, ``down`` or ``""`` for a plain pill."""
    rendered = "".join(
        f'<span class="pill"><span class="pill-dot {state}"></span>{text}</span>'
        if state
        else f'<span class="pill">{text}</span>'
        for state, text in pills
    )
    st.markdown(
        f'<div class="hero"><div class="hero-title">{title}</div>'
        f'<p class="hero-sub">{subtitle}</p>'
        f'<div class="hero-pills">{rendered}</div></div>',
        unsafe_allow_html=True,
    )


#: The mark is the product in miniature: a meandering watercourse with a
#: gauging station on it, and the same downstream animation the map uses.
BRAND_MARK = """
<svg class="side-mark" viewBox="0 0 64 64" fill="none"
     xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="France River Flow">
  <defs>
    <linearGradient id="frf-water" x1="8" y1="60" x2="52" y2="22" gradientUnits="userSpaceOnUse">
      <stop stop-color="#2f95cf"/><stop offset="1" stop-color="#1c6fa8"/>
    </linearGradient>
    <linearGradient id="frf-sun" x1="47" y1="6" x2="47" y2="24" gradientUnits="userSpaceOnUse">
      <stop stop-color="#f9c04b"/><stop offset="1" stop-color="#f0982a"/>
    </linearGradient>
  </defs>
  <g fill="url(#frf-sun)">
    <path d="M38.8,22.2 L27.1,20.6 L38.9,21.8 Z M39.3,20.3 L33.4,17.8 L39.4,19.9 Z M40.1,18.5 L30.6,11.6 L40.4,18.2 Z M41.4,17.0 L37.4,12.1 L41.7,16.7 Z M43.0,15.8 L37.7,5.3 L43.4,15.6 Z M44.8,15.1 L43.5,8.9 L45.2,15.0 Z M46.8,14.8 L47.0,3.0 L47.2,14.8 Z M48.8,15.0 L50.5,8.9 L49.2,15.1 Z M50.6,15.6 L56.3,5.3 L51.0,15.8 Z M52.3,16.7 L56.6,12.1 L52.6,17.0 Z M53.6,18.2 L63.4,11.6 L53.9,18.5 Z M54.6,19.9 L60.6,17.8 L54.7,20.3 Z M55.1,21.8 L66.9,20.6 L55.2,22.2 Z"/>
    <path d="M39.4,23.0 a7.6,7.6 0 0 1 15.2,0 z"/>
  </g>
  <path d="M 9.6,66.4 9.8,66.3 10.1,66.1 10.5,65.8 11.0,65.6 11.6,65.3 12.3,64.9 13.0,64.6 13.8,64.2 14.6,63.8 15.5,63.4 16.4,63.0 17.3,62.6 18.2,62.1 19.1,61.6 20.0,61.2 20.9,60.7 21.9,60.2 22.7,59.6 23.6,59.1 24.5,58.5 25.3,57.9 26.1,57.2 26.9,56.5 27.6,55.6 28.4,54.6 29.0,53.3 29.5,51.7 29.6,50.0 29.4,48.6 29.0,47.4 28.4,46.3 27.9,45.5 27.3,44.7 26.7,44.0 26.1,43.4 25.5,42.8 24.9,42.3 24.3,41.8 23.7,41.3 23.1,40.8 22.6,40.3 22.1,39.9 21.7,39.5 21.3,39.2 21.0,38.9 20.7,38.6 20.6,38.5 20.5,38.5 20.5,38.7 20.5,39.0 20.4,39.6 20.2,40.1 20.0,40.4 19.9,40.4 19.9,40.3 20.0,40.2 20.2,40.0 20.5,39.7 20.9,39.4 21.4,39.2 21.9,38.9 22.5,38.6 23.1,38.3 23.8,38.0 24.5,37.7 25.2,37.4 25.9,37.1 26.7,36.9 27.5,36.6 28.2,36.3 29.0,36.0 29.8,35.7 30.5,35.4 31.3,35.2 32.0,34.9 32.7,34.6 33.4,34.3 34.0,34.0 34.6,33.7 35.1,33.4 35.7,33.1 36.2,32.8 36.8,32.5 37.3,32.2 37.9,31.9 38.4,31.7 39.0,31.4 39.5,31.1 40.0,30.8 40.5,30.6 41.0,30.3 41.5,30.0 42.0,29.8 42.5,29.5 43.0,29.3 43.5,29.0 43.9,28.8 44.4,28.6 44.9,28.4 45.3,28.1 45.7,27.9 46.1,27.7 46.6,27.5 47.0,27.4 47.4,27.2 47.7,27.0 48.1,26.9 48.5,26.7 48.9,26.5 49.3,26.4 49.7,26.3 50.0,26.1 50.4,26.0 50.7,25.9 51.1,25.8 51.4,25.7 51.8,25.6 52.1,25.5 52.4,25.4 52.7,25.3 53.0,25.2 53.3,25.1 53.6,25.0 53.8,24.9 54.1,24.9 54.3,24.8 54.5,24.7 54.8,24.7 54.9,24.6 55.1,24.5 L 54.9,23.5 54.7,23.5 54.5,23.5 54.3,23.5 54.1,23.5 53.9,23.6 53.6,23.6 53.3,23.6 53.0,23.6 52.7,23.6 52.4,23.7 52.1,23.7 51.8,23.7 51.4,23.8 51.0,23.8 50.7,23.8 50.3,23.9 49.9,23.9 49.5,24.0 49.1,24.0 48.7,24.1 48.3,24.2 47.8,24.3 47.4,24.3 46.9,24.4 46.5,24.5 46.0,24.6 45.6,24.8 45.1,24.9 44.6,25.0 44.2,25.1 43.7,25.3 43.2,25.4 42.7,25.6 42.1,25.7 41.6,25.9 41.1,26.1 40.6,26.2 40.0,26.4 39.5,26.6 38.9,26.8 38.4,26.9 37.8,27.1 37.2,27.3 36.7,27.5 36.1,27.7 35.5,27.9 34.9,28.1 34.3,28.3 33.8,28.5 33.2,28.7 32.6,28.9 32.0,29.0 31.4,29.2 30.8,29.4 30.2,29.6 29.5,29.7 28.8,29.9 28.0,30.1 27.3,30.2 26.5,30.4 25.7,30.6 24.9,30.8 24.0,31.0 23.2,31.2 22.4,31.4 21.6,31.6 20.8,31.8 20.0,32.1 19.2,32.3 18.4,32.6 17.7,32.9 16.9,33.2 16.2,33.6 15.5,34.0 14.8,34.5 14.1,35.2 13.4,35.9 12.8,36.9 12.4,38.2 12.2,39.5 12.4,40.8 12.7,41.8 13.0,42.7 13.5,43.5 14.0,44.3 14.4,45.0 14.9,45.6 15.4,46.2 15.9,46.8 16.4,47.4 16.9,48.0 17.4,48.5 17.8,49.1 18.2,49.6 18.5,50.0 18.8,50.4 19.0,50.8 19.1,51.0 19.1,51.1 19.0,51.1 18.9,50.8 18.8,50.2 18.8,49.5 19.0,48.7 19.1,48.2 19.2,48.0 19.1,48.0 18.9,48.1 18.6,48.3 18.2,48.5 17.6,48.7 17.0,49.0 16.4,49.3 15.6,49.6 14.9,49.9 14.1,50.2 13.2,50.5 12.4,50.7 11.5,51.0 10.7,51.3 9.8,51.6 9.0,51.8 8.2,52.1 7.4,52.3 6.7,52.5 5.9,52.7 5.2,52.9 4.6,53.2 3.9,53.4 3.4,53.6 Z" fill="url(#frf-water)"/>
  <path class="mark-current" d="M 6.5,60.0 L 6.9,59.8 L 7.3,59.6 L 7.9,59.4 L 8.5,59.1 L 9.1,58.9 L 9.9,58.6 L 10.6,58.3 L 11.4,58.0 L 12.2,57.7 L 13.1,57.4 L 14.0,57.0 L 14.8,56.6 L 15.7,56.3 L 16.6,55.9 L 17.5,55.5 L 18.3,55.1 L 19.1,54.7 L 19.9,54.3 L 20.6,53.9 L 21.3,53.5 L 21.9,53.1 L 22.5,52.7 L 23.0,52.2 L 23.4,51.8 L 23.8,51.4 L 24.0,51.0 L 24.1,50.6 L 24.2,50.1 L 24.1,49.7 L 24.0,49.2 L 23.8,48.7 L 23.5,48.2 L 23.1,47.7 L 22.7,47.2 L 22.3,46.7 L 21.8,46.2 L 21.3,45.7 L 20.8,45.1 L 20.3,44.6 L 19.8,44.1 L 19.3,43.6 L 18.8,43.1 L 18.3,42.6 L 17.9,42.1 L 17.5,41.6 L 17.1,41.1 L 16.8,40.6 L 16.6,40.2 L 16.4,39.7 L 16.4,39.3 L 16.4,38.9 L 16.5,38.5 L 16.7,38.1 L 17.0,37.8 L 17.3,37.4 L 17.7,37.1 L 18.2,36.8 L 18.7,36.5 L 19.3,36.2 L 19.9,35.9 L 20.6,35.6 L 21.2,35.3 L 21.9,35.1 L 22.7,34.8 L 23.4,34.6 L 24.2,34.3 L 25.0,34.1 L 25.8,33.8 L 26.6,33.6 L 27.4,33.4 L 28.1,33.1 L 28.9,32.9 L 29.7,32.7 L 30.4,32.4 L 31.1,32.2 L 31.8,32.0 L 32.4,31.7 L 33.0,31.5 L 33.6,31.3 L 34.2,31.0 L 34.7,30.8 L 35.3,30.5 L 35.9,30.3 L 36.4,30.1 L 37.0,29.8 L 37.5,29.6 L 38.1,29.3 L 38.6,29.1 L 39.2,28.9 L 39.7,28.7 L 40.2,28.4 L 40.8,28.2 L 41.3,28.0 L 41.8,27.8 L 42.3,27.6 L 42.8,27.4 L 43.3,27.2 L 43.8,27.0 L 44.3,26.8 L 44.7,26.6 L 45.2,26.5 L 45.6,26.3 L 46.1,26.1 L 46.5,26.0 L 46.9,25.9 L 47.3,25.7 L 47.8,25.6 L 48.2,25.5 L 48.6,25.4 L 49.0,25.3 L 49.4,25.2 L 49.8,25.1 L 50.1,25.0 L 50.5,24.9 L 50.9,24.8 L 51.2,24.7 L 51.6,24.7 L 51.9,24.6 L 52.3,24.5 L 52.6,24.5 L 52.9,24.4 L 53.2,24.4 L 53.5,24.3 L 53.7,24.3 L 54.0,24.2 L 54.2,24.2 L 54.4,24.1 L 54.6,24.1 L 54.8,24.0 L 55.0,24.0" fill="none" stroke="#ffffff"
        stroke-opacity=".55" stroke-width="1.5" stroke-linecap="round"/>
</svg>
"""


def sidebar_brand(title: str, tagline: str) -> None:
    st.markdown(
        f'<div class="side-brand">{BRAND_MARK}'
        f'<div><div class="side-name">{title}</div>'
        f'<div class="side-tag">{tagline}</div></div></div>',
        unsafe_allow_html=True,
    )


def footer(credit_html: str) -> None:
    """Persistent site credit line."""
    st.markdown(
        f'<div class="site-foot"><span>{credit_html}</span></div>',
        unsafe_allow_html=True,
    )


def sidebar_section(label: str) -> None:
    st.markdown(f'<div class="side-section">{label}</div>', unsafe_allow_html=True)


def swatch_rows(entries: list[tuple[str, str]]) -> str:
    """Legend rows from ``(colour, label)`` pairs."""
    return "".join(
        f'<div class="state-row" style="margin:3px 0;">'
        f'<span class="state-dot" style="background:{color}"></span>{label}</div>'
        for color, label in entries
    )


def flow_legend_html(labels: list[str]) -> str:
    colors = [color for _, color, _ in FLOW_CLASSES] + [NO_DATA_COLOR]
    return swatch_rows(list(zip(colors, labels)))


def normal_legend_html(labels: list[str]) -> str:
    colors = [color for _, color, _ in NORMAL_CLASSES] + [NORMAL_UNKNOWN_COLOR]
    return swatch_rows(list(zip(colors, labels)))
