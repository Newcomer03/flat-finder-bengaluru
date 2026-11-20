import json

import mb_crawl


def test_fetch_never_caches_a_page_without_data(tmp_path, monkeypatch):
    """A block or error page must not be stored as if it were a project page, or a rerun would never refetch it."""
    class Reply:
        def read(self):
            return b"<html>Access denied" + b"x" * 5000 + b"</html>"

    monkeypatch.setattr(mb_crawl, "CACHE", tmp_path)
    monkeypatch.setattr(mb_crawl, "_fails", 0)
    monkeypatch.setattr(mb_crawl.time, "sleep", lambda s: None)
    monkeypatch.setattr(mb_crawl.urllib.request, "urlopen", lambda req, timeout=0: Reply())
    assert mb_crawl.fetch("https://example.com/blocked") is None
    assert list(tmp_path.iterdir()) == []


def test_projects_limit_takes_cards_with_facts_first(tmp_path, monkeypatch):
    monkeypatch.setattr(mb_crawl, "OUT", tmp_path)
    monkeypatch.setattr(mb_crawl, "fetch", lambda url: None)
    index = [{"name": "stub", "url": "u1"}, {"name": "has units", "url": "u2", "units": 10}, {"name": "has price", "url": "u3", "price_min": 5}]
    (tmp_path / "mb_index.json").write_text(json.dumps(index))
    mb_crawl.crawl_projects(2)
    out = json.loads((tmp_path / "mb_projects.json").read_text())
    assert [p["name"] for p in out] == ["has units", "has price"]
