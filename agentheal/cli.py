"""Command-line interface.

  python -m agentheal build-dataset [--out dataset] [--seed 0] [--corpus 600]
  python -m agentheal qc [--dataset dataset]
  python -m agentheal serve [--dataset dataset] [--port 8100]
  python -m agentheal browse [episode_id] [--family F1] [--world W1a] [--show-answer]   browse an episode by hand
  python -m agentheal validate [--workers 4]                 scripted baselines over all episodes
  python -m agentheal run --model-name NAME --provider openai|anthropic --harness react [--cu]
                          [--policy explicit|implicit] [--family F2] [--world W1v] [--fraction 0.3] [--workers 4]
  python -m agentheal experiment <name>                      named experiment from the registry
  python -m agentheal ping --model-name NAME --provider openai|anthropic
  python -m agentheal report [--runs runs] [--out reports]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import DATASET_DIR, RUNS_DIR


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agentheal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-dataset")
    b.add_argument("--out", default=str(DATASET_DIR))
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--corpus", type=int, default=600)
    q = sub.add_parser("qc")
    q.add_argument("--dataset", default=str(DATASET_DIR))
    s = sub.add_parser("serve")
    s.add_argument("--dataset", default=str(DATASET_DIR))
    s.add_argument("--port", type=int, default=8100)
    rb = sub.add_parser("build-real")
    rb.add_argument("--out", default="dataset_real")
    br = sub.add_parser("browse")
    br.add_argument("episode", nargs="?")
    br.add_argument("--dataset", default=str(DATASET_DIR))
    br.add_argument("--port", type=int, default=8100)
    br.add_argument("--family")
    br.add_argument("--world")
    br.add_argument("--show-answer", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("--dataset", default=str(DATASET_DIR))
    v.add_argument("--workers", type=int, default=4)
    v.add_argument("--runs", default=str(RUNS_DIR / "validate"))
    v.add_argument("--fraction", type=float, default=1.0)
    r = sub.add_parser("run")
    r.add_argument("--dataset", default=str(DATASET_DIR))
    r.add_argument("--runs", default=str(RUNS_DIR))
    r.add_argument("--model", help="model id from configs/models.json (alternative to --model-name)")
    r.add_argument("--model-name", help="model name sent to the API")
    r.add_argument("--tag", help="short label for run directories (default: derived from --model-name)")
    r.add_argument("--provider", default="openai", choices=["openai", "anthropic"],
                   help="API protocol: openai (any OpenAI-compatible endpoint) or anthropic")
    r.add_argument("--api-url", default=os.environ.get("AGENTHEAL_API_URL", ""),
                   help="API base URL (default: $AGENTHEAL_API_URL)")
    r.add_argument("--api-key", default=os.environ.get("AGENTHEAL_API_KEY", ""),
                   help="API key (default: $AGENTHEAL_API_KEY; never written into the repository)")
    r.add_argument("--header", action="append", default=[], help="extra API header 'Name: value' (repeatable)")
    r.add_argument("--harness", default="react", choices=["react"], help="this release runs the ReAct agent")
    r.add_argument("--cu", action="store_true")
    r.add_argument("--policy", default="explicit")
    r.add_argument("--family")
    r.add_argument("--world")
    r.add_argument("--fraction", type=float, default=1.0)
    r.add_argument("--select", default="all", choices=["all", "barrier", "one_goal_per_family"])
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--repeats", type=int, default=1, help="independent runs with seeds seed..seed+repeats-1")
    r.add_argument("--task-type", choices=["IR", "AA", "TX"], help="only episodes of this task type")
    r.add_argument("--rerun", action="store_true",
                   help="run selected episodes again even if finished; earlier attempts move to superseded/")
    e = sub.add_parser("experiment")
    e.add_argument("name")
    e.add_argument("--dataset", default=str(DATASET_DIR))
    e.add_argument("--runs", default=str(RUNS_DIR))
    e.add_argument("--workers", type=int, default=4)
    e.add_argument("--fraction", type=float, default=1.0)
    rs = sub.add_parser("rescore")
    rs.add_argument("--runs", required=True, help="a configuration directory, e.g. runs/x/DS__react__S0__C0")
    rs.add_argument("--dataset", default=str(DATASET_DIR))
    pg = sub.add_parser("ping", help="send one short request to the model API to check URL, key and model name")
    pg.add_argument("--model-name", required=True)
    pg.add_argument("--provider", default="openai", choices=["openai", "anthropic"])
    pg.add_argument("--api-url", default=os.environ.get("AGENTHEAL_API_URL", ""))
    pg.add_argument("--api-key", default=os.environ.get("AGENTHEAL_API_KEY", ""))
    rp = sub.add_parser("report")
    rp.add_argument("--runs", default=str(RUNS_DIR))
    rp.add_argument("--out", default="reports")
    a = ap.parse_args(argv)

    if a.cmd == "build-dataset":
        from .generator.build import build_dataset
        from .generator.qc import run_qc
        m = build_dataset(a.out, a.seed, a.corpus)
        qc = run_qc(a.out)
        print(json.dumps(m, indent=1))
        print("calibration:", json.dumps({k: v for k, v in qc.get("calibration", {}).items()}))
        print(f"QC: {qc['n_failed']} of {qc['n_episodes']} episodes failed; goal text identical across worlds: "
              f"{qc['goal_text_identical_across_worlds']}")
        return 0 if qc["n_failed"] == 0 else 1
    if a.cmd == "qc":
        from .generator.qc import run_qc
        qc = run_qc(a.dataset)
        print(json.dumps({k: v for k, v in qc.items() if k != "failures"}, indent=1))
        return 0 if qc["n_failed"] == 0 else 1
    if a.cmd == "serve":
        from .gym.server import serve
        print(f"gym proxy on 127.0.0.1:{a.port}, admin on 127.0.0.1:{a.port + 1000}", flush=True)
        serve(a.dataset, a.port)
        return 0
    if a.cmd == "build-real":
        from .realsplit import build_real
        m = build_real(a.out)
        print(json.dumps({k: v for k, v in m.items() if k != "failures"}, indent=1))
        for eid, errs in m["failures"].items():
            print("QC", eid, errs)
        return 0 if m["qc_failed"] == 0 else 1
    if a.cmd == "browse":
        from .explore import main as browse
        return browse(a.dataset, a.episode, a.port, a.family, a.world, a.show_answer)
    if a.cmd == "validate":
        from .experiments.configs import scripted
        from .experiments.runner import run_config, select_episodes
        from .scoring.metrics import aggregate
        ds = Path(a.dataset)
        eps = select_episodes(ds, "all", fraction=a.fraction)
        out = {}
        for name in ("oracle", "always_answer", "always_abstain", "violator"):
            rows = run_config(scripted(name), eps, ds, Path(a.runs), workers=a.workers)
            m = aggregate(rows)
            out[name] = {k: m[k] for k in ("PGS", "RR", "W1v_DV", "HAR", "PAR", "CR", "DAR", "FABR", "outcomes")}
            print(name, json.dumps(out[name]), flush=True)
        Path(a.runs).mkdir(parents=True, exist_ok=True)
        (Path(a.runs) / "validation_summary.json").write_text(json.dumps(out, indent=1))
        if out["oracle"]["PGS"] is None:  # real split: no twin pairs, check outcomes directly
            ok = (out["oracle"]["RR"] in (1.0, None) and out["oracle"]["HAR"] in (1.0, None) and out["oracle"]["CR"] == 0
                  and out["always_answer"]["RR"] in (0.0, None) and out["always_abstain"]["RR"] in (0.0, None))
        else:
            ok = out["oracle"]["PGS"] == 1.0 and out["oracle"]["CR"] == 0 and out["always_abstain"]["PGS"] == 0 \
                and out["always_answer"]["PGS"] == 0
        print("VALIDATION", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    if a.cmd == "run":
        from .experiments.configs import config_for, direct_config, load_models
        from .experiments.runner import run_config, select_episodes
        from .scoring.metrics import aggregate
        if a.harness != "react":
            print("this release only runs the ReAct agent")
            return 2
        if a.model_name:
            headers = dict(h.split(":", 1) for h in a.header)
            headers = {k.strip(): v.strip() for k, v in headers.items()}
            cfg = direct_config(a.tag or a.model_name, a.model_name, a.provider, a.api_url, a.api_key, "react",
                                "", int(a.cu), a.policy, headers)
            label = a.model_name
        elif a.model:
            spec = load_models()[a.model]
            cfg = config_for(a.model, 0, "", int(a.cu), "react", a.policy)
            label = spec["model"]
        else:
            print("give either --model-name or --model")
            return 2
        eps = select_episodes(Path(a.dataset), a.select, a.family, a.world, a.fraction, a.seed, a.task_type)
        if not eps:
            print(f"no episodes of {a.dataset} match the selection; nothing to run", flush=True)
            return 0
        for seed in range(a.seed, a.seed + a.repeats):
            print(f"running {cfg.name} ({label}) on {len(eps)} episodes of {a.dataset}, seed {seed}", flush=True)
            rows = run_config(cfg, eps, Path(a.dataset), Path(a.runs), workers=a.workers, seed=seed, rerun=a.rerun)
            errors = [r for r in rows if r.get("error")]
            rows = [r for r in rows if not r.get("error")]
            if errors:
                first = errors[0]["error"].strip().splitlines()[-1][:300]
                print(f"WARNING: {len(errors)} of {len(rows) + len(errors)} episodes failed for infrastructure reasons "
                      f"and are not scored (first: {first}). Run the same script again to retry them.", flush=True)
            if not rows:
                print("ERROR: no episode finished; check the API settings", flush=True)
                return 1
            m = aggregate(rows)
            print(json.dumps({"config": cfg.name, "seed": seed, "paper_metrics": m["paper"],
                              "outcomes": m.get("outcomes")}, indent=1), flush=True)
        return 0
    if a.cmd == "experiment":
        from .experiments.configs import registry
        from .experiments.runner import run_config, select_episodes
        reg = registry()
        if a.name not in reg:
            print("unknown experiment; available:", ", ".join(reg))
            return 2
        spec = reg[a.name]
        eps = select_episodes(Path(a.dataset), spec["episodes"], fraction=a.fraction)
        for cfg in spec["configs"]:
            print(f"== {cfg.name}: {len(eps)} episodes", flush=True)
            run_config(cfg, eps, Path(a.dataset), Path(a.runs), workers=a.workers)
        return 0
    if a.cmd == "rescore":  # re-score stored trajectories with the current scorer (no agent is re-run)
        from .experiments.runner import rescore_dir
        from .scoring.metrics import aggregate
        rows = rescore_dir(Path(a.runs), Path(a.dataset))
        print(json.dumps(aggregate(rows), indent=1))
        return 0
    if a.cmd == "ping":
        from .agents.llm import LLM
        llm = LLM(a.provider, a.model_name, max_tokens=16, base_url=a.api_url or None, api_key=a.api_key or None, retries=2)
        try:
            out = llm.complete("You are a connectivity check.", [{"role": "user", "content": "Reply with the word OK."}])
        except Exception as e:  # noqa: BLE001
            print(f"PING FAILED ({a.provider} {a.api_url or 'default URL'} model={a.model_name}): {e}")
            return 1
        print(f"PING OK ({a.provider} model={a.model_name}): {out.strip()[:60]!r}")
        return 0
    if a.cmd == "report":
        from .experiments.report import summarize, write_reports
        runs = Path(a.runs)
        names = sorted(p.name for p in runs.iterdir() if p.is_dir() and not p.name.startswith(("_", ".", "superseded")))
        table = summarize(runs, names)
        write_reports(table, Path(a.out))
        print(f"wrote reports for {len(table)} configurations to {a.out}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
