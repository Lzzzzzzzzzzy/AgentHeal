"""Statistics: cluster bootstrap CIs, exact McNemar tests, Holm-Bonferroni, exact Shapley attribution over
the 2x2x2 factorial, and (optionally, if statsmodels is installed) mixed-effects logistic regression."""
from __future__ import annotations

import itertools
import math
import random
from collections import defaultdict
from typing import Callable


def cluster_bootstrap(rows: list[dict], stat: Callable[[list[dict]], float | None], cluster: str = "goal_id",
                      n: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float | None, float | None, float | None]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r[cluster]].append(r)
    keys = list(groups)
    if not keys:
        return None, None, None
    rng = random.Random(seed)
    point = stat(rows)
    vals = []
    for _ in range(n):
        sample = [r for k in (rng.choice(keys) for _ in keys) for r in groups[k]]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    if not vals:
        return point, None, None
    vals.sort()
    lo = vals[int(alpha / 2 * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return point, lo, hi


def mcnemar_exact(a: list[bool], b: list[bool]) -> dict:
    """Paired binary outcomes a[i], b[i] for the same items."""
    n01 = sum(1 for x, y in zip(a, b) if not x and y)
    n10 = sum(1 for x, y in zip(a, b) if x and not y)
    n = n01 + n10
    if n == 0:
        return {"n01": 0, "n10": 0, "p": 1.0}
    k = min(n01, n10)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return {"n01": n01, "n10": n10, "p": min(1.0, 2 * p)}


def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, reject = {}, True
    for i, (k, p) in enumerate(items):
        adj = min(1.0, p * (m - i))
        reject = reject and p <= alpha / (m - i)
        out[k] = {"p": p, "p_holm": adj, "reject": reject}
    return out


def shapley(values: dict[tuple[int, int, int], float], factors=("H", "S", "C")) -> dict[str, float]:
    """values[(h, s, c)] -> metric for all 8 cells. Exact Shapley contribution of each factor."""
    F = list(range(len(factors)))
    phi = {}
    for i in F:
        tot = 0.0
        others = [j for j in F if j != i]
        for r in range(len(others) + 1):
            for T in itertools.combinations(others, r):
                w = math.factorial(len(T)) * math.factorial(len(F) - len(T) - 1) / math.factorial(len(F))
                with_i = tuple(1 if (j in T or j == i) else 0 for j in F)
                without = tuple(1 if j in T else 0 for j in F)
                tot += w * (values[with_i] - values[without])
        phi[factors[i]] = round(tot, 4)
    return phi


def mixed_effects(rows: list[dict], outcome: str = "success"):
    """Logistic mixed model y ~ H*S*C with goal and family variance components (statsmodels, optional)."""
    try:
        import pandas as pd
        from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    except Exception as e:  # pragma: no cover - optional dependency
        return {"skipped": f"statsmodels unavailable: {e}"}
    df = pd.DataFrame(rows)
    if df[outcome].nunique() < 2:
        return {"skipped": "outcome has no variation"}
    model = BinomialBayesMixedGLM.from_formula(f"{outcome} ~ H * S * C", {"goal": "0 + C(goal_id)",
                                                                       "family": "0 + C(family)"}, df)
    fit = model.fit_vb()
    return {"params": dict(zip(model.exog_names, map(float, fit.fe_mean))),
            "sd": dict(zip(model.exog_names, map(float, fit.fe_sd)))}
