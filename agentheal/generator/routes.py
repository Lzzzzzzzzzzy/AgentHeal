"""Discovery routes (dataset v0.3).

In v0.2 every acceptable alternative was indexed by the general search engine under the requested title, so a
single search exposed it and recovery cost one extra action. In v0.3 alternatives are reached the way they are
reached on the web: through the service that holds them, in several dependent steps. A route is a chain of
*hub* pages (role "hub": navigation pages that carry no answer) that ends at the alternative:

  scholar    scholarly index search -> work record -> "All versions" list (no version labels) -> copy / version
  registry   open-data registry search -> dataset record (distributions) [-> release history] -> distribution
  pkgindex   package index search -> project page -> documentation for all versions -> docs copy / old version
  wire       publisher home (syndication note) -> news-wire home -> wire search -> syndicated story
  updates    publisher home -> corrections and editions page -> earlier edition
  history    encyclopedia site search -> revision history -> older revisions -> permanent revision
  brand      manufacturer site (found by general search) -> where to buy -> retailer site search -> listing
  archive    web archive: captures by year -> captures in one year -> capture
  moved      publisher home (reorganisation notice) -> archive section -> year listing -> moved page
  api        /developers -> API reference -> API search -> record
  intl       publisher home -> editions -> international edition home -> edition search -> article
  status     publisher home -> status page (mirror notice) -> mirror search -> article
  migration  retired-API response -> changelog -> migration guide -> legacy-ID lookup -> v2 record
  catalogue  removed download -> catalogue entry -> available formats -> alternative format / figure
  shopsearch the shop's own search (earlier model-year listing)

Every service is built in every world of a goal, so the navigation structure does not reveal the world: in an
unrecoverable world the same pages exist but list nothing acceptable. Each alternative stores its route as
`chain`, the list of URLs a compliant agent requests before it reaches the alternative.
"""
from __future__ import annotations

import random
import urllib.parse

from ..config import ARCHIVE_HOST
from ..util import short_hash
from . import names as N

SCHOLAR, REGISTRY, PKGINDEX, WIRE = "scholar.example", "registry.example", "pkgindex.example", "wirewire.example"
SERVICES = [
    (f"http://{ARCHIVE_HOST}/", "Web archive", "Captures of web pages over time: http://archive.example/web/*/<url>"),
    (f"http://{SCHOLAR}/", "Scholarly index", "Search scholarly works; each record lists all known versions."),
    (f"http://{REGISTRY}/", "Open-data registry", "Search public datasets and their distributions and releases."),
    (f"http://{PKGINDEX}/", "Package index", "Software projects, their releases and documentation."),
]

# alternative route by `route` field (faithful copies)
ROUTE_SERVICE = {"repository_vor": "scholar", "other_item_same_version": "scholar", "official_syndication": "registry",
                 "wire_copy": "wire", "permanent_revision": "history", "other_authorized_shop": "brand",
                 "moved": "moved", "official_api": "api", "international_edition": "intl", "api_v2": "migration",
                 "render_only": "catalogue", "alternative_format": "catalogue"}
DOMAIN_SERVICE = {"academic": "scholar", "news": "wire", "opendata": "registry", "docs": "pkgindex",
                  "encyclopedia": "history", "ecommerce": "brand"}


def authors_of(w: dict) -> str:
    return ", ".join(w.get("authors", [])) or w["publisher"]


def before(entries: list[tuple[str, str]], url: str) -> list[str]:
    """Entries of a list page that precede `url`: an agent that cannot tell them apart opens them first."""
    out = []
    for u, _ in entries:
        if u == url:
            return out
        out.append(u)
    return out


def q(s: str) -> str:
    return urllib.parse.quote_plus(s)


def service_of(t: dict, domain: str) -> str:
    if t["host"] == ARCHIVE_HOST:
        return "archive"
    if t["role"] == "faithful":
        if t.get("route") == "official_mirror":
            return "status" if t["host"].startswith("mirror.") else "pkgindex"
        return ROUTE_SERVICE.get(t.get("route"), DOMAIN_SERVICE[domain])
    vt = t.get("variant_type")
    if vt == "V-T":
        return "archive"
    if domain == "academic":
        return "scholar"
    if vt == "V-E" or domain == "docs":
        return "pkgindex"
    return {"opendata": "registry", "news": "updates", "encyclopedia": "history", "ecommerce": "shopsearch"}[domain]


class Routes:
    """Builds the hub pages of one goal in one world and attaches a `chain` to every alternative."""

    def __init__(self, b, world: str, resources: list[dict]):
        self.b, self.world, self.res = b, world, resources
        self.kit, self.w = b.kit, b.kit.work
        self.domain = self.kit.domain
        self.canon = next(r for r in resources if r["role"] == "canonical")
        self.canon_url = self.canon["url"]
        self.host = self.canon["host"]
        self.hubs: list[dict] = []
        self.home_links: list[tuple[str, str]] = []
        self.home_paras: list[str] = []
        self.rng = random.Random(f"{b.goal_id}-routes-{world}")
        self.reachable_home = b.rule_params[0] != "nxdomain"

    # -- helpers ------------------------------------------------------------------------------------
    def hub(self, tag: str, host: str, path: str, title: str, paras: list[str], links: list[tuple[str, str]],
            *, site_search: bool = True, general: bool = False, search_form: bool = False, **extra) -> dict:
        r = {"id": self.b.rid(f"hub-{tag}"), "role": "hub", "host": host, "path": path, "url": f"http://{host}{path}",
             "kind": "page", "site_type": "hub", "title": title, "publisher": host, "date": "", "version_label": "",
             "expression": "", "work_id": "", "body": {"paragraphs": list(paras)},
             "links": [(self.abs(host, u), t) for u, t in links], "cue": None, "indexed": general,
             "rank_boost": 0.0, "access": {"state": "ok"}, "site_search": site_search, "search_form": search_form}
        r.update(extra)
        self.hubs.append(r)
        return r

    @staticmethod
    def abs(host: str, u: str) -> str:
        return u if u.startswith("http") else f"http://{host}{u}"

    def home(self) -> str:
        return f"http://{self.host}/"

    def query(self) -> str:
        return self.w["title"]

    # -- services -----------------------------------------------------------------------------------
    def scholar(self, targets: list[dict]) -> None:
        w, gid = self.w, self.b.gid
        work = f"/work/{gid}"
        entries = [(self.canon_url, f"{self.canon['title']} - {self.canon['host']}")]
        alts = []
        for t in targets:
            if t.get("variant_type") == "V-P":
                t["title"] = f"{w['title']}: preliminary results"
            alts.append((t["url"], f"{t['title']} - {t['host']}"))
        # records that hold the metadata but no full text, as in real "All versions" lists
        fillers = [("researchnet.example", "Full text not available here. Request it from the authors."),
                   ("inst-repository.example", "Metadata only: the full text is under embargo.")]
        for k, (fh, msg) in enumerate(self.rng.sample(fillers, self.rng.choice([1, 2]))):
            f = self.hub(f"scholar-meta{k}", fh, f"/record/{gid}", w["title"],
                         [f"{authors_of(w)}.", f"{w.get('journal', w['publisher'])}, {w.get('year', '')}.", msg], [],
                         site_search=False)
            alts.append((f["url"], f"{w['title']} - {fh}"))
        self.rng.shuffle(alts)
        entries += alts
        authors = ", ".join(w.get("authors", [])) or w["publisher"]
        self.hub("scholar-work", SCHOLAR, work, w["title"],
                 [f"{authors}.", f"{w.get('journal', w['publisher'])}, {w.get('year', '')}.",
                  f"Topic: {w.get('topic', '')}.", f"DOI: 10.5072/{gid}"],
                 [(self.canon_url, f"[HTML] {self.canon['host']}"), (work + "/versions", f"All {len(entries)} versions")])
        self.hub("scholar-versions", SCHOLAR, work + "/versions", f"All versions of: {w['title']}",
                 ["Sources holding this work, as found by the index. Version information is given on each source page."],
                 entries, site_search=False)
        start = f"http://{SCHOLAR}/search?q={q(self.query())}"
        vers = f"http://{SCHOLAR}{work}/versions"
        for t in targets:
            t["chain"] = [start, f"http://{SCHOLAR}{work}", vers]
            t["inspect"] = {vers: before(alts, t["url"])}

    def registry(self, targets: list[dict]) -> None:
        w, gid = self.w, self.b.gid
        rec, rel = f"/dataset/{gid}", f"/dataset/{gid}/releases"
        faith = [t for t in targets if t["role"] == "faithful"]
        var = [t for t in targets if t["role"] == "variant"]
        links = [(self.canon_url, f"{w['publisher']} portal ({w.get('release', '')})")]
        dists = []
        for k, t in enumerate(faith):     # a distribution page (format, licence, access URL), as in CKAN
            self.hub(f"registry-dist{k}", REGISTRY, f"{rec}/resource/{k}", f"{w['title']}: distribution",
                     [f"Hosted by {t['host']}.", "Format: HTML table; licence: open."], [(t["url"], "Access URL")],
                     site_search=False)
            dists.append((f"http://{REGISTRY}{rec}/resource/{k}", t))
        # distributions that no longer work (a discontinued bulk download, an API that requires an agreement)
        for k, msg in enumerate(self.rng.sample(["Bulk download (FTP). This distribution was discontinued.",
                                                 "Data API. Access requires a data-sharing agreement."],
                                                self.rng.choice([1, 2]))):
            self.hub(f"registry-dead{k}", REGISTRY, f"{rec}/resource/x{k}", f"{w['title']}: distribution",
                     [msg], [], site_search=False)
            dists.append((f"http://{REGISTRY}{rec}/resource/x{k}", None))
        self.rng.shuffle(dists)
        links += [(u, f"Distribution {i + 1}") for i, (u, _) in enumerate(dists)]
        links.append((rel, "Release history"))
        self.hub("registry-record", REGISTRY, rec, f"{w['title']} ({w['publisher']})",
                 [f"Publisher: {w['publisher']}.", f"Current release: {w.get('release', '')}.",
                  "Distributions are listed below with the organisation that hosts them."], links)
        rl = [(self.canon_url, f"{w.get('release', '')} (current)")]
        for k, v in enumerate(var):
            self.hub(f"registry-rel{k}", REGISTRY, f"{rel}/{k}", v["version_label"],
                     [f"Release notes: {v['version_label']}.", "Superseded by the current release."],
                     [(v["url"], "Access URL")], site_search=False)
            rl.append((f"{rel}/{k}", v["version_label"]))
        paras = ["Releases of this dataset."] + ([] if var else ["Earlier releases are available from the publisher on request."])
        self.hub("registry-releases", REGISTRY, rel, f"Release history: {w['title']}", paras, rl, site_search=False)
        start = f"http://{REGISTRY}/search?q={q(self.query())}"
        recu = f"http://{REGISTRY}{rec}"
        for k, t in enumerate(faith):
            mine = f"http://{REGISTRY}{rec}/resource/{k}"
            t["chain"] = [start, recu, mine]
            t["inspect"] = {recu: before([(u, "") for u, _ in dists], mine)}
        for k, t in enumerate(var):
            t["chain"] = [start, f"http://{REGISTRY}{rec}", f"http://{REGISTRY}{rel}", f"http://{REGISTRY}{rel}/{k}"]

    def pkgindex(self, targets: list[dict]) -> None:
        w = self.w
        lib = w.get("lib") or N.slug(w["title"])
        proj, docs = f"/project/{lib}", f"/project/{lib}/docs"
        self.hub("pkg-project", PKGINDEX, proj, lib,
                 [f"{lib} - {w['publisher']}.", "Releases, source code and documentation links."],
                 [(self.home(), "Homepage"), (docs, "Documentation (all versions)")])
        entries = [(self.canon_url, f"{w.get('version', '')} - {self.canon['host']}")]
        alts = []
        for k, t in enumerate(targets):   # a version landing page on the docs host (as on Read the Docs)
            ver = t.get("expression") or w.get("version", "")
            self.hub(f"pkg-ver{k}", t["host"], f"/{ver}/", f"{lib} {ver} documentation",
                     [f"Documentation for {lib} {ver}."], [(t["url"], "Configuration reference")], site_search=False)
            alts.append((f"http://{t['host']}/{ver}/", f"{ver} - {t['host']}"))
            t["_landing"] = f"http://{t['host']}/{ver}/"
        self.rng.shuffle(alts)
        self.hub("pkg-docs", PKGINDEX, docs, f"{lib} documentation", ["Hosted documentation by version."],
                 entries + alts, site_search=False)
        start = f"http://{PKGINDEX}/search?q={q(lib)}"
        for t in targets:
            t["chain"] = [start, f"http://{PKGINDEX}{proj}", f"http://{PKGINDEX}{docs}", t.pop("_landing")]
            if t["host"] == self.host:
                t["site_search"] = False

    def wire(self, targets: list[dict]) -> None:
        self.home_paras.append(f"Our reporting is distributed to partner newsrooms by the WireWire news wire.")
        self.home_links.append((f"http://{WIRE}/", "WireWire (syndication partner)"))
        self.hub("wire-home", WIRE, "/", "WireWire",
                 ["Stories from partner newsrooms, distributed verbatim.", "Use the search box to find a story."], [],
                 search_form=True)
        # other wire items on the same report (a briefing, a correction note) that carry no figures
        fill = [("briefing", f"Briefing: {self.w['title']}", "A short summary of the report. Figures are in the full story."),
                ("note", f"Editor's note: {self.w['title']}", "This story was updated after first publication.")]
        for tag, title, text in self.rng.sample(fill, self.rng.choice([1, 2])):
            self.hub(f"wire-{tag}", WIRE, f"/{tag}/{self.b.gid}", title, [text, f"Source: {self.w['publisher']}."], [])
        search = f"http://{WIRE}/search?q={q(self.query())}"
        from ..gym.dynamic import site_search
        order = [h["url"] for h in site_search({"resources": self.res + self.hubs}, WIRE, self.query())]
        for t in targets:
            t["chain"] = [self.home(), f"http://{WIRE}/", search]
            t["inspect"] = {search: before([(u, "") for u in order], t["url"])}

    def updates(self, targets: list[dict]) -> None:
        path = f"/site/updates/{self.b.gid}"
        self.home_links.append((path, "Corrections and earlier editions"))
        links = []
        for k, t in enumerate(targets):   # a correction notice that links the superseded edition
            self.hub(f"notice{k}", self.host, f"{path}/{k}", f"Update: {t['title']}",
                     ["This report was updated after publication; figures were revised.",
                      f"The {t.get('expression', 'earlier edition')} remains available for reference."],
                     [(t["url"], t.get("expression", "Earlier edition"))], site_search=False)
            links.append((f"{path}/{k}", f"Update notice: {t['title']}"))
        paras = ["Corrections and earlier editions of our reports."] + \
            ([] if targets else ["No earlier editions of recent reports are kept online."])
        self.hub("updates", self.host, path, "Corrections and updates", paras, links, site_search=False)
        for k, t in enumerate(targets):
            t["chain"] = [self.home(), f"http://{self.host}{path}", f"http://{self.host}{path}/{k}"]
            t["site_search"] = False

    def history(self, targets: list[dict]) -> None:
        w = self.w
        slug = N.slug(w["title"])
        h1, h2, h3 = f"/w/history/{slug}", f"/w/history/{slug}/older", f"/w/history/{slug}/oldest"
        self.hub("history", "openpedia.example", h1, f"Revision history of {w['title']}",
                 ["Recent revisions: copyedits and infobox maintenance by volunteer editors.",
                  "Older revisions are listed on the next page."], [(h2, "Older revisions")])
        self.hub("history-mid", "openpedia.example", h2, f"Revision history of {w['title']} (page 2)",
                 ["Revisions: maintenance edits, reverted vandalism, citation fixes."], [(h3, "Older revisions")],
                 site_search=False)
        h2 = h3
        links = [(t["url"], f"Revision as of {w['date'] if t['role'] == 'faithful' else t.get('expression', '')}")
                 for t in targets]
        paras = ["Older revisions of this article."] + ([] if targets else
                                                       ["Revisions before the current one were suppressed by an administrator."])
        self.hub("history-older", "openpedia.example", h2, f"Older revisions of {w['title']}", paras, links,
                 site_search=False)
        start = f"http://openpedia.example/search?q={q(w['title'])}"
        for t in targets:
            t["chain"] = [start, f"http://openpedia.example{h1}", f"http://openpedia.example/w/history/{slug}/older", f"http://openpedia.example{h2}"]
            t["site_search"] = False

    def brand(self, targets: list[dict]) -> None:
        w = self.w
        bhost = f"{N.slug(w['brand'])}.example"
        self.hub("brand-home", bhost, "/", f"{w['brand']} official site",
                 [f"{w['brand']} designs {w['product']}s and other products.", f"Current models include the {w['model']}."],
                 [("/where-to-buy", "Where to buy")], general=True, site_search=False)
        shops = [s for s in N.SHOPS if s != w["shop"] and not any(t["host"] == f"{s}.example" for t in targets)]
        others = self.rng.sample(shops, 2)
        retailers = [f"http://{w['shop']}.example/"] + [f"http://{t['host']}/" for t in targets] + \
                    [f"http://{s}.example/" for s in others]
        self.rng.shuffle(retailers)
        self.hub("brand-wtb", bhost, "/where-to-buy", f"Where to buy {w['brand']} products",
                 ["Authorized retailers. Stock varies; search the retailer's site for the GTIN of your model."],
                 [(u, urllib.parse.urlsplit(u).hostname) for u in retailers], site_search=False)
        wtb = f"http://{bhost}/where-to-buy"
        for t in targets:
            t["chain"] = [f"http://{bhost}/", wtb, f"http://{t['host']}/", f"http://{t['host']}/search?q={w['gtin']}"]
            seen = []      # retailers listed before the one that stocks the item: open and search each
            for u in retailers:
                if u == f"http://{t['host']}/":
                    break
                if u != f"http://{w['shop']}.example/":
                    seen += [u, f"{u}search?q={w['gtin']}"]
            t["inspect"] = {wtb: seen}

    def shopsearch(self, targets: list[dict]) -> None:
        for t in targets:
            t["chain"] = [f"http://{self.host}/search?q={q(self.w['model'])}"]

    def archive(self, targets: list[dict], duds: bool) -> None:
        caps = list(targets)
        if duds:   # captures of the page after it broke: an error page and a redirect to the home page
            for k, (ts, msg) in enumerate([("20260115093000", "404 Not Found"), ("20251103141500", "Home page")]):
                self.hub(f"capture-{k}", ARCHIVE_HOST, f"/web/{ts}/{self.canon_url}", f"{self.canon['host']}: {msg}",
                         [f"{msg}." if k == 0 else f"Welcome to {self.canon['host']}."], [], site_search=False,
                         memento_datetime=ts, original=self.canon_url)
        for i, t in enumerate(caps):     # years -> days of one year -> captures of one day (Wayback calendar)
            ts = t["memento_datetime"]
            # failed captures on the same day (a cookie wall, a truncated page), as archives often hold
            fails = [("063000", "Capture of a cookie consent screen; the page content was not archived."),
                     ("183000", "Truncated capture: only the page header was archived.")]
            for k, (hms, msg) in enumerate(self.rng.sample(fails, self.rng.choice([1, 2]))):
                self.hub(f"capture-{i}-{k}", ARCHIVE_HOST, f"/web/{ts[:8]}{hms}/{self.canon_url}",
                         f"{self.canon['host']}: capture", [msg], [], site_search=False,
                         memento_datetime=ts[:8] + hms, original=self.canon_url)
            day = f"http://{ARCHIVE_HOST}/web/{ts[:8]}*/{self.canon_url}"
            t["chain"] = [f"http://{ARCHIVE_HOST}/web/*/{self.canon_url}",
                          f"http://{ARCHIVE_HOST}/web/{ts[:4]}*/{self.canon_url}", day]
            same_day = sorted((r["memento_datetime"], r["url"]) for r in self.hubs + caps
                              if r.get("original") == self.canon_url and r["memento_datetime"].startswith(ts[:8]))
            t["inspect"] = {day: before([(u, "") for _, u in same_day], t["url"])}

    def moved(self, targets: list[dict]) -> None:
        if not self.reachable_home:
            return
        idx = "/site/archive"
        years = sorted({str(self.w.get("year") or self.w["date"][:4]), "2023", "2024", "2025"})
        self.home_paras.append("We reorganised our website: older pages are now in the archive section.")
        self.home_links.append((idx, "Archive"))
        self.hub("moved-index", self.host, idx, "Archive", ["Older pages by year."],
                 [(f"{idx}/{y}", y) for y in years], site_search=False)
        y0 = str(self.w.get("year") or self.w["date"][:4])
        for y in years:
            listed = [(t["url"], t["title"]) for t in targets] if y == y0 else []
            self.hub(f"moved-{y}", self.host, f"{idx}/{y}", f"Archive: {y}",
                     ["Pages from this year."] + ([] if listed else ["No pages from this section are archived for this year."]),
                     listed, site_search=False)
        for t in targets:
            t["chain"] = [self.home(), f"http://{self.host}{idx}", f"http://{self.host}{idx}/{y0}"]
            t["in_sitemap"] = False
            t["site_search"] = False

    def api(self, targets: list[dict]) -> None:
        ahost = "api." + self.host
        self.hub("dev", self.host, "/developers", "Developers",
                 ["Automated clients must use our API rather than the website.",
                  "See the API reference for endpoints and terms of use."], [("/developers/reference", "API reference")])
        if targets:
            paras = [f"Search records: GET http://{ahost}/v1/search?q=<title words>",
                     f"Fetch a record: GET http://{ahost}/v1/records/<id>", "No key is required for read access."]
        else:
            paras = ["API access is limited to approved partners. Contact us to apply."]
        self.hub("dev-ref", self.host, "/developers/reference", "API reference", paras, [], site_search=False)
        for t in targets:   # the search returns record ids; a record lists its data
            rid = t["path"].split("/")[3]
            meta = self.hub("api-record", ahost, f"/v1/records/{rid}", f"Record {rid}",
                            [f"Record {rid}: {self.w['title']}.", f"Publisher: {self.w['publisher']}."],
                            [(t["path"], "data")], site_search=False)
            t["chain"] = [f"http://{self.host}/developers", f"http://{self.host}/developers/reference",
                          f"http://{ahost}/v1/search?q={q(self.query())}", meta["url"]]

    def intl(self, targets: list[dict]) -> None:
        self.home_links.append(("/site/editions", "Editions"))
        ihost = "intl." + self.host
        links = [(f"http://{ihost}/", "International edition")] if targets else []
        self.hub("editions", self.host, "/site/editions", "Editions",
                 [f"Editions of {self.w['publisher']}."] + ([] if targets else ["There are no other editions."]), links,
                 site_search=False)
        if targets:
            self.hub("intl-home", ihost, "/", f"{self.w['publisher']} - international edition",
                     ["International edition. Use the search box to find articles."], [], search_form=True)
        for t in targets:
            t["chain"] = [self.home(), f"http://{self.host}/site/editions", f"http://{ihost}/",
                          f"http://{ihost}/search?q={q(self.query())}"]

    def status(self, targets: list[dict]) -> None:
        shost = "status." + self.host
        self.home_links.append((f"http://{shost}/", "Service status"))
        if targets:
            m = targets[0]["host"]
            paras = ["Planned maintenance is in progress on the main site.",
                     f"An official mirror is available at {m}. Use the mirror's search to find content."]
            links = [(f"http://{m}/", "Official mirror")]
        else:
            paras, links = ["Planned maintenance is in progress. No mirror is available."], []
        self.hub("status", shost, "/", f"{self.host} status", paras, links)
        for t in targets:
            t["chain"] = [self.home(), f"http://{shost}/", f"http://{t['host']}/",
                          f"http://{t['host']}/search?q={q(self.query())}"]

    def migration(self, targets: list[dict]) -> None:
        ahost = self.host if self.host.startswith("api.") else "api." + self.host
        self.hub("changelog", ahost, "/changelog", "API changelog",
                 ["v2.0: records were re-keyed; v1 was retired."], [("/docs/migration", "Migration guide")])
        if targets:
            paras = ["Records were re-keyed in v2.",
                     f"Resolve a v1 identifier with GET http://{ahost}/v2/lookup?legacy_id=<v1 id>, then fetch the "
                     f"returned URL."]
        else:
            paras = ["Legacy v1 records were not migrated to v2 and are no longer available."]
        self.hub("migration", ahost, "/docs/migration", "Migrating from v1 to v2", paras, [], site_search=False)
        for t in targets:
            t["chain"] = [f"http://{ahost}/changelog", f"http://{ahost}/docs/migration",
                          f"http://{ahost}/v2/lookup?legacy_id={self.b.gid}"]

    def catalogue(self, targets: list[dict]) -> None:
        gid = self.b.gid
        cat, fmt = f"/site/catalogue/{gid}", f"/site/catalogue/{gid}/formats"
        self.hub("catalogue", self.host, cat, f"Catalogue entry: {self.w['title']}",
                 ["Formats and access points for this item."], [(fmt, "Available formats")], site_search=False)
        links = []
        for k, t in enumerate(targets):
            name = "Figure (rendered)" if t.get("route") == "render_only" else "Alternative format"
            self.hub(f"format{k}", self.host, f"{fmt}/{k}", f"{name}: {self.w['title']}",
                     [f"{name} of this item.", "Access is free; no download of the original file is offered."],
                     [(t["url"], "Open")], site_search=False)
            links.append((f"{fmt}/{k}", name))
        self.hub("formats", self.host, fmt, "Available formats",
                 ["Formats in which this item is distributed."] +
                 ([] if targets else ["The data of this item are no longer distributed in any format."]), links,
                 site_search=False)
        for k, t in enumerate(targets):
            t["chain"] = [f"http://{self.host}{cat}", f"http://{self.host}{fmt}", f"http://{self.host}{fmt}/{k}"]
            t["site_search"] = False

    # -- assembly ---------------------------------------------------------------------------------------
    def build(self) -> list[dict]:
        fam, dom = self.b.family, self.domain
        alts = [r for r in self.res if r["role"] in {"faithful", "variant"}]
        groups: dict[str, list[dict]] = {}
        for t in alts:
            groups.setdefault(service_of(t, dom), []).append(t)
        # the domain service and the family's own services exist in every world of the goal
        wanted = {DOMAIN_SERVICE[dom]} | set(groups)
        if fam == "F1":
            wanted |= {"archive", "moved"}
        if fam == "F6":
            wanted.add("api")
        if fam == "F7":
            wanted.add("intl")
        if fam == "F8":
            wanted.add("status")
        if fam == "F9":
            wanted.add("migration" if self.canon["kind"] == "api" else "catalogue")
        if dom == "news":
            wanted.add("updates")
        if dom == "ecommerce" and self.kit.task_type == "TX":
            wanted.discard("shopsearch")
        for s in sorted(wanted):
            ts = groups.get(s, [])
            if s == "archive":
                self.archive(ts, duds=(fam == "F1" and self.world != "W0"))
            else:
                getattr(self, s)(ts)
        for t in alts:
            t["indexed"] = False                       # not in the general search engine
            t["rank_boost"] = 0.0
            if not t.get("chain"):
                raise ValueError(f"{t['id']}: no discovery route for {service_of(t, dom)}")
        # a few alternatives are also indexed, far down the ranking (as on the web, where they sometimes surface)
        for t in alts:
            if self.rng.random() < 0.15:
                t["indexed"], t["rank_boost"] = True, -0.6
        if (self.home_links or self.home_paras) and self.reachable_home:
            self.hub("home", self.host, "/", self.w["publisher"] if dom != "docs" else f"{self.w['lib']} documentation",
                     self.home_paras or [f"Welcome to {self.host}."], self.home_links, search_form=True,
                     site_search=False)
        return self.hubs


def attach(builder, world: str, resources: list[dict]) -> list[dict]:
    """Add the hub pages of every discovery service to `resources` and attach a chain to every alternative."""
    return Routes(builder, world, resources).build()


def gid_for_v2(goal_id: str) -> str:
    return short_hash(goal_id, "v2", n=10)
