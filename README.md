# Flat Finder

Every housing society in a city on one night map. Set the smallest bedroom you can live with, size, BHK, amenities and budget, and watch the societies that fit light up. Every number links to where it came from.

Gurugram is first: about 2,700 projects from Magicbricks, building outlines from OpenStreetMap, and a set of societies verified by reading builder brochures and HRERA plans.

## Bengaluru edition

This copy is adapted from [kairothq/flat-finder](https://github.com/kairothq/flat-finder) to build and open Bengaluru by default. Gurugram's built data is kept as a second city (`?city=gurgaon`).

It is published with GitHub Pages at https://newcomer03.github.io/flat-finder-bengaluru/. Every push to the `bengaluru` branch rebuilds `web/` and publishes it (`.github/workflows/pages.yml`); the built data in `web/public/data` is committed, so nothing is crawled there. The page asks search engines not to index it. Pages serves static files only, so the `/mcp` connector described below is not available on this copy; the map, filters, cards and CSV downloads are.

What is different from the original:

- **Bengaluru is about ten times bigger.** Magicbricks lists roughly 29,000 projects there, so the crawl takes hours, takes an optional limit for a pilot run, stops by itself if it starts being refused, and never caches a page that has no data in it.
- **Buildings are fetched per society, not per city.** OpenStreetMap has over 800,000 buildings in the area; only those inside named areas near a crawled project are downloaded.
- **Portal stubs are dropped.** Listings with no units, towers, price, rating or live listings are left out and counted (`stubs_dropped`). Set `"drop_stubs": false` in `data/cities.json` to keep them.
- **Locality-level pins are labelled.** Magicbricks pins about a quarter of Bengaluru projects at the centre of their locality rather than at the site. When five or more projects share one exact pin, the card says "Approximate location" above the nearby distances, and Directions searches by name instead of using the pin (`approx_location` in the build counts). So each can still be clicked, the build draws them as small stand-in sites in a honeycomb around the pin (`at` in the data). That spot is a drawing aid only: `lat`, `lng`, the CSV and the nearby distances stay the portal's. Because those distances are the pin's, a nearby filter leaves these societies "not checked" (faint) instead of matching or failing them, on the site and in the MCP server. For the same reason their Flat Finder score leaves out the nearby part and is rescaled from the resident rating and amenities; with no ratings and no amenities listed there is no score at all. The few found by name in OpenStreetMap are drawn at their outline, measured from it, and filtered and scored as usual.
- **Namma Metro is read from station tags**, not from "metro" appearing in a name.
- **Bedroom sizes are not read yet** for Bengaluru, so the smallest-bedroom filter is hidden there. Prices, rents, amenities, nearby places, scores and ratings all work.

```bash
# data: the two crawl commands run for a long time, so start them yourself
cd pipeline
caffeinate -i python3 mb_crawl.py list bangalore 100        # pilot: first 100 list pages. Drop the number for the full city.
caffeinate -i python3 mb_crawl.py projects bangalore 2000   # pilot: 2,000 projects. Drop the number for the full city.
python3 osm_fetch.py bangalore
python3 build_city.py bangalore                             # -> web/public/data/

# site
cd ../web && npm install && npm run dev

# terminal search against the local build
node ../cli/flatfinder.mjs --bhk 2,3 --max-rent 60k --amenity pool
```

Every script now needs the city named: a bare `python3 build_city.py` exits instead of rebuilding Gurugram.

## What the colours mean

- **Bright**: matches your search.
- **Amber**: likely. The rooms we have read pass, but not every bedroom has been read yet.
- **Faint outline**: not checked yet. We have no room sizes for it, so it is neither a pass nor a fail.
- **Dark**: does not match.

Building shapes come from OpenStreetMap where they are mapped. Where they are not, towers are drawn from the listed tower count and say "approximate shape" on the card. Shapes are visual only; data numbers are never estimated.

## How bedroom sizes are read

Four sources, most trusted first. Each unit on a card says which one it came from.

1. **Checked by hand**: rooms read from builder brochures or HRERA plans by a person, page cited (`data/verified/<city>.json`).
2. **OCR of a floor plan image**: macOS's built-in text recognition reads every printed size on the plan; code pairs each size with its own room label and takes the smallest bedroom. Free and local (`pipeline/plan_ocr.py`). Where Jev also read the plan, the two must agree within 2 inches.
3. **OCR of brochures and HRERA filings**: the same reading on brochure pages and HRERA "approved building plans" (`pipeline/brochure_ocr.py`, `pipeline/hrera.py`). A page can hold two unit plans, so these are never "complete": a failing room still fails, passing rooms only make a society "likely".
4. **Jev (TypeSafe)**: a fast typed-decision model that answers multiple-choice and yes/no questions about the plan image (`pipeline/jev_reader.py`). Used as a cross-check and a fallback. In spot checks it overstated a room about 1 time in 10, so a Jev-only reading is never more than "likely".

Bedrooms under 8 ft wide are dropped as mis-pairings. Plans that are 3D renders without printed sizes are skipped.

## Buy or rent

Every society shows buy prices and monthly rents per BHK: medians, ranges and counts of live Magicbricks listings (22,018 homes for sale and 7,371 for rent in Gurugram). Where a society has no listings, the site shows **our estimate, marked "~"**, with the working shown:

- rent from price (or price from rent) using the rental yield measured on 960 society and BHK pairs that have both (about 2.5% of the price per year, correlation between log price and log rent 0.91), using the locality's own yield where it has at least 4 pairs;
- when there are no listings at all, unit size x the project's price per sq ft, then rent via yield.

Cards also show resident ratings by category, review snippets, the 5-year price per sq ft trend, and links to Google Maps (with Google reviews) and directions.

## Download the data

- `/data/gurgaon-societies.csv`: one row per society (location, type, listings, buy and rent medians and estimates per BHK, ratings, amenities, links).
- `/data/gurgaon-units.csv`: one row per unit type, with bedroom sizes and sources.
- "Export these results" on the site downloads whatever your filters currently match.

## Use it inside Claude (connector)

Flat Finder is an MCP server at `https://flat-finder.pages.dev/mcp`. In Claude, add a custom connector with that URL, then ask things like "3 BHK in Gurgaon under ₹80k rent, every bedroom at least 11 by 12, park within 500 m". Tools: `search_societies` (any sector, budget, size, amenity, distance; up to 200 results per call), `breakdown` (group by sector, BHK, amenity, metro distance or rent band), `list_localities`, `get_society` (with reviews and rating categories), `compare_societies`. Listing prices that look like typos are flagged with a reason and not used for filtering.

## Search from a terminal

```bash
npx github:kairothq/flat-finder --bhk 3,4 --min-bedroom "11'3x12'3" --min-sqft 1620 --amenity squash --likely
npx github:kairothq/flat-finder --bhk 3 --max-rent 80k --amenity pool
```

## Use it with Claude Code

`skills/flat-finder/SKILL.md` is a Claude Code skill. Copy it into `~/.claude/skills/flat-finder/` and ask Claude to "add Bangalore to flat finder", "verify Ireo Skyon", or "find me a 3 BHK with every bedroom at least 11 by 12 feet". It follows the same rules as this repo: primary sources first, never estimate, every number keeps its page.

## Run it

```bash
# data
cd pipeline
python3 mb_crawl.py list gurgaon && python3 mb_crawl.py projects gurgaon   # polite, cached, resumable
python3 osm_fetch.py gurgaon
python3 build_city.py gurgaon                                               # -> web/public/data/

# site
cd ../web && npm install && npm run dev
```

Tests: `cd pipeline && uv run --with pytest pytest` and `cd web && npx vitest run --root .. cli web/src`.

Cities live in `data/cities.json`. Gurugram is built; Bengaluru and Mumbai are configured and need the pipeline run (see the skill, Job 2).

Press `/` to search for a society. The Streets button switches to a street map with road and sector names.

Useful links: `?city=gurgaon`, `?map=streets` or `?map=light`, `?preset=divy` loads the example search, `?open=<society id>` opens one society, `?nointro` skips the globe fly-in.

## Add verified research

Verified rows live in `data/verified/<city>.json`. Each unit type lists its bedrooms exactly as printed (`12'10"x16'4"` or millimetres `3350x3750`) with the source URL and page. Open a pull request, or use "Research this society" on any card to request one.

## Sources

Magicbricks project pages (listing facts, live sale and rent listings, resident ratings and reviews), OpenStreetMap contributors (outlines, ODbL), Esri World Imagery (basemap), OpenFreeMap (roads and city buildings), HRERA Gurugram and builder brochures (verified rows).
