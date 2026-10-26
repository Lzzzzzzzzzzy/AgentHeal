"""HTML -> readable text with numbered links and forms, for DOM-level agents.

Like an accessibility-tree reader, it skips <script>, <style> and elements with the `hidden`
attribute, but it does NOT know about CSS layout: text covered by an overlay is still returned,
exactly as for a real DOM agent.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

SKIP = {"script", "style", "noscript", "template"}
BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "header", "footer", "section", "article", "form",
         "table", "caption", "ul", "ol", "br", "label"}
VOID = {"br", "img", "input", "meta", "link", "hr"}


class _P(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.out: list[str] = []
        self.skip = 0
        self.stack: list[tuple[str, bool]] = []
        self.links: list[tuple[str, str]] = []
        self.forms: list[dict] = []
        self.cur_link: list | None = None
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        hidden = "hidden" in a or tag in SKIP
        if tag not in VOID:
            self.stack.append((tag, hidden))
        if hidden:
            self.skip += 1
            if tag in VOID:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag == "title":
            self._in_title = True
        if tag in BLOCK:
            self.out.append("\n")
        if tag == "a" and a.get("href"):
            self.cur_link = [urljoin(self.base, a["href"]), ""]
        if tag == "td" or tag == "th":
            self.out.append(" | ")
        if tag == "img":
            self.out.append(f"[image{(': ' + a['alt']) if a.get('alt') else ''}]")
        if tag == "form":
            self.forms.append({"action": urljoin(self.base, a.get("action", "")), "method": a.get("method", "get").upper(),
                               "fields": {}})
        if tag in {"input", "select", "textarea"} and self.forms:
            name = a.get("name")
            if name:
                self.forms[-1]["fields"][name] = a.get("value", "")
                kind = a.get("type", "text")
                if kind != "hidden":
                    self.out.append(f"[{kind} field '{name}']")

    def handle_endtag(self, tag):
        while self.stack:
            t, hidden = self.stack.pop()
            if hidden:
                self.skip -= 1
            if t == tag:
                break
        if self.skip:
            return
        if tag == "title":
            self._in_title = False
        if tag == "a" and self.cur_link is not None:
            self.links.append((self.cur_link[1].strip() or self.cur_link[0], self.cur_link[0]))
            self.out.append(f" [{len(self.links)}]")
            self.cur_link = None
        if tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self._in_title:
            self.title += data
            return
        self.out.append(data)
        if self.cur_link is not None:
            self.cur_link[1] += data


def html_to_text(html: str, base: str, max_chars: int = 6000) -> dict:
    p = _P(base)
    try:
        p.feed(html)
    except Exception:
        pass
    text = "".join(p.out)
    lines = [" ".join(l.split()) for l in text.splitlines()]
    text = "\n".join(l for l in lines if l)
    links = "\n".join(f"[{i + 1}] {t[:80]} -> {u}" for i, (t, u) in enumerate(p.links))
    forms = "\n".join(f"form {i + 1}: {f['method']} {f['action']} fields={list(f['fields'])}" for i, f in enumerate(p.forms))
    body = f"Title: {p.title.strip()}\n{text[:max_chars]}"
    if links:
        body += f"\n\nLinks:\n{links[:3000]}"
    if forms:
        body += f"\n\nForms:\n{forms}"
    return {"title": p.title.strip(), "text": body, "links": p.links, "forms": p.forms}
