"""Black-box acceptance checks. No product, fake server, or PASS-only stub.

Exit 0: named automated subset passed; manual criteria are still required.
Exit 1: an assertion/operation failed. Exit 2: environment is unverified.
Never print response bodies, commands, fixture values, or authentication data.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid


class SetupError(Exception):
    pass


class RPCError(Exception):
    def __init__(self, message):
        self.payload = message
        super().__init__("MCP JSON-RPC error (payload withheld)")


def require(condition, label):
    # Deliberately not Python assert: -O must not disable acceptance checks.
    if not condition:
        raise AssertionError(label)


def check_expected(result, expected):
    require(isinstance(result, dict) and not result.get("isError", False), "tool result is an error")
    require(isinstance(expected, list) and bool(expected), "non-empty result assertions required")
    for assertion in expected:
        require(isinstance(assertion.get("path"), list) and bool(assertion["path"]), "result path required")
        require("equals" in assertion, "expected result value required")
        value = result
        try:
            for key in assertion["path"]:
                value = value[key]
        except (KeyError, IndexError, TypeError):
            raise AssertionError("expected result path absent") from None
        require(value == assertion["equals"], "actual tool result differs from expected value")


def render(value, service):
    if isinstance(value, str):
        return value.replace("$SERVICE", service)
    if isinstance(value, list):
        return [render(v, service) for v in value]
    if isinstance(value, dict):
        return {k: render(v, service) for k, v in value.items()}
    return value


def private_url(value, *, loopback_only=False, remote_only=False):
    if not isinstance(value, str) or not value:
        raise SetupError("endpoint must be configured")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupError("only explicit credential-free HTTP(S) endpoints are supported")
    host = parsed.hostname.lower()
    local = host == "localhost"
    tailnet = host.endswith(".ts.net")
    try:
        address = ipaddress.ip_address(host)
        local = address.is_loopback
        tailnet = address in ipaddress.ip_network("100.64.0.0/10") if address.version == 4 else address in ipaddress.ip_network("fd7a:115c:a1e0::/48")
    except ValueError:
        pass
    if not (local or tailnet) or (loopback_only and not local) or (remote_only and local):
        raise SetupError("endpoint is outside the declared local/private test boundary")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SetupError("redirect refused: configure the final test endpoint explicitly")


class MCP:
    """Small JSON/SSE Streamable HTTP probe, not a general MCP SDK."""
    def __init__(self, url, versions):
        self.url = private_url(url)
        self.versions = versions
        self.session = None
        self.protocol = None
        self.sequence = 0
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def exchange(self, method, params=None, *, notification=False):
        self.sequence += 1
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            payload["id"] = self.sequence
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        req = Request(self.url, json.dumps(payload).encode("utf-8"), headers, method="POST")
        with self.opener.open(req, timeout=8) as response:
            self.session = response.headers.get("Mcp-Session-Id", self.session)
            if notification:
                require(response.status == 202, "notification must be accepted with HTTP 202")
                return None
            kind = response.headers.get_content_type()
            if kind == "application/json":
                raw = response.read(1_048_577)
                require(len(raw) <= 1_048_576, "response exceeds probe limit")
                message = json.loads(raw)
            elif kind == "text/event-stream":
                message = self._sse_response(response, payload["id"])
            else:
                raise AssertionError("MCP returned neither JSON nor SSE")
        require(isinstance(message, dict) and message.get("jsonrpc") == "2.0", "invalid JSON-RPC envelope")
        require(message.get("id") == payload["id"], "JSON-RPC response id mismatch")
        if "error" in message:
            raise RPCError(message["error"])
        require("result" in message, "JSON-RPC response has no result")
        return message["result"]

    @staticmethod
    def _sse_response(response, request_id):
        deadline = time.monotonic() + 20
        data, consumed = [], 0
        while time.monotonic() < deadline:
            raw = response.readline(65_537)
            require(raw and len(raw) <= 65_536, "SSE ended without a bounded response")
            consumed += len(raw)
            require(consumed <= 1_048_576, "SSE response exceeds probe limit")
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line == "" and data:
                message = json.loads("\n".join(data))
                data = []
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
        raise AssertionError("SSE response timed out")

    def initialize(self):
        require(isinstance(self.versions, list) and bool(self.versions), "supported protocol versions required")
        result = self.exchange("initialize", {"protocolVersion": self.versions[0], "capabilities": {}, "clientInfo": {"name": "mcp-hub-acceptance", "version": "1.0.0"}})
        require(result.get("protocolVersion") in self.versions, "unverified negotiated protocol version")
        require(isinstance(result.get("serverInfo"), dict), "serverInfo missing")
        self.protocol = result["protocolVersion"]
        self.exchange("notifications/initialized", notification=True)
        return self

    def tool_names(self):
        names, cursor = set(), None
        for _ in range(20):
            result = self.exchange("tools/list", {"cursor": cursor} if cursor else {})
            require(isinstance(result.get("tools"), list), "tools/list missing tools")
            names.update(tool["name"] for tool in result["tools"])
            cursor = result.get("nextCursor")
            if not cursor:
                return names
        raise AssertionError("tools/list pagination did not finish")

    def close(self):
        if self.session:
            headers = {"Mcp-Session-Id": self.session, "MCP-Protocol-Version": self.protocol}
            try:
                with self.opener.open(Request(self.url, headers=headers, method="DELETE"), timeout=8):
                    pass
            except (HTTPError, URLError, TimeoutError):
                # Session deletion is best effort and never constitutes a test pass.
                pass


class Checks:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = Path(cfg["sandbox_root"]).resolve(strict=True)
        require(self.root.is_dir(), "sandbox_root must be a directory")
        marker = self.root / ".mcp-hub-acceptance"
        if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != "isolated-test-environment":
            raise SetupError("isolated test directory marker missing")
        self.gateway = private_url(cfg["gateway_url"])
        self.versions = cfg["protocol_versions"]
        require({s["transport"] for s in cfg["services"]} == {"stdio", "http"} and len(cfg["services"]) == 2, "exactly two transport fixtures required")

    def probe_file(self, key):
        path = Path(self.cfg[key]).resolve(strict=True)
        require(path.is_file() and path.is_relative_to(self.root), "probe file outside isolated directory")
        return path

    @contextmanager
    def client(self, endpoint=None):
        client = MCP(endpoint or self.gateway, self.versions)
        try:
            client.initialize()
            yield client
        finally:
            client.close()

    def call(self, service, *, denied=False, endpoint=None):
        request = render(service["call"], service["name"])
        with self.client(endpoint) as client:
            if not denied:
                require(request["name"] in client.tool_names(), "configured gateway tool absent")
                result = client.exchange("tools/call", request)
                check_expected(result, render(service["expected"], service["name"]))
                return result
            try:
                result = client.exchange("tools/call", request)
            except RPCError as error:
                result = error.payload
            else:
                require(result.get("isError") is True, "disabled/deleted/forbidden tool succeeded")
            needle = service.get("denied_contains")
            require(isinstance(needle, str) and bool(needle), "explicit expected denial text required")
            require(needle in json.dumps(result, ensure_ascii=False), "denial did not match expected cause")

    def pair_calls(self, services=None, endpoint=None):
        for service in services or self.cfg["services"]:
            self.call(service, endpoint=endpoint)

    def unavailable(self, endpoint=None):
        try:
            with self.client(endpoint):
                pass
        except (URLError, TimeoutError, ConnectionError, RPCError):
            return
        raise AssertionError("Gateway still accepts initialize after stop")

    @contextmanager
    def browser(self):
        url = private_url(self.cfg["ui_url"], loopback_only=True)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SetupError("Playwright is not installed; UI checks are UNVERIFIED") from None
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                # The real @1mcp/agent lifecycle includes Windows process-identity
                # checks and downstream startup. T-003 can legitimately take
                # under a minute; a 15-second browser default made a live apply
                # look like a product failure.
                page.set_default_timeout(90_000)
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(url)
                page.get_by_role("heading", name="MCP Hub", exact=True).wait_for()
                yield page
            finally:
                browser.close()

    @staticmethod
    def click(page, name):
        page.get_by_role("button", name=name, exact=True).click()

    @staticmethod
    def row(page, service):
        return page.get_by_role("row").filter(has=page.get_by_text(service["name"], exact=True))

    def apply(self, page):
        self.click(page, "儲存並套用")
        page.get_by_role("status").filter(has_text="設定已套用").wait_for()

    def add_pair(self, page):
        services = json.loads(json.dumps(self.cfg["services"]))
        suffix = uuid.uuid4().hex[:10]
        for service in services:
            service["name"] = "mcp-hub-acceptance-" + suffix + "-" + service["transport"]
            page.get_by_label("服務名稱", exact=True).fill(service["name"])
            page.get_by_label("傳輸類型", exact=True).select_option(service["transport"])
            if service["transport"] == "stdio":
                page.get_by_label("啟動命令", exact=True).fill(service["command"])
                page.get_by_label("命令參數", exact=True).fill(json.dumps(service["arguments"], ensure_ascii=False))
            else:
                page.get_by_label("服務 URL", exact=True).fill(private_url(service["url"], loopback_only=True))
            self.click(page, "新增 MCP Server")
            self.apply(page)
        page.reload()
        for service in services:
            self.row(page, service).wait_for()
        self.pair_calls(services)
        return services

    def lifecycle(self, page, services=None, endpoint=None):
        self.pair_calls(services, endpoint)
        self.click(page, "停止 Gateway")
        page.get_by_role("status").filter(has_text="Gateway 已停止").wait_for()
        self.unavailable(endpoint)
        self.click(page, "啟動 Gateway")
        # Real downstream MCP startup (not UI feedback) drives this wait; measured
        # against the real @1mcp/agent CLI it took 10-16s for a 2-service fixture,
        # tight against the page's 15s default. Widened explicitly for this one
        # external-process wait; other UI waits keep the inherited 15s default.
        page.get_by_role("status").filter(has_text="Gateway 運作中").wait_for(timeout=30_000)
        self.pair_calls(services, endpoint)
        self.click(page, "重啟 Gateway")
        page.get_by_role("status").filter(has_text="Gateway 運作中").wait_for(timeout=30_000)
        self.pair_calls(services, endpoint)

    def edit(self, page, services):
        target = next(s for s in services if s["transport"] == "http")
        replacement = self.cfg["replacement_http"]
        require(replacement["expected"] != target["expected"], "edit fixture must produce a different known result")
        self.row(page, target).get_by_role("button", name="編輯", exact=True).click()
        page.get_by_label("服務 URL", exact=True).fill(private_url(replacement["url"], loopback_only=True))
        self.apply(page)
        target.update({"url": replacement["url"], "expected": replacement["expected"]})
        page.reload()
        self.row(page, target).wait_for()
        self.pair_calls(services)

    def remove_or_disable(self, page, services, *, delete):
        target = next(s for s in services if s["transport"] == "http")
        self.row(page, target).get_by_role("button", name="刪除" if delete else "停用", exact=True).click()
        self.apply(page)
        page.reload()
        row = self.row(page, target)
        if delete:
            require(row.count() == 0, "deleted service still listed")
        else:
            row.wait_for()
        self.call(target, denied=True)
        self.call(next(s for s in services if s["transport"] == "stdio"))

    def health(self, page, services):
        for service in services:
            row = self.row(page, service)
            row.get_by_role("button", name="測試連線", exact=True).click()
            row.get_by_text("可連線", exact=True).wait_for()
            stamp = row.locator("time[datetime]").get_attribute("datetime")
            require(isinstance(stamp, str), "check timestamp missing")
            checked = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            require(checked.tzinfo is not None, "check timestamp must include timezone")
            require(-5 <= (datetime.now(timezone.utc) - checked).total_seconds() < 120, "check timestamp stale or in future")

    def logs(self, page):
        path = self.probe_file("gateway_log")
        before = path.read_bytes()
        marker = self.cfg["log_marker"]
        require(isinstance(marker, str) and bool(marker) and marker.encode() in before, "real log fixture event absent")
        self.click(page, "查看日誌")
        panel = page.get_by_role("log")
        panel.wait_for()
        require(marker in panel.inner_text(), "actual diagnostic event missing from log view")
        require(path.read_bytes().startswith(before), "viewing log changed or truncated original contents")

    def check_001(self):
        self.pair_calls()

    def check_002(self):
        with self.browser() as page:
            self.lifecycle(page)
            page.close()
            self.pair_calls()

    def check_003(self):
        with self.browser() as page:
            self.add_pair(page)

    def check_004(self):
        with self.browser() as page:
            self.edit(page, self.add_pair(page))

    def check_005(self):
        with self.browser() as page:
            self.remove_or_disable(page, self.add_pair(page), delete=False)

    def check_006(self):
        with self.browser() as page:
            self.remove_or_disable(page, self.add_pair(page), delete=True)

    def check_007(self):
        with self.browser() as page:
            services = self.add_pair(page)
            self.health(page, services)
            self.remove_or_disable(page, services, delete=False)
            self.row(page, next(s for s in services if s["transport"] == "http")).get_by_text("已停用", exact=True).wait_for()

    def check_008(self):
        with self.browser() as page:
            self.logs(page)

    def check_009(self):
        sentinel = self.probe_file("outside_sentinel")
        before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
        self.call(self.cfg["file_allowed"])
        self.call(self.cfg["file_denied"], denied=True)
        require(hashlib.sha256(sentinel.read_bytes()).hexdigest() == before, "outside sentinel changed")

    def check_010(self):
        endpoint = private_url(self.cfg["private_gateway_url"], remote_only=True)
        with self.browser() as page:
            services = self.add_pair(page)
            self.lifecycle(page, services, endpoint)

    def check_011(self):
        # Re-run each independent automated subset on the same running build.
        for n in range(1, 11):
            getattr(self, f"check_{n:03d}")()
        # Additional continuous local Golden Path, not a substitute for iPhone.
        with self.browser() as page:
            services = self.add_pair(page)
            self.health(page, services)
            page.close()
            endpoint = private_url(self.cfg["private_gateway_url"], remote_only=True)
            self.pair_calls(services, endpoint)
        with self.browser() as page:
            self.edit(page, services)
            self.remove_or_disable(page, services, delete=False)
            self.remove_or_disable(page, services, delete=True)
            self.logs(page)
            remaining = [s for s in services if s["transport"] == "stdio"]
            self.lifecycle(page, remaining)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", choices=[f"T-{n:03d}" for n in range(1, 12)], required=True)
    parser.add_argument("--config", default=os.environ.get("MCP_HUB_ACCEPTANCE_CONFIG"))
    args = parser.parse_args(argv)
    try:
        if not args.config or not Path(args.config).is_file():
            raise SetupError("explicit isolated fixture file missing; no service contacted")
        if os.environ.get("MCP_HUB_ACCEPTANCE_ALLOW_MUTATION") != "1":
            raise SetupError("explicit test-mutation opt-in missing; no service contacted")
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if cfg.get("isolated") is not True:
            raise SetupError("fixture must declare isolated test environment")
        checks = Checks(cfg)
        getattr(checks, "check_" + args.ticket[2:])()
    except SetupError as error:
        print("UNVERIFIED: " + str(error), file=sys.stderr)
        return 2
    except Exception as error:
        # Avoid leaking subprocess commands, credentials, paths, or server bodies.
        print(f"CHECK_FAILED {args.ticket}: {type(error).__name__}; inspect the isolated test environment", file=sys.stderr)
        return 1
    print(f"AUTOMATED_CHECK_PASS {args.ticket}")
    print("MANUAL_CRITERIA_STILL_REQUIRED: this is not an iPhone or whole-ticket verdict")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
