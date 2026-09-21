"""Unit tests for the Hub'Eau client: conversion, status handling, shaping.

No network access -- the HTTP session is patched.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import requests

from src.services import hubeau
from src.services.hubeau import HubeauError, litres_per_second_to_m3s


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", url="https://example.test"):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})
        self.url = url

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


# --------------------------------------------------------------------------
# Unit conversion -- the API publishes litres per second
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("litres_per_second", "expected"),
    [(1670.0, 1.67), (1000, 1.0), (0, 0.0), (12_345_678, 12345.678), (0.5, 0.0005)],
)
def test_litres_per_second_to_m3s(litres_per_second, expected):
    assert litres_per_second_to_m3s(litres_per_second) == pytest.approx(expected)


def test_conversion_returns_none_for_missing_values():
    # None must stay None: an absent reading is not a measured zero.
    assert litres_per_second_to_m3s(None) is None
    assert litres_per_second_to_m3s("not-a-number") is None


# --------------------------------------------------------------------------
# HTTP status handling -- 206 is a success for this API
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status", [200, 206])
def test_success_statuses_are_accepted(status):
    with patch.object(hubeau._SESSION, "get", return_value=FakeResponse(status, {"data": [{"a": 1}]})):
        assert hubeau._get_json("https://example.test", {}) == {"data": [{"a": 1}]}


@pytest.mark.parametrize("status", [204, 400, 401, 404, 429, 500, 503])
def test_error_statuses_raise_hubeau_error(status):
    with patch.object(hubeau._SESSION, "get", return_value=FakeResponse(status, {"error": "x"})):
        with pytest.raises(HubeauError):
            hubeau._get_json("https://example.test", {})


def test_network_failure_raises_friendly_error():
    with patch.object(hubeau._SESSION, "get", side_effect=requests.ConnectionError("reset")):
        with pytest.raises(HubeauError) as excinfo:
            hubeau._get_json("https://example.test", {})
    # The message must be user-facing, never a raw response dump.
    assert "reset" not in str(excinfo.value)


def test_unparseable_body_raises_hubeau_error():
    with patch.object(hubeau._SESSION, "get", return_value=FakeResponse(200, None, text="<html>")):
        with pytest.raises(HubeauError):
            hubeau._get_json("https://example.test", {})


# --------------------------------------------------------------------------
# Stations
# --------------------------------------------------------------------------
STATION_ROWS = [
    {
        "code_station": "Y210001001", "libelle_station": "Hérault at Agde",
        "libelle_cours_eau": "l'Hérault", "latitude_station": 43.31,
        "longitude_station": 3.47, "libelle_departement": "Hérault", "en_service": True,
    },
    {  # duplicate -- must be collapsed
        "code_station": "Y210001001", "libelle_station": "Hérault at Agde",
        "libelle_cours_eau": "l'Hérault", "latitude_station": 43.31,
        "longitude_station": 3.47, "libelle_departement": "Hérault", "en_service": True,
    },
    {  # unusable coordinates -- must be dropped
        "code_station": "Y999999999", "libelle_station": "Broken",
        "libelle_cours_eau": None, "latitude_station": None,
        "longitude_station": None, "libelle_departement": "Hérault", "en_service": True,
    },
]


def test_get_active_stations_dedupes_and_drops_unusable_rows():
    with patch.object(hubeau, "_get_json", return_value={"data": STATION_ROWS, "next": None}):
        frame = hubeau.get_active_stations("34")
    assert list(frame["code_station"]) == ["Y210001001"]
    assert set(hubeau.STATION_COLUMNS).issubset(frame.columns)


def test_get_active_stations_returns_empty_frame_when_no_data():
    with patch.object(hubeau, "_get_json", return_value={"data": [], "next": None}):
        frame = hubeau.get_active_stations("34")
    assert frame.empty
    assert list(frame.columns) == hubeau.STATION_COLUMNS


# --------------------------------------------------------------------------
# Observations
# --------------------------------------------------------------------------
OBSERVATION_ROWS = [
    {"code_station": "A1", "date_obs": "2026-08-20T08:00:00Z", "resultat_obs": 1000.0},
    {"code_station": "A1", "date_obs": "2026-08-20T09:00:00Z", "resultat_obs": 2500.0},
    {"code_station": "B2", "date_obs": "2026-08-20T08:30:00Z", "resultat_obs": 400.0},
]


def test_latest_flow_per_station_uses_most_recent_observation():
    with patch.object(hubeau, "_get_json", return_value={"data": OBSERVATION_ROWS, "next": None}):
        result = hubeau.get_latest_flows_for_stations(["A1", "B2"])
    assert result.ok
    assert result.snapshots["A1"].flow_m3s == pytest.approx(2.5)   # 09:00, not 08:00
    assert result.snapshots["A1"].flow_lps == pytest.approx(2500.0)
    assert result.snapshots["B2"].flow_m3s == pytest.approx(0.4)


def test_station_without_reading_is_absent_not_zero():
    with patch.object(hubeau, "_get_json", return_value={"data": OBSERVATION_ROWS, "next": None}):
        result = hubeau.get_latest_flows_for_stations(["A1", "B2", "C3"])
    assert "C3" not in result.snapshots


def test_bulk_fetch_degrades_gracefully_on_api_failure():
    with patch.object(hubeau, "_get_json", side_effect=HubeauError("down")):
        result = hubeau.get_latest_flows_for_stations(["A1"])
    assert result.snapshots == {}
    assert result.ok is False
    assert result.message


def test_bulk_fetch_batches_long_code_lists():
    codes = [f"S{i:04d}" for i in range(hubeau.MAX_CODES_PER_REQUEST * 2 + 1)]
    calls = []

    def record(url, params, timeout=None):
        calls.append(params["code_entite"].split(","))
        return {"data": [], "next": None}

    with patch.object(hubeau, "_get_json", side_effect=record):
        hubeau.get_latest_flows_for_stations(codes)

    assert len(calls) == 3  # 50 + 50 + 1
    assert all(len(batch) <= hubeau.MAX_CODES_PER_REQUEST for batch in calls)


def test_observations_use_code_entite_parameter():
    captured = {}

    def capture(url, params, timeout=None):
        captured.update(params)
        return {"data": [], "next": None}

    with patch.object(hubeau, "_get_json", side_effect=capture):
        hubeau.get_latest_flows_for_stations(["A1"])

    # Regression guard: code_station does NOT filter this endpoint.
    assert captured["code_entite"] == "A1"
    assert "code_station" not in captured
    assert captured["grandeur_hydro"] == "Q"


def test_history_is_sorted_and_converted():
    rows = [
        {"code_station": "A1", "date_obs": "2026-08-20T09:00:00Z", "resultat_obs": 2000.0},
        {"code_station": "A1", "date_obs": "2026-08-20T08:00:00Z", "resultat_obs": 1000.0},
    ]
    with patch.object(hubeau, "_get_json", return_value={"data": rows, "next": None}):
        history = hubeau.get_station_flow_history("A1", hours=24)

    assert list(history["flow_m3s"]) == [1.0, 2.0]
    assert history["date_obs"].is_monotonic_increasing


def test_history_returns_empty_frame_when_nothing_published():
    with patch.object(hubeau, "_get_json", return_value={"data": [], "next": None}):
        assert hubeau.get_station_flow_history("A1").empty


def test_observation_rows_fall_back_to_requested_code():
    # Guards against the API dropping code_station from the payload.
    rows = [{"date_obs": "2026-08-20T09:00:00Z", "resultat_obs": 1500.0}]
    frame = hubeau._observations_frame(rows, fallback_codes=["A1"])
    assert list(frame["code_station"]) == ["A1"]
    assert frame["flow_m3s"].iloc[0] == pytest.approx(1.5)


def test_pagination_follows_next_links():
    pages = [
        {"data": [{"code_station": "A1", "date_obs": "2026-08-20T08:00:00Z", "resultat_obs": 1.0}],
         "next": "https://example.test/page2"},
        {"data": [{"code_station": "A1", "date_obs": "2026-08-20T09:00:00Z", "resultat_obs": 2.0}],
         "next": None},
    ]
    with patch.object(hubeau, "_get_json", side_effect=pages):
        rows = hubeau._paginate("https://example.test", {})
    assert len(rows) == 2


# --------------------------------------------------------------------------
# Whole-country station list -- the department list has a hard cap
# --------------------------------------------------------------------------
def _station_row(code, commune, department):
    return {
        "code_station": code, "libelle_station": f"Station {code}",
        "libelle_cours_eau": "Le Test", "latitude_station": 43.9,
        "longitude_station": 3.7, "libelle_commune": commune,
        "code_departement": department, "libelle_departement": "TEST",
        "en_service": 1,
    }


def test_national_station_list_is_chunked_under_the_department_cap():
    """Hub'Eau rejects more than 50 values in code_departement with a 400.

    That is a silent trap: one request for 96 departments looks reasonable and
    fails outright, so the request must be split before it is sent.
    """
    codes = [f"{n:02d}" for n in range(1, 96)]
    sent = []

    def fake_get(url, params=None, timeout=None):
        sent.append(params["code_departement"].split(","))
        return FakeResponse(200, {"data": [_station_row("A1", "AGDE", "34")]})

    with patch.object(hubeau._SESSION, "get", side_effect=fake_get):
        hubeau.get_active_stations_for_departments(codes)

    assert len(sent) > 1, "95 departments must not go out as a single request"
    assert all(len(batch) <= hubeau.MAX_DEPARTMENTS_PER_REQUEST for batch in sent)
    # Every department asked for is asked for exactly once.
    assert sorted(code for batch in sent for code in batch) == sorted(codes)


def test_national_station_list_rejects_a_bad_department_code():
    """Codes reach the URL, so they are validated before the request, not after."""
    with pytest.raises(ValueError):
        hubeau.get_active_stations_for_departments(["34", "../etc/passwd"])


def test_national_station_list_deduplicates_and_keeps_the_commune():
    rows = [_station_row("A1", "AGDE", "34"), _station_row("A1", "AGDE", "34")]
    with patch.object(hubeau._SESSION, "get", return_value=FakeResponse(200, {"data": rows})):
        frame = hubeau.get_active_stations_for_departments(["34"])
    assert len(frame) == 1
    assert frame.iloc[0]["libelle_commune"] == "AGDE"


def test_no_departments_means_no_request():
    with patch.object(hubeau._SESSION, "get", side_effect=AssertionError("must not call")):
        assert hubeau.get_active_stations_for_departments([]).empty
