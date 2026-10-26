"""Dynamic pages of the sandbox (site search, web-archive listings, API search and lookup) as pure functions of
an episode, so that the gym server and the static quality gates compute exactly the same results."""
from __future__ import annotations

import re
import urllib.parse

from ..config import ARCHIVE_HOST, SEARCH_HOST
from .search import BM25

ARCHIVE_LIST = re.compile(r"^/(?:web/(\d{8}|\d{4})?\*|timemap|lookup)/?(.*)$")


def site_docs(ep: dict, host: str) -> list[dict]:
    return [x for x in ep["resources"] if x["host"] == host and x["role"] != "honeypot" and x.get("site_search", True)]


def site_search(ep: dict, host: str, q: str, n: int = 10) -> list[dict]:
    docs = site_docs(ep, host)
    return BM25(docs).search(q, n) if docs and q else []


def archive_captures(ep: dict, original: str) -> list[dict]:
    caps = [r for r in ep["resources"] if r["host"] == ARCHIVE_HOST and r.get("original") == original]
    return sorted(caps, key=lambda r: r["memento_datetime"])


def parse_archive_listing(path: str, query: str) -> tuple[str | None, str] | None:
    """('2024' | None, original URL) for /web/*/<url>, /web/2024*/<url>, /timemap/<url>, /lookup?url=<url>."""
    if path.startswith("/lookup"):
        return None, (urllib.parse.parse_qs(query).get("url") or [""])[0]
    m = ARCHIVE_LIST.match(path)
    if not m:
        return None
    orig = m.group(2) + (f"?{query}" if query else "")
    return m.group(1), orig


def api_search(ep: dict, host: str, q: str) -> list[dict]:
    docs = [x for x in ep["resources"] if x["host"] == host and x.get("route") == "official_api"]
    hits = BM25(docs).search(q, 10) if docs and q else []
    by_url = {d["url"]: d for d in docs}
    out = []
    for h in hits:
        rid = by_url[h["url"]]["path"].split("/")[3]
        out.append({"id": rid, "title": h["title"], "url": f"http://{host}/v1/records/{rid}"})
    return out


def v2_lookup(ep: dict, host: str, legacy_id: str) -> dict | None:
    canon = next(r for r in ep["resources"] if r["role"] == "canonical")
    v2 = next((x for x in ep["resources"] if x["host"] == host and x.get("route") == "api_v2"), None)
    if v2 is None or legacy_id != canon["path"].rsplit("/", 1)[-1]:
        return None
    return {"legacy_id": legacy_id, "id": v2["path"].rsplit("/", 1)[-1], "url": v2["url"]}


def links_of(ep: dict, url: str, corpus_index: BM25 | None = None) -> list[str]:
    """URLs a page links to, for static hub pages and for dynamic pages. Used by the quality gates."""
    u = urllib.parse.urlsplit(url)
    host, path, query = u.hostname or "", u.path or "/", u.query
    qs = urllib.parse.parse_qs(query)
    r = next((x for x in ep["resources"] if x["url"] == url), None)
    if r is not None and r["role"] == "hub":
        return [h for h, _ in r.get("links", [])]
    if host == ARCHIVE_HOST:
        p = parse_archive_listing(path, query)
        if p:
            year, orig = p
            caps = archive_captures(ep, orig)
            if year is None:
                return [f"http://{ARCHIVE_HOST}/web/{y}*/{orig}" for y in sorted({c['memento_datetime'][:4] for c in caps})]
            if len(year) == 4:
                return [f"http://{ARCHIVE_HOST}/web/{d}*/{orig}"
                        for d in sorted({c['memento_datetime'][:8] for c in caps if c['memento_datetime'].startswith(year)})]
            return [c["url"] for c in caps if c["memento_datetime"].startswith(year)]
    if path == "/search" and host != SEARCH_HOST:
        return [h["url"] for h in site_search(ep, host, (qs.get("q") or [""])[0])]
    if path == "/v1/search":
        return [h["url"] for h in api_search(ep, host, (qs.get("q") or [""])[0])]
    if path == "/v2/lookup":
        hit = v2_lookup(ep, host, (qs.get("legacy_id") or [""])[0])
        return [hit["url"]] if hit else []
    return []
