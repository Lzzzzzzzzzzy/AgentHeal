"""A small BM25 search engine over the corpus and the current episode's indexed resources."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOK = re.compile(r"[a-z0-9]+")
STOP = set("the a an of in on for to and or with by from is are was were at as its it this that be".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOK.findall((text or "").lower()) if t not in STOP]


def doc_text(d: dict) -> str:
    parts = [d.get("title", ""), d.get("title", ""), d.get("publisher", ""), d.get("version_label", ""),
             d.get("keywords", ""), " ".join(d.get("body", {}).get("paragraphs", [])),
             str(d.get("entity", "")), str(d.get("field_label", "")), d.get("gtin", "") or "",
             d.get("host", ""), d.get("cue") or ""]
    return " ".join(parts)


class BM25:
    def __init__(self, docs: list[dict], k1: float = 1.4, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(doc_text(d))) for d in docs]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = sum(self.len) / max(1, len(self.len))
        df = Counter()
        for t in self.tf:
            df.update(t.keys())
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def search(self, query: str, n: int = 10) -> list[dict]:
        q = tokenize(query)
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                if w in tf:
                    f = tf[w]
                    s += self.idf.get(w, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                s *= 1 + 0.25 * float(self.docs[i].get("rank_boost", 0) or 0)
                scores.append((s, i))
        scores.sort(reverse=True)
        out = []
        for s, i in scores[:n]:
            d = self.docs[i]
            paras = d.get("body", {}).get("paragraphs", [])
            snippet = " ".join(x for x in [d.get("publisher", ""), d.get("version_label", ""),
                                           (paras[0] if paras else "")] if x)[:220]
            out.append({"title": d.get("title", ""), "url": d["url"], "snippet": snippet, "score": round(s, 3)})
        return out
