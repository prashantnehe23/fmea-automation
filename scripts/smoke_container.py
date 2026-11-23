"""
scripts/smoke_container.py — B-058 (ADR-035): check a running install end to end, with the standard library only.

    python scripts/smoke_container.py --base http://127.0.0.1:8000 --model-url http://127.0.0.1:9100/v1

It expects a fresh install (no administrator yet) and a fake model server (scripts/fake_model_server.py) reachable from the
install at --model-url. Steps: health; a fresh install asks for its first administrator; create one; sign in state; point
the app at the fake model; run one small scan and expect a finished result. Exits 0 when every step passes, 1 otherwise,
printing each step.
"""

import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

CODE = '''def preview(url):
    import requests
    return requests.get(url, timeout=5).text
'''


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body=None, timeout: int = 60):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-Requested-With": "fmea"})
        try:
            with self.opener.open(req, timeout=timeout) as res:
                return res.status, res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def json(self, method: str, path: str, body=None, timeout: int = 60):
        status, text = self.call(method, path, body, timeout)
        try:
            return status, json.loads(text)
        except ValueError:
            return status, {"raw": text[:300]}


def run(base: str, model_url: str, username: str = "smoke-admin", password: str = "Smoke-test-pass-1") -> list[tuple[str, bool, str]]:
    c = Client(base)
    results: list[tuple[str, bool, str]] = []

    def step(name: str, ok: bool, detail: str = "") -> bool:
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
        return ok

    status, body = c.json("GET", "/api/health")
    if not step("health answers ok", status == 200 and body.get("status") == "ok", f"HTTP {status}"):
        return results
    status, body = c.json("GET", "/api/auth/status")
    if not step("a fresh install asks for its first administrator", status == 200 and body.get("setup_required") is True, str(body)[:120]):
        return results
    status, body = c.json("POST", "/api/auth/setup", {"username": username, "password": password, "display_name": "Smoke"})
    if not step("the first administrator is created and signed in", status == 201, f"HTTP {status}"):
        return results
    status, body = c.json("GET", "/api/auth/me")
    if not step("the session knows who is signed in", status == 200 and body.get("role") == "admin", f"HTTP {status}"):
        return results
    status, body = c.json("GET", "/api/auth/status")
    step("the install no longer asks for setup", status == 200 and body.get("setup_required") is False)

    for name, method, path, payload in (
        ("the fake model endpoint is accepted", "PUT", "/api/settings/providers/local/endpoint", {"endpoint": model_url}),
        ("the fake model is added", "POST", "/api/settings/models/custom", {"provider": "local", "id": "fake-model", "display": "Fake model"}),
        ("the fake model is made active", "PATCH", "/api/settings/model", {"model": "fake-model"}),
    ):
        status, body = c.json(method, path, payload)
        if not step(name, status in (200, 201), f"HTTP {status} {str(body)[:100]}"):
            return results

    status, text = c.call("POST", "/api/scan", {"code": CODE, "workspace": {"customer": "Smoke", "project": "container", "function": "",
                          "business_tier": "Tier 1", "user_type": "internal_staff", "business_context": "", "customer_learning": False}}, timeout=300)
    done = '"stage": "complete"' in text
    step("one scan runs to a finished result", status == 200 and done, f"HTTP {status}" + ("" if done else f" {text[-200:]}"))
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--model-url", default="http://127.0.0.1:9100/v1")
    args = ap.parse_args(argv)
    results = run(args.base, args.model_url)
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} steps passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed or not results else 0


if __name__ == "__main__":
    sys.exit(main())
