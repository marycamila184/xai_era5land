"""Municipal and state outlines from IBGE, for map context.

Fetched once from the IBGE mesh API and cached under data/boundaries/. Parsed
with json alone -- a boundary is just rings of lon/lat, and drawing them needs
no GIS stack. If the download fails the maps are drawn without them.
"""

import gzip
import json
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

CACHE = Path(__file__).resolve().parent / "data" / "boundaries"
API = "https://servicodados.ibge.gov.br/api/v3/malhas"

CURITIBA = "4106902"            # IBGE municipality code
STATES = ("41", "42", "35")     # Parana, Santa Catarina, Sao Paulo


def _fetch(kind, code, extra=""):
    """Return the GeoJSON for one boundary, from the cache or the API."""
    path = CACHE / f"{kind}_{code}.json"
    if path.exists():
        return json.loads(path.read_text())

    url = f"{API}/{kind}/{code}?formato=application/vnd.geo+json{extra}"
    with urllib.request.urlopen(url, timeout=60) as response:
        raw = response.read()
    # The API gzips whatever the request asks for, and urllib hands the bytes
    # over as they came.
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    payload = json.loads(raw)
    if "features" not in payload:
        raise ValueError(f"IBGE returned no features for {kind}/{code}: {payload}")

    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return payload


def _rings(geojson):
    """Every ring of every feature, as (n, 2) lon/lat arrays."""
    out = []
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        polygons = ([geometry["coordinates"]] if geometry["type"] == "Polygon"
                    else geometry["coordinates"])
        out.extend(np.asarray(ring) for polygon in polygons for ring in polygon)
    return out


def outlines():
    """(state rings, Curitiba rings). Either list is empty if unavailable."""
    try:
        states = [ring for uf in STATES for ring in _rings(_fetch("estados", uf))]
        city = _rings(_fetch("municipios", CURITIBA, "&qualidade=maxima"))
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        print(f"  boundaries unavailable, drawing without them: {exc}")
        return [], []
    return states, city


def draw(ax, states, city, city_color="#0b0b0b"):
    """Draw the outlines on a lon/lat axis."""
    for ring in states:
        ax.plot(ring[:, 0], ring[:, 1], color="#8a8984", linewidth=0.7,
                zorder=6, solid_joinstyle="round")
    for ring in city:
        ax.plot(ring[:, 0], ring[:, 1], color=city_color, linewidth=1.6,
                zorder=7, solid_joinstyle="round")
