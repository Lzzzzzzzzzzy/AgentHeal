"""Background corpus of distractor documents served in every episode.

Distractors share vocabulary with the goals (topics, stations, agencies, libraries) so that search
is not trivial, but none of them carries a goal's entity together with its field, so they cannot
be mistaken for a substitute by an auditing agent.
"""
from __future__ import annotations

from ..util import rng_for
from . import names as N

HOSTS = ["fieldnotes.example", "techdigest.example", "opendata-watch.example", "campusnews.example",
         "devforum.example", "travelwiki.example", "scholar-blog.example", "shopreviews.example"]


def build_corpus(seed: int, n: int) -> list[dict]:
    docs = []
    for i in range(n):
        rng = rng_for(seed, "corpus", i)
        host = rng.choice(HOSTS)
        kind = rng.choice(["topic", "news", "product", "data", "lib", "wiki"])
        if kind == "topic":
            title = f"Notes on {rng.choice(N.TOPICS)} at {rng.choice(N.PLACES)}"
            body = [f"A field diary entry about {rng.choice(N.TOPICS)}.",
                    f"Mentions station {rng.choice(N.STATIONS)} in passing."]
        elif kind == "news":
            title = f"{rng.choice(N.NEWS_OUTLETS)} roundup: {rng.choice(N.NEWS_SUBJECTS)}"
            body = ["A weekly roundup of regional stories.", "No figures are reported here."]
        elif kind == "product":
            b = rng.choice(N.BRANDS)
            p = rng.choice(N.PRODUCTS)
            title = f"Review: {b} {p[0]} first impressions"
            body = [f"Hands-on with a {p[0]} from {b}.", "Specifications vary by retailer; check the listing."]
        elif kind == "data":
            title = f"How to use the {rng.choice(N.AGENCIES)} open-data portal"
            body = ["A tutorial on downloading public datasets.", "Releases are listed on each dataset page."]
        elif kind == "lib":
            lib = rng.choice(N.LIBRARIES)
            title = f"{lib}: migration guide and FAQ"
            body = [f"Community notes on upgrading {lib}.", "See the official documentation for defaults."]
        else:
            s = rng.choice(N.WIKI_SUBJECTS)
            title = f"Travel tips near {s[0]}"
            body = [f"Visiting {s[0]}: getting there and where to stay.", "Opening hours change seasonally."]
        path = f"/p/{i:05d}-{N.slug(title)}"
        docs.append({"id": f"corpus-{i:05d}", "host": host, "path": path, "url": f"http://{host}{path}",
                     "title": title, "body": {"paragraphs": body}, "kind": "page", "site_type": "blog",
                     "role": "context", "indexed": True, "rank_boost": 0.0})
    return docs
