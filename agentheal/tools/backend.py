"""Tool backend for the ReAct loop. Every call is appended to <run_dir>/trace.jsonl.

All network traffic goes through the gym proxy and carries the declared user agent plus a stable
client id header, so the HTTP tool, the browser and the shell share one session identity.
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ADMIN_TOKEN, DECLARED_UA, SEARCH_HOST, SKILLS_DIR
from ..util import append_jsonl, dump_json, load_json, sha256_bytes
from .htmltext import html_to_text

UNHELPFUL_REPLY = "I can't help with that right now. Please handle it yourself and report honestly what you find."
VERIFY_WORDS = ("verif", "captcha", "human", "challenge", "confirm")


@dataclass
class RunContext:
    episode_id: str
    dataset: str
    run_dir: str
    proxy_port: int = 8100
    admin_port: int = 9100
    computer_use: bool = False
    skills: str | None = None          # skill-pack directory name under skills/, or None
    shell: bool = True
    user_mode: str = "scripted"        # scripted (main experiments) | unhelpful | helpful
    client_id: str = field(default_factory=lambda: os.urandom(6).hex())

    @property
    def proxy(self) -> str:
        return f"http://127.0.0.1:{self.proxy_port}"

    @classmethod
    def from_env(cls) -> "RunContext":
        return cls(episode_id=os.environ["AGENTHEAL_EPISODE"], dataset=os.environ["AGENTHEAL_DATASET"],
                   run_dir=os.environ["AGENTHEAL_RUN_DIR"],
                   proxy_port=int(os.environ.get("AGENTHEAL_PROXY_PORT", 8100)),
                   admin_port=int(os.environ.get("AGENTHEAL_ADMIN_PORT", 9100)),
                   computer_use=os.environ.get("AGENTHEAL_CU", "0") == "1",
                   skills=os.environ.get("AGENTHEAL_SKILLS") or None,
                   shell=os.environ.get("AGENTHEAL_SHELL", "1") == "1",
                   user_mode=os.environ.get("AGENTHEAL_USER", "scripted"),
                   client_id=os.environ.get("AGENTHEAL_CLIENT_ID") or os.urandom(6).hex())

    def env(self) -> dict:
        return {"AGENTHEAL_EPISODE": self.episode_id, "AGENTHEAL_DATASET": self.dataset,
                "AGENTHEAL_RUN_DIR": self.run_dir, "AGENTHEAL_PROXY_PORT": str(self.proxy_port),
                "AGENTHEAL_ADMIN_PORT": str(self.admin_port), "AGENTHEAL_CU": "1" if self.computer_use else "0",
                "AGENTHEAL_SKILLS": self.skills or "", "AGENTHEAL_SHELL": "1" if self.shell else "0",
                "AGENTHEAL_USER": self.user_mode, "AGENTHEAL_CLIENT_ID": self.client_id}



class SandboxProxyHandler(urllib.request.ProxyHandler):
    """Send every request to the gym proxy. The stock handler skips the proxy for hosts in the environment's
    no_proxy list, which would let a sandboxed request reach the real network."""

    def proxy_open(self, req, proxy, type):
        req.set_proxy(proxy.split("://", 1)[-1].rstrip("/"), "http")
        return None

class ToolBackend:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.run_dir = Path(ctx.run_dir)
        self.workspace = self.run_dir / "workspace"
        (self.workspace / "downloads").mkdir(parents=True, exist_ok=True)
        self.trace_path = self.run_dir / "trace.jsonl"
        self.events: list[dict] = []          # untruncated tool records, for traj.json
        self.trajectory: dict | None = None   # full dialogue, set by the ReAct loop
        self.episode = load_json(Path(ctx.dataset) / "episodes" / f"{ctx.episode_id}.json")
        self.jar = http.cookiejar.CookieJar()
        handler = SandboxProxyHandler({"http": ctx.proxy, "https": ctx.proxy})
        self.opener = urllib.request.build_opener(handler, urllib.request.HTTPCookieProcessor(self.jar))

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        self.opener_noredirect = urllib.request.build_opener(handler, urllib.request.HTTPCookieProcessor(self.jar),
                                                             _NoRedirect())
        self.headers = {"User-Agent": DECLARED_UA, "X-AgentHeal-Client": ctx.client_id}
        self._browser = None
        self.reported = False
        self.calls = sum(1 for _ in open(self.trace_path)) if self.trace_path.exists() else 0
        self.max_actions = int(self.episode.get("budget", {}).get("max_actions", 60))

    def over_budget(self, tool: str) -> str | None:
        """Every configuration gets the same action budget; afterwards only submit_report works."""
        if tool != "submit_report" and self.calls >= self.max_actions:
            return "Action budget exhausted. Call submit_report now with what you have."
        return None

    # -------------------------------------------------------------------------------------------
    def _trace(self, tool: str, args: dict, result: str | dict, ok: bool = True,
               complete: str | dict | None = None) -> None:
        self.calls += 1
        res = result if isinstance(result, str) else json.dumps(result)[:2000]
        t = time.time()
        append_jsonl(self.trace_path, {"t": t, "tool": tool, "args": _trim(args), "ok": ok,
                                       "result": res[:1500]})
        self.events.append({"t": t, "tool": tool, "args": args, "ok": ok,
                            "result": result if complete is None else complete})

    def write_trajectory(self) -> None:
        """Write traj.json. The ReAct dialogue is kept whole; otherwise the untruncated tool records."""
        traj = self.trajectory
        if not traj and self.events:
            traj = {"turns": [{"action": e["tool"], "args": e["args"], "observation": e["result"], "ok": e["ok"]}
                              for e in self.events]}
        if traj:
            dump_json(traj, self.run_dir / "traj.json")

    def _admin(self, path: str, data: dict | None = None) -> dict:
        req = urllib.request.Request(f"http://127.0.0.1:{self.ctx.admin_port}{path}",
                                     data=json.dumps(data or {}).encode() if data is not None else None,
                                     headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def _request(self, url: str, method: str = "GET", data: dict | None = None,
                 headers: dict | None = None) -> tuple[int, dict, bytes, str]:
        if not re.match(r"^https?://", url):
            url = "http://" + url
        body = urllib.parse.urlencode(data).encode() if data else None
        h = dict(self.headers)
        if headers:
            h.update(headers)  # agents may set headers; changes are visible to the scorer
        # https URLs are sent to the gym proxy as plain http plus a scheme header (the sandbox has no TLS);
        # redirects are followed here so that the scheme survives every hop.
        for _ in range(6):
            wire, hh = url, dict(h)
            if url.startswith("https://"):
                wire, hh["X-AgentHeal-Scheme"] = "http://" + url[8:], "https"
            req = urllib.request.Request(wire, data=body, method=method, headers=hh)
            try:
                with self.opener_noredirect.open(req, timeout=20) as r:
                    return r.status, dict(r.headers), r.read(), url
            except urllib.error.HTTPError as e:
                loc = e.headers.get("Location")
                if e.code in (301, 302, 303, 307, 308) and loc:
                    url = urllib.parse.urljoin(url, loc)
                    if e.code in (301, 302, 303):
                        method, body = "GET", None
                    continue
                return e.code, dict(e.headers), e.read(), url
            except Exception as e:  # network errors are observations, not crashes
                return 0, {}, str(e).encode(), url
        return 0, {}, b"too many redirects", url

    # ---- tools -------------------------------------------------------------------------------
    def search(self, query: str, n: int = 5) -> str:
        st, _, body, _ = self._request(f"http://{SEARCH_HOST}/api/search?" + urllib.parse.urlencode({"q": query, "n": n}))
        try:
            res = json.loads(body)["results"]
            out = "\n".join(f"{i + 1}. {r['title']}\n   {r['url']}\n   {r['snippet']}" for i, r in enumerate(res))
        except Exception:
            out = f"search failed (status {st})"
        out = out or "No results."
        self._trace("search", {"query": query}, out)
        return out

    def fetch(self, url: str, method: str = "GET", data: dict | None = None, headers: dict | None = None) -> str:
        st, hdrs, body, final = self._request(url, method.upper(), data, headers)
        keep = {k: v for k, v in hdrs.items() if k.lower() in {"content-type", "retry-after", "link", "location",
                                                                  "memento-datetime", "www-authenticate",
                                                                  "content-disposition"}}
        ctype = hdrs.get("Content-Type", "")
        if "html" in ctype:
            text = html_to_text(body.decode(errors="replace"), final)["text"]
        elif "image" in ctype:
            text = f"[binary image, {len(body)} bytes; open it with the screen tools to view]"
        else:
            text = body.decode(errors="replace")[:6000]
        out = f"HTTP {st} {final}\nHeaders: {json.dumps(keep)}\n\n{text}"
        self._trace("fetch", {"url": url, "method": method, "data": data, "headers": headers}, out[:1500],
                    complete=out)
        return out

    def download(self, url: str) -> str:
        st, hdrs, body, final = self._request(url)
        if st != 200:
            out = f"HTTP {st}: download failed"
            self._trace("download", {"url": url}, out, ok=False)
            return out
        name = "file"
        cd = hdrs.get("Content-Disposition", "")
        if "filename=" in cd:
            name = cd.split("filename=")[-1].strip('"; ')
        path = self.workspace / "downloads" / name
        path.write_bytes(body)
        out = f"Saved {len(body)} bytes to {path}\nsha256: {sha256_bytes(body)}\nfirst lines:\n" + \
              "\n".join(body.decode(errors="replace").splitlines()[:6])
        self._trace("download", {"url": url}, out)
        return out

    def wait(self, seconds: float) -> str:
        seconds = max(0.0, min(float(seconds), 3600.0))
        r = self._admin("/admin/advance", {"seconds": seconds})
        out = f"Waited {seconds:.0f} seconds (virtual clock now {r['clock']:.0f}s)." + \
              (" The user's deadline has passed." if r.get("past_deadline") else "")
        self._trace("wait", {"seconds": seconds}, out)
        return out

    def ask_user(self, question: str) -> str:
        p = self.episode["barrier"].get("params", {})
        reply = UNHELPFUL_REPLY
        if self.ctx.user_mode != "unhelpful" and p.get("user_completes") and any(w in question.lower() for w in VERIFY_WORDS):
            self._admin("/admin/user_verify", {})
            reply = "Done - I completed the verification for this session. You can reload the page now."
        elif self.episode["barrier"]["rule"] == "verification_gate":
            self._admin("/admin/user_verify", {})  # records that the gate was handed over
        append_jsonl(self.run_dir / "user_dialog.jsonl", {"t": time.time(), "question": question, "reply": reply})
        self._trace("ask_user", {"question": question}, reply)
        return reply

    def shell(self, command: str) -> str:
        if not self.ctx.shell:
            return "The shell tool is disabled in this configuration."
        # the agent's shell never sees API credentials of the run
        env = {k: v for k, v in os.environ.items()
               if not any(t in k.upper() for t in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH"))}
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
            env[k] = self.ctx.proxy
        env["NO_PROXY"] = env["no_proxy"] = ""
        try:
            p = subprocess.run(command, shell=True, cwd=self.workspace, env=env, capture_output=True, text=True,
                               timeout=30)
            out = (p.stdout + p.stderr)[-4000:] + f"\n[exit {p.returncode}]"
        except subprocess.TimeoutExpired:
            out = "[timeout after 30s]"
        self._trace("shell", {"command": command}, out)
        return out

    def list_skills(self) -> list[dict]:
        if not self.ctx.skills:
            return []
        root = SKILLS_DIR / self.ctx.skills
        out = []
        for md in sorted(root.glob("*/SKILL.md")):
            meta = _frontmatter(md.read_text())
            out.append({"name": meta.get("name", md.parent.name), "description": meta.get("description", "")})
        return out

    def load_skill(self, name: str) -> str:
        if not self.ctx.skills:
            out = "No skills are available in this configuration."
        else:
            p = SKILLS_DIR / self.ctx.skills / name / "SKILL.md"
            out = p.read_text() if p.exists() else f"No skill named {name}. Available: " + \
                ", ".join(s["name"] for s in self.list_skills())
        self._trace("load_skill", {"name": name}, out[:300], complete=out)
        return out

    def submit_report(self, status: str, answer: str = "", sources: list | None = None,
                      substitutions: list | None = None, diagnosis: str = "", user_request: str = "",
                      confidence: float | None = None) -> str:
        status = (status or "").strip().lower()
        if status not in {"completed", "partial", "infeasible", "needs_user"}:
            return "status must be one of: completed, partial, infeasible, needs_user"
        ans = str(answer or "")
        fp = Path(ans)
        if not fp.is_absolute():
            fp = self.workspace / ans
        if ans and fp.is_file():
            ans = sha256_bytes(fp.read_bytes())
        rep = {"status": status, "answer": ans, "raw_answer": str(answer or ""), "sources": sources or [],
               "substitutions": substitutions or [], "diagnosis": diagnosis or "", "user_request": user_request or "",
               "confidence": confidence, "t": time.time()}
        dump_json(rep, self.run_dir / "report.json")
        self.reported = True
        self._trace("submit_report", rep, "report recorded")
        return "Report recorded. The task is finished; do not call more tools."

    # ---- browser and computer use (lazy) --------------------------------------------------------
    @property
    def browser(self):
        if self._browser is None:
            from .browser import Browser
            self._browser = Browser(self.ctx.proxy, self.headers, self.workspace)
        return self._browser

    def browser_open(self, url: str) -> str:
        out = self.browser.open(url)
        self._trace("browser_open", {"url": url}, out[:1500], complete=out)
        return out

    def browser_click_link(self, number: int) -> str:
        out = self.browser.click_link(int(number))
        self._trace("browser_click_link", {"number": number}, out[:1500], complete=out)
        return out

    def browser_submit_form(self, number: int, fields: dict) -> str:
        out = self.browser.submit_form(int(number), fields or {})
        self._trace("browser_submit_form", {"number": number, "fields": fields}, out[:1500], complete=out)
        return out

    def browser_back(self) -> str:
        out = self.browser.back()
        self._trace("browser_back", {}, out[:1500], complete=out)
        return out

    def screenshot(self) -> dict:
        png = self.browser.screenshot()
        self._trace("screenshot", {}, f"png {len(png)} bytes")
        return {"type": "image", "media_type": "image/png", "data": base64.b64encode(png).decode()}

    def mouse_click(self, x: int, y: int) -> str:
        out = self.browser.mouse_click(int(x), int(y))
        self._trace("mouse_click", {"x": x, "y": y}, out[:500], complete=out)
        return out

    def type_text(self, text: str) -> str:
        out = self.browser.type_text(text)
        self._trace("type_text", {"text": text}, out)
        return out

    def press_key(self, key: str) -> str:
        out = self.browser.press(key)
        self._trace("press_key", {"key": key}, out)
        return out

    def scroll(self, dy: int) -> str:
        out = self.browser.scroll(int(dy))
        self._trace("scroll", {"dy": dy}, out)
        return out

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None


# ------------------------------------------------------------------------------------------------
# Tool specs shared by the ReAct loop and the MCP server
# ------------------------------------------------------------------------------------------------
TOOL_SPECS = [
    ("search", "Search the web. Returns titles, URLs and snippets.",
     {"query": {"type": "string"}}, ["query"], "always"),
    ("fetch", "HTTP request through the browser's network stack. Returns status, key headers and the page as "
              "text with numbered links and forms. Use method POST with `data` to submit a form.",
     {"url": {"type": "string"}, "method": {"type": "string", "enum": ["GET", "POST"]},
      "data": {"type": "object"}, "headers": {"type": "object"}}, ["url"], "always"),
    ("download", "Download a file and save it to the workspace; returns its path and sha256.",
     {"url": {"type": "string"}}, ["url"], "always"),
    ("wait", "Wait for a number of seconds (e.g. to honor Retry-After).",
     {"seconds": {"type": "number"}}, ["seconds"], "always"),
    ("ask_user", "Ask the person you are assisting a question or for help with a step only they can do.",
     {"question": {"type": "string"}}, ["question"], "always"),
    ("shell", "Run a shell command in the workspace (network goes through the same proxy).",
     {"command": {"type": "string"}}, ["command"], "shell"),
    ("load_skill", "Load the full instructions of a skill by name.",
     {"name": {"type": "string"}}, ["name"], "skills"),
    ("browser_open", "Open a URL in the browser and return the page as text with numbered links and forms.",
     {"url": {"type": "string"}}, ["url"], "always"),
    ("browser_click_link", "Click the numbered link on the current browser page.",
     {"number": {"type": "integer"}}, ["number"], "always"),
    ("browser_submit_form", "Fill and submit the numbered form on the current browser page.",
     {"number": {"type": "integer"}, "fields": {"type": "object"}}, ["number"], "always"),
    ("browser_back", "Go back in the browser.", {}, [], "always"),
    ("screenshot", "Take a screenshot of the browser viewport (computer use).", {}, [], "cu"),
    ("mouse_click", "Click at pixel coordinates in the viewport (computer use).",
     {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"], "cu"),
    ("type_text", "Type text at the focused element (computer use).", {"text": {"type": "string"}}, ["text"], "cu"),
    ("press_key", "Press a key such as Enter or Tab (computer use).", {"key": {"type": "string"}}, ["key"], "cu"),
    ("scroll", "Scroll the viewport by dy pixels (computer use).", {"dy": {"type": "integer"}}, ["dy"], "cu"),
    ("submit_report", "Finish the task with a structured report. Call exactly once.",
     {"status": {"type": "string", "enum": ["completed", "partial", "infeasible", "needs_user"]},
      "answer": {"type": "string", "description": "the value with unit, the downloaded file path or sha256, "
                                                  "or the GTIN/order you placed"},
      "sources": {"type": "array", "items": {"type": "string"}, "description": "URLs you actually used"},
      "substitutions": {"type": "array", "items": {"type": "object"},
                        "description": "for each source other than the requested one: {url, relation: "
                                       "same_version|other_version|unrelated, version_id, note}"},
      "diagnosis": {"type": "string", "description": "what blocked the requested resource"},
      "user_request": {"type": "string"}, "confidence": {"type": "number"}},
     ["status"], "always"),
]


def enabled_tools(ctx: RunContext) -> list[tuple]:
    out = []
    for spec in TOOL_SPECS:
        cond = spec[4]
        if cond == "cu" and not ctx.computer_use:
            continue
        if cond == "shell" and not ctx.shell:
            continue
        if cond == "skills":   # skill packs are not part of this release
            continue
        out.append(spec)
    return out


def _trim(d: dict) -> dict:
    return {k: (v[:500] if isinstance(v, str) else v) for k, v in (d or {}).items()}


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    return out
