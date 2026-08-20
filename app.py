"""France River Flow — Streamlit dashboard.

Live hydrometric discharge from the free Hub'Eau API, drawn over the French
river network (BD TOPAGE), for all 96 metropolitan departments, in English or
French.

Run locally:  python -m streamlit run app.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import (
    ATTRIBUTION,
    DEFAULT_REGION_KEY,
    FLOW_SPEED_DEFAULT,
    FLOW_SPEED_MAX,
    FLOW_SPEED_MIN,
    FRESH_MINUTES,
    FRESHNESS_DELAYED,
    FRESHNESS_UNAVAILABLE,
    LOD_DETAIL,
    LOD_HIDDEN,
    LOD_OVERVIEW,
    RIVER_BASE_COLOR,
    RIVER_FLOW_COLOR,
    flow_color,
    load_regions,
    normal_ratio_color,
)
from src.data_loading import (
    build_station_table,
    clear_live_caches,
    load_boundary,
    load_dams,
    load_latest_flows,
    load_rivers,
    load_seasonal_normals,
    load_station_history,
    load_stations,
    relative_age,
    utc_label,
)
from src.i18n import DEFAULT_LANGUAGE, LANGUAGES, language_label, t
from src.rivers import count_features, detail_is_available
from src.services.hubeau import DEFAULT_LOOKBACK_HOURS
from src.services.hubeau import empty_stations as hubeau_empty
from src.utils import theme
from src.utils.formatters import (
    add_freshness_column,
    format_coordinates,
    format_flow,
    format_litres,
    format_timestamp,
    freshness_label,
)
from src.utils.map_helpers import (
    build_map,
    find_clicked_station,
    split_rivers,
)
from src.utils.tables import apply_filters, build_display_table

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

HISTORY_WINDOW_HOURS = {"chart.24h": 24, "chart.7d": 168}
TOP_N_STATIONS = 10
LOD_KEYS = {LOD_OVERVIEW: "lod.overview", LOD_DETAIL: "lod.detail", LOD_HIDDEN: "lod.hidden"}
FLOW_LEGEND_KEYS = ["flow.under1", "flow.1to10", "flow.10to100", "flow.over100", "flow.none"]
NORMAL_LEGEND_KEYS = [
    "normal.much_below", "normal.below", "normal.near",
    "normal.above", "normal.much_above", "normal.unknown",
]

st.set_page_config(
    page_title="France River Flow",
    page_icon="🌊",  # browser-tab icon only; the interface itself uses words
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject_theme()


def render_language_switch() -> str:
    """EN / FR control, pinned to the top right of the page."""
    # A keyed container gives the element a stable ".st-key-langbar" class,
    # which the stylesheet uses to float it inside the hero instead of giving
    # it a row of its own.
    with st.container(key="langbar"):
        choice = st.segmented_control(
            "Language",
            options=list(LANGUAGES),
            format_func=language_label,
            default=st.session_state.get("lang", DEFAULT_LANGUAGE),
            key="lang_switch",
            label_visibility="collapsed",
        )
    lang = choice or st.session_state.get("lang", DEFAULT_LANGUAGE)
    st.session_state["lang"] = lang
    return lang


# ==========================================================================
# Sidebar
# ==========================================================================
def render_sidebar(lang: str) -> dict:
    """Draw the controls and return the current view state.

    Everything that does not depend on live data is drawn immediately, so the
    interface is usable while Hub'Eau is still being queried. The discharge
    slider and the freshness caption are reserved as placeholders and filled
    by :func:`render_live_sidebar_parts`.
    """
    regions = load_regions()
    keys = list(regions)

    with st.sidebar:
        theme.sidebar_brand(t("app.title", lang), t("app.tagline", lang))

        theme.sidebar_section(t("side.area", lang))
        region_key = st.selectbox(
            t("side.department", lang),
            options=keys,
            index=keys.index(DEFAULT_REGION_KEY) if DEFAULT_REGION_KEY in keys else 0,
            format_func=lambda key: regions[key].label,
            label_visibility="collapsed",
            help=t("side.department_help", lang),
            key="ctl_region",
        )
        region = regions[region_key]

        theme.sidebar_section(t("side.layers", lang))
        show_stations = st.toggle(t("side.stations", lang), value=True, key="ctl_stations")
        show_dams = st.toggle(
            t("side.dams", lang), value=False, help=t("side.dams_help", lang), key="ctl_dams"
        )
        show_labels = st.toggle(t("side.labels", lang), value=False, key="ctl_labels")
        color_by_normal = st.toggle(
            t("side.normal", lang), value=False, help=t("side.normal_help", lang),
            key="ctl_normal",
        )

        theme.sidebar_section(t("side.rivers", lang))
        detail = st.selectbox(
            t("side.river_layer", lang),
            options=list(LOD_KEYS),
            index=list(LOD_KEYS).index(LOD_OVERVIEW),
            format_func=lambda key: t(LOD_KEYS[key], lang),
            label_visibility="collapsed",
            key="ctl_detail",
        )
        animate = st.toggle(
            t("side.animate", lang), value=True, help=t("side.animate_help", lang),
            key="ctl_animate",
        )
        flow_speed = FLOW_SPEED_DEFAULT
        if animate:
            multiplier = st.slider(
                t("side.speed", lang), min_value=0.4, max_value=3.0,
                value=1.0, step=0.1, format="%.1f×", key="ctl_speed",
            )
            # A higher multiplier must mean faster, i.e. a shorter CSS duration.
            flow_speed = max(
                FLOW_SPEED_MIN, min(FLOW_SPEED_MAX, FLOW_SPEED_DEFAULT / multiplier)
            )

        theme.sidebar_section(t("side.filters", lang))
        only_with_flow = st.toggle(
            t("side.only_recent", lang), value=False,
            help=t("side.only_recent_help", lang, hours=DEFAULT_LOOKBACK_HOURS),
            key="ctl_only_recent",
        )
        search = st.text_input(
            "search", placeholder=t("side.search", lang), label_visibility="collapsed",
            key="ctl_search",
        )
        slider_slot = st.empty()

        theme.sidebar_section(t("side.data", lang))
        status_slot = st.empty()
        if st.button(t("side.refresh", lang), width="stretch"):
            clear_live_caches()
            st.rerun()

        with st.expander(t("side.about", lang)):
            st.markdown(about_text(lang))
            st.caption(ATTRIBUTION)

    return {
        "region": region,
        "region_key": region_key,
        "detail": detail,
        "show_rivers": detail != LOD_HIDDEN,
        "show_stations": show_stations,
        "show_dams": show_dams,
        "show_labels": show_labels,
        "color_by_normal": color_by_normal,
        "animate": animate,
        "flow_speed": flow_speed,
        "only_with_flow": only_with_flow,
        "search": search.strip(),
        "flow_range": None,
        "_slider_slot": slider_slot,
        "_status_slot": status_slot,
    }


def about_text(lang: str) -> str:
    if lang == "fr":
        return f"""
Le **débit (Q)** provient de l'API gratuite
[Hub'Eau Hydrométrie v2](https://hubeau.eaufrance.fr/page/api-hydrometrie),
qui publie ses valeurs en **litres par seconde** ; toutes sont converties ici
en **m³/s**. Les mesures paraissent toutes les 5 à 60 minutes et sont mises en
cache 10 minutes. Une mesure de moins de {FRESH_MINUTES} minutes est
*{t("fresh.recent", lang)}*, une plus ancienne *{t("fresh.delayed", lang)}*, et
une station sans publication *{t("fresh.unavailable", lang)}*.

**Débit vs normale** compare la dernière mesure à la **médiane des moyennes
mensuelles du même mois calendaire** sur toutes les années publiées (données
élaborées Hub'Eau, généralement 10 à 25 ans). Les stations disposant de moins
de 5 années de recul restent non classées.

**Cours d'eau, barrages et retenues** proviennent de **BD TOPAGE 2024**
(IGN / OFB), simplifiés pour l'affichage. Ils servent de contexte : la grande
majorité des tronçons affichés n'est pas jaugée, et aucun barrage n'est mesuré
en temps réel.

Il s'agit de débits observés provisoires — ni données validées, ni prévision
de crue, ni indicateur de qualité de l'eau.
"""
    return f"""
**Discharge (Q)** comes from the free
[Hub'Eau Hydrométrie API v2](https://hubeau.eaufrance.fr/page/api-hydrometrie),
which publishes values in **litres per second**; every value here is converted
to **m³/s**. Readings appear every 5–60 minutes and are cached for 10 minutes.
A reading up to {FRESH_MINUTES} minutes old is *{t("fresh.recent", lang)}*, an
older one *{t("fresh.delayed", lang)}*, and a station with nothing published
*{t("fresh.unavailable", lang)}*.

**Flow vs normal** compares the latest reading with the **median monthly mean
for the same calendar month** across all published years (Hub'Eau elaborated
data, typically 10–25 years). Stations with fewer than 5 years of record are
left unclassified rather than given a weak estimate.

**Rivers, dams and reservoirs** come from **BD TOPAGE 2024** (IGN / OFB),
simplified for display. They are context only: the great majority of drawn
river segments have no gauging station, and no dam here is measured live.

These are provisional observed flows — not validated records, not flood
forecasts, and not water-quality indicators.
"""


def render_live_sidebar_parts(controls: dict, stations: pd.DataFrame, fetched_at, lang: str) -> None:
    """Fill the sidebar placeholders that depend on live data."""
    controls["_status_slot"].caption(
        t("side.updated", lang, age=relative_age(fetched_at, lang), stamp=utc_label(fetched_at))
    )

    measured = stations["flow_m3s"].dropna() if "flow_m3s" in stations else pd.Series(dtype=float)
    with controls["_slider_slot"].container():
        if not measured.empty and float(measured.max()) > 0:
            ceiling = round(float(measured.max()) + 0.01, 2)
            controls["flow_range"] = st.slider(
                t("side.range", lang), min_value=0.0, max_value=ceiling,
                value=(0.0, ceiling), help=t("side.range_help", lang),
                # Keyed on the ceiling: when a new department changes the
                # range, the widget must reset rather than clamp to the old one.
                key=f"ctl_range_{ceiling}",
            )
        else:
            st.caption(t("side.range_unavailable", lang))


# ==========================================================================
# Main sections
# ==========================================================================
def render_national_metrics(rivers: dict | None, lang: str) -> None:
    """Network statistics for the whole-country view, where there is no
    per-station live data to summarise."""
    features = (rivers or {}).get("features") or []
    lengths = [
        (f.get("properties") or {}).get("length_km") or 0 for f in features
    ]
    named = [
        f for f in features if (f.get("properties") or {}).get("name")
    ]
    longest = max(features, key=lambda f: (f["properties"].get("length_km") or 0), default=None)

    columns = st.columns(4)
    columns[0].metric(t("metric.rivers", lang), f"{len(features):,}")
    columns[1].metric(t("metric.length", lang), f"{int(sum(lengths)):,} km")
    columns[2].metric(t("metric.departments", lang), f"{len(load_regions()) - 1}")
    columns[3].metric(
        t("metric.longest", lang),
        (longest["properties"].get("name") or "—") if longest and named else "—",
    )


def render_metrics(stations: pd.DataFrame, lang: str) -> None:
    measured = stations["flow_m3s"].dropna() if "flow_m3s" in stations else pd.Series(dtype=float)
    columns = st.columns(4)
    columns[0].metric(t("metric.shown", lang), f"{len(stations):,}")
    columns[1].metric(t("metric.recent", lang), f"{len(measured):,}")
    columns[2].metric(
        t("metric.median", lang),
        format_flow(float(measured.median()), lang) if len(measured) else "—",
    )
    columns[3].metric(
        t("metric.max", lang),
        format_flow(float(measured.max()), lang) if len(measured) else "—",
    )


def render_map_legend(controls: dict, lang: str) -> None:
    """Legend, collapsed by default so it never covers the map."""
    by_normal = controls["color_by_normal"]
    title = t("legend.title_normal" if by_normal else "legend.title_flow", lang)
    with st.expander(title, expanded=False):
        keys = NORMAL_LEGEND_KEYS if by_normal else FLOW_LEGEND_KEYS
        labels = [t(key, lang) for key in keys]
        body = (theme.normal_legend_html if by_normal else theme.flow_legend_html)(labels)

        extras = []
        if controls["show_rivers"]:
            extras.append(
                '<div class="state-row" style="margin:3px 0;">'
                f'<span style="width:18px;height:3px;background:{RIVER_FLOW_COLOR};'
                'display:inline-block;border-radius:2px;"></span>'
                f'{escape(t("legend.main_river", lang))}</div>'
                '<div class="state-row" style="margin:3px 0;">'
                f'<span style="width:18px;height:2px;background:{RIVER_BASE_COLOR};'
                'display:inline-block;border-radius:2px;"></span>'
                f'{escape(t("legend.tributary", lang))}</div>'
            )
        if controls["show_dams"]:
            extras.append(
                '<div class="state-row" style="margin:3px 0;">'
                '<span class="state-dot" style="background:#7b5ea7"></span>'
                f'{escape(t("legend.dam", lang))}</div>'
                '<div class="state-row" style="margin:3px 0;">'
                '<span class="state-dot" style="background:#4aa3c7"></span>'
                f'{escape(t("legend.reservoir", lang))}</div>'
            )
        separator = (
            '<div style="border-top:1px solid var(--hairline);margin:8px 0 6px;"></div>'
            if extras else ""
        )
        st.markdown(body + separator + "".join(extras), unsafe_allow_html=True)
        st.markdown(f'<div class="foot">{escape(ATTRIBUTION)}</div>', unsafe_allow_html=True)


def render_history_chart(
    code_station: str, station_name: str, normal_m3s: float | None, lang: str
) -> None:
    """Plotly discharge history. Only called once a station is selected."""
    window_key = st.radio(
        "history", options=list(HISTORY_WINDOW_HOURS),
        format_func=lambda key: t(key, lang), horizontal=True,
        key=f"history_window_{code_station}", label_visibility="collapsed",
    )
    hours = HISTORY_WINDOW_HOURS[window_key]

    with st.spinner(t("msg.loading_history", lang)):
        history = load_station_history(code_station, hours)

    if history.empty:
        st.info(t("chart.none", lang, window=t(window_key, lang).lower()))
        return

    figure = go.Figure()
    if normal_m3s:
        # Reference line for the seasonal normal, so the series has context.
        figure.add_hline(
            y=normal_m3s, line_dash="dot", line_color="#9aa9b6", line_width=1.4,
            annotation_text=t("chart.normal_line", lang, value=format_flow(normal_m3s, lang)),
            annotation_position="top left",
            annotation_font={"size": 10, "color": "#7b8fa1"},
        )
    figure.add_trace(
        go.Scatter(
            x=history["date_obs"], y=history["flow_m3s"], mode="lines",
            line={"color": RIVER_FLOW_COLOR, "width": 2, "shape": "spline", "smoothing": .4},
            fill="tozeroy", fillcolor="rgba(28,111,168,0.13)",
            hovertemplate="%{x|%d %b %H:%M} UTC<br><b>%{y:.3f} m³/s</b><extra></extra>",
            name="Q",
        )
    )
    figure.update_layout(
        height=235, margin={"l": 0, "r": 6, "t": 10, "b": 0},
        yaxis={"title": None, "rangemode": "tozero", "gridcolor": "#eef2f6",
               "ticksuffix": " m³/s", "tickfont": {"size": 10}},
        xaxis={"title": None, "gridcolor": "#eef2f6", "tickfont": {"size": 10}},
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
        transition={"duration": 350, "easing": "cubic-in-out"},
    )
    # A stable key lets Streamlit update the existing chart in place rather
    # than unmounting and remounting it, which is what made it blink.
    st.plotly_chart(
        figure, width="stretch", config={"displayModeBar": False},
        key=f"history-{code_station}",
    )
    st.caption(t("chart.readings", lang, count=f"{len(history):,}"))


def render_station_details(stations: pd.DataFrame, selected_code: str | None, lang: str) -> None:
    if not selected_code or stations.empty:
        st.markdown(
            f'<div class="panel panel-empty">{escape(t("detail.empty", lang))}</div>',
            unsafe_allow_html=True,
        )
        return

    matches = stations[stations["code_station"] == selected_code]
    if matches.empty:
        st.markdown(
            f'<div class="panel panel-empty">{escape(t("detail.filtered_out", lang))}</div>',
            unsafe_allow_html=True,
        )
        return

    station = matches.iloc[0]
    flow_m3s = None if pd.isna(station["flow_m3s"]) else float(station["flow_m3s"])
    normal_m3s = None if pd.isna(station.get("normal_m3s")) else float(station["normal_m3s"])
    ratio = None if pd.isna(station.get("normal_ratio")) else float(station["normal_ratio"])
    state = station.get("freshness", FRESHNESS_UNAVAILABLE)

    st.markdown(
        f'<div class="panel"><div class="panel-title">'
        f'{escape(str(station["libelle_station"]))}</div>'
        f'<div class="panel-sub">{escape(str(station["libelle_cours_eau"]))} · '
        f'{escape(str(station.get("libelle_departement") or ""))}</div></div>',
        unsafe_allow_html=True,
    )

    st.metric(t("detail.latest", lang), format_flow(flow_m3s, lang))
    st.markdown(
        f'<div class="state-row"><span class="state-dot" '
        f'style="background:{flow_color(flow_m3s)}"></span>'
        f"<span><b>{escape(freshness_label(state, lang))}</b> · "
        f"{escape(format_timestamp(station['measured_at']))}</span></div>",
        unsafe_allow_html=True,
    )

    if ratio is not None:
        color = normal_ratio_color(ratio)
        label = t(NORMAL_LEGEND_KEYS[_normal_index(ratio)], lang)
        st.markdown(
            f'<div style="margin-top:9px;"><span class="chip" '
            f'style="border-color:{color};color:{color};">'
            f'<span class="state-dot" style="background:{color}"></span>'
            f'{escape(label)} · {escape(t("detail.times_normal", lang, ratio=f"{ratio:.2f}"))}'
            "</span></div>",
            unsafe_allow_html=True,
        )

    if state == FRESHNESS_UNAVAILABLE:
        st.warning(t("detail.no_recent", lang, hours=DEFAULT_LOOKBACK_HOURS))
    elif state == FRESHNESS_DELAYED:
        st.info(t("detail.delayed", lang, minutes=FRESH_MINUTES))

    with st.expander(t("detail.reference", lang)):
        years = station.get("normal_years")
        normal_line = ""
        if normal_m3s and not pd.isna(years):
            normal_line = (
                f"- **{t('detail.normal', lang)}:** {format_flow(normal_m3s, lang)}"
                f" ({t('detail.normal_years', lang, years=int(years))})\n"
            )
        st.markdown(
            f"- **{t('detail.code', lang)}:** `{station['code_station']}`\n"
            f"- **{t('detail.river', lang)}:** {station['libelle_cours_eau']}\n"
            f"- **{t('detail.department', lang)}:** "
            f"{station.get('libelle_departement') or '—'}\n"
            f"- **{t('detail.coordinates', lang)}:** "
            f"{format_coordinates(station['latitude_station'], station['longitude_station'])}\n"
            f"- **{t('detail.published', lang)}:** {format_litres(station.get('flow_lps'))}\n"
            f"{normal_line}"
        )

    render_history_chart(
        str(station["code_station"]), str(station["libelle_station"]), normal_m3s, lang
    )


def _normal_index(ratio: float) -> int:
    """Index into NORMAL_LEGEND_KEYS for a current/normal ratio."""
    from src.config import NORMAL_CLASSES

    for index, (upper, _, _) in enumerate(NORMAL_CLASSES):
        if upper is None or ratio < upper:
            return index
    return len(NORMAL_LEGEND_KEYS) - 1


def render_top_stations_chart(stations: pd.DataFrame, lang: str) -> None:
    measured = stations.dropna(subset=["flow_m3s"])
    if measured.empty:
        st.info(t("top.none", lang))
        return

    top = measured.nlargest(min(TOP_N_STATIONS, len(measured)), "flow_m3s").iloc[::-1]
    figure = go.Figure(
        go.Bar(
            x=top["flow_m3s"], y=top["libelle_station"], orientation="h",
            marker={"color": [flow_color(v) for v in top["flow_m3s"]], "line": {"width": 0}},
            customdata=top[["libelle_cours_eau"]],
            hovertemplate="<b>%{y}</b><br>%{customdata[0]}<br>%{x:.3f} m³/s<extra></extra>",
        )
    )
    figure.update_layout(
        height=max(240, 28 * len(top)), margin={"l": 0, "r": 10, "t": 6, "b": 0},
        xaxis={"title": "m³/s", "gridcolor": "#eef2f6"},
        yaxis={"title": None, "automargin": True},
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
        transition={"duration": 350, "easing": "cubic-in-out"},
    )
    st.plotly_chart(
        figure, width="stretch", config={"displayModeBar": False}, key="top-stations"
    )


# ==========================================================================
# App
# ==========================================================================
def return_early_footer(lang: str) -> None:
    """Closing notes shown on the national view, which has no station panels."""
    st.markdown(
        f'<div class="foot" style="margin-top:12px;">{escape(t("foot.disclaimer", lang))} '
        f"{escape(ATTRIBUTION)}</div>",
        unsafe_allow_html=True,
    )
    theme.footer(t("foot.credit", lang, year=datetime.now(timezone.utc).year))


def main() -> None:
    lang = render_language_switch()
    controls = render_sidebar(lang)
    region = controls["region"]

    # The header costs nothing to draw and needs no API, so it goes up before
    # the network call. During a Hub'Eau outage the retry budget is ~17 s, and
    # a branded header beats 17 s of empty page.
    hero_slot = st.empty()
    with hero_slot.container():
        theme.hero(
            t("app.title", lang), t("hero.subtitle", lang),
            [("", t("hero.connecting", lang)),
             ("", t("hero.dept", lang, name=region.name, code=region.code))],
        )

    if region.is_national:
        # No per-station fetch: live discharge is a per-department query, and
        # doing it for every gauging station in France would be dozens of
        # calls against a free public API on every page load.
        stations = hubeau_empty()
        codes: tuple[str, ...] = ()
        flows = load_latest_flows(codes, "")
    else:
        with st.spinner(t("msg.loading", lang)):
            stations = load_stations(region.code)
            codes = tuple(stations["code_station"].tolist()) if not stations.empty else ()
            flows = load_latest_flows(codes, region.code)

    # Seasonal normals are an extra API round-trip, so only pay for them when
    # a feature that uses them is switched on.
    normals = pd.DataFrame()
    if codes and controls["color_by_normal"]:
        with st.spinner(t("msg.loading_normals", lang)):
            normals = load_seasonal_normals(codes, datetime.now(timezone.utc).month)

    table = add_freshness_column(build_station_table(stations, flows.frame, normals))
    render_live_sidebar_parts(controls, table, flows.fetched_at, lang)

    measured_count = int(table["flow_m3s"].notna().sum()) if not table.empty else 0
    if region.is_national:
        state, pill = "", t("national.pill", lang)
    elif stations.empty:
        state, pill = "down", t("hero.down", lang)
    elif flows.from_cache:
        state, pill = "stale", t("hero.cached", lang)
    elif not flows.ok or measured_count == 0:
        state, pill = "stale", t("hero.partial", lang)
    else:
        state, pill = "live", t("hero.live", lang, age=relative_age(flows.fetched_at, lang))

    scope_pill = (
        t("national.name", lang) if region.is_national
        else t("hero.dept", lang, name=region.name, code=region.code)
    )
    pills = [(state, pill), ("", scope_pill)]
    if not region.is_national:
        pills.append(("", t("hero.stations", lang, count=f"{len(stations):,}")))
    with hero_slot.container():
        theme.hero(t("app.title", lang), t("hero.subtitle", lang), pills)

    if region.is_national:
        st.info(t("national.prompt", lang))
    elif stations.empty:
        st.error(t("msg.api_down", lang))
    elif flows.from_cache:
        st.warning(
            t("msg.cached", lang,
              age=relative_age(flows.cached_at, lang), stamp=utc_label(flows.cached_at))
        )
    elif not flows.ok and flows.message:
        st.warning(flows.message)

    filtered = apply_filters(table, controls)
    rivers = load_rivers(controls["region_key"], controls["detail"])

    if region.is_national:
        render_national_metrics(rivers, lang)
    else:
        render_metrics(filtered, lang)

    if not region.is_national and filtered.empty and not table.empty:
        st.info(t("msg.no_match", lang))

    if controls["show_rivers"] and rivers is None:
        st.warning(t("msg.rivers_missing", lang, label=region.label, code=region.code))
    if (
        controls["detail"] == LOD_DETAIL
        and rivers is not None
        and not detail_is_available(region, LOD_DETAIL)
    ):
        st.caption(t("msg.detail_fallback", lang, name=region.name, code=region.code))

    dams = load_dams(controls["region_key"]) if controls["show_dams"] else None
    if controls["show_dams"] and dams is None:
        st.info(t("msg.dams_missing", lang, label=region.label, code=region.code))

    if controls["color_by_normal"] and not table.empty and table["normal_ratio"].notna().sum() == 0:
        st.info(t("msg.no_normals", lang))

    if region.is_national:
        map_column, detail_column = st.container(), None
    else:
        map_column, detail_column = st.columns([4.15, 1], gap="medium")

    with map_column:
        river_map = build_map(
            region=region,
            stations=filtered,
            rivers_geojson=rivers,
            show_rivers=controls["show_rivers"],
            show_stations=controls["show_stations"],
            show_dams=controls["show_dams"],
            show_labels=controls["show_labels"],
            color_by_normal=controls["color_by_normal"],
            animate=controls["animate"],
            flow_speed=controls["flow_speed"],
            boundary_geojson=load_boundary(controls["region_key"]),
            dams_geojson=dams,
            selected_code=st.session_state.get("selected_station"),
        )
        map_state = st_folium(
            river_map, height=780, width=None,
            returned_objects=["last_object_clicked"],
            key=f"map-{controls['region_key']}-{controls['detail']}",
        )

        pieces = []
        if rivers is not None and controls["show_rivers"]:
            _, major = split_rivers(rivers)
            pieces.append(f"{count_features(rivers):,} · {len(major['features']):,} ~")
        if dams:
            pieces.append(f"{len(dams.get('features') or []):,} ⌂")
        pieces.append(ATTRIBUTION)
        st.markdown(
            f'<div class="foot">{escape(" · ".join(pieces))}</div>', unsafe_allow_html=True
        )
        render_map_legend(controls, lang)

    clicked = find_clicked_station(filtered, (map_state or {}).get("last_object_clicked"))
    if clicked:
        st.session_state["selected_station"] = clicked

    if detail_column is None:
        return_early_footer(lang)
        return

    with detail_column:
        st.markdown(f"### {t('detail.heading', lang)}")
        codes_shown = filtered["code_station"].tolist() if not filtered.empty else []
        if codes_shown:
            labels = dict(zip(codes_shown, filtered["libelle_station"].tolist()))
            current = st.session_state.get("selected_station")
            # No default selection: history is only requested once the user
            # picks a station, on the map or here.
            chosen = st.selectbox(
                "station", options=codes_shown,
                index=codes_shown.index(current) if current in codes_shown else None,
                format_func=lambda code: labels.get(code, code),
                placeholder=t("detail.choose", lang), label_visibility="collapsed",
            )
            if chosen:
                st.session_state["selected_station"] = chosen
        selected = st.session_state.get("selected_station")
        render_station_details(filtered, selected if selected in codes_shown else None, lang)

    display = build_display_table(filtered, lang)

    with st.expander(t("table.heading", lang, count=f"{len(filtered):,}"), expanded=False):
        if filtered.empty:
            st.write(t("table.empty", lang))
        else:
            st.dataframe(display, width="stretch", hide_index=True)
            st.download_button(
                t("table.download", lang),
                data=display.to_csv(index=False).encode("utf-8"),
                file_name=f"river-flow-{region.key}-{utc_label().replace(' ', '_')}.csv",
                mime="text/csv",
            )
            st.markdown(
                f'<div class="foot">{escape(t("table.disclaimer", lang))}</div>',
                unsafe_allow_html=True,
            )

    with st.expander(t("top.heading", lang, n=TOP_N_STATIONS), expanded=False):
        render_top_stations_chart(filtered, lang)

    st.markdown(
        f'<div class="foot" style="margin-top:14px;">{escape(t("foot.disclaimer", lang))} '
        f"{escape(ATTRIBUTION)}</div>",
        unsafe_allow_html=True,
    )
    theme.footer(t("foot.credit", lang, year=datetime.now(timezone.utc).year))


if __name__ == "__main__":
    main()
