import osm_fetch


def g(*pts):
    return [{"lon": x, "lat": y} for x, y in pts]


def test_ring_from_relation_joins_reversed_segments():
    el = {"members": [
        {"role": "outer", "geometry": g((0, 0), (1, 0), (1, 1))},
        {"role": "outer", "geometry": g((0, 0), (0, 1), (1, 1))},  # reversed direction
        {"role": "inner", "geometry": g((0.2, 0.2), (0.3, 0.2))},
    ]}
    rings = osm_fetch.ring_from_relation(el)
    assert len(rings) == 1
    assert rings[0][0] == rings[0][-1] and len(rings[0]) == 5


def test_height_of():
    assert osm_fetch.height_of({"height": "60 m"}) == 60
    assert osm_fetch.height_of({"building:levels": "10"}) == 32
    assert osm_fetch.height_of({}) is None


# ---- Bengaluru: Namma Metro tagging, and buildings fetched per candidate area ----
import geo


def test_poi_kind_reads_metro_from_tags_not_from_any_name_with_metro_in_it():
    namma = {"railway": "station", "station": "subway", "subway": "yes", "network": "Namma Metro", "name": "Indiranagar"}
    assert osm_fetch.poi_kind(namma) == "metro"
    assert osm_fetch.poi_kind({"railway": "station", "name": "HUDA City Centre Metro Station"}) == "metro"
    assert osm_fetch.poi_kind({"railway": "station", "name": "Krishnarajapuram"}) == "rail"
    assert osm_fetch.poi_kind({"railway": "halt", "name": "Hebbal"}) == "rail"
    assert osm_fetch.poi_kind({"amenity": "hospital", "name": "Metro Hospital"}) == "hospital"
    assert osm_fetch.poi_kind({"shop": "supermarket", "name": "Metro Cash and Carry"}) == "shopping"
    assert osm_fetch.poi_kind({"shop": "mall", "name": "MGF Metropolitan"}) == "shopping"
    assert osm_fetch.poi_kind({"railway": "proposed", "station": "subway", "name": "Nagawara (Proposed)"}) is None
    assert osm_fetch.poi_kind({"railway": "stop", "subway": "yes", "name": "Majestic"}) is None


def _area(name, center, r):
    return {"properties": {"osm": "way/" + name, "name": name}, "geometry": {"type": "Polygon", "coordinates": [geo.circle(center, r)]}}


def test_candidate_boxes_are_the_areas_the_build_would_match():
    near, far, huge = _area("Lakeside", (77.64, 12.97), 150), _area("Hilltop", (77.70, 13.05), 150), _area("Big Layout", (77.64, 12.97), 700)
    boxes = osm_fetch.candidate_boxes([near, far, huge], [{"name": "Prestige Lakeside", "lng": 77.6405, "lat": 12.9702}])
    assert len(boxes) == 1
    s, w, n, e = boxes[0]
    assert s < 12.97 < n and w < 77.64 < e  # south, west, north, east: the order Overpass wants
    assert osm_fetch.candidate_boxes([near, far, huge], []) == []   # crawled, nothing located: fetch nothing
    assert len(osm_fetch.candidate_boxes([near, far, huge])) == 2   # no crawl yet: every area small enough to be a site
    stranger = {"name": "Green Nest", "lng": 77.6405, "lat": 12.9702}  # inside Lakeside (~70,000 m2) but shares no name
    assert len(osm_fetch.candidate_boxes([near], [stranger])) == 1                      # the default cap allows it
    assert osm_fetch.candidate_boxes([near], [stranger], inside_only_max=60_000) == []  # Bengaluru's cap does not
