"""robots.txt evaluation following RFC 9309 (longest match wins; on a tie, allow wins; '*' and '$' supported).

Used by the gym to decide whether a request in a real-split episode is disallowed for the declared agent.
"""
from __future__ import annotations

import re
from functools import lru_cache

AGENT_TOKEN = "agentheal-agent"


@lru_cache(maxsize=256)
def parse(text: str, agent: str = AGENT_TOKEN) -> tuple[tuple[str, str], ...]:
    groups, cur, in_rules = [], None, False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if cur is None or in_rules:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
                in_rules = False
            cur["agents"].append(v.lower())
        elif k in ("allow", "disallow") and cur is not None:
            in_rules = True
            if v:
                cur["rules"].append((k, v))
    mine = [r for g in groups if any(a != "*" and a in agent for a in g["agents"]) for r in g["rules"]]
    return tuple(mine or [r for g in groups if "*" in g["agents"] for r in g["rules"]])


def _rx(p: str) -> re.Pattern:
    pat = re.escape(p).replace(r"\*", ".*")
    if pat.endswith(r"\$"):
        pat = pat[:-2] + "$"
    return re.compile(pat)


def decide(text: str, path: str) -> tuple[bool, str | None]:
    best = None
    for kind, p in parse(text):
        if _rx(p).match(path):
            key = (len(p), kind == "allow")
            if best is None or key > best[0]:
                best = (key, kind, p)
    if best is None:
        return True, None
    return best[1] == "allow", f"{best[1].capitalize()}: {best[2]}"


def allowed(text: str, path: str) -> bool:
    return decide(text, path)[0]


# Documented, public programmatic interfaces. robots.txt addresses crawlers; these endpoints are governed by
# their own published terms (rate limits, user-agent etiquette), so requests to them are not robots violations.
OFFICIAL_API = {
    "en.wikipedia.org": (r"/w/api\.php", r"/api/rest_v1/"),
    "www.wikidata.org": (r"/w/api\.php", r"/wiki/Special:EntityData/"),
    "export.arxiv.org": (r"/api/",),
    "pypi.org": (r"/pypi/[^/]+(/[^/]+)?/json",),
    "registry.npmjs.org": (r"/",),
    "hn.algolia.com": (r"/api/",),
    "archive.org": (r"/wayback/available",),
    "web.archive.org": (r"/cdx/",),
    "openlibrary.org": (r"/api/", r"/isbn/[^/]+\.json", r"/search\.json"),
    "data.sec.gov": (r"/",),
    "eutils.ncbi.nlm.nih.gov": (r"/entrez/eutils/",),
    "www.ebi.ac.uk": (r"/europepmc/webservices/rest/",),
    "content.guardianapis.com": (r"/",),
    "www.googleapis.com": (r"/",),
    "ajax.googleapis.com": (r"/ajax/services/",),
    "huggingface.co": (r"/api/",),
    "zenodo.org": (r"/api/",),
    "github.com": (r"/api/v2/",),
    "nominatim.openstreetmap.org": (r"/search", r"/reverse", r"/lookup"),
    "clinicaltrials.gov": (r"/api/",),
    "musicbrainz.org": (r"/ws/",),
    "archive-api.open-meteo.com": (r"/",),
}


def official_api(host: str, path: str) -> bool:
    host = host.lower()
    if host.startswith("api.") or host.startswith("api-"):
        return True
    return any(re.match(p, path) for p in OFFICIAL_API.get(host, ()))
