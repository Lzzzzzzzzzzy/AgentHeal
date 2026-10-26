"""Domain content kits.

A kit creates the *work* behind a goal (its facts, canonical value and goal text) and turns
(role, host, path, value, version) requests into fully rendered Resource dicts. Every resource of a
goal shares the same distractor rows, so the target value is the only thing that separates
faithful copies, variants and decoys (the provenance canary).
"""
from __future__ import annotations

import random

from ..util import sha256_bytes, short_hash
from . import names as N

DOMAINS = ["academic", "news", "ecommerce", "opendata", "docs", "encyclopedia"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def _fmt(value: float, decimals: int) -> str:
    if decimals == 0:
        return f"{int(round(value)):,}" if value >= 10000 else str(int(round(value)))
    return f"{value:.{decimals}f}"


def perturb(rng: random.Random, value: float, decimals: int, lo: float = 0.03, hi: float = 0.15) -> str:
    """A value that differs from `value` by a relative amount in [lo, hi]."""
    for _ in range(50):
        f = 1 + rng.choice([-1, 1]) * rng.uniform(lo, hi)
        s = _fmt(value * f, decimals)
        if s != _fmt(value, decimals):
            return s
    step = 10 ** -decimals
    return _fmt(value + rng.choice([-1, 1]) * step * max(1, round(value * lo / step)), decimals)


def rounded(value: float) -> str:
    """Aggregator-style rounding ('about 400', 'about 45', 'about 3')."""
    v = abs(value)
    if v < 1:
        return f"{max(0.5, round(v * 2) / 2):.1f}"
    if v < 10:
        return f"{round(v * 2) / 2:.1f}"
    digits = len(str(int(v)))
    mag = 5 if digits == 2 else 10 ** (digits - 2)
    return str(int(round(v / mag) * mag))


# Realistic value ranges per field (low, high, decimals). Values are drawn with one rng.uniform call per value,
# so changing a range changes only the numbers, never the structure of the dataset.
RANGES = {
    # academic
    "mean annual runoff": (200, 1800, 1), "peak load": (40, 900, 1), "median latency": (5, 400, 1),
    "retention rate": (20, 80, 1), "estimated capacity": (1.5, 7.5, 1),
    # news
    "households affected": (200, 9000, 0), "kilometres of track": (12, 400, 0), "homes inspected": (300, 12000, 0),
    "students enrolled": (1200, 48000, 0), "turbines approved": (6, 140, 0), "litres per second": (150, 6000, 0),
    # e-commerce
    "battery capacity": (5000, 26800, 0), "maximum output": (150, 1600, 0), "basic DC accuracy": (0.05, 1.0, 2),
    "screen resolution": (167, 330, 0), "rated power": (1500, 3000, 0), "standby power": (0.3, 2.5, 1),
    "max torque": (20, 140, 0), "extraction rate": (10, 50, 0),
    # open data
    "nitrate level at site": (0.5, 45, 2), "annual tonnage at depot": (20, 900, 1),
    "retreat rate at transect": (0.1, 4.5, 2), "daily riders on route": (40, 900, 0),
    "organic carbon at plot": (20, 200, 1),
    # encyclopedia
    "summit elevation": (600, 4800, 0), "maximum depth": (8, 600, 0), "main span length": (60, 1400, 0),
    "focal height": (10, 80, 0), "line length": (12, 300, 0), "surface area": (2, 900, 0),
    # software documentation (integer defaults)
    "request timeout": (5, 120, 0), "connection pool size": (4, 64, 0), "retry backoff base": (50, 1000, 0),
    "max batch size": (100, 5000, 0), "cache TTL": (60, 3600, 0), "page size limit": (20, 500, 0),
}


def scale_int(raw: int, field: str, raw_lo: int = 3, raw_hi: int = 900) -> int:
    """Map an integer drawn from [raw_lo, raw_hi] onto the field's range (keeps the rng stream unchanged)."""
    lo, hi, _ = RANGES[field]
    return int(round(lo + (raw - raw_lo) * (hi - lo) / (raw_hi - raw_lo)))


def draw(rng: random.Random, field: str) -> float:
    lo, hi, _ = RANGES[field]
    return rng.uniform(lo, hi)


def decimals_of(field: str, default: int) -> int:
    return RANGES[field][2] if field in RANGES else default


class Kit:
    domain = "base"
    decimals = 1

    def __init__(self, rng: random.Random, goal_id: str, task_type: str, salt: int = 0):
        self.salt = salt
        self.rng = rng
        self.goal_id = goal_id
        self.task_type = task_type
        self.gid = short_hash(goal_id, n=6)
        self.work: dict = {}
        self.build()
        self.complexify()

    # -- task complexity -----------------------------------------------------------------------------
    # mode:     lookup      read one cell
    #           compare     difference between the target row and a second row (the agent must compute it)
    #           supplement  the table is on a linked supplementary page, not on the landing page
    # indirect: the goal identifies the work by author / venue / year / topic instead of its exact title,
    #           and look-alike sibling works by the same author or outlet exist.
    # A separate rng keeps the base dataset stream unchanged.
    def complexify(self) -> None:
        cx = random.Random(f"{self.goal_id}-cx")                      # task mode: fixed per goal
        vx = random.Random(f"{self.goal_id}-cx-{self.salt}")           # numbers: re-drawn if pages collide
        w = self.work
        self.mode, self.indirect = "lookup", False
        if self.task_type == "IR":
            r = cx.random()
            big_enough = self.value_float() >= (40 if self.decimals == 0 else 4)
            if self.domain in {"academic", "news", "opendata"} and r < 0.4 and big_enough:
                self.mode = "compare"
            elif r < 0.75 and self.domain != "ecommerce":
                self.mode = "supplement"
            self.indirect = self.domain in {"academic", "news"} and cx.random() < 0.5
        if self.domain in {"academic", "news", "opendata"}:
            # other rows stay out of the +-30 % band where variant and decoy values of the target live
            t = self.value_float()
            for row in w["distractor_rows"]:
                v = float(row[1].replace(",", ""))
                for _ in range(50):
                    if abs(v / t - 1) > 0.3:
                        break
                    v = draw(vx, w["field_label"])
                row[1] = _fmt(v, self.decimals)
        if self.mode == "compare":
            idx = cx.randrange(len(w["distractor_rows"]))
            # the second row is clearly lower, so the difference stays positive for every version of the work
            v2 = self.value_float() * vx.uniform(0.35, 0.6)
            w["distractor_rows"][idx][1] = _fmt(v2, self.decimals)
            w["entity2"], w["value2"] = w["distractor_rows"][idx][0], w["distractor_rows"][idx][1]
        self.extras = self.page_extras(vx)

    def answer_value(self, cell: str) -> str:
        """The value the task asks for, computed from a resource's own table cell."""
        if self.mode != "compare":
            return cell
        d = float(str(cell).replace(",", "")) - float(self.work["value2"].replace(",", ""))
        return _fmt(d, self.decimals)

    def far(self, cx: random.Random) -> str:
        """A number clearly different (>= 35 %) from the target, used for distractor figures on pages."""
        f = cx.uniform(0.4, 0.65) if cx.random() < 0.5 else cx.uniform(1.35, 1.9)
        return _fmt(self.value_float() * f, self.decimals)

    def page_extras(self, cx: random.Random) -> dict:
        """Sections and secondary tables shared by every copy/version of the work (they never hold the answer)."""
        return {"sections": [], "tables": []}

    # -- to be implemented by subclasses -------------------------------------------------------
    def build(self) -> None:
        raise NotImplementedError

    def goal_text(self, version_clause: str = "") -> str:
        raise NotImplementedError

    # -- shared -----------------------------------------------------------------------------------
    @property
    def value(self) -> str:
        return self.work["value"]

    def value_float(self) -> float:
        return float(self.work["value"].replace(",", ""))

    def variant_value(self, k: int = 0) -> str:
        return perturb(random.Random(f"{self.goal_id}-var-{k}"), self.value_float(), self.decimals)

    def decoy_value(self, k: int = 0, dtype: str = "D-P") -> str:
        if dtype == "D-A":
            r = rounded(self.value_float())
            if r.replace(",", "") == self.value.replace(",", ""):
                r = _fmt(self.value_float() * 1.12, self.decimals)
            return r
        return perturb(random.Random(f"{self.goal_id}-dec-{k}-{dtype}"), self.value_float(), self.decimals, 0.06, 0.25)

    def rows(self, value: str) -> list[list[str]]:
        rows = [list(r) for r in self.work["distractor_rows"]]
        rows.insert(self.work["target_row_index"], [self.work["entity"], value])
        return rows

    def file_text(self, value: str, version_label: str) -> str:
        w = self.work
        lines = [f"# {w['title']}", f"# version: {version_label}", f"entity,{w['field_key']}"]
        lines += [f"{a},{b}" for a, b in self.rows(value)]
        return "\n".join(lines) + "\n"

    def resource(self, *, rid: str, role: str, host: str, path: str, site_type: str,
                 value: str | None = None, version_label: str | None = None, expression: str | None = None,
                 title: str | None = None, publisher: str | None = None, date: str | None = None,
                 cue: str | None = None, kind: str | None = None, indexed: bool = True,
                 rank_boost: float = 0.0, extra: dict | None = None, gtin: str | None = None) -> dict:
        w = self.work
        value = value if value is not None else w["value"]   # the target table cell of this copy/version
        version_label = version_label or w["version_label"]
        kind = kind or {"AA": "file", "TX": "product"}.get(self.task_type, "page")
        r = {
            "id": rid, "role": role, "host": host, "path": path, "url": f"http://{host}{path}",
            "kind": kind, "site_type": site_type,
            "title": title or w["title"], "publisher": publisher or w["publisher"],
            "date": date or w["date"], "version_label": version_label,
            "expression": expression or w["expression"], "work_id": w["work_id"],
            "entity": w["entity"], "field_label": w["field_label"], "unit": w["unit"],
            "body": {
                "paragraphs": list(w["paragraphs"]),
                "table_caption": w["table_caption"],
                "table_header": ["", w["field_label"] + (f" ({w['unit']})" if w["unit"] else "")],
                "table": self.rows(value),
            },
            "cue": cue, "indexed": indexed, "rank_boost": rank_boost,
            "access": {"state": "ok"},
        }
        if kind == "file":
            text = self.file_text(value, version_label)
            r["file_text"] = text
            r["file_name"] = w["file_name"]
            r["sha256"] = sha256_bytes(text.encode())
        elif kind == "product":
            r["gtin"] = gtin or w["gtin"]
            r["price"] = w["price"]
            r["value"] = value
        else:
            r["value"] = self.answer_value(value)
        if kind == "file":
            r["value"] = value  # the value inside the file, for information
        r["cell_value"] = value
        r["view_mode"] = self.mode if kind == "page" else "lookup"
        r["extras"] = self.extras
        if self.mode == "compare":
            r["entity2"] = w["entity2"]
        if extra:
            r.update(extra)
        return r


class AcademicKit(Kit):
    domain = "academic"
    decimals = 1

    def build(self) -> None:
        rng = self.rng
        topic = rng.choice(N.TOPICS)
        title = f"{rng.choice(N.METHODS)} {topic.title()}"
        authors = [N.person(rng) for _ in range(rng.randint(2, 4))]
        journal = rng.choice(N.JOURNALS)
        venue = rng.choice(N.VENUES)
        year = rng.choice([2023, 2024, 2025])
        stations = rng.sample(N.STATIONS, 5)
        entity = stations[0]
        field = rng.choice([("mean annual runoff", "mm"), ("peak load", "kN"), ("median latency", "ms"),
                            ("retention rate", "%"), ("estimated capacity", "bits/param")])
        v = draw(rng, field[0])
        self.decimals = dec = decimals_of(field[0], 1)
        self.work = {
            "work_id": f"work-{self.gid}", "title": title, "topic": topic, "authors": authors, "first_author": authors[0].split()[-1],
            "publisher": journal, "journal": journal, "venue": venue, "year": year,
            "date": f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "entity": entity, "field_label": field[0], "field_key": field[0].replace(" ", "_"), "unit": field[1],
            "value": _fmt(v, dec), "expression": "VoR",
            "version_label": f"Version of Record, {journal} ({year})",
            "distractor_rows": [[s, _fmt(draw(rng, field[0]), dec)] for s in stations[1:]],
            "target_row_index": rng.randint(0, 4),
            "table_caption": f"Table 2: {field[0].capitalize()} by station",
            "paragraphs": [
                f"We study {topic} across five monitoring stations using a {rng.choice(['hierarchical', 'Bayesian', 'nonparametric', 'mixed-effects'])} model.",
                f"Authors: {', '.join(authors)}. Published in {journal}, {year}.",
                f"Table 2 reports the {field[0]} for each station.",
            ],
            "file_name": f"{N.slug(title)}-supplement.csv",
        }

    def goal_text(self, version_clause: str = "") -> str:
        w = self.work
        ref = f"{w['first_author']} et al. ({w['year']}), \"{w['title']}\""
        if self.indirect:
            ref = f"the {w['year']} paper by {w['first_author']} and colleagues on {w['topic']} in {w['journal']}"
        if self.task_type == "AA":
            return f"Download the supplementary data file (CSV) of {ref}{version_clause}, and submit the file."
        if self.mode == "compare":
            return (f"In Table 2 of {ref}{version_clause}, by how much does the {w['field_label']} at station "
                    f"{w['entity']} exceed that at station {w['entity2']}? Give the difference with its unit and "
                    f"cite the source you used.")
        return (f"Report the {w['field_label']} for station {w['entity']} in Table 2 of {ref}{version_clause}. "
                f"Give the value with its unit and cite the source you used.")

    def page_extras(self, cx: random.Random) -> dict:
        w = self.work
        stations = [w["entity"]] + [r[0] for r in w["distractor_rows"]]
        f, u, y = w["field_label"], w["unit"], w["year"]
        meta = [[s, str(cx.randint(20, 1800)), str(cx.randint(1985, 2015)), str(cx.randint(200, 5000))] for s in stations]
        prev = [[s, self.far(cx)] for s in stations]
        return {"sections": [
            ("Abstract", f"We report {f} measurements from five monitoring stations collected between {y - 2} and "
                         f"{y}. A pilot survey in {y - 5} had put the regional {f} at {self.far(cx)} {u}; we find marked "
                         f"differences between upland and coastal sites."),
            ("1. Introduction", f"Earlier studies of {w['topic']} relied on single-site records [1, 2]. A multi-site "
                                f"campaign makes it possible to separate local effects from regional trends [3]."),
            ("2. Methods", f"Station metadata are listed in Table 1. Measurements follow the protocol of [3]. Values from "
                           f"the {y - 3} campaign are given in Table 3 for comparison and are not directly comparable "
                           f"with the {y} campaign because the instruments changed."),
            ("3. Results", f"Table 2 reports the {f} for each station in the {y} campaign. The largest change "
                           f"relative to {y - 3} was observed at station {cx.choice(stations)}."),
            ("4. Discussion", "The spread between stations exceeds the measurement uncertainty, which suggests "
                              "that site conditions dominate. Longer records are needed to confirm the trend."),
            ("References", f"[1] {cx.choice(N.SURNAMES)} et al. ({y - 6}). [2] {cx.choice(N.SURNAMES)} and "
                           f"{cx.choice(N.SURNAMES)} ({y - 4}). [3] {cx.choice(N.SURNAMES)} et al. ({y - 3})."),
        ], "tables": [
            {"caption": "Table 1: Station metadata", "header": ["Station", "Elevation (m)", "Established", "Records"],
             "rows": meta, "before_target": True},
            {"caption": f"Table 3: {f.capitalize()} in the {y - 3} campaign", "header": ["", f"{f} ({u})"],
             "rows": prev, "before_target": False},
        ]}

    def sibling_specs(self, cx: random.Random) -> list[dict]:
        """Look-alike works: same author on the same topic in another year, and another group in the same year."""
        w = self.work
        other = [m for m in N.METHODS if not w["title"].startswith(m)]
        a2 = [n for n in N.SURNAMES if n != w["first_author"]]
        return [
            {"title": f"{cx.choice(other)} {w['topic'].title()}", "first_author": w["first_author"],
             "year": w["year"] - 1 if w["year"] > 2023 else w["year"] + 1, "journal": w["journal"]},
            {"title": f"{cx.choice(other)} {w['topic'].title()}", "first_author": cx.choice(a2),
             "year": w["year"], "journal": w["journal"]},
        ]


class NewsKit(Kit):
    domain = "news"
    decimals = 0

    def build(self) -> None:
        rng = self.rng
        outlet = rng.choice(N.NEWS_OUTLETS)
        subject = rng.choice(N.NEWS_SUBJECTS)
        fig = rng.choice(N.NEWS_FIGURES)
        year = rng.choice([2024, 2025])
        date = f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        districts = rng.sample(N.PLACES, 5)
        v = draw(rng, fig[0])
        self.work = {
            "work_id": f"work-{self.gid}", "title": f"Report: {subject.capitalize()} findings released",
            "publisher": outlet, "date": date, "subject": subject,
            "entity": f"{districts[0]} district", "field_label": fig[0], "field_key": fig[0].replace(" ", "_"),
            "unit": fig[1], "value": _fmt(v, 0), "expression": "published article",
            "version_label": f"{outlet}, published {date}",
            "distractor_rows": [[f"{d} district", _fmt(draw(rng, fig[0]), 0)] for d in districts[1:]],
            "target_row_index": rng.randint(0, 4),
            "table_caption": f"Figures by district ({fig[0]})",
            "paragraphs": [f"{outlet} obtained the final report on {subject}.",
                           f"The report lists {fig[0]} for five districts."],
            "file_name": f"{N.slug(subject)}-figures.csv",
        }

    def goal_text(self, version_clause: str = "") -> str:
        w = self.work
        when = w["date"]
        if self.indirect:
            y, m = w["date"][:4], int(w["date"][5:7])
            when = f"{MONTHS[m - 1]} {y}"
        ref = f"{w['publisher']}'s {when} report on {w['subject']}{version_clause}"
        if self.task_type == "AA":
            return f"Download the data table (CSV) attached to {ref}, and submit the file."
        if self.mode == "compare":
            return (f"According to {ref}, what is the difference between the {w['field_label']} figure for "
                    f"{w['entity']} and the figure for {w['entity2']} ({w['entity']} minus {w['entity2']})? "
                    f"Cite the source you used.")
        return (f"According to {ref}, how many {w['field_label']} were recorded for {w['entity']}? "
                f"Cite the source you used.")

    def page_extras(self, cx: random.Random) -> dict:
        w = self.work
        y = int(w["date"][:4])
        districts = [w["entity"]] + [r[0] for r in w["distractor_rows"]]
        return {"sections": [
            ("", f"{w['publisher']} has obtained the final report on {w['subject']}, which officials had delayed "
                 f"twice since the spring."),
            ("What the report found", f"The report breaks down {w['field_label']} by district. Officials cautioned "
                                      f"that figures for two districts are provisional."),
            ("Background", f"Last year's report counted {self.far(cx)} {w['unit']} in {cx.choice(districts)}; the "
                           f"methodology has since changed, so the numbers are not directly comparable."),
            ("Reaction", f"\u201cWe expect the numbers to be revised as more inspections are completed,\u201d a "
                         f"spokesperson for the {cx.choice(N.PLACES)} council said."),
        ], "tables": [
            {"caption": f"Figures by district ({y - 1} report)", "header": ["", f"{w['field_label']} ({w['unit']})"],
             "rows": [[d, self.far(cx)] for d in districts], "before_target": False},
        ]}

    def sibling_specs(self, cx: random.Random) -> list[dict]:
        w = self.work
        y, m = int(w["date"][:4]), int(w["date"][5:7])
        m2 = m + 2 if m <= 10 else m - 3
        return [
            {"title": f"Follow-up: {w['subject'].capitalize()} figures revised", "publisher": w["publisher"],
             "date": f"{y}-{m2:02d}-{cx.randint(1, 28):02d}"},
            {"title": f"{w['subject'].capitalize()}: what we know", "publisher": cx.choice(
                [o for o in N.NEWS_OUTLETS if o != w["publisher"]]), "date": w["date"]},
        ]


class EcommerceKit(Kit):
    domain = "ecommerce"
    decimals = 0

    def build(self) -> None:
        rng = self.rng
        brand = rng.choice(N.BRANDS)
        prod = rng.choice(N.PRODUCTS)
        model = f"{brand} {rng.choice(['X', 'Pro', 'Lite', 'Max', 'S'])}{rng.randint(2, 9)}0"
        shop = rng.choice(N.SHOPS)
        v = draw(rng, prod[1])
        dec = decimals_of(prod[1], 0)
        self.decimals = dec
        self.work = {
            "work_id": f"work-{self.gid}", "title": f"{model} {prod[0]}", "publisher": f"{shop}.example",
            "brand": brand, "model": model, "product": prod[0], "shop": shop,
            "date": "2025-06-01", "entity": model, "field_label": prod[1], "field_key": prod[1].replace(" ", "_"),
            "unit": prod[2], "value": _fmt(v, dec), "expression": "product listing",
            "version_label": f"{model} listing", "gtin": N.gtin(rng), "price": f"{rng.uniform(19, 399):.2f}",
            "distractor_rows": [["weight", f"{rng.randint(80, 2400)} g"], ["warranty", f"{rng.randint(1, 3)} years"],
                                ["colour", rng.choice(["graphite", "sand", "teal"])], ["model year", "2025"]],
            "target_row_index": rng.randint(0, 4),
            "table_caption": "Specifications",
            "paragraphs": [f"The {model} is a {prod[0]} by {brand}.", "Ships in 2–4 business days."],
            "file_name": f"{N.slug(model)}-spec.csv",
        }

    def goal_text(self, version_clause: str = "") -> str:
        w = self.work
        if self.task_type == "TX":
            return (f"Buy one {w['model']} {w['product']} with GTIN {w['gtin']}. The user found it at "
                    f"{w['shop']}.example; any authorized shop selling exactly this GTIN is acceptable. "
                    f"Report the order you placed.")
        return (f"What is the {w['field_label']} of the {w['model']} {w['product']} (GTIN {w['gtin']}) according "
                f"to its listing at {w['shop']}.example{version_clause}? Cite the source you used.")

    def page_extras(self, cx: random.Random) -> dict:
        w = self.work
        sibs = [f"{w['model'].split()[0]} {s}{cx.randint(2, 9)}0" for s in ("X", "Pro", "Lite", "Max")]
        sibs = [x for x in sibs if x != w["model"]][:3]
        return {"sections": [
            ("Description", f"The {w['model']} {w['product']} is designed for everyday use. See the specification "
                            f"table for details; values for similar models are listed for comparison."),
            ("Customer questions", f"Q: Is the {w['field_label']} the same as on the older {sibs[0]}? A: No, see the "
                                   f"comparison table; the older model is rated {self.far(cx)} {w['unit']}."),
            ("Reviews", f"\u2605\u2605\u2605\u2605\u2606 \u201cDoes what it says.\u201d \u2014 verified buyer. "
                        f"\u2605\u2605\u2605\u2606\u2606 \u201cGood, but the {sibs[1]} felt sturdier.\u201d"),
        ], "tables": [
            {"caption": "Compare similar models", "header": ["Model", f"{w['field_label']} ({w['unit']})"],
             "rows": [[x, self.far(cx)] for x in sibs], "before_target": False},
        ]}


class OpenDataKit(Kit):
    domain = "opendata"
    decimals = 2

    def build(self) -> None:
        rng = self.rng
        agency = rng.choice(N.AGENCIES)
        ds = rng.choice(N.DATASETS)
        release = rng.choice(["release 3", "release 4", "2025 edition", "version 2.1"])
        places = rng.sample(N.PLACES, 5)
        v = draw(rng, ds[1])
        self.decimals = dec = decimals_of(ds[1], 2)
        self.work = {
            "work_id": f"work-{self.gid}", "title": ds[0].title(), "publisher": agency, "agency": agency,
            "release": release, "date": f"2025-{rng.randint(1, 9):02d}-01",
            "entity": places[0], "field_label": ds[1], "field_key": ds[1].replace(" ", "_"), "unit": ds[2],
            "value": _fmt(v, dec), "expression": release, "version_label": f"{ds[0].title()}, {release}",
            "distractor_rows": [[p, _fmt(draw(rng, ds[1]), dec)] for p in places[1:]],
            "target_row_index": rng.randint(0, 4),
            "table_caption": f"{ds[1].capitalize()} by site",
            "paragraphs": [f"Published by the {agency}.", f"This page describes {release} of the dataset."],
            "file_name": f"{N.slug(ds[0])}-{N.slug(release)}.csv",
        }

    def goal_text(self, version_clause: str = "") -> str:
        w = self.work
        ref = f"the {w['agency']}'s \"{w['title']}\" ({w['release']})"
        if self.task_type == "AA":
            return f"Download the CSV file of {ref}{version_clause}, and submit the file."
        if self.mode == "compare":
            return (f"From {ref}{version_clause}, what is the difference between the {w['field_label']} {w['entity']} "
                    f"and the {w['field_label']} {w['entity2']} ({w['entity']} minus {w['entity2']})? Give the "
                    f"difference with its unit and cite the source you used.")
        return f"From {ref}{version_clause}, report the {w['field_label']} {w['entity']}. Cite the source you used."

    def page_extras(self, cx: random.Random) -> dict:
        w = self.work
        places = [w["entity"]] + [r[0] for r in w["distractor_rows"]]
        return {"sections": [
            ("Description", f"{w['title']} is published by the {w['agency']} under an open licence. Values are "
                            f"reported per site and are updated with each release."),
            ("Methodology", "Samples are collected quarterly and aggregated to annual figures. Sites with fewer than "
                            "three valid samples are flagged as provisional."),
            ("Release notes", f"This release revises the value for {cx.choice(places)}; the previous release reported "
                              f"{self.far(cx)} {w['unit']}. Older releases remain available on request."),
            ("How to cite", f"{w['agency']} ({w['date'][:4]}). {w['title']}, {w['release']}."),
        ], "tables": [
            {"caption": "Values in the previous release", "header": ["Site", f"{w['field_label']} ({w['unit']})"],
             "rows": [[pl, self.far(cx)] for pl in places], "before_target": False},
        ]}


class DocsKit(Kit):
    domain = "docs"
    decimals = 0

    def build(self) -> None:
        rng = self.rng
        lib = rng.choice(N.LIBRARIES)
        p = rng.choice(N.PARAMS)
        version = f"v{rng.randint(2, 5)}.{rng.randint(0, 9)}"
        v = scale_int(rng.randint(3, 900), p[0])
        others = [q for q in N.PARAMS if q != p]
        self.work = {
            "work_id": f"work-{self.gid}", "title": f"{lib} {version} configuration reference",
            "publisher": f"{lib} project", "lib": lib, "version": version, "date": "2025-04-10",
            "entity": p[2], "field_label": p[0], "field_key": p[2], "unit": p[1],
            "value": str(v), "expression": version, "version_label": f"{lib} documentation {version}",
            "distractor_rows": [[q[2], str(scale_int(rng.randint(3, 900), q[0]))] for q in rng.sample(others, 4)],
            "target_row_index": rng.randint(0, 4),
            "table_caption": "Configuration options and defaults",
            "paragraphs": [f"This page documents configuration options for {lib} {version}.",
                           "Defaults apply when an option is not set."],
            "file_name": f"{lib}-{version}-config-schema.json",
        }

    def goal_text(self, version_clause: str = "") -> str:
        w = self.work
        if self.task_type == "AA":
            return (f"Download the official configuration schema file of {w['lib']} {w['version']}{version_clause}, "
                    f"and submit the file.")
        return (f"What is the default value of the `{w['field_key']}` option ({w['field_label']}) in {w['lib']} "
                f"{w['version']}{version_clause}, according to the official documentation? Cite the source you used.")

    def page_extras(self, cx: random.Random) -> dict:
        w = self.work
        keys = [r[0] for r in w["distractor_rows"]]
        major = int(w["version"][1])
        return {"sections": [
            ("Overview", f"Options can be set in the configuration file, as keyword arguments, or through "
                         f"environment variables prefixed with {w['lib'].upper().replace('-', '_')}_."),
            ("Changelog", f"v{major}.0: the default of `{cx.choice(keys)}` changed from {self.far(cx)} to the value "
                          f"shown below. v{major - 1}.4: `{cx.choice(keys)}` deprecated in favour of `{w['field_key']}`."),
            ("Notes", f"Defaults differ between minor versions; check the documentation for the version you run. "
                      f"The example configuration in the tutorial uses {self.far(cx)} for `{w['field_key']}`."),
        ], "tables": [
            {"caption": "Deprecated options", "header": ["Option", "Removed in", "Use instead"],
             "rows": [[f"legacy_{k}", f"v{major}.0", k] for k in keys[:2]], "before_target": False},
        ]}


class EncyclopediaKit(Kit):
    domain = "encyclopedia"
    decimals = 0

    def build(self) -> None:
        rng = self.rng
        subj = rng.choice(N.WIKI_SUBJECTS)
        rev_date = f"2025-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}"
        v = draw(rng, subj[1])
        self.work = {
            "work_id": f"work-{self.gid}", "title": subj[0], "publisher": "Openpedia", "date": rev_date,
            "entity": subj[0], "field_label": subj[1], "field_key": subj[1].replace(" ", "_"), "unit": subj[2],
            "value": _fmt(v, 0), "expression": f"revision of {rev_date}",
            "version_label": f"Openpedia revision of {rev_date}",
            "distractor_rows": [["first recorded", str(rng.randint(1700, 1990))], ["region", rng.choice(N.PLACES)],
                                ["coordinates", f"{rng.uniform(40, 70):.2f}N {rng.uniform(5, 30):.2f}E"],
                                ["status", "protected"]],
            "target_row_index": rng.randint(0, 4),
            "table_caption": "Key facts",
            "paragraphs": [f"{subj[0]} is a landmark in the fictional region of {rng.choice(N.PLACES)}.",
                           "This article is maintained by volunteer editors."],
            "file_name": f"{N.slug(subj[0])}-facts.csv",
        }

    def goal_text(self, version_clause: str = "") -> str:
        w = self.work
        if self.task_type == "AA":
            return (f"Download the facts table (CSV) of the Openpedia article on {w['title']} "
                    f"(revision of {w['date']}){version_clause}, and submit the file.")
        return (f"According to the Openpedia article on {w['title']} (revision of {w['date']}){version_clause}, "
                f"what is its {w['field_label']}? Cite the source you used.")

    def page_extras(self, cx: random.Random) -> dict:
        w = self.work
        y1, y2 = cx.randint(1890, 1950), cx.randint(1955, 2005)
        return {"sections": [
            ("History", f"A survey in {y1} reported a {w['field_label']} of {self.far(cx)} {w['unit']}. Later "
                        f"measurements revised this figure, and the value in the infobox reflects the current "
                        f"consensus."),
            ("Geography", f"{w['title']} lies in the fictional region of {cx.choice(N.PLACES)}, about "
                          f"{cx.randint(12, 140)} km from the nearest town."),
            ("See also", f"List of landmarks in {cx.choice(N.PLACES)}; Surveys of the {cx.choice(N.PLACES)} region."),
        ], "tables": [
            {"caption": "Measurements over time", "header": ["Year", f"{w['field_label']} ({w['unit']})", "Source"],
             "rows": [[str(y1), self.far(cx), "regional survey"], [str(y2), self.far(cx), "national survey"]],
             "before_target": False},
        ]}


KITS = {"academic": AcademicKit, "news": NewsKit, "ecommerce": EcommerceKit, "opendata": OpenDataKit,
        "docs": DocsKit, "encyclopedia": EncyclopediaKit}


def make_kit(domain: str, rng: random.Random, goal_id: str, task_type: str, salt: int = 0) -> Kit:
    return KITS[domain](rng, goal_id, task_type, salt)
