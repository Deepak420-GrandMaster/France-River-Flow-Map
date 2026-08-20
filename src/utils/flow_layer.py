"""A GeoJSON line layer rendered by Leaflet with an explicit renderer.

Why this exists instead of ``folium.GeoJson``:

* **Renderer control.** The flow animation is a CSS rule on
  ``stroke-dashoffset``, which only applies to SVG. But drawing *every* river
  as SVG means ~900 DOM nodes to repaint on each pan. This layer lets the map
  default to the (much faster) canvas renderer while the small animated subset
  opts into SVG.
* **Smaller payload.** ``folium.GeoJson`` evaluates its ``style_function`` in
  Python and embeds a style object into every feature. Here the style is a
  single client-side function, so only geometry crosses the wire.
"""

from __future__ import annotations

import json

from branca.element import MacroElement
from jinja2 import Template

#: Characters that must never reach the browser literally when JSON is
#: embedded inside a <script> element. JSON does not escape "/", so a river
#: name containing "</script>" would terminate the enclosing script tag and
#: everything after it would be parsed as HTML -- a script-injection hole fed
#: by whatever the source dataset happens to contain. These are valid JSON
#: escapes, so the parsed value is unchanged.
_JSON_HTML_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", "\u2028": "\\u2028", "\u2029": "\\u2029"}


def embed_json(data: dict) -> str:
    """Serialise ``data`` for safe inclusion in an inline <script> block."""
    text = json.dumps(data, separators=(",", ":"))
    for character, replacement in _JSON_HTML_ESCAPES.items():
        text = text.replace(character, replacement)
    return text


class FlowLayer(MacroElement):
    """Polyline layer with a client-side style function and a chosen renderer."""

    _template = Template(
        """
        {% macro script(this, kwargs) %}
            var {{ this.get_name() }} = L.geoJSON(
                {{ this.data }},
                {
                    renderer: {{ this.renderer }},
                    interactive: false,
                    smoothFactor: {{ this.smooth_factor }},
                    style: function (feature) {
                        var w = feature.properties.weight_class || 1;
                        return {
                            color: "{{ this.color }}",
                            weight: {{ this.base_weight }} + {{ this.weight_step }} * w,
                            opacity: {{ this.opacity }},
                            lineCap: "round",
                            lineJoin: "round"
                            {%- if this.class_name %},
                            className: "{{ this.class_name }}"
                            {%- endif %}
                        };
                    }
                }
            ).addTo({{ this._parent.get_name() }});
        {% endmacro %}
        """
    )

    def __init__(
        self,
        data: dict,
        color: str,
        opacity: float,
        *,
        base_weight: float = 0.75,
        weight_step: float = 0.5,
        class_name: str = "",
        use_svg: bool = False,
        smooth_factor: float = 1.5,
        name: str = "FlowLayer",
    ) -> None:
        super().__init__()
        self._name = name
        # separators= keeps the embedded JSON tight; embed_json also neutralises
        # any "</script>" hiding in a feature name.
        self.data = embed_json(data)
        self.color = color
        self.opacity = opacity
        self.base_weight = base_weight
        self.weight_step = weight_step
        self.class_name = class_name
        self.smooth_factor = smooth_factor
        self.renderer = "L.svg({padding: 0.4})" if use_svg else "L.canvas({padding: 0.4})"


class FlowSpeed(MacroElement):
    """Publishes the animation duration as a CSS custom property.

    This exists because of how ``st_folium`` decides whether to re-render:
    its component key is ``generate_js_hash(leaflet, ...)``, computed from the
    map's **script** only. Anything that lives purely in the ``<style>`` block
    -- which is where a CSS animation naturally goes -- can change freely
    without changing that key, so the component is never re-rendered and the
    new value never reaches the browser. That is exactly what made the flow
    speed control look inert.

    Emitting the duration as a line of JavaScript puts it inside the hashed
    script, so moving the slider genuinely updates the map.
    """

    _template = Template(
        """
        {% macro script(this, kwargs) %}
            document.documentElement.style.setProperty(
                "--flow-duration", "{{ this.duration }}s"
            );
        {% endmacro %}
        """
    )

    def __init__(self, duration_seconds: float) -> None:
        super().__init__()
        self._name = "FlowSpeed"
        self.duration = f"{duration_seconds:.2f}"
