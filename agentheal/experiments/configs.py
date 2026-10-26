"""Configurations: the harness x skills x computer-use factorial, model specs and the experiment registry.

Model specs live in configs/models.json, e.g.
  {"M1": {"model": "claude-opus-4-1", "native_harness": "claude_code", "react_provider": "anthropic"},
   "M2": {"model": "qwen3-vl-32b", "native_harness": "openclaw", "react_provider": "openai",
          "base_url": "http://127.0.0.1:8000/v1"}}
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import asdict, dataclass, field

from ..config import ROOT


@dataclass(frozen=True)
class Config:
    name: str
    agent: str                  # react | claude_code | codex | openclaw | scripted:<oracle|always_answer|...>
    model: str = ""
    provider: str = ""          # for react: anthropic | openai
    base_url: str = ""
    H: int = 0
    S: str = ""                 # skill pack name ("" = S0); curated | placebo | never_give_up | self_generated
    C: int = 0
    policy: str = "explicit"
    user_mode: str = "scripted"
    headers: dict = field(default_factory=dict)   # extra HTTP headers for the model API (e.g. User-Agent)
    session_header: str = ""                      # header that carries a fresh session id per episode
    api_key: str = field(default="", repr=False)  # model API key; never written to run directories

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("api_key", None)
        return d


def load_models() -> dict:
    p = ROOT / "configs" / "models.json"
    if not p.exists():
        p = ROOT / "configs" / "models.example.json"
    return json.loads(p.read_text())


def cell_name(mid: str, h: int, s: str, c: int, harness: str, policy: str = "explicit") -> str:
    hs = "react" if not h else harness
    return f"{mid}__{hs}__S{'-' + s if s else '0'}__C{c}" + ("" if policy == "explicit" else f"__{policy}")


def config_for(mid: str, h: int, s: str, c: int, harness: str | None = None, policy: str = "explicit") -> Config:
    spec = load_models()[mid]
    harness = harness or spec.get("native_harness") or "react"
    if h:
        raise ValueError("this release only runs the ReAct agent")
    return Config(name=cell_name(mid, h, s, c, harness, policy), agent="react",
                  model=spec["model"] if not h else spec.get("harness_model", spec["model"]),
                  provider=spec.get("react_provider", "anthropic"), base_url=spec.get("base_url", ""),
                  H=h, S=s, C=c, policy=policy, headers=dict(spec.get("headers", {})),
                  session_header=spec.get("session_header", ""))


HARNESS_NAMES = ("react",)


def direct_config(tag: str, model: str, provider: str, api_url: str, api_key: str, harness: str = "react",
                  skills: str = "", cu: int = 0, policy: str = "explicit", headers: dict | None = None,
                  session_header: str = "") -> Config:
    """A configuration given directly on the command line (used by the experiment scripts), without models.json.
    This release accepts harness='react'."""
    if harness not in HARNESS_NAMES:
        raise ValueError(f"unknown harness {harness!r}; choose one of {', '.join(HARNESS_NAMES)}")
    tag = re.sub(r"[^A-Za-z0-9.-]+", "-", tag).strip("-") or "model"
    h = 0 if harness == "react" else 1
    return Config(name=cell_name(tag, h, skills, cu, harness, policy), agent=harness, model=model,
                  provider=provider, base_url=api_url, H=h, S=skills, C=cu, policy=policy,
                  headers=dict(headers or {}), session_header=session_header, api_key=api_key)


def factorial(mid: str, skills: str = "curated", harness: str | None = None) -> list[Config]:
    return [config_for(mid, h, skills if s else "", c, harness) for h, s, c in itertools.product((0, 1), repeat=3)]


def half_fraction(mid: str, skills: str = "curated") -> list[Config]:
    cells = [(0, 0, 0), (1, 1, 0), (1, 0, 1), (0, 1, 1)]
    return [config_for(mid, h, skills if s else "", c) for h, s, c in cells]


def scripted(name: str) -> Config:
    return Config(name=f"scripted__{name}", agent=f"scripted:{name}")


# Experiment registry (Appendix of the paper). Each entry: configs + episode selector.
def registry() -> dict:
    return {
        "validate": {"configs": [scripted(n) for n in ("oracle", "always_answer", "always_abstain", "violator")],
                     "episodes": "all"},
        "smoke": {"configs": [scripted("oracle"), scripted("always_abstain")], "episodes": "one_goal_per_family"},
    }
