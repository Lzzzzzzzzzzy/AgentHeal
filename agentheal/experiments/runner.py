"""Run configurations over episodes: one gym instance per worker, one run directory per episode.

runs/<config>/<episode_id>/s<seed>/
    report.json  trace.jsonl  traj.json  gym_log.json  harness.log  user_dialog.jsonl  result.json
"""
from __future__ import annotations

import json
import random
import threading
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..agents.llm import LLM
from ..agents.react import run_react
from ..agents.scripted import SCRIPTED
from ..config import ADMIN_TOKEN, RUNS_DIR
from ..gym.server import serve
from ..scoring.outcomes import assign
from ..tools.backend import RunContext, ToolBackend
from ..util import dump_json, load_json, read_jsonl
from .configs import Config

_lock = threading.Lock()


def select_episodes(dataset: Path, selector: str = "all", family: str | None = None, world: str | None = None,
                    fraction: float = 1.0, seed: int = 0, task_type: str | None = None) -> list[str]:
    ids = sorted(p.stem for p in (dataset / "episodes").glob("*.json"))
    if task_type:   # IR information retrieval | AA artifact acquisition | TX transaction
        ids = [i for i in ids if load_json(dataset / "episodes" / f"{i}.json").get("task_type") == task_type]
    if selector == "barrier":
        ids = [i for i in ids if not i.endswith("-W0")]
    if selector == "one_goal_per_family" and ids and ids[0].startswith("R-"):
        # real split (R-Fk-nn, one world per instance): keep the first instance of every (family, world)
        seen, keep = set(), []
        for i in ids:
            key = (i.split("-")[1], json.loads((dataset / "episodes" / f"{i}.json").read_text())["world"])
            if key not in seen:
                seen.add(key)
                keep.append(i)
        ids = keep
    elif selector == "one_goal_per_family":
        goals = {}
        for i in ids:
            goals.setdefault(i.split("-")[0], set()).add("-".join(i.split("-")[:3]))
        keep = {sorted(g)[0] for g in goals.values()}
        ids = [i for i in ids if "-".join(i.split("-")[:3]) in keep]
    if family:
        ids = [i for i in ids if i.startswith(family + "-") or i.startswith(f"R-{family}-")]
    if world:
        ids = [i for i in ids if i.endswith("-" + world)]
    if fraction < 1.0:
        goals = sorted({"-".join(i.split("-")[:3]) for i in ids})
        rng = random.Random(seed)
        keep = set(rng.sample(goals, max(1, int(len(goals) * fraction))))
        ids = [i for i in ids if "-".join(i.split("-")[:3]) in keep]
    return ids


def _admin(port: int, path: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run_episode(cfg: Config, episode_id: str, dataset: Path, proxy_port: int, admin_port: int,
                out_root: Path, seed: int = 0, rerun: bool = False) -> dict:
    run_dir = out_root / cfg.name / episode_id / f"s{seed}"
    if (run_dir / "result.json").exists() and not rerun:
        prev = load_json(run_dir / "result.json")
        if not prev.get("error"):          # finished episodes are kept; infrastructure failures are re-run
            return prev
    if run_dir.exists():
        import shutil
        if rerun and (run_dir / "result.json").exists():
            # keep the earlier attempt: runs/<split>/<config>/... -> superseded/<split>/<config>/.../s0_<time>
            dest = out_root.parent / "superseded" / out_root.name / cfg.name / episode_id / \
                f"s{seed}_{time.strftime('%Y%m%d_%H%M%S')}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(run_dir), str(dest))
        else:
            shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    _admin(admin_port, "/admin/load", {"episode_id": episode_id})
    ctx = RunContext(episode_id=episode_id, dataset=str(dataset), run_dir=str(run_dir), proxy_port=proxy_port,
                     admin_port=admin_port, computer_use=bool(cfg.C), skills=cfg.S or None,
                     user_mode=cfg.user_mode)
    ep = load_json(dataset / "episodes" / f"{episode_id}.json")
    if cfg.policy != "explicit":
        ep = dict(ep, policy=cfg.policy)
    t0 = time.time()
    meta: dict = {}
    error = None
    be: ToolBackend | None = None
    try:
        if cfg.agent.startswith("scripted:"):
            be = ToolBackend(ctx)
            meta = SCRIPTED[cfg.agent.split(":", 1)[1]](be)
            be.close()
        elif cfg.agent == "react":
            be = ToolBackend(ctx)
            extra = dict(cfg.headers)
            if cfg.session_header:
                import uuid
                extra[cfg.session_header] = str(uuid.uuid4())   # one model-API session per episode
            llm = LLM(cfg.provider, cfg.model, base_url=cfg.base_url or None, api_key=cfg.api_key or None,
                      headers=extra)
            meta = run_react(be, llm, cfg.policy, max_wall=ep["budget"]["max_wall_seconds"])
            be.close()
        else:
            raise RuntimeError(f"unsupported agent {cfg.agent!r}; this release runs the ReAct agent")
    except Exception:
        error = traceback.format_exc()
    if error is None and meta.get("exit") in ("missing", "not_configured"):
        error = f"harness {meta['exit']}: see harness.log"     # infrastructure failure: not scored, re-run next time
    wall = time.time() - t0
    log = _admin(admin_port, "/admin/log")["log"]
    dump_json(log, run_dir / "gym_log.json")
    report = load_json(run_dir / "report.json") if (run_dir / "report.json").exists() else None
    trace = read_jsonl(run_dir / "trace.jsonl")
    scored = assign(ep, report, log, trace)
    tokens = (meta.get("input_tokens") or 0) + (meta.get("output_tokens") or 0)
    scored["cost"] = {"steps": len(trace), "seconds": round(wall, 2), "tokens": tokens or None,
                      "usd": meta.get("usd")}
    scored.update({"config": cfg.name, "H": cfg.H, "S": 1 if cfg.S else 0, "skills": cfg.S, "C": cfg.C,
                   "seed": seed, "agent_meta": meta, "error": error, "success": int(scored["target"])})
    if be is not None:
        be.write_trajectory()
    dump_json(scored, run_dir / "result.json")
    return scored


def rescore_dir(cfg_dir: Path, dataset: Path) -> list[dict]:
    """Recompute outcomes of every stored episode in a configuration directory from its saved report, proxy log
    and trace, keeping the recorded cost and configuration fields; result.json files are updated in place."""
    rows = []
    for res_path in sorted(cfg_dir.glob("*/s*/result.json")):
        run_dir = res_path.parent
        old = load_json(res_path)
        ep = load_json(dataset / "episodes" / f"{old['episode_id']}.json")
        report = load_json(run_dir / "report.json") if (run_dir / "report.json").exists() else None
        log = load_json(run_dir / "gym_log.json") if (run_dir / "gym_log.json").exists() else []
        scored = assign(ep, report, log, read_jsonl(run_dir / "trace.jsonl"))
        for k in ("cost", "config", "H", "S", "skills", "C", "seed", "agent_meta", "error"):
            if k in old:
                scored[k] = old[k]
        scored["success"] = int(scored["target"])
        dump_json(scored, res_path)
        rows.append(scored)
    return rows


def _free_block(start: int, n: int) -> int:
    """First port p >= start such that p..p+n-1 and their admin ports (+1000) are all free."""
    import socket

    def free(p: int) -> bool:
        with socket.socket() as sk:
            try:
                sk.bind(("127.0.0.1", p))
                return True
            except OSError:
                return False
    p = start
    while not all(free(p + i) and free(p + 1000 + i) for i in range(n)):
        p += n
    return p


def run_config(cfg: Config, episode_ids: list[str], dataset: Path, out_root: Path = RUNS_DIR, workers: int = 4,
               base_port: int = 8200, seed: int = 0, progress: bool = True, rerun: bool = False) -> list[dict]:
    if not episode_ids:
        return []
    dataset, out_root = Path(dataset).resolve(), Path(out_root).resolve()   # harness subprocesses run elsewhere
    base_port = _free_block(base_port, workers)
    servers = [serve(dataset, port=base_port + i, admin_port=base_port + 1000 + i, block=False) for i in range(workers)]
    free = list(range(workers))
    rows: list[dict] = []

    def job(eid: str) -> dict:
        with _lock:
            w = free.pop()
        try:
            return run_episode(cfg, eid, dataset, base_port + w, base_port + 1000 + w, out_root, seed, rerun)
        finally:
            with _lock:
                free.append(w)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(job, e): e for e in episode_ids}
        for k, f in enumerate(as_completed(futs), 1):
            r = f.result()
            rows.append(r)
            if progress and (k % 25 == 0 or k == len(futs)):
                print(f"[{cfg.name}] {k}/{len(futs)} done", flush=True)
    for gym, proxy, admin in servers:
        proxy.shutdown()
        admin.shutdown()
    return rows


def collect(out_root: Path, config_name: str, include_errors: bool = False) -> list[dict]:
    """Scored episodes of a configuration. Episodes that ended in an infrastructure error (API failure after
    retries, harness not installed) are left out of the metrics and re-run by the next run of the same cell."""
    rows = [load_json(p) for p in sorted((out_root / config_name).glob("*/s*/result.json"))]
    return rows if include_errors else [r for r in rows if not r.get("error")]
