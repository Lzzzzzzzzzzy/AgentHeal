"""Episode specification: the JSON contract between the generator, the gym server and the scorer.

An episode is a plain JSON object (dict). This module documents its fields, validates them, and
offers small accessors. Keeping episodes as dicts makes the dataset language-agnostic.

Episode
-------
episode_id   "F4-ACA-007-W1v"           unique id
goal_id      "F4-ACA-007"               base goal shared by the recoverable, unrecoverable and twin
family       "F1".."F9"
world        "W0" | "W1a" | "W1b" | "W1v" | "W2" | "W3"
domain       academic | news | ecommerce | opendata | docs | encyclopedia
task_type    IR (information retrieval) | AA (artifact acquisition) | TX (transaction)
goal         natural-language instruction given to the agent (identical across worlds of a goal)
answer       {"kind": "value"|"file"|"order", "field": str, "unit": str, "canonical": str}
resources    list of Resource (below)
barrier      {"rule": str, "signal": "explicit"|"ambiguous"|"silent", "targets": [resource ids], "params": {...}}
challenge    optional verification-challenge spec (F5)
credentials  optional {"host", "username", "password"} supplied by the user in the goal (F3)
deadline_s   optional virtual-time deadline (F8)
expected     {"outcomes": [allowed target outcomes], "must_disclose": [...], "route": str}
oracle       {"actions": [...]}  a legitimate action sequence realizing the target outcome
pair         {"recoverable": id, "unrecoverable": id, "twin": id}
policy       "explicit" | "implicit"

Resource
--------
id, role       canonical | faithful | variant | decoy | honeypot | context | related | hub
               (hub: a navigation page of a discovery route; it never carries an answer)
chain          for faithful copies and variants: the URLs a compliant agent requests, in order, to reach it
url, host, path, kind (page | file | product | api | image)
site_type      journal | repository | preprint | review | archive | news | shop | portal | docs |
               wiki | blog | mirror | cache | forum | honeypot | api
title, publisher, date, version_label, expression (JAV stage or release), work_id
value          canary for IR answers (string)
file_text      artifact content for AA (its sha256 is the canary)
gtin           product identifier for TX
body           rendering fields ({"paragraphs": [...], "table": [[k, v], ...], ...})
cue            the audit cue rendered on the page (variants and decoys)
variant_type / decoy_type
delta          {field: {"differs": bool, "observable": bool}} for variants
indexed        whether the search engine indexes it; rank_boost to order results
access         {"state": "ok" | "dead" | "gated" | "render_only", ...}
"""
from __future__ import annotations

from typing import Any

from .config import FAMILIES, WORLDS

ROLES = {"canonical", "faithful", "variant", "decoy", "honeypot", "context", "related", "hub"}
KINDS = {"page", "file", "product", "api", "image"}
VARIANT_TYPES = {"V-P", "V-S", "V-R", "V-C", "V-T", "V-E"}
DECOY_TYPES = {"D-P", "D-E", "D-A", "D-U"}


class SpecError(ValueError):
    pass


def resources_by_role(ep: dict, role: str) -> list[dict]:
    return [r for r in ep["resources"] if r["role"] == role]


def resource(ep: dict, rid: str) -> dict:
    for r in ep["resources"]:
        if r["id"] == rid:
            return r
    raise KeyError(rid)


def canary_of(r: dict, answer_kind: str) -> str | None:
    if answer_kind == "value":
        return r.get("value")
    if answer_kind == "file":
        return r.get("sha256")
    if answer_kind == "order":
        return r.get("gtin")
    return None


def validate_episode(ep: dict) -> None:
    """Raise SpecError if the episode violates structural invariants."""
    need = ["episode_id", "goal_id", "family", "world", "domain", "task_type", "goal", "answer",
            "resources", "barrier", "expected", "oracle"]
    for k in need:
        if k not in ep:
            raise SpecError(f"{ep.get('episode_id')}: missing {k}")
    if ep["family"] not in FAMILIES:
        raise SpecError(f"bad family {ep['family']}")
    if ep["world"] not in WORLDS:
        raise SpecError(f"bad world {ep['world']}")
    ids = [r["id"] for r in ep["resources"]]
    if len(ids) != len(set(ids)):
        raise SpecError(f"{ep['episode_id']}: duplicate resource ids")
    urls = [r["url"] for r in ep["resources"]]
    if len(urls) != len(set(urls)):
        raise SpecError(f"{ep['episode_id']}: duplicate resource urls")
    for r in ep["resources"]:
        if r["role"] not in ROLES:
            raise SpecError(f"{ep['episode_id']}: bad role {r['role']}")
        if r["kind"] not in KINDS:
            raise SpecError(f"{ep['episode_id']}: bad kind {r['kind']}")
        if r["role"] == "variant" and r.get("variant_type") not in VARIANT_TYPES:
            raise SpecError(f"{ep['episode_id']}: variant without type")
        if r["role"] == "decoy" and r.get("decoy_type") not in DECOY_TYPES:
            raise SpecError(f"{ep['episode_id']}: decoy without type")
        if r["role"] in {"variant", "decoy"} and not r.get("cue"):
            raise SpecError(f"{ep['episode_id']}: {r['id']} has no audit cue")
    canon = resources_by_role(ep, "canonical")
    if len(canon) != 1:
        raise SpecError(f"{ep['episode_id']}: expected exactly one canonical resource")
    kind = ep["answer"]["kind"]
    if canary_of(canon[0], kind) != ep["answer"]["canonical"]:
        raise SpecError(f"{ep['episode_id']}: canonical canary mismatch")
    # Canaries must separate faithful/canonical from decoys.
    star = ep["answer"]["canonical"]
    for r in resources_by_role(ep, "faithful"):
        if canary_of(r, kind) != star:
            raise SpecError(f"{ep['episode_id']}: faithful {r['id']} canary differs")
    for r in resources_by_role(ep, "decoy"):
        if canary_of(r, kind) == star:
            raise SpecError(f"{ep['episode_id']}: decoy {r['id']} shares the canonical canary")


def summary(ep: dict) -> dict[str, Any]:
    roles: dict[str, int] = {}
    for r in ep["resources"]:
        roles[r["role"]] = roles.get(r["role"], 0) + 1
    return {"id": ep["episode_id"], "family": ep["family"], "world": ep["world"],
            "task_type": ep["task_type"], "domain": ep["domain"], "roles": roles,
            "rule": ep["barrier"]["rule"]}
