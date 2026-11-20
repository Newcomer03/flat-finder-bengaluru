"""Fetch residential areas and building footprints for a city bbox from Overpass, once.

usage: python osm_fetch.py <city>  -> out/<city>/osm_areas.geojson, out/<city>/osm_buildings.geojson
<city> is a key in data/cities.json (required). Run mb_crawl.py first: buildings are fetched only
for the named areas that build_city would match to a crawled project.
"""
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

import geo

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "osm"
OUT = ROOT / "out"
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text())
CITY = next((a for a in sys.argv[1:] if a in CITIES), "gurgaon")  # import-time fallback only: the command line must name a city
BBOX = tuple(CITIES[CITY]["bbox"])  # south, west, north, east
BATCH = 40             # area boxes per Overpass query
SITE_MAX_M2 = 250_000  # build_city.match_area skips bigger areas unless the project itself is that big
OUT = OUT / CITY
CACHE = CACHE / CITY
MIRRORS = [  # tried in this order; overpass() moves a failing one to the back
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def overpass(query, name, timeout=300):
    """Run one Overpass query, cached. The cache file is named after the query text, so a changed bbox refetches."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{name}_{hashlib.sha1(query.encode()).hexdigest()[:12]}.json"
    if f.exists():
        return json.loads(f.read_text())
    body = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(len(MIRRORS) * 4):
        url = MIRRORS[0]  # the mirror that answered last stays first; one that fails goes to the back of the line
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "flat-finder/0.1"})
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            data = json.loads(raw)
            if data.get("remark"):  # a timeout or out-of-memory arrives as HTTP 200 with a remark: not a result
                raise RuntimeError(data["remark"][:160])
            f.write_bytes(raw)
            time.sleep(2)
            return data
        except Exception as e:
            print("mirror failed", url, e, flush=True)
            MIRRORS.append(MIRRORS.pop(0))
            time.sleep(5 * (attempt // len(MIRRORS) + 1))
    raise SystemExit("all Overpass mirrors failed (they are often busy: rerun later, finished queries are cached)")


def _pts(geom):
    return [(round(p["lon"], 6), round(p["lat"], 6)) for p in geom]


def ring_from_relation(el):
    """Join a multipolygon relation's outer member ways into closed rings."""
    segs = [_pts(m["geometry"]) for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
    rings = []
    while segs:
        ring = segs.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[::-1][1:]
                elif s[-1] == ring[0]:
                    ring = s[:-1] + ring
                elif s[0] == ring[0]:
                    ring = s[::-1][:-1] + ring
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def height_of(tags):
    try:
        if tags.get("height"):
            return float(str(tags["height"]).split()[0])
        if tags.get("building:levels"):
            return float(tags["building:levels"]) * 3.2
    except ValueError:
        pass
    return None


def candidate_boxes(feats, projects=None, inside_only_max=SITE_MAX_M2):
    """Bounding boxes (south, west, north, east) of the named areas whose buildings the build can use.

    A big city has close to a million buildings, and build_city only draws the ones inside the named
    area it matches to a society. So ask build_city which area each crawled project would get, and
    fetch buildings for those areas alone. Before any crawl, fall back to every area small enough to be a site.
    """
    if projects is None:
        picked = [f for f in feats if geo.area_m2(f["geometry"]["coordinates"][0]) <= SITE_MAX_M2]
    else:
        import build_city  # here, not at the top: only this path needs it
        grid = build_city.Grid(feats, lambda a: geo.centroid(a["geometry"]["coordinates"][0]))
        found = {}
        for p in projects:
            a = build_city.match_area(p, grid, inside_only_max)
            if a:
                found[id(a)] = a
        picked = list(found.values())
    boxes = []
    for f in picked:
        x0, y0, x1, y1 = geo.bbox(f["geometry"]["coordinates"][0])
        boxes.append((y0, x0, y1, x1))
    return boxes


def main():
    s, w, n, e = BBOX
    bb = f"({s},{w},{n},{e})"
    areas = overpass(f'[out:json][timeout:280];(way["landuse"="residential"]["name"]{bb};relation["landuse"="residential"]["name"]{bb};);out geom;', "areas")
    feats = []
    for el in areas["elements"]:
        rings = ring_from_relation(el) if el["type"] == "relation" else [_pts(el["geometry"])]
        for r in rings:
            feats.append({"type": "Feature", "properties": {"osm": f"{el['type']}/{el['id']}", "name": el["tags"]["name"]},
                          "geometry": {"type": "Polygon", "coordinates": [r]}})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "osm_areas.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print("areas", len(feats))

    pj = OUT / "mb_projects.json"
    projects = None
    if pj.exists():
        projects = [p for p in json.loads(pj.read_text()) if p.get("lat") and p.get("lng") and p.get("name")]
    else:
        print("no mb_projects.json yet: fetching buildings for every small named area (run mb_crawl.py first to narrow this)")
    boxes = candidate_boxes(feats, projects, CITIES[CITY].get("inside_only_max_m2", SITE_MAX_M2))
    print("areas matched to a crawled project", len(boxes))
    bf, seen = [], set()
    for i in range(0, len(boxes), BATCH):
        q = "[out:json][timeout:120];(" + "".join(
            f'way["building"]({a:.5f},{b:.5f},{c:.5f},{d:.5f});' for a, b, c, d in boxes[i:i + BATCH]) + ");out geom;"
        blds = overpass(q, "buildings", timeout=150)
        for el in blds["elements"]:
            if "geometry" not in el or el["id"] in seen:
                continue
            seen.add(el["id"])
            r = _pts(el["geometry"])
            if r[0] != r[-1]:
                r.append(r[0])
            bf.append({"type": "Feature", "properties": {"osm": el["id"], "h": height_of(el.get("tags", {}))},
                       "geometry": {"type": "Polygon", "coordinates": [r]}})
        print(f"buildings batch {i // BATCH + 1}/{-(-len(boxes) // BATCH)}: {len(bf)}", flush=True)
    (OUT / "osm_buildings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": bf}))
    print("buildings", len(bf))


POI_QUERY = """[out:json][timeout:280];(
  way["leisure"="park"]{bb};relation["leisure"="park"]{bb};node["leisure"="park"]{bb};
  node["railway"="station"]{bb};node["station"="subway"]{bb};node["railway"="halt"]{bb};
  node["amenity"="school"]{bb};way["amenity"="school"]{bb};
  node["amenity"="hospital"]{bb};way["amenity"="hospital"]{bb};
  node["shop"="mall"]{bb};way["shop"="mall"]{bb};way["shop"="supermarket"]{bb};node["shop"="supermarket"]{bb};
);out center tags;"""


def poi_kind(t):
    if t.get("leisure") == "park":
        return "park"
    if t.get("railway") in ("station", "halt"):
        # metro by its tags, its network, or "metro" as a whole word in the name ("Metropolitan" is a mall)
        name, net = (t.get("name") or "").lower(), (t.get("network") or "").lower()
        if t.get("station") in ("subway", "light_rail") or t.get("subway") == "yes" or "metro" in net or re.search(r"\bmetro\b", name):
            return "metro"
        return "rail"
    if t.get("amenity") in ("school", "hospital"):
        return t["amenity"]
    if t.get("shop") in ("mall", "supermarket"):
        return "shopping"
    return None


def fetch_pois():
    s, w, n, e = BBOX
    data = overpass(POI_QUERY.replace("{bb}", f"({s},{w},{n},{e})"), "pois")
    out = []
    for el in data["elements"]:
        c = el.get("center") or ({"lat": el["lat"], "lon": el["lon"]} if "lat" in el else None)
        k = poi_kind(el.get("tags", {}))
        if c and k:
            out.append({"k": k, "name": el.get("tags", {}).get("name"), "lng": round(c["lon"], 5), "lat": round(c["lat"], 5)})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "osm_pois.json").write_text(json.dumps(out))
    from collections import Counter
    print("pois", Counter(p["k"] for p in out))


if __name__ == "__main__":
    if not any(a in CITIES for a in sys.argv[1:]):
        sys.exit("usage: python osm_fetch.py <city> [pois]    cities: " + ", ".join(CITIES))
    if "pois" in sys.argv:
        fetch_pois()
    else:
        main()
        fetch_pois()
