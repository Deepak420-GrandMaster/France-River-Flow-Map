"""Folium map construction: flowing rivers, stations, dams and labels.

Value formatting lives in :mod:`src.utils.formatters`; this module only turns
already-shaped data into map objects.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from html import escape

import folium
import pandas as pd
from folium.plugins import MarkerCluster

from src.config import (
    ATTRIBUTION,
    BASEMAP_ATTR,
    BASEMAP_LABELS_TILES,
    BASEMAP_MAX_NATIVE_ZOOM,
    BASEMAP_TILES,
    DAM_COLOR,
    FLOW_SPEED_DEFAULT,
    LABEL_COLOR,
    NORMAL_UNKNOWN_COLOR,
    RESERVOIR_COLOR,
    RIVER_BASE_COLOR,
    RIVER_BASE_OPACITY,
    RIVER_FLOW_COLOR,
    RIVER_FLOW_OPACITY,
    Region,
    flow_color,
    normal_ratio_color,
    normal_ratio_label,
)
from src.utils.flow_layer import FlowLayer, FlowSpeed
from src.utils.formatters import format_flow, format_litres, format_timestamp

# --------------------------------------------------------------------------
# Viewport maths
# --------------------------------------------------------------------------
#: Assumed map viewport used to derive a zoom level, in CSS pixels. The exact
#: values matter little -- they only need to be in the right ballpark, because
#: the resulting zoom is floored to an integer.
VIEWPORT_PX = (1000, 600)
MIN_ZOOM, MAX_ZOOM = 3, 15
TILE_SIZE_PX = 256
#: Leaflet is told to allow quarter-level zoom (zoomSnap), so a department can
#: be framed tightly instead of being rounded down by up to a whole level --
#: a whole level is a factor of two in area, which is what made a single
#: department look like a wide regional view.
ZOOM_STEP = 0.25
#: Fraction of the viewport left as breathing room around the department.
VIEW_PADDING = 0.94

#: Above this many stations, cluster them. Keeps a single department as plain
#: markers while staying usable if the scope ever widens.
CLUSTER_THRESHOLD = 150

#: Rivers big enough to carry the flow animation. Animating every line would
#: repaint thousands of SVG paths per frame; animating the ones a reader
#: actually looks at gives the same impression at a fraction of the cost.
MAJOR_WEIGHT_CLASS = 2
MAJOR_LENGTH_KM = 12.0

#: Flow-animation dash geometry, in screen pixels. A longer dash with a clear
#: gap reads as moving water; a short one just shimmers.
DASH_LENGTH_PX = 11
DASH_GAP_PX = 13
#: Full dash cycles travelled per animation period. Must stay an integer so
#: the loop is seamless.
DASH_CYCLES_PER_PERIOD = 4

#: Hard ceiling on animated paths. The animated layer is the only SVG layer on
#: the map, and every one of its paths is a DOM node repainted each frame. The
#: national layer marks nearly every river as "major", which would put 3,272
#: paths on screen; capping to the longest few hundred keeps the effect while
#: keeping the DOM small. Anything over the cap is drawn on canvas instead.
MAX_ANIMATED_FEATURES = 550

#: How many river names to label. Beyond this the map turns into a word cloud.
MAX_RIVER_LABELS = 26


def _mercator_y(latitude: float) -> float:
    """Web-Mercator y for a latitude in degrees (radians, unscaled)."""
    latitude = max(min(latitude, 85.05), -85.05)
    return math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2))


def compute_view(
    bounds: list[list[float]] | None,
    fallback_center: tuple[float, float],
    fallback_zoom: float = 9.0,
    viewport_px: tuple[int, int] = VIEWPORT_PX,
) -> tuple[list[float], float]:
    """Return ``(center, zoom)`` that frames ``bounds`` in the given viewport.

    Folium's ``fit_bounds`` is avoided on purpose: inside the ``st_folium``
    iframe it runs before the container has been laid out, so Leaflet measures
    a zero-size viewport and snaps to maximum zoom. Computing the zoom here is
    deterministic, testable, and independent of render timing.
    """
    if not bounds:
        return [fallback_center[0], fallback_center[1]], fallback_zoom

    (lat_min, lon_min), (lat_max, lon_max) = bounds
    center = [(lat_min + lat_max) / 2, (lon_min + lon_max) / 2]

    width_px, height_px = viewport_px
    lon_span = abs(lon_max - lon_min)
    lat_span = abs(_mercator_y(lat_max) - _mercator_y(lat_min))

    width_px *= VIEW_PADDING
    height_px *= VIEW_PADDING

    zooms = []
    if lon_span > 1e-9:
        zooms.append(math.log2(width_px / TILE_SIZE_PX * 360.0 / lon_span))
    if lat_span > 1e-9:
        zooms.append(math.log2(height_px / TILE_SIZE_PX * (2 * math.pi) / lat_span))
    if not zooms:
        return center, float(fallback_zoom)

    # Round down to the nearest quarter level: still guarantees the whole
    # department fits, but wastes far less of the viewport than floor().
    snapped = math.floor(min(zooms) / ZOOM_STEP) * ZOOM_STEP
    return center, float(max(MIN_ZOOM, min(MAX_ZOOM, snapped)))


def geojson_bounds(geojson: dict | None) -> list[list[float]] | None:
    """Return ``[[lat_min, lon_min], [lat_max, lon_max]]`` for any GeoJSON."""
    if not geojson:
        return None

    lons: list[float] = []
    lats: list[float] = []

    def walk(node) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
                lons.append(float(node[0]))
                lats.append(float(node[1]))
                return
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            for key in ("features", "geometry", "coordinates", "geometries"):
                if key in node:
                    walk(node[key])

    walk(geojson)
    if not lons or not lats:
        return None
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def outside_mask(boundary_geojson: dict | None) -> dict | None:
    """A world-sized polygon with the department punched out of it.

    Drawn under the data layers, it fades everything outside the selected
    department so the chosen area reads as the subject of the map rather than
    as one patch of a regional view.
    """
    if not boundary_geojson:
        return None

    features = boundary_geojson.get("features")
    if features is None:
        features = [boundary_geojson]

    holes: list = []
    for feature in features:
        geometry = (feature or {}).get("geometry") or {}
        kind, coordinates = geometry.get("type"), geometry.get("coordinates")
        if kind == "Polygon" and coordinates:
            holes.append(coordinates[0])
        elif kind == "MultiPolygon" and coordinates:
            holes.extend(polygon[0] for polygon in coordinates if polygon)
    if not holes:
        return None

    world = [[-180.0, -85.0], [180.0, -85.0], [180.0, 85.0], [-180.0, 85.0], [-180.0, -85.0]]
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [world, *holes]},
    }


def stabilise_ids(element, seed: str) -> None:
    """Give every element in the map a deterministic id.

    Folium mints a fresh UUID per object on every build, so an identically
    configured map produces different HTML each Streamlit rerun and
    ``st_folium`` tears Leaflet down and rebuilds it. Deriving ids from the
    inputs instead makes an unchanged map byte-identical, so the component can
    leave the existing map alone.
    """
    counter = itertools.count()
    seen: set[int] = set()

    def walk(node) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        node._id = hashlib.md5(
            f"{seed}:{next(counter)}".encode(), usedforsecurity=False
        ).hexdigest()[:16]

        children = getattr(node, "_children", None)
        if children is not None:
            for child in list(children.values()):
                walk(child)
            # The dict *keys* were derived from the children's original random
            # ids, and folium reuses those keys verbatim as JavaScript variable
            # names. Rebuild them so the emitted script is stable too.
            renamed = {child.get_name(): child for child in children.values()}
            if len(renamed) == len(children):
                children.clear()
                children.update(renamed)

        # Popup keeps its Html/script elements in plain attributes rather than
        # in _children, so a _children-only walk would leave those ids random.
        for name, value in list(vars(node).items()):
            if name != "_parent" and hasattr(value, "_id") and hasattr(value, "_children"):
                walk(value)

    walk(element)


# --------------------------------------------------------------------------
# River rendering
# --------------------------------------------------------------------------
def _is_major(feature: dict) -> bool:
    properties = feature.get("properties") or {}
    return (properties.get("weight_class") or 1) >= MAJOR_WEIGHT_CLASS or (
        properties.get("length_km") or 0
    ) >= MAJOR_LENGTH_KM


def split_rivers(geojson: dict | None) -> tuple[dict, dict]:
    """Split a river layer into (minor, major) collections.

    Only the major collection is animated -- see :data:`MAJOR_WEIGHT_CLASS`
    and :data:`MAX_ANIMATED_FEATURES`. When more features qualify than the cap
    allows, the longest win and the remainder fall back to the static canvas
    layer, so the map still shows every river.
    """
    empty = {"type": "FeatureCollection", "features": []}
    if not geojson:
        return empty, dict(empty)

    features = geojson.get("features") or []
    major = [f for f in features if _is_major(f)]
    minor = [f for f in features if not _is_major(f)]

    if len(major) > MAX_ANIMATED_FEATURES:
        major.sort(key=lambda f: -((f.get("properties") or {}).get("length_km") or 0))
        minor.extend(major[MAX_ANIMATED_FEATURES:])
        major = major[:MAX_ANIMATED_FEATURES]

    return (
        {"type": "FeatureCollection", "features": minor},
        {"type": "FeatureCollection", "features": major},
    )


def _river_weight(feature: dict, scale: float) -> float:
    properties = feature.get("properties") or {}
    return scale * (0.75 + 0.5 * float(properties.get("weight_class") or 1))


def _flow_animation_css(duration_seconds: float) -> str:
    """CSS injected *inside* the map iframe to make the rivers flow.

    Leaflet accepts a ``className`` path option, so the animation is a single
    keyframe rule shared by every animated path rather than per-feature
    JavaScript. ``stroke-dashoffset`` counts down so the dashes travel in the
    direction the geometry is digitised, which in BD TOPAGE is downstream.

    The dash pattern and travel distance are deliberately generous: with a
    short pattern the motion is technically present but too subtle to read as
    a current, which made the speed control look broken. One period now moves
    each dash four full cycles, so the difference between the slow and fast
    ends of the slider is unmistakable.
    """
    dash, gap = DASH_LENGTH_PX, DASH_GAP_PX
    travel = (dash + gap) * DASH_CYCLES_PER_PERIOD
    return f"""
    <style>
      .river-flow {{
        stroke-dasharray: {dash} {gap};
        stroke-linecap: butt;
        /* The duration comes from --flow-duration, which FlowSpeed sets from
           the script side; see src/utils/flow_layer.py for why. */
        animation: riverflow var(--flow-duration, {duration_seconds:.2f}s) linear infinite;
        will-change: stroke-dashoffset;
      }}
      @keyframes riverflow {{
        from {{ stroke-dashoffset: {travel}; }}
        to   {{ stroke-dashoffset: 0; }}
      }}
      .river-label {{
        color: {LABEL_COLOR};
        font: 600 10.5px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        text-shadow: 0 0 3px #fff, 0 0 3px #fff, 0 0 3px #fff, 0 0 3px #fff;
        white-space: nowrap; pointer-events: none;
      }}
      .leaflet-container {{
        background: #eef3f7;
        animation: mapIn .34s cubic-bezier(.22,.61,.36,1) both;
        /* Google-Maps behaviour: a plain arrow over the map, a pointer only
           over things you can actually click. Leaflet's default grab-hand
           made every part of the map look draggable-but-inert. */
        cursor: default;
      }}
      .leaflet-container:active {{ cursor: grabbing; }}
      .leaflet-marker-icon, .leaflet-interactive {{ cursor: pointer; }}
      .station-pin {{
        transition: transform .16s cubic-bezier(.22,.61,.36,1),
                    filter .16s ease-out;
        transform-origin: 50% 100%;
      }}
      .station-pin:hover {{ transform: scale(1.18); filter: brightness(1.05); }}
      .station-pin.is-selected {{ animation: pinDrop .45s cubic-bezier(.2,.9,.3,1.2) both; }}
      @keyframes pinDrop {{
        0%   {{ transform: translateY(-9px) scale(.85); opacity: .4; }}
        100% {{ transform: none; opacity: 1; }}
      }}
      html, body {{ background: #eef3f7; }}
      @keyframes mapIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
      .leaflet-tile {{ transition: opacity .28s ease-out; }}
      @media (prefers-reduced-motion: reduce) {{
        .river-flow, .leaflet-container,
        .station-pin, .station-pin.is-selected {{ animation: none; transition: none; }}
      }}
    </style>
    """


# --------------------------------------------------------------------------
# Popups
# --------------------------------------------------------------------------
def _popup_shell(title: str, subtitle: str, body: str, width: int = 250) -> str:
    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;width:{width}px;">
      <div style="font-size:13.5px;font-weight:650;color:#0d2438;line-height:1.3;">{title}</div>
      <div style="font-size:11.5px;color:#7b8fa1;margin-bottom:8px;">{subtitle}</div>
      <div style="border-top:1px solid #e6ebf0;padding-top:8px;">{body}</div>
    </div>
    """


def _station_popup(row: pd.Series) -> str:
    """Popup markup. Every dynamic value is HTML-escaped."""
    flow_m3s = row.get("flow_m3s")
    flow_value = None if pd.isna(flow_m3s) else float(flow_m3s)
    color = flow_color(flow_value)

    parts = [
        f'<div style="font-size:20px;font-weight:650;color:{color};">'
        f"{escape(format_flow(flow_value))}</div>"
    ]
    flow_lps = row.get("flow_lps")
    if not pd.isna(flow_lps):
        parts.append(
            f'<div style="color:#7b8fa1;font-size:11px;margin-top:2px;">'
            f"{escape(format_litres(flow_lps))} as published</div>"
        )

    ratio = row.get("normal_ratio")
    if ratio is not None and not pd.isna(ratio):
        ratio_value = float(ratio)
        parts.append(
            f'<div style="margin-top:7px;font-size:11.5px;color:#476175;">'
            f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
            f'background:{normal_ratio_color(ratio_value)};margin-right:5px;"></span>'
            f"{escape(normal_ratio_label(ratio_value))} "
            f"({ratio_value:.2f}× normal)</div>"
        )

    parts.append(
        f'<div style="font-size:11px;color:#7b8fa1;margin-top:6px;">'
        f"Measured {escape(format_timestamp(row.get('measured_at')))}</div>"
        f'<div style="font-size:10.5px;color:#9aa9b6;margin-top:2px;">'
        f"Station {escape(str(row.get('code_station') or '-'))}</div>"
    )

    return _popup_shell(
        escape(str(row.get("libelle_station") or "Unnamed station")),
        escape(str(row.get("libelle_cours_eau") or "Unnamed watercourse")),
        "".join(parts),
    )


def _dam_popup(properties: dict) -> str:
    category = escape(str(properties.get("category") or "Water body"))
    area = properties.get("area_ha")
    altitude = properties.get("altitude_m")
    rows = []
    if area is not None:
        rows.append(f"<div>Surface area: <b>{float(area):,.1f} ha</b></div>")
    if altitude is not None and not pd.isna(altitude):
        rows.append(f"<div>Altitude: <b>{float(altitude):,.0f} m</b></div>")
    rows.append(
        '<div style="margin-top:6px;color:#9aa9b6;font-size:10.5px;">'
        "BD TOPAGE — no live measurement at this structure.</div>"
    )
    return _popup_shell(
        escape(str(properties.get("name") or "Unnamed")),
        category,
        f'<div style="font-size:11.5px;color:#476175;line-height:1.55;">{"".join(rows)}</div>',
        width=225,
    )


# --------------------------------------------------------------------------
# Map assembly
# --------------------------------------------------------------------------
def build_map(
    region: Region,
    stations: pd.DataFrame,
    rivers_geojson: dict | None = None,
    *,
    show_rivers: bool = True,
    show_stations: bool = True,
    show_dams: bool = False,
    show_labels: bool = False,
    color_by_normal: bool = False,
    animate: bool = True,
    flow_speed: float = FLOW_SPEED_DEFAULT,
    boundary_geojson: dict | None = None,
    dams_geojson: dict | None = None,
    selected_code: str | None = None,
) -> folium.Map:
    """Assemble the Folium map. A pure function of its inputs."""
    bounds = geojson_bounds(boundary_geojson) or region.bounds
    if bounds is None and len(stations) > 1:
        latitudes = stations["latitude_station"].astype(float)
        longitudes = stations["longitude_station"].astype(float)
        bounds = [
            [float(latitudes.min()), float(longitudes.min())],
            [float(latitudes.max()), float(longitudes.max())],
        ]
    center, zoom = compute_view(bounds, region.center)

    river_map = folium.Map(
        location=center,
        zoom_start=zoom,
        # The basemap is added below rather than here: folium's own ``tiles``
        # argument gives no way to set max_native_zoom, and the labels need a
        # second layer of their own.
        tiles=None,
        control_scale=True,
        # Canvas is the map default: it draws the ~900 static river paths far
        # faster than SVG when panning. Only the small animated subset opts
        # into SVG, because the flow animation is a CSS rule on
        # stroke-dashoffset and that needs real DOM paths.
        prefer_canvas=True,
        zoom_control=True,
        zoomSnap=0.25,
        zoomDelta=0.5,
    )
    _add_basemap(river_map)
    river_map.get_root().html.add_child(folium.Element(_flow_animation_css(flow_speed)))
    # Must be added to the map (not the root html) so it lands in the script
    # that st_folium hashes -- otherwise the speed control has no effect.
    FlowSpeed(flow_speed).add_to(river_map)

    # Fade everything outside the department so the selected area is the
    # subject of the map, not one patch of a wider region.
    mask = outside_mask(boundary_geojson)
    if mask:
        folium.GeoJson(
            mask,
            name="Outside area",
            style_function=lambda _: {
                "stroke": False, "fill": True,
                "fillColor": "#f4f7fa", "fillOpacity": .72,
            },
            interactive=False,
        ).add_to(river_map)

    if boundary_geojson:
        folium.GeoJson(
            boundary_geojson,
            name="Department boundary",
            style_function=lambda _: {
                "color": "#8fa3b3", "weight": 1.3, "opacity": .9,
                "fill": False, "dashArray": "3,4",
            },
            interactive=False,
        ).add_to(river_map)

    if show_rivers and rivers_geojson:
        minor, major = split_rivers(rivers_geojson)

        if minor["features"]:
            FlowLayer(
                minor, RIVER_BASE_COLOR, RIVER_BASE_OPACITY,
                base_weight=0.6, weight_step=0.42, smooth_factor=1.8,
                use_svg=False, name="Tributaries",
            ).add_to(river_map)

        if major["features"]:
            # Static under-stroke keeps the river readable between dashes.
            FlowLayer(
                major, RIVER_BASE_COLOR, 0.8,
                base_weight=1.1, weight_step=0.72, smooth_factor=1.5,
                use_svg=False, name="Rivers",
            ).add_to(river_map)
            # Animated over-stroke: the visible current.
            FlowLayer(
                major, RIVER_FLOW_COLOR, RIVER_FLOW_OPACITY,
                base_weight=1.0, weight_step=0.62, smooth_factor=1.5,
                class_name="river-flow" if animate else "",
                use_svg=bool(animate), name="Flow",
            ).add_to(river_map)

        if show_labels:
            _add_river_labels(river_map, major)

    if show_dams and dams_geojson:
        _add_dams(river_map, dams_geojson)

    if show_stations and not stations.empty:
        _add_stations(river_map, stations, color_by_normal, selected_code)

    # Same inputs -> same element ids -> byte-identical HTML, so st_folium can
    # leave an unchanged map in place instead of rebuilding Leaflet.
    stabilise_ids(
        river_map.get_root(),
        "|".join(
            str(part)
            for part in (
                region.code, show_rivers, show_stations, show_dams, show_labels,
                color_by_normal, animate, round(flow_speed, 3), selected_code,
                len(stations), rivers_geojson is not None, dams_geojson is not None,
            )
        ),
    )
    return river_map


def _add_basemap(river_map: folium.Map) -> None:
    """Lay down the basemap, and its place names when they ship separately.

    ``max_native_zoom`` is the point of doing this by hand: Esri's raster
    canvas has no tiles past z16, and without it Leaflet asks for z17+ and
    renders blank squares instead of upscaling the last level it has.

    The labels go on immediately, before the out-of-area mask and the river
    layers, so the map keeps the stacking CARTO gave it for free when place
    names were baked into the tile: names sit under the data, and names
    outside the selected department fade with everything else.
    """
    folium.TileLayer(
        BASEMAP_TILES,
        attr=BASEMAP_ATTR,
        name="Basemap",
        max_native_zoom=BASEMAP_MAX_NATIVE_ZOOM,
        control=False,
    ).add_to(river_map)

    if BASEMAP_LABELS_TILES:
        folium.TileLayer(
            BASEMAP_LABELS_TILES,
            attr=BASEMAP_ATTR,
            name="Place names",
            max_native_zoom=BASEMAP_MAX_NATIVE_ZOOM,
            overlay=True,
            control=False,
        ).add_to(river_map)


def _add_river_labels(river_map: folium.Map, major: dict) -> None:
    """Label the longest named rivers at their midpoint."""
    named = [
        feature
        for feature in major.get("features", [])
        if (feature.get("properties") or {}).get("name")
    ]
    named.sort(key=lambda f: -(f["properties"].get("length_km") or 0))

    group = folium.FeatureGroup(name="River names")
    seen: set[str] = set()
    for feature in named:
        name = str(feature["properties"]["name"])
        if name in seen:
            continue
        point = _midpoint(feature.get("geometry"))
        if point is None:
            continue
        seen.add(name)
        folium.Marker(
            location=point,
            icon=folium.DivIcon(
                html=f'<div class="river-label">{escape(name)}</div>',
                icon_size=(0, 0),
                icon_anchor=(0, 0),
            ),
        ).add_to(group)
        if len(seen) >= MAX_RIVER_LABELS:
            break
    group.add_to(river_map)


def _midpoint(geometry: dict | None) -> list[float] | None:
    """Middle vertex of a (Multi)LineString, as ``[lat, lon]``."""
    if not geometry:
        return None
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "MultiLineString":
        if not coordinates:
            return None
        coordinates = max(coordinates, key=len)
    if not coordinates or not isinstance(coordinates[0], (list, tuple)):
        return None
    longitude, latitude = coordinates[len(coordinates) // 2][:2]
    return [float(latitude), float(longitude)]


#: Above this many structures, cluster them rather than drawing every marker.
DAM_CLUSTER_THRESHOLD = 250


def _add_dams(river_map: folium.Map, dams_geojson: dict) -> None:
    features = dams_geojson.get("features") or []
    if len(features) > DAM_CLUSTER_THRESHOLD:
        group = MarkerCluster(name="Dams & reservoirs", options={"maxClusterRadius": 45})
    else:
        group = folium.FeatureGroup(name="Dams & reservoirs")
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        longitude, latitude = geometry["coordinates"][:2]
        properties = feature.get("properties") or {}
        is_dam = properties.get("category") == "Dam"
        color = DAM_COLOR if is_dam else RESERVOIR_COLOR
        area = properties.get("area_ha") or 0

        folium.CircleMarker(
            location=[latitude, longitude],
            radius=4 if is_dam else min(3 + math.log10(max(area, 1)) * 1.6, 8),
            color="#ffffff",
            weight=1.1,
            fill=True,
            fill_color=color,
            fill_opacity=.85,
            tooltip=(
                f"{escape(str(properties.get('name') or 'Unnamed'))} — "
                f"{escape(str(properties.get('category') or ''))}"
            ),
            popup=folium.Popup(_dam_popup(properties), max_width=250),
        ).add_to(group)
    group.add_to(river_map)


def _pin_svg(color: str, selected: bool) -> str:
    """A Google-Maps-style teardrop pin, coloured by the active scheme."""
    size = 34 if selected else 28
    ring = "#0d2438" if selected else "#ffffff"
    return (
        f'<svg class="station-pin{" is-selected" if selected else ""}" '
        f'width="{size}" height="{size}" viewBox="0 0 24 32" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<ellipse cx="12" cy="29.5" rx="4.2" ry="1.7" fill="rgba(13,36,56,.22)"/>'
        f'<path d="M12 1.5c-5.2 0-9.4 4.2-9.4 9.4 0 6.7 8.2 15.4 8.6 15.8a1.1 1.1 0 0 0 1.7 0'
        f'c.3-.4 8.6-9.1 8.6-15.8 0-5.2-4.3-9.4-9.5-9.4z" '
        f'fill="{color}" stroke="{ring}" stroke-width="1.7"/>'
        f'<circle cx="12" cy="10.8" r="3.4" fill="#ffffff" fill-opacity=".92"/>'
        f"</svg>"
    )


def _add_stations(
    river_map: folium.Map,
    stations: pd.DataFrame,
    color_by_normal: bool,
    selected_code: str | None,
) -> None:
    if len(stations) > CLUSTER_THRESHOLD:
        container = MarkerCluster(name="Gauging stations").add_to(river_map)
    else:
        container = folium.FeatureGroup(name="Gauging stations").add_to(river_map)

    for row in stations.itertuples(index=False):
        record = pd.Series(row._asdict())
        flow_m3s = record.get("flow_m3s")
        flow_value = None if pd.isna(flow_m3s) else float(flow_m3s)

        if color_by_normal:
            ratio = record.get("normal_ratio")
            ratio_value = None if ratio is None or pd.isna(ratio) else float(ratio)
            fill = (
                normal_ratio_color(ratio_value)
                if ratio_value is not None
                else NORMAL_UNKNOWN_COLOR
            )
        else:
            fill = flow_color(flow_value)

        is_selected = selected_code is not None and record["code_station"] == selected_code
        size = 34 if is_selected else 28

        folium.Marker(
            location=[record["latitude_station"], record["longitude_station"]],
            icon=folium.DivIcon(
                html=_pin_svg(fill, is_selected),
                icon_size=(size, size),
                # Anchor at the tip of the teardrop, so the pin points at the
                # actual coordinate rather than being centred on it.
                icon_anchor=(size // 2, size),
                popup_anchor=(0, -size + 4),
                class_name="station-pin-wrap",
            ),
            tooltip=(
                f"{escape(str(record.get('libelle_station') or ''))} — "
                f"{escape(format_flow(flow_value))}"
            ),
            popup=folium.Popup(_station_popup(record), max_width=290),
        ).add_to(container)


def find_clicked_station(stations: pd.DataFrame, clicked: dict | None) -> str | None:
    """Map an ``st_folium`` click back to a station code by coordinates.

    ``st_folium`` reports the clicked position rather than a feature id, so we
    match on proximity. The tolerance is ~30 m, far below the spacing between
    gauging stations.
    """
    if not clicked or stations.empty:
        return None
    latitude, longitude = clicked.get("lat"), clicked.get("lng")
    if latitude is None or longitude is None:
        return None

    distances = (stations["latitude_station"] - latitude).abs() + (
        stations["longitude_station"] - longitude
    ).abs()
    if distances.empty or distances.min() > 0.0005:
        return None
    return str(stations.loc[distances.idxmin(), "code_station"])


__all__ = [
    "ATTRIBUTION", "build_map", "compute_view", "find_clicked_station",
    "geojson_bounds", "outside_mask", "split_rivers", "stabilise_ids",
]
