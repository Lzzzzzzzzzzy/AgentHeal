"""Reports: per-configuration metrics, per-family breakdowns, factorial Shapley tables (CSV / Markdown / LaTeX)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..scoring.metrics import aggregate, by_family
from ..scoring.stats import cluster_bootstrap, shapley
from .runner import collect

MAIN_COLS = ["RR", "CRR", "W1v_DV", "VDR", "DAR", "HAR", "PAR", "CR", "PGS", "U"]


def _pgs(rows):
    return aggregate(rows)["PGS"]


def summarize(out_root: Path, configs: list[str]) -> dict:
    table = {}
    for name in configs:
        rows = collect(out_root, name)
        if not rows:
            continue
        m = aggregate(rows)
        m["n_errors"] = len(collect(out_root, name, include_errors=True)) - len(rows)
        m["PGS_CI"] = cluster_bootstrap(rows, _pgs, n=1000)[1:]
        m["by_family"] = by_family(rows)
        table[name] = m
    return table


def factorial_shapley(table: dict, metric: str = "PGS", paper: bool = False) -> dict:
    """Group configs named <model>__<harness|react>__S..__C. into 8 cells and compute Shapley values.
    Only the curated skill pack (S-curated) counts as s=1; placebo and persistence controls are ignored."""
    react: dict[str, dict] = {}
    prod: dict[tuple[str, str], dict] = {}
    for name, m in table.items():
        parts = name.split("__")
        value = (m.get("paper") or {}).get(metric) if paper else m.get(metric)
        if len(parts) != 4 or value is None or parts[2] not in ("S0", "S-curated"):
            continue
        mid, h, s, c = parts
        cell = (0 if h == "react" else 1, 0 if s == "S0" else 1, int(c[1:]))
        if h == "react":
            react.setdefault(mid, {})[cell] = value
        else:
            prod.setdefault((mid, h), {})[cell] = value
    out = {}
    for (mid, h), cells in prod.items():
        full = {**react.get(mid, {}), **cells}
        if len(full) == 8:
            out[f"{mid} ({h})"] = shapley(full)
    return out


PAPER_COLS = [("TS0", "TaskSuccess_barrier_free"), ("TS", "TaskSuccess_barrier"), ("RR", "RecoveryRate"),
              ("RC_actions", "RecoveryOverhead_steps"), ("RC_time", "RecoveryOverhead_seconds"),
              ("RC_all", "RecoveryCost_censored"), ("UE", "UnrecoverableEffort"),
              ("AA", "AuditAccuracy"), ("HR", "HonestReportingRate"), ("VR", "ViolationRate"),
              ("PGP", "GoalPreservationScore")]


def write_paper_tables(table: dict, out: Path) -> None:
    """Paper-facing table (Table 2 / Figure 6 / Figure 7 inputs): rates in %, RC as a ratio."""
    def fmt(k, v):
        if v is None:
            return "--"
        return f"{v:.2f}" if k.startswith("RC") or k == "UE" else f"{100 * v:.1f}"
    modes = sorted({k for m in table.values() for k in (m.get("paper") or {}).get("FailureModes", {})})
    with (out / "paper_results.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config", "n_episodes"] + [c for c, _ in PAPER_COLS] + [f"fail_{k}" for k in modes])
        for name, m in table.items():
            p = m.get("paper") or {}
            w.writerow([name, m["n_episodes"]] + [p.get(k) for _, k in PAPER_COLS]
                       + [p.get("FailureModes", {}).get(k) for k in modes])
    md = ["| config | n | " + " | ".join(c for c, _ in PAPER_COLS) + " |", "|" + "---|" * (len(PAPER_COLS) + 2)]
    tex = []
    for name, m in table.items():
        p = m.get("paper") or {}
        vals = [fmt(c, p.get(k)) for c, k in PAPER_COLS]
        md.append(f"| {name} | {m['n_episodes']} | " + " | ".join(vals) + " |")
        tex.append(name.replace("_", r"\_") + " & " + " & ".join(vals) + r" \\")
    (out / "paper_results.md").write_text("\n".join(md) + "\n")
    (out / "paper_results.tex").write_text("\n".join(tex) + "\n")
    with (out / "paper_by_family.csv").open("w", newline="") as f:  # per-family inputs (Figures 6, 7, 8c)
        w = csv.writer(f)
        w.writerow(["config", "family", "n_episodes"] + [c for c, _ in PAPER_COLS] + [f"fail_{k}" for k in modes])
        for name, m in table.items():
            for fam, fm in (m.get("by_family") or {}).items():
                p = fm.get("paper") or {}
                w.writerow([name, fam, fm.get("n_episodes")] + [p.get(k) for _, k in PAPER_COLS]
                           + [p.get("FailureModes", {}).get(k) for k in modes])
    sh = {metric: factorial_shapley(table, key, paper=True)
          for metric, key in (("RR", "RecoveryRate"), ("AA", "AuditAccuracy"), ("HR", "HonestReportingRate"),
                              ("VR", "ViolationRate"), ("PGP", "GoalPreservationScore"))}
    sh = {k: v for k, v in sh.items() if v}
    if sh:
        (out / "paper_shapley.json").write_text(json.dumps(sh, indent=1))


def write_reports(table: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(table, indent=1))
    with (out / "main_results.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config"] + MAIN_COLS + ["ROR_steps", "n"])
        for name, m in table.items():
            w.writerow([name] + [m.get(c) for c in MAIN_COLS] + [m.get("ROR", {}).get("steps"), m["n_episodes"]])
    fmt = lambda v: "--" if v is None else (f"{100 * v:.1f}" if isinstance(v, float) and abs(v) <= 1 else f"{v}")
    md = ["| config | " + " | ".join(MAIN_COLS) + " |", "|" + "---|" * (len(MAIN_COLS) + 1)]
    tex = []
    for name, m in table.items():
        md.append(f"| {name} | " + " | ".join(fmt(m.get(c)) for c in MAIN_COLS) + " |")
        tex.append(name.replace("_", r"\_") + " & " + " & ".join(fmt(m.get(c)) for c in MAIN_COLS) + r" \\")
    (out / "main_results.md").write_text("\n".join(md) + "\n")
    (out / "main_results.tex").write_text("\n".join(tex) + "\n")
    sh = factorial_shapley(table)
    if sh:
        (out / "shapley.json").write_text(json.dumps(sh, indent=1))
    write_paper_tables(table, out)
