"""Playwright-backed browser for DOM tools and pixel-level computer-use tools.

Under C0 an agent reads pages as text and acts on numbered links and forms. Under C1 it can also take
screenshots and act by coordinates, which is what makes render-only figures readable.
"""
from __future__ import annotations

from pathlib import Path

from .htmltext import html_to_text

VIEWPORT = {"width": 1280, "height": 900}


class Browser:
    def __init__(self, proxy: str, headers: dict, workspace: Path):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._b = self._pw.chromium.launch(headless=True, proxy={"server": proxy},
                                          args=["--proxy-bypass-list=<-loopback>"])
        extra = {k: v for k, v in headers.items() if k.lower() != "user-agent"}
        self.ctx = self._b.new_context(user_agent=headers["User-Agent"], viewport=VIEWPORT,
                                       extra_http_headers=extra, accept_downloads=True)
        self.ctx.route("https://**/*", self._https_via_gym)
        self._proxy = proxy
        self.page = self.ctx.new_page()
        self.workspace = workspace

    def _https_via_gym(self, route) -> None:
        """The sandbox has no TLS: https requests are forwarded to the gym proxy as http + a scheme header."""
        import urllib.error
        import urllib.request

        from .backend import SandboxProxyHandler

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        req = route.request
        hdrs = {k: v for k, v in req.headers.items() if not k.startswith(":")}
        hdrs.update({k: v for k, v in req.all_headers().items() if k.lower() == "cookie"})
        hdrs["X-AgentHeal-Scheme"] = "https"
        op = urllib.request.build_opener(SandboxProxyHandler({"http": self._proxy}), _NoRedirect())
        wire = "http://" + req.url[len("https://"):]
        try:
            r = op.open(urllib.request.Request(wire, data=req.post_data_buffer, method=req.method, headers=hdrs),
                        timeout=20)
            status, headers, body = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            status, headers, body = e.code, e.headers, e.read()
        except Exception as e:
            route.fulfill(status=502, body=f"proxy error: {e}")
            return
        out = {k: v for k, v in headers.items() if k.lower() not in ("content-length", "transfer-encoding")}
        route.fulfill(status=status, headers=out, body=body)
        self._parsed: dict | None = None

    def _snapshot(self, status: int | None = None) -> str:
        html = self.page.content()
        self._parsed = html_to_text(html, self.page.url)
        head = f"URL: {self.page.url}" + (f"\nHTTP {status}" if status else "")
        return f"{head}\n{self._parsed['text']}"

    def open(self, url: str) -> str:
        if "://" not in url:
            url = "http://" + url
        try:
            resp = self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            return self._snapshot(resp.status if resp else None)
        except Exception as e:
            return f"Navigation error: {e}"

    def click_link(self, n: int) -> str:
        if not self._parsed or not (1 <= n <= len(self._parsed["links"])):
            return "No such link number on the current page."
        return self.open(self._parsed["links"][n - 1][1])

    def submit_form(self, n: int, fields: dict) -> str:
        forms = self.page.query_selector_all("form")
        if not (1 <= n <= len(forms)):
            return "No such form number on the current page."
        form = forms[n - 1]
        for name, value in fields.items():
            el = form.query_selector(f"[name='{name}']")
            if el is None:
                continue
            kind = (el.get_attribute("type") or "").lower()
            if kind == "checkbox":
                el.set_checked(bool(value) and str(value) not in {"0", "false", "False"})
            else:
                el.fill(str(value))
        try:
            with self.page.expect_navigation(timeout=15000):
                btn = form.query_selector("button, input[type=submit]")
                if btn:
                    btn.click()
                else:
                    form.evaluate("f => f.submit()")
        except Exception as e:
            return f"Submit error: {e}\n" + self._snapshot()
        return self._snapshot()

    def back(self) -> str:
        self.page.go_back()
        return self._snapshot()

    # computer use ----------------------------------------------------------------------------------
    def screenshot(self) -> bytes:
        return self.page.screenshot(full_page=False)

    def mouse_click(self, x: int, y: int) -> str:
        url = self.page.url
        self.page.mouse.click(x, y)
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return f"Clicked at ({x}, {y}). URL: {self.page.url}" + (" (navigated)" if self.page.url != url else "")

    def type_text(self, text: str) -> str:
        self.page.keyboard.type(text)
        return f"Typed {len(text)} characters."

    def press(self, key: str) -> str:
        self.page.keyboard.press(key)
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return f"Pressed {key}. URL: {self.page.url}"

    def scroll(self, dy: int) -> str:
        self.page.mouse.wheel(0, dy)
        return f"Scrolled by {dy}."

    def close(self) -> None:
        try:
            self.ctx.close()
            self._b.close()
            self._pw.stop()
        except Exception:
            pass
