"""English / French interface strings.

French is a first-class language here rather than an afterthought: the data,
the rivers and most of the audience are French. Terms follow standard French
hydrological usage — *débit* for discharge, *station hydrométrique* for a
gauging station, *étiage/crue* vocabulary avoided since these are raw
observations rather than an alert product.

Usage::

    from src.i18n import t
    t("hero.title", lang)

Unknown keys return the key itself, which makes a missing translation obvious
in the UI instead of crashing.
"""

from __future__ import annotations

LANGUAGES = {"en": "EN", "fr": "FR"}
DEFAULT_LANGUAGE = "en"

#: Regional-indicator flag emoji for the language switch. Windows Chrome does
#: not render these as flags and falls back to the two letters ("GB", "FR"),
#: which still reads correctly next to the language code -- so the control is
#: never left as a bare unlabelled square.
LANGUAGE_FLAGS = {"en": "\U0001F1EC\U0001F1E7", "fr": "\U0001F1EB\U0001F1F7"}


def language_label(code: str) -> str:
    """Flag + code, e.g. "🇬🇧 EN"."""
    return f"{LANGUAGE_FLAGS.get(code, '')} {LANGUAGES.get(code, code)}".strip()

STRINGS: dict[str, dict[str, str]] = {
    # -- header --------------------------------------------------------
    "app.title": {"en": "France River Flow", "fr": "Débits des rivières de France"},
    "app.tagline": {
        "en": "Live hydrometric observations",
        "fr": "Observations hydrométriques en direct",
    },
    "hero.subtitle": {
        "en": "Observed discharge at hydrometric gauging stations, drawn over the "
              "French river network. Every metropolitan department, updated through the day.",
        "fr": "Débits observés aux stations hydrométriques, superposés au réseau "
              "hydrographique français. Tous les départements métropolitains, actualisés "
              "au fil de la journée.",
    },
    "hero.connecting": {"en": "Connecting to Hub'Eau…", "fr": "Connexion à Hub'Eau…"},
    "hero.live": {"en": "Live · updated {age}", "fr": "En direct · actualisé {age}"},
    "hero.partial": {"en": "Live data partial", "fr": "Données partielles"},
    "hero.cached": {"en": "Cached data", "fr": "Données en cache"},
    "hero.down": {"en": "Hub'Eau unavailable", "fr": "Hub'Eau indisponible"},
    "hero.dept": {"en": "{name} · dept. {code}", "fr": "{name} · dép. {code}"},
    "hero.stations": {"en": "{count} active stations", "fr": "{count} stations actives"},

    # -- sidebar -------------------------------------------------------
    "side.area": {"en": "Area", "fr": "Territoire"},
    "national.name": {"en": "France — all rivers", "fr": "France — tous les cours d'eau"},
    "national.pill": {"en": "Whole country", "fr": "France entière"},
    "national.prompt": {
        "en": "Showing the main river network of metropolitan France. "
              "**Pick a department** in the sidebar to load live gauging stations "
              "and discharge for that area.",
        "fr": "Réseau hydrographique principal de la France métropolitaine. "
              "**Choisissez un département** dans la barre latérale pour charger les "
              "stations et les débits en direct de ce territoire.",
    },
    "metric.rivers": {"en": "Rivers drawn", "fr": "Cours d'eau tracés"},
    "metric.length": {"en": "Network length", "fr": "Linéaire du réseau"},
    "metric.departments": {"en": "Departments", "fr": "Départements"},
    "metric.longest": {"en": "Longest river", "fr": "Plus long cours d'eau"},
    "side.department": {"en": "Department", "fr": "Département"},
    "side.department_help": {
        "en": "All 96 metropolitan departments. Live stations come from Hub'Eau.",
        "fr": "Les 96 départements métropolitains. Les stations proviennent de Hub'Eau.",
    },
    "side.layers": {"en": "Map layers", "fr": "Couches de la carte"},
    "side.stations": {"en": "Gauging stations", "fr": "Stations hydrométriques"},
    "side.dams": {"en": "Dams & reservoirs", "fr": "Barrages et retenues"},
    "side.dams_help": {
        "en": "Structures from BD TOPAGE. These are not measured in real time.",
        "fr": "Ouvrages issus de BD TOPAGE. Ils ne font l'objet d'aucune mesure en temps réel.",
    },
    "side.labels": {"en": "River names", "fr": "Noms des cours d'eau"},
    "side.normal": {"en": "Flow vs normal", "fr": "Débit vs normale"},
    "side.normal_help": {
        "en": "Recolours stations by how today's discharge compares with the median "
              "for this calendar month across all published years.",
        "fr": "Recolore les stations selon l'écart entre le débit du jour et la médiane "
              "du même mois calendaire sur toutes les années publiées.",
    },
    "side.rivers": {"en": "Rivers", "fr": "Cours d'eau"},
    "side.river_layer": {"en": "River layer", "fr": "Couche hydrographique"},
    "side.animate": {"en": "Animate the current", "fr": "Animer le courant"},
    "side.animate_help": {
        "en": "Dashes travel downstream along the main rivers.",
        "fr": "Les tirets se déplacent vers l'aval le long des cours d'eau principaux.",
    },
    "side.speed": {"en": "Flow speed", "fr": "Vitesse d'animation"},
    "side.filters": {"en": "Filters", "fr": "Filtres"},
    "side.only_recent": {
        "en": "Only stations with recent flow",
        "fr": "Uniquement les stations avec un débit récent",
    },
    "side.only_recent_help": {
        "en": "Hides stations with no discharge published in the last {hours} hours.",
        "fr": "Masque les stations sans débit publié depuis {hours} heures.",
    },
    "side.cities": {"en": "City", "fr": "Commune"},
    "side.cities_placeholder": {"en": "All cities", "fr": "Toutes les communes"},
    "side.cities_help": {
        "en": "Keeps only the stations sited in the chosen communes. "
              "Leave it empty to keep every city.",
        "fr": "Ne garde que les stations situées dans les communes choisies. "
              "Laisser vide pour toutes les communes.",
    },
    "side.cities_unavailable": {
        "en": "City filter unavailable: no stations loaded.",
        "fr": "Filtre par commune indisponible : aucune station chargée.",
    },
    "side.search": {"en": "River, station or code", "fr": "Cours d'eau, station ou code"},
    "side.range": {"en": "Discharge range (m³/s)", "fr": "Plage de débit (m³/s)"},
    "side.range_help": {
        "en": "Stations without a reading are kept unless the toggle above hides them.",
        "fr": "Les stations sans mesure sont conservées, sauf si l'option ci-dessus les masque.",
    },
    "side.range_unavailable": {
        "en": "Discharge filter unavailable: no live readings loaded.",
        "fr": "Filtre de débit indisponible : aucune mesure chargée.",
    },
    "side.data": {"en": "Data", "fr": "Données"},
    "side.refresh": {"en": "Refresh live data", "fr": "Actualiser les données"},
    "side.updated": {"en": "Updated {age} · {stamp}", "fr": "Actualisé {age} · {stamp}"},
    "side.about": {"en": "About the data", "fr": "À propos des données"},

    # -- levels of detail ----------------------------------------------
    "lod.overview": {"en": "Overview", "fr": "Vue d'ensemble"},
    "lod.detail": {"en": "Detailed", "fr": "Détaillée"},
    "lod.hidden": {"en": "Hide rivers", "fr": "Masquer les cours d'eau"},

    # -- metrics -------------------------------------------------------
    "metric.shown": {"en": "Stations shown", "fr": "Stations affichées"},
    "metric.recent": {"en": "With recent flow", "fr": "Avec débit récent"},
    "metric.median": {"en": "Median discharge", "fr": "Débit médian"},
    "metric.max": {"en": "Highest discharge", "fr": "Débit maximal"},

    # -- station detail ------------------------------------------------
    "detail.heading": {"en": "Station details", "fr": "Détail de la station"},
    "detail.choose": {"en": "Choose a station", "fr": "Choisir une station"},
    "detail.empty": {
        "en": "Select a station on the map, or choose one above, to see its readings and history.",
        "fr": "Sélectionnez une station sur la carte, ou choisissez-en une ci-dessus, "
              "pour voir ses mesures et son historique.",
    },
    "detail.filtered_out": {
        "en": "The selected station is outside the current filters.",
        "fr": "La station sélectionnée est exclue par les filtres actuels.",
    },
    "detail.latest": {"en": "Latest discharge", "fr": "Dernier débit"},
    "detail.reference": {"en": "Station reference", "fr": "Fiche station"},
    "detail.code": {"en": "Station code", "fr": "Code station"},
    "detail.river": {"en": "River", "fr": "Cours d'eau"},
    "detail.department": {"en": "Department", "fr": "Département"},
    "detail.coordinates": {"en": "Coordinates", "fr": "Coordonnées"},
    "detail.published": {"en": "Published value", "fr": "Valeur publiée"},
    "detail.normal": {"en": "Normal for this month", "fr": "Normale du mois"},
    "detail.normal_years": {"en": "median of {years} years", "fr": "médiane sur {years} ans"},
    "detail.no_recent": {
        "en": "No discharge published in the last {hours} hours.",
        "fr": "Aucun débit publié depuis {hours} heures.",
    },
    "detail.delayed": {
        "en": "This reading is more than {minutes} minutes old. Publication delays are "
              "normal for some stations.",
        "fr": "Cette mesure date de plus de {minutes} minutes. Certains postes publient "
              "avec un décalage.",
    },
    "detail.times_normal": {"en": "{ratio}× normal", "fr": "{ratio}× la normale"},

    # -- history chart -------------------------------------------------
    "chart.24h": {"en": "24 hours", "fr": "24 heures"},
    "chart.7d": {"en": "7 days", "fr": "7 jours"},
    "chart.none": {
        "en": "No discharge published for this station in the last {window}. "
              "Real-time coverage is limited and varies by station.",
        "fr": "Aucun débit publié pour cette station sur les dernières {window}. "
              "La couverture temps réel est partielle et variable selon les stations.",
    },
    "chart.readings": {
        "en": "{count} readings, converted from L/s. Source: Hub'Eau.",
        "fr": "{count} mesures, converties depuis les L/s. Source : Hub'Eau.",
    },
    "chart.normal_line": {
        "en": "Normal for this month: {value}",
        "fr": "Normale du mois : {value}",
    },

    # -- legend --------------------------------------------------------
    "legend.title_flow": {"en": "Legend — Latest discharge", "fr": "Légende — Dernier débit"},
    "legend.title_normal": {"en": "Legend — Flow vs normal", "fr": "Légende — Débit vs normale"},
    "legend.main_river": {
        "en": "Main river (animated downstream)",
        "fr": "Cours d'eau principal (animé vers l'aval)",
    },
    "legend.tributary": {"en": "Tributary", "fr": "Affluent"},
    "legend.dam": {"en": "Dam", "fr": "Barrage"},
    "legend.reservoir": {"en": "Reservoir or lake", "fr": "Retenue ou lac"},

    # -- flow classes --------------------------------------------------
    "flow.under1": {"en": "Under 1 m³/s", "fr": "Moins de 1 m³/s"},
    "flow.1to10": {"en": "1 – 10 m³/s", "fr": "1 – 10 m³/s"},
    "flow.10to100": {"en": "10 – 100 m³/s", "fr": "10 – 100 m³/s"},
    "flow.over100": {"en": "Over 100 m³/s", "fr": "Plus de 100 m³/s"},
    "flow.none": {"en": "No recent reading", "fr": "Aucune mesure récente"},

    # -- normal classes ------------------------------------------------
    "normal.much_below": {"en": "Much below normal", "fr": "Très inférieur à la normale"},
    "normal.below": {"en": "Below normal", "fr": "Inférieur à la normale"},
    "normal.near": {"en": "Near normal", "fr": "Proche de la normale"},
    "normal.above": {"en": "Above normal", "fr": "Supérieur à la normale"},
    "normal.much_above": {"en": "Much above normal", "fr": "Très supérieur à la normale"},
    "normal.unknown": {"en": "No reference data", "fr": "Pas de référence"},

    # -- freshness -----------------------------------------------------
    "fresh.recent": {"en": "Recent", "fr": "Récent"},
    "fresh.delayed": {"en": "Delayed", "fr": "Différé"},
    "fresh.unavailable": {"en": "Unavailable", "fr": "Indisponible"},

    # -- table ---------------------------------------------------------
    "table.heading": {"en": "Station data — {count} rows", "fr": "Données stations — {count} lignes"},
    "table.station": {"en": "Station", "fr": "Station"},
    "table.river": {"en": "River", "fr": "Cours d'eau"},
    "table.code": {"en": "Code", "fr": "Code"},
    "table.discharge": {"en": "Discharge (m³/s)", "fr": "Débit (m³/s)"},
    "table.observed": {"en": "Observed at (UTC)", "fr": "Mesuré le (UTC)"},
    "table.freshness": {"en": "Freshness", "fr": "Fraîcheur"},
    "table.download": {"en": "Download filtered data (CSV)", "fr": "Télécharger les données (CSV)"},
    "table.empty": {
        "en": "No stations match the current filters.",
        "fr": "Aucune station ne correspond aux filtres actuels.",
    },
    "table.disclaimer": {
        "en": "Observed discharge only. Not flood-risk predictions and not "
              "water-quality indicators.",
        "fr": "Débits observés uniquement. Ni prévision de crue, ni indicateur de "
              "qualité de l'eau.",
    },
    "top.heading": {"en": "Highest discharge — top {n}", "fr": "Débits les plus élevés — top {n}"},
    "top.none": {"en": "No live readings available to rank.", "fr": "Aucune mesure à classer."},

    # -- messages ------------------------------------------------------
    "msg.api_down": {
        "en": "Hub'Eau is not responding right now, so no gauging stations could be "
              "loaded. The river network is still shown below. Use **Refresh live data** "
              "in the sidebar to try again in a few minutes.",
        "fr": "Hub'Eau ne répond pas actuellement : aucune station n'a pu être chargée. "
              "Le réseau hydrographique reste affiché ci-dessous. Utilisez **Actualiser "
              "les données** dans la barre latérale pour réessayer dans quelques minutes.",
    },
    "msg.cached": {
        "en": "Hub'Eau is unreachable, so these are the **last readings retrieved, "
              "taken {age}** ({stamp}). Nothing here is estimated — each value keeps its "
              "own measurement time and freshness label.",
        "fr": "Hub'Eau est injoignable : voici les **dernières mesures récupérées, "
              "datées de {age}** ({stamp}). Aucune valeur n'est estimée — chacune conserve "
              "son horodatage et son indicateur de fraîcheur.",
    },
    "msg.no_match": {
        "en": "No stations match the current filters. Widen the search or the discharge range.",
        "fr": "Aucune station ne correspond aux filtres. Élargissez la recherche ou la plage de débit.",
    },
    "msg.rivers_missing": {
        "en": "River layer missing for {label}. Build it with "
              "`python scripts/prepare_rivers.py --department {code}`. Stations are still displayed.",
        "fr": "Couche hydrographique absente pour {label}. Générez-la avec "
              "`python scripts/prepare_rivers.py --department {code}`. Les stations restent affichées.",
    },
    "msg.dams_missing": {
        "en": "No dam or reservoir layer for {label}. Build it with "
              "`python scripts/prepare_dams.py --department {code}`.",
        "fr": "Aucune couche de barrages pour {label}. Générez-la avec "
              "`python scripts/prepare_dams.py --department {code}`.",
    },
    "msg.detail_fallback": {
        "en": "No detail layer built for {name} yet — showing the overview network. "
              "Build it with `python scripts/prepare_rivers.py --department {code} --level detail`.",
        "fr": "Aucune couche détaillée pour {name} — la vue d'ensemble est affichée. "
              "Générez-la avec `python scripts/prepare_rivers.py --department {code} --level detail`.",
    },
    "msg.no_normals": {
        "en": "No multi-year reference could be built for these stations, so "
              "flow-vs-normal colouring has nothing to show.",
        "fr": "Aucune référence pluriannuelle n'a pu être construite pour ces stations : "
              "la coloration débit vs normale n'a rien à afficher.",
    },
    "msg.loading": {
        "en": "Loading gauging stations and latest discharge",
        "fr": "Chargement des stations et des derniers débits",
    },
    "msg.loading_normals": {
        "en": "Building seasonal reference from multi-year records",
        "fr": "Construction de la référence saisonnière pluriannuelle",
    },
    "msg.loading_history": {"en": "Loading discharge history", "fr": "Chargement de l'historique"},

    # -- footer --------------------------------------------------------
    "foot.disclaimer": {
        "en": "Provisional real-time observations from Hub'Eau — not validated "
              "hydrological records and not a flood-warning system. River lines and "
              "reservoirs are illustrative context; the great majority are ungauged.",
        "fr": "Observations temps réel provisoires de Hub'Eau — ni données validées, "
              "ni système d'alerte de crue. Les cours d'eau et retenues sont fournis à "
              "titre indicatif ; la grande majorité n'est pas jaugée.",
    },
    "foot.credit": {
        "en": "Created by <strong>Deepak Prajapati</strong> · © {year}. All rights reserved.",
        "fr": "Réalisé par <strong>Deepak Prajapati</strong> · © {year}. Tous droits réservés.",
    },
}


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """Translate ``key`` into ``lang``, formatting any placeholders."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
