"""Polite, cached, resumable Magicbricks crawler.

usage: python mb_crawl.py list <city> [pages]      # list pages -> out/<city>/mb_index.json
       python mb_crawl.py projects <city> [count]  # project pages -> out/<city>/mb_projects.json
<city> is a key in data/cities.json (required). The optional number limits the run, for a pilot:
the first [pages] list pages, or the first [count] projects (those with facts on their card first).
Rerun to resume: every page fetched is cached.
"""
import gzip
import hashlib
import json
import pathlib
import sys
import threading
import time
import urllib.parse
import urllib.request

import mb_parse

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "mb"
OUT = ROOT / "out"
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text())
CITY = next((a for a in sys.argv[1:] if a in CITIES), "gurgaon")  # import-time fallback only: the command line must name a city
CFG = CITIES[CITY]
LIST_URL = "https://www.magicbricks.com/residential-projects-in-" + CFG["magicbricks"] + "-nprid/page-{}"
OUT = OUT / CITY
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
DELAY = 1.0
MARKER = "SERVER_PRELOADED_STATE_"  # every real list or project page embeds its data under this name
MAX_FAILS = 25  # this many pages in a row without data means we are being refused: stop, do not hammer
BLOCKED = threading.Event()
_lock = threading.Lock()
_fails = 0


def _note(ok):
    global _fails
    with _lock:
        _fails = 0 if ok else _fails + 1
        if _fails >= MAX_FAILS:
            BLOCKED.set()


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")
    if f.exists() and f.stat().st_size > 2000:
        return gzip.decompress(f.read_bytes()).decode("utf-8", "ignore")
    for attempt in range(3):
        if BLOCKED.is_set():
            return None
        try:
            # a project slug can hold a curly apostrophe; the cache key above stays the plain url
            req = urllib.request.Request(urllib.parse.quote(url, safe=":/?&=%"), headers={"User-Agent": UA})
            html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
            if MARKER not in html:  # a block or error page: never cache it as if it were data
                raise ValueError("page has no data in it")
            f.write_bytes(gzip.compress(html.encode("utf-8"), 9))
            _note(True)
            time.sleep(DELAY)
            return html
        except Exception as e:  # network hiccup: back off and retry
            print("  retry", attempt + 1, url, e, flush=True)
            time.sleep(5 * (attempt + 1))
    _note(False)
    return None


def crawl_list(limit=None):
    first = fetch(LIST_URL.format(1))
    total = mb_parse.parse_total(first) if first else None
    if not total:
        sys.exit("list page 1 did not load or has no totalCount: nothing crawled")
    pages = -(-total // 20)
    if limit:
        pages = min(pages, limit)
    projects, missed = {}, []
    for n in range(1, pages + 1):
        if BLOCKED.is_set():
            missed.extend(range(n, pages + 1))
            break
        html = fetch(LIST_URL.format(n))
        cards = mb_parse.parse_list_page(html) if html else []
        if not cards:
            missed.append(n)
            continue
        for c in cards:
            projects[c["psmid"]] = mb_parse.card_to_project(c)
        print(f"list {n}/{pages}: {len(projects)} projects", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mb_index.json").write_text(json.dumps(list(projects.values()), indent=0))
    print("total reported", total, "collected", len(projects))
    if missed:
        print(f"{len(missed)} list pages gave no cards (rerun to retry): {missed[:30]}{' ...' if len(missed) > 30 else ''}")
    if BLOCKED.is_set():
        print(f"stopped early: {MAX_FAILS} pages in a row came back without data. Wait a while, then rerun to resume.")


def crawl_projects(limit=None):
    index = json.loads((OUT / "mb_index.json").read_text())
    # cards that already carry facts go first, so a run that is cut short still gives a useful build
    index.sort(key=lambda p: not (p.get("units") or p.get("towers") or p.get("price_min") or p.get("card_units")))
    index = index[:limit]
    from concurrent.futures import ThreadPoolExecutor

    def one(p):
        html = fetch(p["url"])
        try:
            detail = mb_parse.parse_project_page(html) if html else {}
        except Exception as e:
            print("  parse failed", p["url"], e, flush=True)
            detail = {}
        return {**p, **{k: v for k, v in detail.items() if v not in (None, [], "")}}

    out = []
    every = 1000 if len(index) > 5000 else 100  # the file gets big: rewrite it less often on a full-city run
    with ThreadPoolExecutor(max_workers=3) as ex:
        for i, merged in enumerate(ex.map(one, index), 1):
            out.append(merged)
            if i % 100 == 0 or i == len(index):
                print(f"project {i}/{len(index)}", flush=True)
            if i % every == 0 or i == len(index):
                (OUT / "mb_projects.json").write_text(json.dumps(out, indent=0))
    located = sum(1 for p in out if p.get("lat") and p.get("lng"))
    print(f"{located}/{len(out)} projects have coordinates")
    if BLOCKED.is_set():
        print(f"stopped early: {MAX_FAILS} pages in a row came back without data. Wait a while, then rerun to resume.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("list", "projects") or not any(a in CITIES for a in args[1:]):
        sys.exit("usage: python mb_crawl.py list|projects <city> [limit]    cities: " + ", ".join(CITIES))
    limit = next((int(a) for a in args[1:] if a.isdigit()), None)
    {"list": crawl_list, "projects": crawl_projects}[args[0]](limit)
