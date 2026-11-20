import math

import build_city
import geo


def area(name, center, r=150):
    return {"type": "Feature", "properties": {"osm": "way/" + name, "name": name},
            "geometry": {"type": "Polygon", "coordinates": [geo.circle(center, r)]}}


def test_match_area_inside_and_by_name():
    areas = [area("Heritage One", (77.0891, 28.4027)), area("Skyon", (77.0966, 28.3995))]
    g = build_city.Grid(areas, lambda a: geo.centroid(a["geometry"]["coordinates"][0]))
    p = {"name": "Conscient Heritage One", "lng": 77.0893, "lat": 28.4030}
    assert build_city.match_area(p, g)["properties"]["name"] == "Heritage One"
    near = {"name": "Ireo Skyon", "lng": 77.0966 + 0.0025, "lat": 28.3995}  # ~245 m east, outside
    assert build_city.match_area(near, g)["properties"]["name"] == "Skyon"
    far = {"name": "Random Homes", "lng": 77.2, "lat": 28.5}
    assert build_city.match_area(far, g) is None


def test_dedupe_merges_phases_close_by():
    a = {"name": "Heritage One", "lng": 77.0890, "lat": 28.4034, "url": "a"}
    b = {"name": "Heritage One", "lng": 77.0891, "lat": 28.4021, "url": "b"}
    c = {"name": "Heritage One", "lng": 77.2, "lat": 28.5, "url": "c"}
    out = build_city.dedupe([a, b, c])
    assert len(out) == 2 and out[0]["merged"] == ["b"]


def test_kind_of():
    assert build_city.kind_of({"config_text": "2, 3, 4 BHK Multistorey Apartments"}) == "apartment"
    assert build_city.kind_of({"config_text": "Residential Plot"}) == "plot"
    assert build_city.kind_of({"config_text": "4 BHK Villa"}) == "villa"


def test_neighbourhood_sized_area_is_not_a_society_site():
    big = area("DLF Phase 4", (77.08, 28.46), r=700)  # ~1.5 km2
    g = build_city.Grid([big], lambda a: geo.centroid(a["geometry"]["coordinates"][0]))
    p = {"name": "Some Apartments", "lng": 77.08, "lat": 28.46, "acres": 5}
    assert build_city.match_area(p, g) is None


def test_kind_from_unit_codes_when_text_missing():
    assert build_city.kind_of({"configs": {"units": [{"kind": "10000"}]}}) == "plot"
    assert build_city.kind_of({"configs": {"units": [{"kind": "10008"}, {"kind": "10002"}]}}) == "apartment"
    assert build_city.kind_of({}) == "apartment~"


def test_kind_from_card_type_codes():
    assert build_city.kind_of({"type_codes": ["10000"]}) == "plot"
    assert build_city.kind_of({"card_units": [{"kind": "10003", "bhk": 3, "sqft": 1900.0}]}) == "builder floor"


def test_infer_kind_from_name():
    assert build_city.kind_of({"name": "Sai Ram Apartment"}) == "apartment~"
    assert build_city.kind_of({"name": "Rzone Land Plot"}) == "plot~"
    assert build_city.kind_of({"name": "Emaar Business District 114"}) == "commercial~"
    assert build_city.kind_of({"name": "Ashiana Villas"}) == "villa~"


def test_match_verified_needs_whole_name_and_sector():
    ps = [{"mb_id": 1, "name": "M3M", "locality": "Sector 65"},
          {"mb_id": 2, "name": "M3M Heights", "locality": "Sector 65"},
          {"mb_id": 3, "name": "M3M St Andrews at SCDA", "locality": "Sector 113"},
          {"mb_id": 4, "name": "M3M St. Andrews", "locality": "Sector 65"}]
    assert build_city.match_verified({"match": ["M3M Heights"], "sector": "65"}, ps)["mb_id"] == 2
    assert build_city.match_verified({"match": ["M3M St Andrews"], "sector": "65"}, ps)["mb_id"] == 4
    assert build_city.match_verified({"match": ["M3M Heights"], "sector": "65"}, ps, taken={2}) is None


# ---- Bengaluru: named layouts, portal typos, stubs, and a build with nothing but the crawl ----
import json

import verified


def test_absurd_acres_do_not_unlock_a_neighbourhood_sized_area():
    big = area("Sai Layout", (77.60, 12.97), r=700)  # ~1.5 km2
    g = build_city.Grid([big], lambda a: geo.centroid(a["geometry"]["coordinates"][0]))
    typo = {"name": "Sai Deepam", "lng": 77.60, "lat": 12.97, "acres": 3000}  # a real card: "15 units, 3000 Acre"
    assert build_city.match_area(typo, g) is None
    township = {"name": "Sai Deepam", "lng": 77.60, "lat": 12.97, "acres": 150}  # plausible: 3 x 150 acres covers it
    assert build_city.match_area(township, g) is not None


def test_inside_only_match_is_capped():
    layout = area("HSR Layout Sector 2", (77.64, 12.91), r=200)  # ~125,000 m2 of individual houses
    g = build_city.Grid([layout], lambda a: geo.centroid(a["geometry"]["coordinates"][0]))
    inside = {"name": "Green Nest", "lng": 77.64, "lat": 12.91}
    assert build_city.match_area(inside, g, inside_only_max=60_000) is None  # no shared name: too big to claim
    assert build_city.match_area(inside, g) is not None                      # default cap: as before
    named = {"name": "HSR Residency", "lng": 77.64, "lat": 12.91}
    assert build_city.match_area(named, g, inside_only_max=60_000) is not None  # shares its name: allowed


def test_match_verified_by_locality():
    ps = [{"mb_id": 1, "name": "Prestige Lakeside Habitat", "locality": "Varthur"},
          {"mb_id": 2, "name": "Prestige Lakeside Habitat", "locality": "Whitefield"}]
    assert build_city.match_verified({"match": ["Prestige Lakeside Habitat"], "locality": "whitefield"}, ps)["mb_id"] == 2


def test_has_facts():
    assert not build_city.has_facts({"name": "Sai Nilayam", "lat": 12.9, "lng": 77.6})
    assert build_city.has_facts({"units": 120})
    assert build_city.has_facts({"configs": {"units": [{"bhk": 2}]}})


def test_flag_shared_points():
    """Five societies on one exact pin is the portal's locality centre; two can be phases of one project."""
    centre = [{"name": f"Layout {i}", "lat": 12.968048, "lng": 77.739097} for i in range(5)]
    phases = [{"name": f"Towers Phase {i}", "lat": 12.91, "lng": 77.65} for i in range(2)]
    alone = {"name": "Own Pin", "lat": 12.95, "lng": 77.7}
    assert build_city.flag_shared_points(centre + phases + [alone]) == 5
    assert all(s["loc_shared"] == 5 for s in centre)
    assert not any("loc_shared" in s for s in phases + [alone])


def test_hex_spiral_cells_are_distinct_and_one_apart():
    cells = build_city.hex_spiral(40)
    assert cells[0] == (0.0, 0.0) and len(cells) == 40
    gaps = [math.dist(a, b) for i, a in enumerate(cells) for b in cells[i + 1:]]
    assert min(gaps) > 0.999  # no two cells closer than one spacing
    assert all(0.999 < math.dist(cells[0], c) < 1.001 for c in cells[1:7])  # the first ring hugs the centre


def test_spread_shared_points_keeps_the_pin_and_separates_the_spots():
    stack = [{"id": f"s{i}", "name": f"Layout {i}", "lat": 12.968048, "lng": 77.739097, "units": 10 * i} for i in range(7)]
    assert build_city.spread_shared_points(stack, spacing_m=80) == 7
    assert all((s["lat"], s["lng"]) == (12.968048, 77.739097) for s in stack)  # the portal's pin is data: untouched
    biggest = max(stack, key=lambda s: s["units"])
    assert biggest["at"] == [77.739097, 12.968048]  # most units sits on the pin itself
    spots = [tuple(s["at"]) for s in stack]
    gaps = [build_city.geo.dist_m(a, b) for i, a in enumerate(spots) for b in spots[i + 1:]]
    assert min(gaps) > 79 and max(gaps) < 161


def test_score_leaves_out_nearby_when_the_location_is_only_a_shared_pin():
    nearby = {"park": {"m": 100}, "metro": {"m": 900}, "school": {"m": 500}, "hospital": {"m": 1500}, "shopping": {"m": 1000}}
    own = {"rating": 4.0, "amenities": ["a"] * 15, "nearby": nearby}
    assert build_city.score(own) == (8.0, {"residents": 8.0, "nearby": 10.0, "amenities": 5.0})  # 8*.5 + 10*.3 + 5*.2
    pinned = {**own, "loc_shared": 246}
    assert build_city.score(pinned) == (7.1, {"residents": 8.0, "amenities": 5.0})  # (8*.5 + 5*.2) / .7: the pin's parks are not its parks
    found = {**pinned, "osm_area": "way/1"}  # found by name in OpenStreetMap: measured from its own outline, so scored in full
    assert build_city.score(found) == build_city.score(own)
    assert build_city.score({"amenities": [], "nearby": {}, "loc_shared": 9}) == (None, {})  # nothing known: no score, not a zero
    assert build_city.score({"amenities": [], "nearby": {}}) == (0.0, {"nearby": 0.0, "amenities": 0.0})  # located, and nothing is near it


def test_builds_a_city_from_the_crawl_alone(tmp_path, monkeypatch):
    """No OSM files, no verified research, no OCR output: the first Bengaluru build must still work."""
    out, web = tmp_path / "out", tmp_path / "web"
    (out / "bangalore").mkdir(parents=True)
    projects = [
        {"mb_id": 1, "name": "Prestige Test Towers", "url": "https://example.com/1", "lat": 12.97, "lng": 77.64,
         "locality": "Indiranagar", "units": 200, "towers": 4, "amenities": ["Swimming Pool", "Gym"], "price_min": 12000000},
        {"mb_id": 2, "name": "Sobha Sample", "url": "https://example.com/2", "lat": 12.93, "lng": 77.68, "units": 90},
        {"mb_id": 3, "name": "Bare Stub", "url": "https://example.com/3", "lat": 12.95, "lng": 77.60},           # no facts: dropped
        {"mb_id": 4, "name": "Far Away Homes", "url": "https://example.com/4", "lat": 28.4, "lng": 77.0, "units": 50},  # not in the bbox
    ]
    (out / "bangalore" / "mb_projects.json").write_text(json.dumps(projects))
    monkeypatch.setattr(build_city, "OUT", out)
    monkeypatch.setattr(build_city, "WEB", web)
    monkeypatch.setattr(verified, "ROOT", tmp_path)
    build_city.main("bangalore")
    doc = json.loads((web / "bangalore.json").read_text())
    assert doc["city"]["name"] == "Bengaluru" and doc["room_model"] is None
    c = doc["counts"]
    assert (c["listed"], c["on_map"], c["not_located"], c["stubs_dropped"], c["verified"], c["ai_read"]) == (4, 2, 1, 1, 0, 0)
    assert doc["sources"] == ["Magicbricks project pages", "OpenStreetMap contributors"]
    assert {s["shape"] for s in doc["societies"]} == {"generated"}
    located = [e["finding"] for e in doc["events"] if e["step"] == "Located on map"]
    assert located[0].startswith("Indiranagar") and located[1].startswith("Bengaluru")  # no locality: the city's own name
    assert json.loads((web / "cities.json").read_text()) == {"bangalore": {"name": "Bengaluru", "default": True}}
    for name in ("bangalore-shapes.geojson", "bangalore-details.json", "bangalore-societies.csv", "bangalore-units.csv"):
        assert (web / name).exists()
