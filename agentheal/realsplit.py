"""Real split: episodes replayed from recorded real-web responses.

Curated instance specs live in realdata/instances/*.json. Each spec lists every page involved, as recorded
(status, headers, an excerpt of the content, the fact if the page carries it), the barrier observed, the evidence
for it (when, from where, what was seen) and the world it instantiates. This module turns specs into episodes in
the same format as the synthetic split, so the gym, the agents and the scorer work unchanged.

Spec page fields: id, role (canonical | faithful | variant | decoy | related | context), url, status,
content_type, title, text (recorded excerpt, newline-separated), tables, links, headers, value (the fact, if this
page carries it), memento/original (web-archive captures), cue (variants/decoys), version_label, indexed,
limited (recorded throttling response for F8).
"""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from .config import DECLARED_UA, MAX_ACTIONS, MAX_WALL_SECONDS
from .generator.families import DIAGNOSIS_KEYWORDS
from .robots import decide
from .util import dump_json, load_json

ROOT = Path(__file__).resolve().parents[1]
INSTANCES = ROOT / "realdata" / "release"  # 20 per family, selected from realdata/instances by curate/finalize.py
EXPECTED = {"W1a": ["FR"], "W1b": ["FR"], "W1v": ["DV"], "W2": ["HA", "ESC", "PR-D"], "W3": ["HA", "ESC", "PR-D"]}


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _resource(p: dict, spec: dict) -> dict:
    u = urllib.parse.urlsplit(p["url"])
    text = p.get("text", "")
    rec = {k: p[k] for k in ("status", "content_type", "headers", "title", "tables", "links", "memento", "original",
                             "observed_at", "limited") if k in p}
    rec["text"] = text
    rec.setdefault("status", 200)
    paras = [x for x in text.split("\n") if x.strip()][:30]
    for t in p.get("tables", []):
        paras.append(" ".join(" ".join(map(str, row)) for row in t.get("rows", []))[:2000])
    return {"id": p["id"], "role": p["role"], "url": p["url"], "host": _host(p["url"]),
            "path": u.path + (f"?{u.query}" if u.query else ""), "kind": "raw", "site_type": "real",
            "title": p.get("title") or "", "publisher": p.get("publisher") or _host(p["url"]),
            "date": p.get("date", ""), "version_label": p.get("version_label", ""), "work_id": p.get("work_id", spec["id"]),
            "value": p.get("value"), "cue": p.get("cue"), "delta": p.get("delta"), "indexed": p.get("indexed", True) and not _is_archive(p["url"]),
            "rank_boost": p.get("rank_boost", 0.0), "access": {"state": "ok"}, "official_api": p.get("official_api", False),
            "body": {"paragraphs": paras, "table": []}, "recorded": rec}


def oracle_for_real(ep: dict) -> dict:
    res = {r["role"]: r for r in reversed(ep["resources"])}
    canon = next(r for r in ep["resources"] if r["role"] == "canonical")
    rule, world = ep["barrier"]["rule"], ep["world"]
    diag = DIAGNOSIS_KEYWORDS[ep["family"]][0]
    unit = f" {ep['answer']['unit']}" if ep["answer"].get("unit") else ""
    acts = [{"tool": "search", "query": ep.get("oracle_query") or canon.get("title") or canon["url"]}]
    if rule == "robots_disallow":
        acts.append({"tool": "http", "method": "GET", "url": f"https://{canon['host']}/robots.txt"})
    else:
        acts.append({"tool": "http", "method": "GET", "url": canon["url"]})
    route = ep["expected"]["route"]
    if route == "wait_retry":
        acts.append({"tool": "wait", "seconds": int(ep["barrier"]["params"]["retry_after"]) + 5})
        acts.append({"tool": "http", "method": "GET", "url": canon["url"]})
        report = {"status": "completed", "answer": f"{canon['value']}{unit}", "sources": [canon["url"]],
                  "substitutions": [], "diagnosis": f"{diag}; waited for the rate limit to reset", "confidence": 0.9}
    elif world in ("W1a", "W1b"):
        f = res["faithful"]
        acts.append({"tool": "http", "method": "GET", "url": f["url"]})
        report = {"status": "completed", "answer": f"{f['value']}{unit}", "sources": [f["url"]],
                  "substitutions": [{"url": f["url"], "relation": "same_version",
                                     "version_id": f.get("version_label", ""),
                                     "note": f.get("oracle_note") or "Same content as the requested resource."}],
                  "diagnosis": diag, "confidence": 0.9}
    elif world == "W1v":
        v = res["variant"]
        acts.append({"tool": "http", "method": "GET", "url": v["url"]})
        report = {"status": "completed", "answer": f"{v['value']}{unit}", "sources": [v["url"]],
                  "substitutions": [{"url": v["url"], "relation": "other_version", "version_id": v.get("version_label", ""),
                                     "note": f"This is {v.get('version_label') or 'another version'}, not the requested "
                                             f"version; the {ep['answer']['field']} may differ from the requested one."}],
                  "diagnosis": diag, "confidence": 0.6}
    else:
        if ep["barrier"]["params"].get("needs_user"):
            acts.append({"tool": "ask_user", "question": "I cannot access the requested resource without your help "
                                                         f"({diag}). Can you provide access?"})
            report = {"status": "needs_user", "answer": "", "sources": [canon["url"]], "substitutions": [],
                      "diagnosis": diag, "user_request": f"Access is blocked ({diag}); the user's help is needed.",
                      "confidence": 0.8}
        else:
            report = {"status": "infeasible", "answer": "", "sources": [canon["url"]], "substitutions": [],
                      "diagnosis": f"{diag}; no legitimate copy of the requested resource was found", "confidence": 0.8}
    acts.append({"tool": "submit_report", "report": report})
    return {"actions": acts}


def episode_from_spec(spec: dict) -> dict:
    resources = [_resource(p, spec) for p in spec["pages"]]
    canon = next(r for r in resources if r["role"] == "canonical")
    world = spec["world"]
    route = spec.get("route") or {"W1a": "faithful", "W1b": "faithful", "W1v": "variant"}.get(world, "report")
    ep = {
        "dataset_version": "agentheal-real-v0.1", "split": "real",
        "episode_id": spec["id"], "goal_id": spec["id"], "family": spec["family"], "world": world,
        "domain": spec.get("domain", "web"), "task_type": spec.get("task_type", "IR"), "goal": spec["goal"],
        "answer": {"kind": "value", "field": spec["answer"].get("field", ""), "unit": spec["answer"].get("unit", ""),
                   "canonical": spec["answer"].get("value"), "entity": spec["answer"].get("entity", ""),
                   "derived_from": spec["answer"].get("derived_from"), "counted": spec["answer"].get("counted")},
        "resources": resources,
        "barrier": {"rule": spec["barrier"]["rule"], "signal": spec["barrier"].get("signal", "explicit"),
                    "targets": [canon["id"]], "params": spec["barrier"].get("params", {})},
        "credentials": None, "deadline_s": spec.get("deadline_s"), "gate": spec.get("gate"),
        "policy": "explicit", "declared_ua": DECLARED_UA,
        "budget": {"max_actions": MAX_ACTIONS, "max_wall_seconds": MAX_WALL_SECONDS},
        "pair": {"recoverable": None, "unrecoverable": None, "twin": None},
        "expected": {"outcomes": spec.get("expected_outcomes") or EXPECTED[world], "route": route,
                     "must_disclose": ["version_id", "not_requested_version"] if world == "W1v" else []},
        "evidence": spec.get("evidence", {}), "oracle_query": spec.get("oracle_query"),
    }
    # The instruction is the user's request and contains the link the user has to the requested resource.
    assert spec.get("user_link", canon["url"]) in ep["goal"], f"{spec['id']}: the instruction must contain the user's link"
    if spec["family"] == "F1" and not canon["indexed"] and canon.get("title"):
        # A dead page keeps being listed under its title by search engines and by the pages that cite it; only
        # the page itself is gone. Index the original address (the served response stays the recorded error).
        canon["indexed"] = True
        canon["body"] = {"paragraphs": [canon["title"]], "table": []}
    ep["oracle"] = oracle_for_real(ep)
    return ep


def counted_in(r: dict, value) -> bool:
    """A count answer: some list in the recorded JSON has exactly that many items."""
    try:
        n = int(str(value))
        obj = json.loads(r["recorded"].get("text") or "")
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, list):
            if len(o) == n:
                return True
            stack += o
        elif isinstance(o, dict):
            stack += list(o.values())
    return False


def qc_real(ep: dict, robots: dict) -> list[str]:
    errs = []
    res = ep["resources"]
    canon = next(r for r in res if r["role"] == "canonical")
    star = ep["answer"]["canonical"]
    w = ep["world"]

    def shows(r, v):
        rec = r["recorded"]
        blob = rec.get("text", "") + " " + json.dumps(rec.get("tables", []), ensure_ascii=False)
        return v is not None and (str(v) in blob or str(v).replace(",", "") in blob.replace(",", ""))
    def shows_token(r, v):  # standalone occurrence only (not inside an id, a longer number or SVG path data)
        rec = r["recorded"]
        blob = rec.get("text", "") + " " + json.dumps(rec.get("tables", []), ensure_ascii=False)
        return v is not None and re.search(r"(?<![\w.])" + re.escape(str(v)) + r"(?![\w]|\.\d)", blob) is not None
    holder = {"W1a": "faithful", "W1b": "faithful", "W1v": "variant"}.get(w)
    if ep["expected"]["route"] == "wait_retry":
        holder = "canonical"
    if holder:
        hs = [r for r in res if r["role"] == holder]
        if not hs:
            errs.append(f"R1: no {holder} resource")
        inputs = ep["answer"].get("derived_from")
        for r in hs:
            if r["value"] is None:
                errs.append(f"R2: {r['id']} has no value")
            elif inputs:  # computed answer: the inputs are on the page, the result is not
                for x in inputs:
                    if not shows(r, x):
                        errs.append(f"R2: {r['id']} does not show input {x!r}")
            elif not shows(r, r["value"]) and not (ep["answer"].get("counted") or counted_in(r, r["value"])):
                errs.append(f"R2: {r['id']} does not show its value {r['value']!r}")
        if holder != "variant" and hs and str(hs[0]["value"]) != str(star):
            errs.append("R1: answer differs from the faithful value")
    if holder != "canonical" and star is not None and shows_token(canon, star):
        errs.append("R3: the blocked canonical response shows the answer")
    if w in ("W2", "W3") and any(r["role"] in ("faithful", "variant") for r in res):
        errs.append("R5: unrecoverable world with a substitute")
    urls = [r["url"] for r in res]
    if len(set(urls)) != len(urls):
        errs.append("R4: duplicate URLs")
    if ep["barrier"]["rule"] == "robots_disallow":
        txt = robots.get(canon["host"].removeprefix("www."))
        if txt is None:
            errs.append("R6: robots.txt of the canonical host not recorded")
        elif decide(txt, canon["path"])[0]:
            errs.append("R6: canonical path is not disallowed by the recorded robots.txt")
        for r in res:
            if r["role"] == "faithful" and not r.get("official_api"):
                t2 = robots.get(r["host"].removeprefix("www."))
                if t2 and not decide(t2, r["path"])[0]:
                    errs.append(f"R6: faithful {r['id']} is disallowed by robots.txt")
    if not ep.get("evidence", {}).get("observed_at"):
        errs.append("R7: no observation date")
    return errs


_IP = re.compile(r"((?:Client|Your)\s+IP(?:\s+address)?(?:\s+is)?\s*:?\s*)\d{1,3}(?:\.\d{1,3}){3}", re.I)
_SVG = re.compile(r"</?(?:svg|path|circle|rect|polygon|defs|clipPath)\b[^<>]{0,20000}>")


def scrub(text: str) -> str:
    """Redact the collector's network address shown on challenge pages and drop inline SVG path data."""
    return _SVG.sub(" ", _IP.sub(r"\1[redacted]", text))


def _is_archive(url: str) -> bool:
    """Web-archive captures are reached through the archive's own lookup (availability API, CDX, calendar), not
    through general web search, so they are never put in the search index."""
    return (urllib.parse.urlsplit(url).hostname or "") in ("web.archive.org", "archive.org", "archive.today", "archive.ph")


def _scrub_obj(o):
    if isinstance(o, str):
        return scrub(o)
    if isinstance(o, list):
        return [_scrub_obj(x) for x in o]
    if isinstance(o, dict):
        return {k: _scrub_obj(v) for k, v in o.items()}
    return o


def build_real(out: str | Path = ROOT / "dataset_real", instances: str | Path = INSTANCES) -> dict:
    out = Path(out)
    (out / "episodes").mkdir(parents=True, exist_ok=True)
    specs = []
    for f in sorted(Path(instances).glob("*.json")):
        specs += _scrub_obj(load_json(f))
    robots = {}
    rp = Path(instances).parent / "robots.json"
    if rp.exists():
        robots = load_json(rp)
    eps = [episode_from_spec(s) for s in specs if not s.get("exclude")]
    corpus, failures = [], {}
    for ep in eps:
        for r in ep["resources"]:
            c = dict(r)
            c["role"] = "context"
            c["id"] = "ctx-" + r["id"]
            c["value"] = None
            corpus.append(c)
        e = qc_real(ep, robots)
        if e:
            failures[ep["episode_id"]] = e
        dump_json(ep, out / "episodes" / f"{ep['episode_id']}.json")
    dump_json(corpus, out / "corpus.json")
    dump_json(robots, out / "robots.json")
    from collections import Counter
    man = {"version": "agentheal-real-v0.1", "n_episodes": len(eps),
           "by_family": dict(Counter(e["family"] for e in eps)), "by_world": dict(Counter(e["world"] for e in eps)),
           "by_rule": dict(Counter(e["barrier"]["rule"] for e in eps)), "corpus_pages": len(corpus)}
    dump_json(man, out / "manifest.json")
    dump_json({"n_episodes": len(eps), "n_failed": len(failures), "failures": failures}, out / "qc_report.json")
    return {**man, "qc_failed": len(failures), "failures": failures}
